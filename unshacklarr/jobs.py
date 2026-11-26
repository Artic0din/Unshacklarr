import errno
import json
import math
import os
import re
import sys
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, RLock
from types import MappingProxyType
from typing import Literal, NamedTuple, TypeVar, get_args
from urllib.parse import quote

from unshacklarr.files import PRIVATE, write_atomic

if sys.platform == "win32":
    import msvcrt
    from time import sleep

    WINDOWS_LOCK_RETRY_SECONDS = 0.05

    def _lock_fd(fd: int) -> None:
        while True:
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                return
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EDEADLK):
                    raise
                sleep(WINDOWS_LOCK_RETRY_SECONDS)

    def _unlock_fd(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock_fd(fd: int) -> None:
        fcntl.lockf(fd, fcntl.LOCK_EX)

    def _unlock_fd(fd: int) -> None:
        fcntl.lockf(fd, fcntl.LOCK_UN)


SCHEMA_VERSION = 1
LEGACY_QUEUE_FILENAME = "queue.json"
BATCH_ID_PATTERN = re.compile(r"\d{8}-\d{6}-[0-9a-f]{6}")
EPOCH_UTC = datetime(1970, 1, 1, tzinfo=timezone.utc)
ALLOWED_PARTS = ("2", "3", "4")
EPISODE_NAME_MODES = ("joined", "keep", "always")
EPISODE_RE = re.compile(r"S(\d+)E(\d+)(\.\d+)?")
STORE_UPDATE_ATTEMPTS = 8
_STORE_LOCKS: dict[tuple[int, Path], RLock] = {}
_LOCK_DEPTH: dict[tuple[int, Path], int] = {}
_LOCKS_GUARD = Lock()
JobState = Literal["waiting", "running", "paused", "completed", "completed_with_errors", "failed", "cancelled", "removed"]
JobChildState = Literal["waiting", "queued", "downloading", "completed", "failed", "cancelled", "interrupted"]
FailureScope = Literal["child", "shared"]
ChildFailureCode = Literal["title", "manifest", "licence", "download", "decrypt", "mux", "decode", "interrupted"]
SharedFailureCode = Literal["provider_access", "cdm_route", "proxy", "storage", "output_path"]
FailureCode = Literal[ChildFailureCode, SharedFailureCode]
JOB_STATES: frozenset[JobState] = frozenset(get_args(JobState))
JOB_CHILD_STATES: frozenset[JobChildState] = frozenset(get_args(JobChildState))
CHILD_FAILURE_CODES: frozenset[ChildFailureCode] = frozenset(get_args(ChildFailureCode))
SHARED_FAILURE_CODES: frozenset[SharedFailureCode] = frozenset(get_args(SharedFailureCode))
FAILURE_SCOPES: dict[FailureScope, frozenset[FailureCode]] = {"child": CHILD_FAILURE_CODES, "shared": SHARED_FAILURE_CODES}
T = TypeVar("T")


class JobError(Exception): ...


class LegacyQueueConversionError(JobError, ValueError): ...


class JobStoreError(JobError, OSError): ...


def _expect(value: object, kind: type[T]) -> T:
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise ValueError(f"Expected {kind.__name__}")
    return value


def _optional(value: object, kind: type[T]) -> T | None:
    return None if value is None else _expect(value, kind)


def _choice(value: object, choices: Collection[T]) -> T:
    for choice in choices:
        if value == choice:
            return choice
    raise ValueError("Unrecognized job state or failure classification")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _strip_fields(record: object, **fields: str | None) -> None:
    for name, value in fields.items():
        if value is not None:
            _require(bool(value := value.strip()), "Expected non-empty text")
            object.__setattr__(record, name, value)


def _object(value: object) -> dict[str, object]:
    return {_expect(key, str): item for key, item in _expect(value, Mapping).items()}


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _sequence(value: object) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray, memoryview)):
        raise ValueError("Expected a sequence")
    return value


def _integer(value: object) -> int:
    return int(value) if isinstance(value, str) else _expect(value, int)


def _freeze_json(value: object, path: tuple[str, ...] = ()) -> object:
    if path[-2:] == ("numbering", "season_map"):
        fields = _expect(value, Mapping)
        seasons = {_integer(key): _integer(item) for key, item in fields.items()}
        _require(len(seasons) == len(fields), "Duplicate season map key")
        return MappingProxyType(seasons)
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_json(item, (*path, key)) for key, item in _object(value).items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
        return tuple(_freeze_json(item) for item in value)
    valid = math.isfinite(value) if isinstance(value, float) else value is None or isinstance(value, (str, int))
    _require(valid, "Expected a JSON value")
    return value


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    return [_thaw_json(item) for item in value] if isinstance(value, tuple) else value


def _canonical_json(value: object) -> str:
    return json.dumps(_thaw_json(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class FailureClassification:
    scope: FailureScope
    code: FailureCode

    def __post_init__(self) -> None:
        _require(self.code in FAILURE_SCOPES.get(self.scope, ()), "Invalid failure classification")

    @classmethod
    def from_dict(cls, value: object) -> "FailureClassification":
        fields = _object(value)
        scope = _choice(fields["scope"], FAILURE_SCOPES)
        return cls(scope, _choice(fields["code"], FAILURE_SCOPES[scope]))


@dataclass(frozen=True)
class JobItemRequest:
    id: str
    label: str
    selector: str | None = None
    sonarr_episode_id: int | None = None

    def __post_init__(self) -> None:
        _strip_fields(self, id=self.id, label=self.label, selector=self.selector)
        if (episode_id := self.sonarr_episode_id) is not None:
            _require(not isinstance(episode_id, bool) and episode_id > 0, "Expected a positive Sonarr episode ID")

    @classmethod
    def from_dict(cls, value: object) -> "JobItemRequest":
        item = _object(value)
        return cls(_expect(item["id"], str), _expect(item["label"], str), _optional(item["selector"], str),
                   _optional(item["sonarr_episode_id"], int))


@dataclass(frozen=True)
class NormalizedJobRequest:
    service: str | None
    title_id: str | None
    items: tuple[JobItemRequest, ...]
    effective_options: Mapping[str, object] = field(compare=False)
    sonarr: str | None = None
    _options_json: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        _strip_fields(self, service=self.service, title_id=self.title_id, sonarr=self.sonarr)
        _require(0 < len({item.id for item in self.items}) == len(self.items), "Expected non-empty unique items")
        frozen = _freeze_json(self.effective_options)
        object.__setattr__(self, "effective_options", frozen)
        object.__setattr__(self, "_options_json", _canonical_json(frozen))

    def to_dict(self) -> dict[str, object]:
        return {
            "service": self.service,
            "title_id": self.title_id,
            "items": [asdict(item) for item in self.items],
            "effective_options": _thaw_json(self.effective_options),
            "sonarr": self.sonarr,
        }

    @classmethod
    def from_dict(cls, value: object) -> "NormalizedJobRequest":
        request = _object(value)
        return cls(
            _optional(request["service"], str), _optional(request["title_id"], str),
            tuple(map(JobItemRequest.from_dict, _expect(request["items"], list))), _object(request["effective_options"]),
            _optional(request["sonarr"], str),
        )


@dataclass(frozen=True)
class JobChild:
    id: str
    request: JobItemRequest
    state: JobChildState = "waiting"
    attempt_job_id: str | None = None
    interruption_count: int = 0
    failure: FailureClassification | None = None

    def __post_init__(self) -> None:
        _strip_fields(self, id=self.id, attempt_job_id=self.attempt_job_id)
        _require(self.state in JOB_CHILD_STATES, "Invalid child state")
        _require(not isinstance(self.interruption_count, bool) and self.interruption_count >= 0, "Invalid interruption count")
        _require(self.failure is None or self.state != "completed", "Completed children cannot have a failure")

    @property
    def failure_scope(self) -> FailureScope | None:
        return self.failure.scope if self.failure else None

    @classmethod
    def from_dict(cls, value: object) -> "JobChild":
        child = _object(value)
        failure = child["failure"]
        return cls(_expect(child["id"], str), JobItemRequest.from_dict(child["request"]), _choice(child["state"], JOB_CHILD_STATES),
                   _optional(child["attempt_job_id"], str), _expect(child["interruption_count"], int),
                   FailureClassification.from_dict(failure) if failure is not None else None)


@dataclass(frozen=True)
class DownstreamJob:
    schema_version: int
    id: str
    request: NormalizedJobRequest
    children: tuple[JobChild, ...]
    state: JobState
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _strip_fields(self, id=self.id)
        _require(not isinstance(self.schema_version, bool) and self.schema_version == SCHEMA_VERSION, "Invalid job schema")
        _require(self.state in JOB_STATES, "Invalid job state")
        _require(tuple(child.request for child in self.children) == self.request.items, "Children must match request order")
        _require(len({child.id for child in self.children}) == len(self.children), "Duplicate child ID")
        for name, timestamp in (("created_at", self.created_at), ("updated_at", self.updated_at)):
            _require(timestamp.utcoffset() is not None, "Expected a timezone-aware datetime")
            object.__setattr__(self, name, timestamp.astimezone(timezone.utc))
        _require(self.updated_at >= self.created_at, "Job was updated before creation")

    def to_dict(self) -> dict[str, object]:
        return vars(self) | {"request": self.request.to_dict(), "children": [asdict(child) for child in self.children],
                             "created_at": self.created_at.isoformat(), "updated_at": self.updated_at.isoformat()}

    @classmethod
    def from_dict(cls, data: object) -> "DownstreamJob":
        record = _object(data)
        request = NormalizedJobRequest.from_dict(record["request"])
        children = tuple(map(JobChild.from_dict, _expect(record["children"], list)))
        created, updated = (datetime.fromisoformat(_expect(record[key], str)) for key in ("created_at", "updated_at"))
        return cls(_expect(record["schema_version"], int), _expect(record["id"], str), request, children,
                   _choice(record["state"], JOB_STATES), created, updated)


class StoreDocument(NamedTuple):
    jobs: tuple[DownstreamJob, ...]
    staged_job_ids: frozenset[str]
    staged_baselines: Mapping[str, tuple[NormalizedJobRequest, JobState]] = MappingProxyType({})


def _parse_store_document(raw: bytes) -> StoreDocument:
    document = _object(json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object))
    _require(_expect(document["schema_version"], int) == SCHEMA_VERSION, "Unknown job store schema")
    records = tuple(map(DownstreamJob.from_dict, _expect(document["jobs"], list)))
    child_ids = [child.id for job in records for child in job.children]
    job_ids = {job.id for job in records}
    _require(len(job_ids) == len(records) and len(set(child_ids)) == len(child_ids), "Duplicate ID")
    staged_ids = _expect(document.get("staged_job_ids", []), list)
    staged = frozenset(_expect(job_id, str) for job_id in staged_ids)
    _require(len(staged) == len(staged_ids) and staged <= job_ids, "Invalid staged job IDs")
    raw_baselines = _object(document.get("staged_baselines", {}))
    _require(raw_baselines.keys() <= staged, "Invalid staged baseline IDs")
    baselines: dict[str, tuple[NormalizedJobRequest, JobState]] = {}
    for job_id, baseline in raw_baselines.items():
        fields = _object(baseline)
        baselines[job_id] = NormalizedJobRequest.from_dict(fields["request"]), _choice(fields["state"], JOB_STATES)
    return StoreDocument(records, staged, MappingProxyType(baselines))


def _encode_store_document(updated: StoreDocument) -> bytes:
    document: dict[str, object] = {"schema_version": SCHEMA_VERSION, "jobs": [job.to_dict() for job in updated.jobs]}
    if updated.staged_job_ids:
        document["staged_job_ids"] = sorted(updated.staged_job_ids)
    if updated.staged_baselines:
        document["staged_baselines"] = {
            job_id: {"request": request.to_dict(), "state": state}
            for job_id, (request, state) in updated.staged_baselines.items()
        }
    return json.dumps(document, allow_nan=False, indent=2).encode("utf-8")


def _fsync_directory_fd(fd: int) -> None:
    try:
        os.fsync(fd)
    except OSError as error:
        if error.errno not in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP):
            raise


def _publish_store(target: Path, data: bytes, *, first_save: bool) -> None:
    if first_save:
        _sync_ancestors(target.parent)
    with ExitStack() as cleanup:
        directory_fd: int | None = None
        if os.name != "nt":
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
            directory_fd = os.open(target.parent, flags)
            cleanup.callback(os.close, directory_fd)
        # Effective options can contain proxy credentials.
        write_atomic(target, data, mode=PRIVATE)
        if directory_fd is not None:
            _fsync_directory_fd(directory_fd)


def _sync_ancestors(directory: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    dev = directory.stat().st_dev
    with ExitStack() as opened:
        fds: list[int] = []
        current = directory
        while current.parent != current:
            current = current.parent
            try:
                fd = os.open(current, flags)
            except PermissionError:
                break
            opened.callback(os.close, fd)
            if os.fstat(fd).st_dev != dev:
                break
            fds.append(fd)
        for fd in reversed(fds):
            _fsync_directory_fd(fd)


def _reset_locks_after_fork() -> None:
    global _LOCKS_GUARD
    _LOCK_DEPTH.clear()
    _STORE_LOCKS.clear()
    _LOCKS_GUARD = Lock()


if sys.platform != "win32" and hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_locks_after_fork)


@contextmanager
def _acquire_lock(target: Path) -> Iterator[None]:
    key = (os.getpid(), target)
    with _LOCKS_GUARD:
        lock = _STORE_LOCKS.setdefault(key, RLock())
    with lock, ExitStack() as cleanup:
        depth = _LOCK_DEPTH.get(key, 0)
        if depth == 0:
            lock_path = target.parent / f".{target.name}.lock"
            target.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            fd = os.open(lock_path, flags, PRIVATE)
            cleanup.callback(os.close, fd)
            _lock_fd(fd)
            cleanup.callback(_unlock_fd, fd)
        _LOCK_DEPTH[key] = depth + 1
        try:
            yield
        finally:
            if depth:
                _LOCK_DEPTH[key] = depth
            else:
                _LOCK_DEPTH.pop(key, None)


def _read_bytes(target: Path) -> bytes | None:
    try:
        return target.read_bytes()
    except FileNotFoundError:
        return None


class JobStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._target_path()

    def _target_path(self) -> Path:
        resolved = self.path.resolve()
        _require(LEGACY_QUEUE_FILENAME not in (self.path.name, resolved.name), "The legacy queue cannot be a job store")
        return resolved

    def load(self) -> tuple[DownstreamJob, ...]:
        try:
            target = self._target_path()
            raw = _read_bytes(target)
            return () if raw is None else _parse_store_document(raw).jobs
        except (OSError, ValueError, KeyError, RecursionError, OverflowError) as error:
            raise JobStoreError(f"Cannot load job store {self.path}") from error

    def save(self, jobs: Sequence[DownstreamJob]) -> tuple[DownstreamJob, ...]:
        records = tuple(jobs)
        job_ids = {job.id for job in records}

        def keep_staged(existing: StoreDocument) -> StoreDocument:
            kept = existing.staged_job_ids & job_ids
            baselines = {job_id: baseline for job_id, baseline in existing.staged_baselines.items() if job_id in kept}
            return StoreDocument(records, kept, MappingProxyType(baselines))

        return self._update(keep_staged)

    def _update(self, merge: Callable[[StoreDocument], StoreDocument]) -> tuple[DownstreamJob, ...]:
        try:
            for _ in range(STORE_UPDATE_ATTEMPTS):
                target = self._target_path()
                with _acquire_lock(target):
                    if self._target_path() != target:
                        continue
                    before = _read_bytes(target)
                    existing = StoreDocument((), frozenset()) if before is None else _parse_store_document(before)
                    updated = merge(existing)
                    data = _encode_store_document(updated)
                    verified = _parse_store_document(data)
                    _require(verified == updated, "Encoded job records differ from the originals")
                    if self._target_path() != target or _read_bytes(target) != before:
                        continue
                    _publish_store(target, data, first_save=before is None)
                    return verified.jobs
        except LegacyQueueConversionError:
            raise
        except (OSError, ValueError, KeyError, RecursionError, OverflowError) as error:
            raise JobStoreError(f"Cannot save job store {self.path}") from error
        raise JobStoreError(f"Job store changed during {STORE_UPDATE_ATTEMPTS} save attempts: {self.path}")


def _whole(value: object) -> int:
    if isinstance(value, float):
        _require(math.isfinite(value), "Expected a finite number")
        return int(value)
    return int(value) if isinstance(value, (int, str)) else _expect(value, int)


def _numbering(raw: object) -> dict[str, object]:
    show = _object(raw)
    numbering: dict[str, object] = {}
    if raw_seasons := show.get("season_map"):
        seasons = {_whole(key): _whole(value) for key, value in _expect(raw_seasons, Mapping).items()}
        if seasons:
            numbering["season_map"] = seasons
    if file_name := str(show.get("file_name") or "").strip():
        numbering["file_name"] = file_name
    if (raw_episodes := show.get("episode_map")) and (mapped := _episode_map(raw_episodes)):
        numbering["episode_map"] = mapped
    if (raw_ep := show.get("episode_offset")) and (ep_offset := _whole(raw_ep)):
        numbering["episode_offset"] = ep_offset
    if (raw_season := show.get("season_offset")) and (season_offset := _whole(raw_season)):
        numbering["season_offset"] = season_offset
        if (raw_from := show.get("season_offset_from")) and (start := _whole(raw_from)) > 1:
            numbering["season_offset_from"] = start
    if show.get("join_parts") is False:
        numbering["join_parts"] = False
    if parts := show.get("parts"):
        _require(str(parts) in ALLOWED_PARTS, "Invalid parts count")
        numbering["parts"] = _whole(parts)
    if (name := show.get("episode_name") or "joined") != "joined":
        _require(name in EPISODE_NAME_MODES, "Invalid episode name mode")
        numbering["episode_name"] = name
    return numbering


def _episode_map(raw: object) -> dict[str, str]:
    episode_map: dict[str, str] = {}
    for source, target in _expect(raw, Mapping).items():
        match = EPISODE_RE.fullmatch(str(source).strip().upper())
        mapped = EPISODE_RE.fullmatch(str(target).strip().upper())
        if not match or match[3] or not mapped:
            raise ValueError("Invalid episode map entry")
        episode_map[f"S{int(match[1]):02}E{int(match[2]):02}"] = f"S{int(mapped[1]):02}E{int(mapped[2]):02}{mapped[3] or ''}"
    return episode_map


def _sync_options(entry: Mapping[str, object]) -> tuple[str | None, dict[str, object]]:
    sonarr = _expect(entry.get("sonarr", ""), str)
    _require(not sonarr or bool(sonarr.strip()), "Expected non-empty Sonarr instance")
    texts = {key: _expect(entry[key], str) for key in ("proxy", "audio", "kind") if key in entry}
    _require(all(value.strip() for value in texts.values()), "Expected non-empty legacy option")
    options: dict[str, object] = {"kind": "manual", "replace": _expect(entry.get("replace", False), bool), **texts}
    options.update({key: _object(entry[key]) for key in ("options", "service_options", "video") if key in entry})
    if "numbering" in entry:
        options["numbering"] = _numbering(entry["numbering"])
    return sonarr.strip() or None, {key: _freeze_json(item, (key,)) for key, item in options.items()}


def _episode_item(sonarr: str | None, episode: int) -> JobItemRequest:
    if sonarr is None:
        return JobItemRequest(f"sonarr:{episode}", f"Episode {episode}", sonarr_episode_id=episode)
    return JobItemRequest(f"sonarr:{quote(sonarr, safe='')}:{episode}", f"{sonarr} Episode {episode}", sonarr_episode_id=episode)


def _batch_request(entries: Sequence[Mapping[str, object]]) -> NormalizedJobRequest:
    base = _sync_options(entries[0])
    base_sonarr, base_options = base
    base_json = _canonical_json(base_options)
    items: dict[tuple[str | None, int], JobItemRequest] = {}
    per_item: dict[str, dict[str, object]] = {}
    for index, entry in enumerate(entries):
        sonarr, options = _sync_options(entry) if index else base
        differs = (sonarr, _canonical_json(options)) != (base_sonarr, base_json)
        override = {**options, "sonarr": sonarr} if sonarr != base_sonarr else options
        episodes = _sequence(entry["episodes"])
        _require(bool(episodes), "Expected one or more episodes")
        for raw_episode in episodes:
            episode = _expect(raw_episode, int)
            key = (sonarr, episode)
            if key in items:
                continue
            item = items[key] = _episode_item(sonarr, episode)
            if differs:
                per_item[item.id] = override
    effective = {**base_options, "item_options": per_item} if per_item else base_options
    return NormalizedJobRequest(None, None, tuple(items.values()), effective, base_sonarr)


def _convert_batch(batch: str, value: object, updated: datetime | None) -> DownstreamJob:
    _require(bool(BATCH_ID_PATTERN.fullmatch(batch)), "Invalid legacy batch ID")
    entries = [_object(value)] if isinstance(value, Mapping) else list(map(_object, _sequence(value)))
    _require(bool(entries), "Expected one or more legacy syncs")
    paused = [_expect(entry.get("paused", False), bool) for entry in entries]
    state: JobState = "paused" if any(paused) else "waiting"
    try:
        created = datetime.strptime(batch.rsplit("-", 1)[0], "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        created = updated or EPOCH_UTC

    request = _batch_request(entries)
    children = tuple(JobChild(f"{batch}:{item.id}", item) for item in request.items)
    return DownstreamJob(SCHEMA_VERSION, batch, request, children, state, created, updated or created)


def convert_legacy_queue(
    raw: bytes | str | Mapping[str, object], *, converted_at: datetime | None = None
) -> tuple[DownstreamJob, ...]:
    """Convert a legacy snapshot without I/O or starting work."""
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        payload: object = json.loads(text, object_pairs_hook=_unique_object) if isinstance(text, str) else text
        _require(converted_at is None or converted_at.utcoffset() is not None, "Expected a timezone-aware datetime")
        updated = converted_at.astimezone(timezone.utc) if converted_at is not None else None
        return tuple(_convert_batch(batch, value, updated) for batch, value in sorted(_object(payload).items()))
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as error:
        raise LegacyQueueConversionError("Invalid legacy queue") from error


def _reconcile_staged_job(
    prior: DownstreamJob | None, incoming: DownstreamJob, baseline: tuple[NormalizedJobRequest, JobState] | None
) -> DownstreamJob:
    if prior is None:
        return incoming
    if baseline is not None and incoming.request == baseline[0]:
        request, children, added_work = prior.request, prior.children, False
    else:
        request = incoming.request
        prior_children = {child.id: child for child in prior.children}
        children = tuple(
            replace(saved, request=child.request) if (saved := prior_children.get(child.id)) is not None else child
            for child in incoming.children
        )
        added_work = any(child.id not in prior_children for child in incoming.children)
    next_state = prior.state
    if added_work and prior.state not in ("waiting", "running", "paused"):
        next_state = incoming.state
    elif prior.state in ("waiting", "paused") and baseline is not None and incoming.state != baseline[1]:
        next_state = incoming.state
    if (prior.request, prior.children, prior.state) == (request, children, next_state):
        return prior
    return replace(
        prior, request=request, children=children, state=next_state,
        updated_at=max(prior.updated_at, incoming.updated_at),
    )


def convert_legacy_queue_file(source_path: Path, target: JobStore | Path, *,
                              converted_at: datetime | None = None) -> tuple[DownstreamJob, ...]:
    store = target if isinstance(target, JobStore) else JobStore(target)
    _require(store._target_path() != source_path.resolve(), "Invalid staging target")

    def merge(existing: StoreDocument) -> StoreDocument:
        _require(store._target_path() != source_path.resolve(), "Invalid staging target")
        converted = {job.id: job for job in convert_legacy_queue(source_path.read_bytes(), converted_at=converted_at)}
        unstaged = {job.id for job in existing.jobs if job.id not in existing.staged_job_ids}
        _require(unstaged.isdisjoint(converted), "Cannot overwrite an unstaged job")
        merged = {job.id: job for job in existing.jobs if job.id in converted or job.id in unstaged}
        for job_id, job in converted.items():
            merged[job_id] = _reconcile_staged_job(merged.get(job_id), job, existing.staged_baselines.get(job_id))
        baselines: dict[str, tuple[NormalizedJobRequest, JobState]] = {
            job_id: (job.request, job.state) for job_id, job in converted.items()
        }
        return StoreDocument(tuple(merged.values()), frozenset(converted), MappingProxyType(baselines))

    return store._update(merge)
