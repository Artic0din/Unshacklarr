import errno
import json
import math
import os
import re
import sys
import uuid
from collections import Counter
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, RLock
from time import monotonic
from types import MappingProxyType
from typing import Literal, NamedTuple, TypeVar, cast, get_args
from urllib.parse import quote, unquote, urlsplit

from unshacklarr.files import PRIVATE, PRIVATE_QUERY_KEY, check_full_path, no_credentials, write_atomic

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
JobChildState = Literal["waiting", "queued", "downloading", "completed", "failed", "cancelled", "interrupted", "stopped"]
FailureScope = Literal["child", "shared"]
ChildFailureCode = Literal["title", "manifest", "licence", "download", "decrypt", "mux", "decode", "interrupted"]
SharedFailureCode = Literal["provider_access", "cdm_route", "proxy", "storage", "output_path"]
FailureCode = Literal[ChildFailureCode, SharedFailureCode]
JOB_STATES: frozenset[JobState] = frozenset(get_args(JobState))
JOB_CHILD_STATES: frozenset[JobChildState] = frozenset(get_args(JobChildState))
CHILD_FAILURE_CODES: frozenset[ChildFailureCode] = frozenset(get_args(ChildFailureCode))
SHARED_FAILURE_CODES: frozenset[SharedFailureCode] = frozenset(get_args(SharedFailureCode))
FAILURE_SCOPES: dict[FailureScope, frozenset[FailureCode]] = {"child": CHILD_FAILURE_CODES, "shared": SHARED_FAILURE_CODES}
ACTIVE_JOB_STATES: frozenset[JobState] = frozenset({"waiting", "running", "paused"})
TERMINAL_JOB_STATES: frozenset[JobState] = JOB_STATES - ACTIVE_JOB_STATES
ACTIVE_CHILD_STATES: frozenset[JobChildState] = frozenset({"waiting", "queued", "downloading", "interrupted"})
TERMINAL_CHILD_STATES: frozenset[JobChildState] = JOB_CHILD_STATES - ACTIVE_CHILD_STATES
AttemptStatus = Literal["queued", "downloading", "completed", "failed", "cancelled", "missing", "unreachable"]
RefusalCode = Literal[
    "invalid_request", "active_failed_child", "partial_overlap", "retry_conflict", "persistence_failed",
    "reconciliation_failed", "timeout", "capacity_full", "legacy_queue_invalid",
]
T = TypeVar("T")


class JobError(Exception): ...


class LegacyQueueConversionError(JobError, ValueError): ...


class JobStoreError(JobError, OSError): ...


class _AdmissionCancelled(Exception): ...


class _CapacityFull(Exception): ...


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


@dataclass(frozen=True)
class Added:
    job_id: str
    outcome: Literal["added"] = field(default="added", init=False)

    def __post_init__(self) -> None:
        _strip_fields(self, job_id=_expect(self.job_id, str))


@dataclass(frozen=True)
class AlreadyQueued:
    job_id: str
    outcome: Literal["already_queued"] = field(default="already_queued", init=False)

    def __post_init__(self) -> None:
        _strip_fields(self, job_id=_expect(self.job_id, str))


@dataclass(frozen=True)
class Refused:
    code: RefusalCode
    message: str
    job_id: str | None = None
    child_id: str | None = None
    outcome: Literal["refused"] = field(default="refused", init=False)

    def __post_init__(self) -> None:
        _strip_fields(self, code=_expect(self.code, str), message=no_credentials(_expect(self.message, str)),
                      job_id=self.job_id, child_id=self.child_id)


AdmissionResult = Added | AlreadyQueued | Refused
ADMISSION_PERSISTENCE_FAILURE = Refused("persistence_failed",
    "DownStream could not save the download job. Check disk space and permissions, then try again.")
ADMISSION_TIMEOUT_REFUSAL = Refused("timeout", "DownStream timed out before the download job could be saved. Try again.")
ADMISSION_CAPACITY_REFUSAL = Refused("capacity_full", "Too many downloads requested at once: wait for some to finish")
ADMISSION_MIGRATION_REFUSAL = Refused("legacy_queue_invalid", "DownStream could not restore the legacy download queue.")


def generate_job_id(now: datetime | None = None, existing_ids: Collection[str] = ()) -> str:
    prefix = _utc(now).strftime("%Y%m%d-%H%M%S")
    while True:
        candidate = f"{prefix}-{uuid.uuid4().hex[:6]}"
        if candidate not in existing_ids:
            return candidate


def _utc(now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc)


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


def _thaw_json(value: object, *, stringify_keys: bool = True) -> object:
    if isinstance(value, Mapping):
        return {(str(key) if stringify_keys else key): _thaw_json(item, stringify_keys=stringify_keys)
                for key, item in value.items()}
    return [_thaw_json(item, stringify_keys=stringify_keys) for item in value] if isinstance(value, tuple) else value


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
        if self.selector is not None and self.id.startswith("direct:"):
            object.__setattr__(self, "selector", direct_selector(self.selector))
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

    @property
    def direct(self) -> bool:
        return self.effective_options.get("mode") == "direct"

    def options_for_item(self, item_id: str) -> Mapping[str, object]:
        overrides = self.effective_options.get("item_options")
        options = overrides.get(item_id) if isinstance(overrides, Mapping) else None
        return _object(options) if isinstance(options, Mapping) else self.effective_options

    def runtime_options(self) -> dict[str, object]:
        return {key: _thaw_json(value, stringify_keys=False) for key, value in self.effective_options.items()}

    @classmethod
    def from_dict(cls, value: object) -> "NormalizedJobRequest":
        request = _object(value)
        return cls(
            _optional(request["service"], str), _optional(request["title_id"], str),
            tuple(map(JobItemRequest.from_dict, _expect(request["items"], list))), _object(request["effective_options"]),
            _optional(request["sonarr"], str),
        )


class DirectRequestValidationError(ValueError): ...


def _direct_require(condition: bool, message: str) -> None:
    if not condition:
        raise DirectRequestValidationError(message)


def _direct_text(value: object, limit: int, field_name: str, *, spaces: bool = False) -> str:
    if not isinstance(value, str) or not value.isprintable():
        raise DirectRequestValidationError(f"Invalid {field_name}")
    text = value.strip()
    _direct_require(0 < len(text) <= limit and (spaces or not any(c.isspace() for c in text)), f"Invalid {field_name}")
    return text


def direct_selector(value: str) -> str:
    match = re.fullmatch(r"S([0-9]{1,4})E([0-9]{1,4})(?:\.([0-9]{1,2}))?", value, re.I)
    if not match:
        raise DirectRequestValidationError("Invalid selector")
    season, episode, part = match.groups()
    return f"S{int(season):02d}E{int(episode):02d}" + (f".{int(part)}" if part else "")


def direct_output_path(value: str | None, downloads_root: Path) -> Path:
    folder = downloads_root if value is None else Path(_direct_text(value, 4096, "output directory", spaces=True))
    try:
        check_full_path(str(folder))
    except ValueError as error:
        raise DirectRequestValidationError("Expected an absolute output path without traversal") from error
    _direct_require(folder.is_absolute(), "Expected an absolute output path")
    root = downloads_root.resolve()
    prefix = next((base for base in (downloads_root, root) if folder.is_relative_to(base)), None)
    if prefix is None:
        raise DirectRequestValidationError("Output directory must be inside downloads")
    target = root
    for part in folder.relative_to(prefix).parts:
        target /= part
        _direct_require(not target.is_symlink(), "Symlink in output directory")
    target = target.resolve()
    _direct_require(target.is_relative_to(root), "Output directory must be inside downloads")
    return target


def _public_text(text: str) -> bool:
    decoded = unquote(text)
    return no_credentials(decoded) == decoded and not re.search(
        r"\b(?:bearer\s+|(?:password|token|secret|api[_-]?key)\s*[:=])|[\w.+-]+@[\w.-]+\.[\w.-]+", decoded, re.I
    ) and not any(re.search(r"[A-Za-z0-9_+=-]{32,}", part) for part in decoded.split("/"))


_TITLE_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I)
_TITLE_SLUG = re.compile(r"[a-z][a-z0-9]{0,19}(?:-[a-z0-9]{1,20})+", re.I)


def _validate_title(title: str) -> None:
    decoded = unquote(title)
    _direct_require(not decoded.startswith("-") and decoded.isprintable() and not any(c.isspace() for c in decoded)
                    and "\\" not in decoded and not re.search(r"\beyJ[\w-]*\.", decoded)
                    and not PRIVATE_QUERY_KEY.search(decoded), "Invalid title ID")
    try:
        url = urlsplit(title)
        path = unquote(url.path)
        if url.scheme or url.netloc:
            _direct_require(url.scheme in ("http", "https") and bool(url.hostname) and url.username is None
                            and bool(path.strip("/")), "Invalid title URL")
        else:
            _direct_require(not path.startswith("/"), "Invalid title ID")
    except ValueError as error:
        raise DirectRequestValidationError("Invalid title URL") from error
    parts = path.split("/")
    _direct_require(".." not in parts and all(_TITLE_UUID.fullmatch(p) or _TITLE_SLUG.fullmatch(p)
                    or _public_text(p) for p in parts) and all(_public_text(v) for v in
                    (url.netloc, url.query, url.fragment)), "Invalid title ID")


@dataclass(frozen=True)
class DirectItemRequest:
    id: str
    selector: str | None
    label: str


@dataclass(frozen=True)
class DirectDownloadRequest:
    service: str
    title_id: str
    items: tuple[DirectItemRequest, ...]
    options: Mapping[str, object] = field(default_factory=dict)
    service_options: Mapping[str, object] = field(default_factory=dict)
    output_dir: str | None = None

    def to_normalized_request(self, downloads_root: Path) -> NormalizedJobRequest:
        service = _direct_text(self.service, 64, "service")
        _direct_require(bool(re.fullmatch(r"[A-Za-z0-9_-]+", service)) and service.upper() != "EXAMPLE", "Invalid service")
        title = _direct_text(self.title_id, 2048, "title ID")
        _direct_require(title == self.title_id, "Invalid title ID")
        _validate_title(title)
        _direct_require(isinstance(self.items, tuple) and bool(self.items), "Select at least one item")
        items: list[JobItemRequest] = []
        for item in self.items:
            _direct_require(isinstance(item, DirectItemRequest), "Invalid direct item")
            identity = _direct_text(item.id, 128, "item ID")
            label = _direct_text(item.label, 256, "label", spaces=True)
            _direct_require(not re.search(r"[<>]", label) and _public_text(label), "Invalid label")
            selector = item.selector
            if selector is None:
                _direct_require(len(self.items) == 1, "Select one film or one or more episodes")
            else:
                selector = _direct_text(selector, 16, "selector")
            key = ":".join(quote(v, safe="") for v in (service, title, identity))
            items.append(JobItemRequest("direct:" + key, label, selector))
        _direct_require(len({i.id for i in items}) == len(items) == len({i.selector for i in items}), "Duplicate selection")
        return NormalizedJobRequest(service, title, tuple(items), {
            "mode": "direct", "options": self.options, "service_options": self.service_options,
            "output_dir": str(direct_output_path(self.output_dir, downloads_root)),
        })


@dataclass(frozen=True)
class Submission:
    backend: str
    service: str
    title_id: str
    output_dir: str
    wanted: tuple[str, ...]
    started_at: datetime

    @classmethod
    def from_dict(cls, value: object) -> "Submission":
        entry = _object(value)
        started_at = datetime.fromisoformat(_expect(entry["started_at"], str))
        _require(started_at.utcoffset() is not None, "Expected a timezone-aware submission time")
        return cls(_expect(entry["backend"], str), _expect(entry["service"], str), _expect(entry["title_id"], str),
                   _expect(entry["output_dir"], str), tuple(_expect(item, str) for item in _expect(entry["wanted"], list)),
                   started_at)


@dataclass(frozen=True)
class AttemptObservation:
    status: AttemptStatus
    failure: FailureClassification | None = None
    attempt_id: str | None = None


@dataclass(frozen=True)
class JobChild:
    id: str
    request: JobItemRequest
    state: JobChildState = "waiting"
    attempt_job_id: str | None = None
    interruption_count: int = 0
    failure: FailureClassification | None = None
    submission: Submission | None = None
    attempt_backend: str | None = None
    attempt_history: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _strip_fields(self, id=self.id, attempt_job_id=self.attempt_job_id)
        if self.attempt_job_id and self.attempt_job_id not in self.attempt_history:
            object.__setattr__(self, "attempt_history", (*self.attempt_history, self.attempt_job_id))
        _require(self.state in JOB_CHILD_STATES, "Invalid child state")
        _require(not isinstance(self.interruption_count, bool) and self.interruption_count >= 0, "Invalid interruption count")
        _require(self.failure is None or self.state != "completed", "Completed children cannot have a failure")

    @property
    def failure_scope(self) -> FailureScope | None:
        return self.failure.scope if self.failure else None

    def to_dict(self) -> dict[str, object]:
        record = asdict(self)
        record["attempt_history"] = list(self.attempt_history)
        record.pop("submission")
        if self.attempt_backend is None:
            record.pop("attempt_backend")
        if self.submission is not None:
            record["submission"] = asdict(self.submission) | {"started_at": self.submission.started_at.isoformat()}
        return record

    @classmethod
    def from_dict(cls, value: object) -> "JobChild":
        child = _object(value)
        failure, submission = child["failure"], child.get("submission")
        return cls(_expect(child["id"], str), JobItemRequest.from_dict(child["request"]), _choice(child["state"], JOB_CHILD_STATES),
                   _optional(child["attempt_job_id"], str), _expect(child["interruption_count"], int),
                   FailureClassification.from_dict(failure) if failure is not None else None,
                   Submission.from_dict(submission) if submission is not None else None,
                   _optional(child.get("attempt_backend"), str),
                   tuple(_expect(v, str) for v in _sequence(child.get("attempt_history", []))))


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

    def find_child(self, identifier: str) -> JobChild | None:
        exact = next((c for c in self.children if identifier in (c.id, c.request.id)), None)
        if exact or not self.request.direct:
            return exact
        return next((c for c in self.children if unquote(c.request.id.rsplit(":", 1)[-1]) == identifier), None)

    def to_dict(self) -> dict[str, object]:
        return vars(self) | {"request": self.request.to_dict(), "children": [child.to_dict() for child in self.children],
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
    paused_all: bool = False
    paused_job_ids: tuple[str, ...] = ()
    legacy_migrated: bool = False

    def holds(self, job: DownstreamJob) -> bool:
        return self.paused_all or job.state == "paused" or job.id in self.paused_job_ids


def _parse_store_document(raw: bytes) -> StoreDocument:
    document = _expect(json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object), dict)
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
    paused = tuple(_expect(job_id, str) for job_id in _expect(document.get("paused_job_ids", []), list))
    _require(len(set(paused)) == len(paused) and set(paused) <= job_ids, "Invalid paused job IDs")
    legacy_migrated = _expect(document.get("legacy_migrated", False), bool)
    _require(not (legacy_migrated and (staged or baselines)), "Invalid migrated store")
    return StoreDocument(records, staged, MappingProxyType(baselines), _expect(document.get("paused_all", False), bool),
                         paused, legacy_migrated)


def _encode_store_document(updated: StoreDocument) -> bytes:
    document: dict[str, object] = {"schema_version": SCHEMA_VERSION, "jobs": [job.to_dict() for job in updated.jobs]}
    if updated.staged_job_ids:
        document["staged_job_ids"] = sorted(updated.staged_job_ids)
    if updated.staged_baselines:
        document["staged_baselines"] = {
            job_id: {"request": request.to_dict(), "state": state}
            for job_id, (request, state) in updated.staged_baselines.items()
        }
    if updated.paused_all:
        document["paused_all"] = True
    if updated.paused_job_ids:
        document["paused_job_ids"] = list(updated.paused_job_ids)
    if updated.legacy_migrated:
        document["legacy_migrated"] = True
    return json.dumps(document, allow_nan=False, indent=2).encode("utf-8")


def _fsync_directory_fd(fd: int) -> None:
    try:
        os.fsync(fd)
    except OSError as error:
        if error.errno not in (errno.EINVAL, errno.ENOSYS, errno.ENOTSUP, errno.EOPNOTSUPP):
            raise


def _publish_store(target: Path, data: bytes, before: bytes | None) -> None:
    if before is None:
        _sync_ancestors(target.parent)
    with ExitStack() as cleanup:
        directory_fd: int | None = None
        if os.name != "nt":
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
            directory_fd = os.open(target.parent, flags)
            cleanup.callback(os.close, directory_fd)
        cleanup.enter_context(_rollback_on_publish_error(target, data, before, directory_fd))
        # Effective options can contain proxy credentials.
        write_atomic(target, data, mode=PRIVATE)
        if directory_fd is not None:
            _fsync_directory_fd(directory_fd)
        _require(_read_bytes(target) == data, "Saved job records differ")


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
        try:
            return _backup_path(target).read_bytes()
        except FileNotFoundError:
            return None


def _backup_path(target: Path) -> Path:
    return target.with_name(f"{target.name}.bak")


def derive_job_state(children: Sequence[JobChild], *, paused: bool = False) -> JobState:
    states = {child.state for child in children}
    if states <= TERMINAL_CHILD_STATES:
        if "completed" in states:
            return "completed" if len(states) == 1 else "completed_with_errors"
        return "failed" if "failed" in states else "cancelled"
    if states & {"queued", "downloading"}:
        return "running"
    return "paused" if paused else "waiting"


def classify_failure(cause: str = "", *, error_code: str = "", phase: str = "", stage: str = "",
                     proxy_down: bool = False, auth_failed: bool = False) -> FailureClassification:
    text = cause.lower()
    code = error_code.upper()
    if proxy_down or code == "INVALID_PROXY" or re.search(
        r"proxy check failed|proxyerror|unable to connect to proxy|407 proxy authentication|does not resolve country codes into proxies", text
    ):
        return FailureClassification("shared", "proxy")
    if auth_failed or code == "AUTH_FAILED" or (code != "FILES_REFUSED" and re.search(
        r"(login|log in|sign in|cookie|auth).*(fail|invalid|expir|reject|required|denied|missing)|"
        r"(fail|invalid|expir|reject|required|denied|missing|could not).*(login|log in|sign in|cookie|authentication)|"
        r"unauthori[sz]ed|not logged in|invalid credentials|expired session", text
    )):
        return FailureClassification("shared", "provider_access")
    if stage == "cdm" or re.search(r"no cdm|cdm device|requested cdm is not permitted|cdm_overrides|missing.*\.(wvd|prd)", text):
        return FailureClassification("shared", "cdm_route")
    if stage == "storage" or re.search(r"no space left on device|enospc|not enough free space|room kept free|disk full", text):
        return FailureClassification("shared", "storage")
    if stage == "output_path" or re.search(
        r"read-only file system|erofs|permission denied.*(output|download)|(output|download).*permission denied|downloads folder reachable", text
    ):
        return FailureClassification("shared", "output_path")
    if stage in CHILD_FAILURE_CODES:
        return FailureClassification("child", cast(ChildFailureCode, stage))
    rules: tuple[tuple[ChildFailureCode, str], ...] = (
        ("mux", r"mkvmerge|mkvpropedit|mux"),
        ("decode", r"ffprobe|mediainfo|missing.*(audio|subtitle)|(audio|subtitle).*check fail|no .* (audio|subtitles) in the download|decode error"),
        ("decrypt", r"shaka|mp4decrypt|decrypt"),
        ("licence", r"licen[cs]e|widevine|playready"),
        ("manifest", r"manifest|\bmpd\b|m3u8|\bhls\b|\bdash\b|list-tracks"),
        ("title", r"another episode, by its title|not on .* yet|unmatched|programme|invalid_title|list-titles"),
    )
    detail = f"{phase.lower()} {code.lower()} {text}"
    for kind, pattern in rules:
        if re.search(pattern, detail):
            return FailureClassification("child", kind)
    return FailureClassification("child", "download")


class AttemptConflict(ValueError): ...


def _check_attempt_owner(child: JobChild, identifier: str, document: StoreDocument) -> None:
    if child.attempt_job_id is None and identifier in child.attempt_history:
        raise AttemptConflict("Attempt already ended")
    if any(other is not child and identifier in other.attempt_history for job in document.jobs for other in job.children):
        raise AttemptConflict("Attempt already belongs to another child")


def _reconcile_child(child: JobChild, result: AttemptStatus | AttemptObservation) -> JobChild:
    observed = result if isinstance(result, AttemptObservation) else AttemptObservation(result)
    if observed.attempt_id and observed.attempt_id not in child.attempt_history:
        child = replace(child, attempt_history=(*child.attempt_history, observed.attempt_id))
    status = observed.status
    if status in ("queued", "downloading", "completed"):
        return replace(child, state="queued" if status == "queued" else "downloading",
                       attempt_job_id=observed.attempt_id or child.attempt_job_id,
                       attempt_backend=child.submission.backend if child.submission else child.attempt_backend,
                       submission=None)
    if status == "cancelled":
        return replace(child, state="stopped", attempt_job_id=None, failure=None, submission=None, attempt_backend=None)
    if status == "failed":
        return replace(child, state="failed", attempt_job_id=None, submission=None, attempt_backend=None,
                       failure=observed.failure or classify_failure())
    if status == "missing":
        return replace(child, state="failed" if child.interruption_count else "waiting", attempt_job_id=None,
                       submission=None, attempt_backend=None, interruption_count=child.interruption_count + 1,
                       failure=FailureClassification("child", "interrupted") if child.interruption_count else None)
    return child


def _existing_admission(active: Sequence[DownstreamJob], request: NormalizedJobRequest) -> AlreadyQueued | Refused | None:
    return _check_active_jobs(active, {item.id for item in request.items}, request=request)


def _check_active_jobs(active: Sequence[DownstreamJob], requested: set[str], *,
                       request: NormalizedJobRequest | None = None, retry: bool = False) -> AlreadyQueued | Refused | None:
    if request and request.direct:
        targets = {i.selector for i in request.items if i.id in requested}
        requested = requested | {c.request.id for job in active if job.request.direct and
                                 (job.request.service, job.request.title_id) == (request.service, request.title_id)
                                 for c in job.children if c.request.selector in targets}
    for job in active:
        for child in job.children:
            if child.request.id in requested and child.state == "failed":
                return Refused("active_failed_child",
                    f"{child.request.label} failed in active job {job.id}. Retry that item in Activity.", job.id, child.id)
    if request is not None and not retry:
        for job in active:
            if all(child.state != "cancelled" for child in job.children) and _same_job_request(job.request, request):
                return AlreadyQueued(job.id)
    for job in active:
        labels = [child.request.label for child in job.children
                  if child.state != "cancelled" and child.request.id in requested]
        if labels:
            return Refused("partial_overlap",
                f"Already in active job {job.id}: {', '.join(labels)}. Change the selection or wait for that job to finish.",
                job.id)
    return None


def _same_job_request(saved: NormalizedJobRequest, request: NormalizedJobRequest) -> bool:
    if saved == request:
        return True
    if "item_options" not in saved.effective_options:
        return False
    options = saved.runtime_options()
    per_item = options.pop("item_options")
    if not isinstance(per_item, Mapping):
        return False
    audio_job = options.get("kind") == "audio_add"

    def continuation(value: object) -> bool:
        return isinstance(value, Mapping) and (
            value.get("kind") == "retry" or audio_job and (
                value.get("kind") == "upgrade" or
                value.get("kind") == "audio_add" and (value.get("anyway") is True or value.get("asked") is True)
            )
        )

    overrides = {item: value for item, value in _object(per_item).items() if not continuation(value)}
    if overrides:
        options["item_options"] = overrides
    return replace(saved, effective_options=options) == request


def activity_retry_duplicate(job: DownstreamJob, request: NormalizedJobRequest) -> bool:
    selected = {item.id for item in request.items}
    items = [child for child in job.children if child.request.id in selected]
    if len(items) != len(selected) or any(child.state not in ACTIVE_CHILD_STATES for child in items):
        return False
    if job.request.direct and request.direct:
        return job.request.service == request.service and job.request.title_id == request.title_id and (
            job.request.effective_options == request.effective_options
        )
    if job.request == request:
        return True
    overrides = job.request.effective_options.get("item_options")
    return isinstance(overrides, Mapping) and all(child.request.id in overrides and
               _canonical_json(overrides[child.request.id]) == request._options_json for child in items)


def _preserve_document(target: Path, backup: Path, before: bytes, directory_fd: int | None) -> None:
    if target.exists():
        backup.unlink(missing_ok=True)
        try:
            os.link(target, backup)
        except OSError as error:
            if error.errno not in {errno.EXDEV, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EPERM, errno.EMLINK}:
                raise
            write_atomic(backup, before, mode=PRIVATE)
    if directory_fd is not None:
        _fsync_directory_fd(directory_fd)


@contextmanager
def _rollback_on_publish_error(
    target: Path, data: bytes, before: bytes | None, directory_fd: int | None,
) -> Iterator[None]:
    backup = _backup_path(target)
    if before is not None:
        _preserve_document(target, backup, before, directory_fd)
    try:
        yield
    except (OSError, ValueError, KeyboardInterrupt):
        try:
            current = _read_bytes(target)
        except OSError:
            current = None
        if current is not None and current == before:
            if target.exists():
                backup.unlink(missing_ok=True)
            raise
        if current is not None and current != data:
            try:
                _parse_store_document(current)
            except (ValueError, KeyError, RecursionError, OverflowError):
                pass
            else:
                raise JobStoreError("A newer job store replaced the saved data")
        try:
            _restore_document(target, before, backup)
        finally:
            if directory_fd is not None:
                try:
                    _fsync_directory_fd(directory_fd)
                except OSError:
                    pass
        raise
    else:
        try:
            backup.unlink(missing_ok=True)
        except OSError:
            pass


def _restore_document(target: Path, before: bytes | None, backup: Path) -> None:
    if before is None:
        target.unlink(missing_ok=True)
        return
    try:
        write_atomic(target, before, mode=PRIVATE)
    except OSError:
        try:
            with target.open("r+b") as restored:
                restored.write(before)
                restored.truncate(len(before))
                restored.flush()
                os.fsync(restored.fileno())
        except OSError:
            try:
                os.replace(backup, target)
            except OSError:
                if target.exists() and target.read_bytes() != before:
                    target.unlink()
                return
    backup.unlink(missing_ok=True)


class JobStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._target_path()
        self._snapshot: tuple[bytes, StoreDocument] | None = None

    def _parse_document(self, raw: bytes) -> StoreDocument:
        snapshot = self._snapshot
        if snapshot is not None and snapshot[0] == raw:
            return snapshot[1]
        document = _parse_store_document(raw)
        self._snapshot = raw, document
        return document

    def _target_path(self) -> Path:
        resolved = self.path.resolve()
        _require(LEGACY_QUEUE_FILENAME not in (self.path.name, resolved.name), "The legacy queue cannot be a job store")
        return resolved

    def _load_document(self) -> StoreDocument:
        try:
            target = self._target_path()
            raw = _read_bytes(target)
            return StoreDocument((), frozenset()) if raw is None else self._parse_document(raw)
        except (OSError, ValueError, KeyError, RecursionError, OverflowError) as error:
            raise JobStoreError(f"Cannot load job store {self.path}") from error

    def load(self) -> tuple[DownstreamJob, ...]:
        return self._load_document().jobs

    def is_paused_all(self) -> bool:
        return self._load_document().paused_all

    def pause_state(self) -> tuple[bool, tuple[str, ...]]:
        document = self._load_document()
        return document.paused_all, document.paused_job_ids

    def get_job(self, job_id: str) -> DownstreamJob | None:
        return next((job for job in self.load() if job.id == job_id), None)

    def save(self, jobs: Sequence[DownstreamJob]) -> tuple[DownstreamJob, ...]:
        records = tuple(jobs)
        job_ids = {job.id for job in records}

        def keep_staged(existing: StoreDocument) -> StoreDocument:
            kept = existing.staged_job_ids & job_ids
            baselines = {job_id: baseline for job_id, baseline in existing.staged_baselines.items() if job_id in kept}
            return StoreDocument(records, kept, MappingProxyType(baselines), existing.paused_all,
                                 tuple(job_id for job_id in existing.paused_job_ids if job_id in job_ids),
                                 existing.legacy_migrated and not kept)

        return self._update(keep_staged, force=True)

    def _update(self, merge: Callable[[StoreDocument], StoreDocument], *, initialize: bool = False,
                force: bool = False, before_write: Callable[[], None] | None = None) -> tuple[DownstreamJob, ...]:
        try:
            for _ in range(STORE_UPDATE_ATTEMPTS):
                target = self._target_path()
                with _acquire_lock(target):
                    if self._target_path() != target:
                        continue
                    before = _read_bytes(target)
                    existing = StoreDocument((), frozenset()) if before is None else self._parse_document(before)
                    updated = merge(existing)
                    if not force and updated == existing and (before is not None or not initialize):
                        return existing.jobs
                    data = _encode_store_document(updated)
                    verified = _parse_store_document(data)
                    _require(verified == updated, "Encoded job records differ from the originals")
                    if self._target_path() != target or _read_bytes(target) != before:
                        continue
                    if before_write is not None:
                        before_write()
                    _publish_store(target, data, before)
                    self._snapshot = data, verified
                    return verified.jobs
        except (AttemptConflict, LegacyQueueConversionError):
            raise
        except (OSError, ValueError, KeyError, RecursionError, OverflowError) as error:
            raise JobStoreError(f"Cannot save job store {self.path}") from error
        raise JobStoreError(f"Job store changed during {STORE_UPDATE_ATTEMPTS} save attempts: {self.path}")

    def admit(self, request: NormalizedJobRequest, *, job_id: str | None = None, now: datetime | None = None,
              paused: bool = False, deadline: float | None = None, cancel_event: Event | None = None,
              reserve_slot: Callable[[], bool] | None = None, release_slot: Callable[[], None] | None = None,
              before_write: Callable[[], None] | None = None) -> AdmissionResult:
        result: AdmissionResult = ADMISSION_PERSISTENCE_FAILURE
        reserved = persisted = False

        def merge(existing: StoreDocument) -> StoreDocument:
            nonlocal result
            active = [job for job in existing.jobs if job.state in ACTIVE_JOB_STATES]
            if prior := _existing_admission(active, request):
                result = prior
                return existing
            ids = {job.id for job in existing.jobs}
            timestamp = _utc(now)
            identifier = generate_job_id(timestamp, ids) if job_id is None else job_id.strip()
            _require(bool(identifier) and identifier not in ids, "Expected a new job ID")
            children = tuple(JobChild(f"{identifier}:{item.id}", item) for item in request.items)
            job = DownstreamJob(SCHEMA_VERSION, identifier, request, children,
                                "paused" if paused or existing.paused_all else "waiting", timestamp, timestamp)
            result = Added(identifier)
            held = (*existing.paused_job_ids, identifier) if paused else existing.paused_job_ids
            return existing._replace(jobs=(*existing.jobs, job), paused_job_ids=held)

        def check_before_write() -> None:
            nonlocal reserved
            if before_write is not None:
                before_write()
            if reserve_slot is not None:
                if not reserve_slot():
                    raise _CapacityFull
                reserved = True
            if (cancel_event is not None and cancel_event.is_set()) or (deadline is not None and monotonic() >= deadline):
                raise _AdmissionCancelled

        try:
            self._update(merge, before_write=check_before_write)
            persisted = True
            return result
        except _AdmissionCancelled:
            result = ADMISSION_TIMEOUT_REFUSAL
        except _CapacityFull:
            result = ADMISSION_CAPACITY_REFUSAL
        except (OSError, ValueError):
            result = ADMISSION_PERSISTENCE_FAILURE
        finally:
            if reserved and not persisted and release_slot is not None:
                release_slot()
        return result

    def check_admission(self, request: NormalizedJobRequest) -> AlreadyQueued | Refused | None:
        with _acquire_lock(self._target_path()):
            return _existing_admission([job for job in self.load() if job.state in ACTIVE_JOB_STATES], request)

    def reconcile_admission(self, request: NormalizedJobRequest, *, job_id: str | None = None,
                            not_before: datetime | None = None) -> AdmissionResult:
        try:
            with _acquire_lock(self._target_path()):
                active = [job for job in self.load() if job.state in ACTIVE_JOB_STATES]
                exact = next((job for job in active if job.id == job_id and job.request == request), None)
                if exact and (not_before is None or exact.created_at >= _utc(not_before)):
                    return Added(exact.id)
                prior = _existing_admission(active, request)
                return prior if isinstance(prior, AlreadyQueued) else ADMISSION_TIMEOUT_REFUSAL
        except OSError:
            return Refused("reconciliation_failed", "DownStream could not confirm whether the download job was saved. Try again.")

    def migrate_legacy_queue(self, source_path: Path, *, converted_at: datetime | None = None) -> tuple[DownstreamJob, ...]:
        try:
            target = self._target_path()
            _require(target != source_path.resolve(), "Invalid migration target")
            with _acquire_lock(target):
                raw = _read_bytes(target)
                if raw is not None and (document := self._parse_document(raw)).legacy_migrated:
                    return document.jobs
                if not source_path.exists():
                    if raw is None:
                        return ()
                    return self._update(lambda existing: existing._replace(
                        staged_job_ids=frozenset(), staged_baselines=MappingProxyType({}), legacy_migrated=True,
                    ))
                converted = convert_legacy_queue(source_path.read_bytes(), converted_at=converted_at)
                return self._update(lambda existing: _merge_legacy(existing, converted, live=True), initialize=True)
        except LegacyQueueConversionError:
            raise
        except (OSError, ValueError, KeyError, RecursionError, OverflowError) as error:
            raise JobStoreError(f"Cannot migrate legacy queue into {self.path}") from error

    def _change_job(self, job_id: str, change: Callable[[DownstreamJob, StoreDocument], DownstreamJob | None],
                    now: datetime | None, *, paused: bool | None = None,
                    before_write: Callable[[], None] | None = None) -> DownstreamJob:
        def merge(document: StoreDocument) -> StoreDocument:
            records = list(document.jobs)
            for index, job in enumerate(records):
                if job.id != job_id:
                    continue
                updated = change(job, document)
                if updated is None:
                    return document
                if updated != job:
                    records[index] = replace(updated, updated_at=max(job.updated_at, _utc(now)))
                held = dict.fromkeys(document.paused_job_ids)
                if updated.state in TERMINAL_JOB_STATES or paused is False:
                    held.pop(job_id, None)
                elif paused or (job.state == "paused" and not document.paused_all) or any(
                    child.failure_scope == "shared" and child != prior for child, prior in zip(updated.children, job.children)
                ):
                    held[job_id] = None
                return document._replace(jobs=tuple(records), paused_job_ids=tuple(held))
            raise ValueError("Unknown job")

        return next(job for job in self._update(merge, before_write=before_write) if job.id == job_id)

    def _change_child(self, job_id: str, child_or_item_id: str,
                      change: Callable[[JobChild, StoreDocument], JobChild], *,
                      paused: bool | None = None, now: datetime | None = None) -> DownstreamJob:
        def update(job: DownstreamJob, document: StoreDocument) -> DownstreamJob:
            children = list(job.children)
            child = job.find_child(child_or_item_id)
            if child is None:
                raise ValueError("Unknown job item")
            updated = change(child, document)
            if updated == child:
                return job
            _require(job.state in ACTIVE_JOB_STATES and child.state in ACTIVE_CHILD_STATES, "Job item is not active")
            children[children.index(child)] = updated
            hold = document.holds(job) or bool(paused)
            failure = updated.failure
            state = derive_job_state(children, paused=hold or bool(failure and failure.scope == "shared"))
            return replace(job, children=tuple(children), state=state)

        return self._change_job(job_id, update, now)

    def set_child_submission(self, job_id: str, item_id: str, submission: Submission | None) -> DownstreamJob:
        return self._change_child(job_id, item_id, lambda child, _: replace(child, submission=submission))

    def start_child_attempt(self, job_id: str, child_or_item_id: str, attempt_job_id: str, *,
                            state: Literal["queued", "downloading"] = "queued", backend: str | None = None,
                            now: datetime | None = None) -> DownstreamJob:
        def start(child: JobChild, document: StoreDocument) -> JobChild:
            identifier = attempt_job_id.strip()
            _require(bool(identifier) and child.state in ACTIVE_CHILD_STATES, "Expected an active item and attempt ID")
            _check_attempt_owner(child, identifier, document)
            _require(child.attempt_job_id in (None, identifier), "Item already has an attempt")
            return replace(child, state=state, attempt_job_id=identifier, attempt_backend=backend, failure=None, submission=None)

        return self._change_child(job_id, child_or_item_id, start, now=now)

    def clear_child_attempt(self, job_id: str, item_id: str, attempt_job_id: str) -> DownstreamJob:
        def clear(child: JobChild, _: StoreDocument) -> JobChild:
            _require(child.attempt_job_id == attempt_job_id, "Attempt changed")
            return replace(child, attempt_job_id=None, attempt_backend=None, state="waiting")

        return self._change_child(job_id, item_id, clear)

    def mark_child_downloading(self, job_id: str, child_or_item_id: str, *, now: datetime | None = None) -> DownstreamJob:
        return self._change_child(job_id, child_or_item_id, lambda child, _: replace(child, state="downloading"), now=now)

    def complete_child(self, job_id: str, child_or_item_id: str, *, paused: bool | None = None,
                       now: datetime | None = None) -> DownstreamJob:
        return self._finish_child(job_id, child_or_item_id, "completed", None, paused, now)

    def cancel_child(self, job_id: str, child_or_item_id: str, *, paused: bool | None = None,
                     now: datetime | None = None) -> DownstreamJob:
        return self._finish_child(job_id, child_or_item_id, "cancelled", None, paused, now)

    def stop_child(self, job_id: str, child_or_item_id: str, *, paused: bool | None = None) -> DownstreamJob:
        return self._finish_child(job_id, child_or_item_id, "stopped", None, paused, None)

    def fail_child(self, job_id: str, child_or_item_id: str, failure: FailureClassification, *,
                   paused: bool | None = None, now: datetime | None = None) -> DownstreamJob:
        return self._finish_child(job_id, child_or_item_id, "failed", failure, paused, now)

    def fail_unstarted_children(self, job_id: str, item_ids: Collection[str], failure: FailureClassification) -> DownstreamJob:
        def fail(job: DownstreamJob, document: StoreDocument) -> DownstreamJob:
            children = tuple(
                replace(child, state="failed", failure=failure)
                if child.request.id in item_ids and child.state == "waiting" and not (child.attempt_job_id or child.submission)
                else child for child in job.children
            )
            if children == job.children:
                return job
            state = derive_job_state(children, paused=document.holds(job) or failure.scope == "shared")
            return replace(job, children=children, state=state)

        return self._change_job(job_id, fail, None)

    def stage_audio_fallback(self, job_id: str, episode_ids: Collection[int]) -> list[int]:
        return self._stage_audio_items(job_id, episode_ids, {"kind": "upgrade", "replace": True}, preserve_audio=True)

    def stage_confirmed_audio(self, job_id: str, episode_id: int, language: str) -> bool:
        return bool(self._stage_audio_items(job_id, (episode_id,), {"kind": "audio_add", "audio": language, "anyway": True}))

    def stage_audio_question(self, job_id: str, episode_id: int, language: str) -> bool:
        return bool(self._stage_audio_items(job_id, (episode_id,), {"kind": "audio_add", "audio": language, "asked": True}))

    def _stage_audio_items(self, job_id: str, episode_ids: Collection[int],
                           item_options: Mapping[str, object], *, preserve_audio: bool = False) -> list[int]:
        def eligible(child: JobChild) -> bool:
            return (child.request.sonarr_episode_id in episode_ids and child.state == "waiting"
                    and child.attempt_job_id is None and child.submission is None)

        def stage(job: DownstreamJob, _: StoreDocument) -> DownstreamJob:
            options = job.request.runtime_options()
            _require(options.get("kind") == "audio_add", "Expected an audio add job")
            per_item = _object(options.get("item_options", {}))
            staged: dict[str, Mapping[str, object]] = {}
            for child in job.children:
                if eligible(child):
                    item_id = child.request.id
                    audio = job.request.options_for_item(item_id).get("audio") if preserve_audio else None
                    staged[item_id] = {**item_options, "audio": audio.strip()} if isinstance(
                        audio, str) and audio.strip() else item_options
            if not staged:
                return job
            options["item_options"] = {**per_item, **staged}
            return replace(job, request=replace(job.request, effective_options=options))

        job = self._change_job(job_id, stage, None)
        return [episode_id for child in job.children
                if (episode_id := child.request.sonarr_episode_id) is not None and eligible(child)]

    def _finish_child(self, job_id: str, item_id: str, state: JobChildState, failure: FailureClassification | None,
                      paused: bool | None, now: datetime | None) -> DownstreamJob:
        def finish(child: JobChild, _: StoreDocument) -> JobChild:
            if child.state in TERMINAL_CHILD_STATES:
                return child
            return replace(child, state=state, attempt_job_id=None, attempt_backend=None, failure=failure, submission=None)

        return self._change_child(job_id, item_id, finish, paused=paused, now=now)

    def reconcile_child_attempt(self, job_id: str, child_or_item_id: str, attempt_job_id: str | None,
                                status: AttemptStatus | AttemptObservation) -> DownstreamJob:
        def reconcile(child: JobChild, document: StoreDocument) -> JobChild:
            identifier = status.attempt_id if isinstance(status, AttemptObservation) else None
            if child.attempt_job_id != attempt_job_id or (identifier and child.attempt_job_id not in (None, identifier)):
                raise AttemptConflict("Attempt changed")
            if identifier:
                _check_attempt_owner(child, identifier, document)
            return _reconcile_child(child, status)

        return self._change_child(job_id, child_or_item_id, reconcile)

    def reconcile_startup(self, probe_attempt: Callable[[DownstreamJob, JobChild], AttemptStatus | AttemptObservation], *,
                          now: datetime | None = None) -> tuple[DownstreamJob, ...]:
        snapshot = self.load()
        changes = {}
        claims: Counter[str] = Counter()
        for job in snapshot:
            if job.state in ACTIVE_JOB_STATES:
                for child in job.children:
                    if child.state in ACTIVE_CHILD_STATES and (
                        child.attempt_job_id is not None or child.submission is not None or child.state in ("queued", "downloading", "interrupted")
                    ):
                        observed = probe_attempt(job, child)
                        if isinstance(observed, AttemptObservation) and observed.attempt_id and child.attempt_job_id not in (None, observed.attempt_id):
                            continue
                        if isinstance(observed, AttemptObservation) and observed.attempt_id and child.attempt_job_id is None:
                            if observed.attempt_id in child.attempt_history:
                                continue
                            claims[observed.attempt_id] += 1
                        updated = _reconcile_child(child, observed)
                        if updated != child:
                            changes[job.id, child.id] = child, updated
        if not changes:
            return snapshot

        def merge(document: StoreDocument) -> StoreDocument:
            owners = {identifier: (job.id, child.id) for job in document.jobs
                      for child in job.children for identifier in child.attempt_history}

            def apply(job_id: str, child: JobChild) -> JobChild:
                owner = job_id, child.id
                pair = changes.get(owner)
                if not pair or pair[0] != child:
                    return child
                for identifier in pair[1].attempt_history:
                    if owners.get(identifier, owner) != owner or (identifier not in child.attempt_history and claims[identifier] > 1):
                        return child
                owners.update(dict.fromkeys(pair[1].attempt_history, owner))
                return pair[1]

            records = []
            held = dict.fromkeys(document.paused_job_ids)
            for job in document.jobs:
                children = tuple(apply(job.id, c) for c in job.children)
                if job.state in ACTIVE_JOB_STATES and children != job.children:
                    shared_failure = any(child.failure_scope == "shared" and child != prior
                                         for child, prior in zip(children, job.children))
                    state = derive_job_state(children, paused=document.holds(job) or shared_failure)
                    if state in TERMINAL_JOB_STATES:
                        held.pop(job.id, None)
                    elif shared_failure or (job.state == "paused" and not document.paused_all):
                        held[job.id] = None
                    job = replace(job, children=children, state=state, updated_at=max(job.updated_at, _utc(now)))
                records.append(job)
            return document._replace(jobs=tuple(records), paused_job_ids=tuple(held))

        return self._update(merge)

    def retry_item(self, job_id: str, item_id: str, *, now: datetime | None = None,
                   effective_options: Mapping[str, object] | None = None) -> DownstreamJob:
        return self.retry_items(job_id, (item_id,), now=now, effective_options=effective_options)

    def requeue_cancelled(self, job_id: str, item_id: str) -> DownstreamJob:
        return self._retry_children(job_id, (item_id,), {"cancelled"}, None, None)

    def retry_failed(self, job_id: str, *, now: datetime | None = None) -> DownstreamJob:
        return self.retry_items(job_id, None, now=now)

    def retry_items(self, job_id: str, item_ids: Collection[str] | None, *, now: datetime | None = None,
                    effective_options: Mapping[str, object] | None = None) -> DownstreamJob:
        return self._retry_children(job_id, item_ids, {"failed", "stopped"}, now, effective_options)

    def _retry_children(self, job_id: str, item_ids: Collection[str] | None, states: Collection[JobChildState],
                        now: datetime | None, effective_options: Mapping[str, object] | None) -> DownstreamJob:
        def retry(job: DownstreamJob, document: StoreDocument) -> DownstreamJob:
            updated = _retry_job(job, document, item_ids, states, effective_options)
            if isinstance(updated, Refused):
                raise ValueError("Job item is active elsewhere")
            return updated

        return self._change_job(job_id, retry, now)

    def stage_activity_retry(self, job_id: str, request: NormalizedJobRequest, *,
                             reserve: Callable[[], None]) -> tuple[DownstreamJob, DownstreamJob] | AlreadyQueued | Refused:
        before: DownstreamJob | None = None
        item_ids = {item.id for item in request.items}
        prior: AlreadyQueued | Refused | None = None

        def stage(job: DownstreamJob, document: StoreDocument) -> DownstreamJob | None:
            nonlocal before, prior
            before = job
            prior = None
            if activity_retry_duplicate(job, request):
                prior = AlreadyQueued(job_id)
                return None
            updated = _retry_job(job, document, item_ids, {"failed", "stopped"}, request.effective_options)
            if isinstance(updated, Refused):
                prior = updated
                return None
            return updated

        staged = self._change_job(job_id, stage, None, before_write=reserve)
        assert before is not None
        return prior if prior is not None else (before, staged)

    def rollback_activity_retry(self, before: DownstreamJob, staged: DownstreamJob, item_ids: Collection[str]) -> DownstreamJob | None:
        def merge(document: StoreDocument) -> StoreDocument:
            for index, job in enumerate(document.jobs):
                if job.id != before.id:
                    continue
                restored = _rollback_retry(job, before, staged, item_ids, document.holds(job))
                if restored == job:
                    return document
                held = document.paused_job_ids
                if restored.state in TERMINAL_JOB_STATES:
                    held = tuple(job_id for job_id in held if job_id != before.id)
                return document._replace(jobs=(*document.jobs[:index], restored, *document.jobs[index + 1:]),
                                         paused_job_ids=held)
            return document

        return next((job for job in self._update(merge) if job.id == before.id), None)

    def set_job_paused(self, job_id: str, paused: bool, *, now: datetime | None = None) -> DownstreamJob:
        def change(job: DownstreamJob, document: StoreDocument) -> DownstreamJob:
            if job.state not in ACTIVE_JOB_STATES:
                return job
            state = ("paused" if paused else derive_job_state(job.children, paused=document.paused_all))
            return replace(job, state=state)

        return self._change_job(job_id, change, now, paused=paused)

    def set_job_options(self, job_id: str, options_override: Mapping[str, object] | None, *,
                        now: datetime | None = None) -> DownstreamJob:
        def change(job: DownstreamJob, _: StoreDocument) -> DownstreamJob:
            options = dict(job.request.effective_options)
            options.pop("options", None)
            if options_override:
                options["options"] = options_override
            return replace(job, request=replace(job.request, effective_options=options))

        return self._change_job(job_id, change, now)

    def _set_all_paused(self, paused: bool, now: datetime | None) -> tuple[DownstreamJob, ...]:
        def merge(document: StoreDocument) -> StoreDocument:
            records = []
            for job in document.jobs:
                if job.state in ACTIVE_JOB_STATES:
                    state = derive_job_state(job.children, paused=paused)
                    if job.state != state:
                        job = replace(job, state=state, updated_at=max(job.updated_at, _utc(now)))
                records.append(job)
            return document._replace(jobs=tuple(records), paused_all=paused,
                                     paused_job_ids=document.paused_job_ids if paused else ())

        return tuple(job for job in self._update(merge) if job.state in ACTIVE_JOB_STATES)

    def pause_all(self, *, now: datetime | None = None) -> tuple[DownstreamJob, ...]:
        return self._set_all_paused(True, now)

    def resume_all(self, *, now: datetime | None = None) -> tuple[DownstreamJob, ...]:
        return self._set_all_paused(False, now)


def _retry_job(job: DownstreamJob, document: StoreDocument, item_ids: Collection[str] | None,
               states: Collection[JobChildState], effective_options: Mapping[str, object] | None) -> DownstreamJob | Refused:
    candidates = job.children if item_ids is None else tuple(c for i in item_ids if (c := job.find_child(i)) is not None)
    selected = [child for child in candidates if child.state in states]
    _require(bool(selected) and (item_ids is None or len({c.id for c in selected}) == len(item_ids)), "Job items are not eligible to retry")
    selected_ids = {child.request.id for child in selected}
    active = [other for other in document.jobs if other.id != job.id and other.state in ACTIVE_JOB_STATES]
    conflict = _check_active_jobs(active, selected_ids, request=job.request if job.request.direct else None, retry=True)
    if isinstance(conflict, Refused):
        return conflict
    children = tuple(replace(child, state="waiting", attempt_job_id=None, failure=None, interruption_count=0)
                     if child in selected else child for child in job.children)
    request = job.request
    if effective_options is not None and not request.direct:
        options = request.runtime_options()
        overrides = _object(options.get("item_options", {}))
        for item_id in selected_ids:
            overrides[item_id] = {**effective_options}
        options["item_options"] = overrides
        request = replace(request, effective_options=options)
    return replace(job, request=request, children=children,
                   state=derive_job_state(children, paused=document.holds(job)))


def _rollback_retry(job: DownstreamJob, before: DownstreamJob, staged: DownstreamJob,
                    item_ids: Collection[str], paused: bool) -> DownstreamJob:
    options = job.request.runtime_options()
    overrides = _object(options.pop("item_options", {}))
    prior = _object(before.request.runtime_options().get("item_options", {}))
    expected = _object(staged.request.runtime_options().get("item_options", {}))
    previous_children = {child.id: child for child in before.children}
    staged_children = {child.id: child for child in staged.children}
    children = []
    for child in job.children:
        item = child.request.id
        if item in item_ids and child == staged_children.get(child.id) and overrides.get(item) == expected.get(item):
            child = previous_children[child.id]
            if item in prior:
                overrides[item] = prior[item]
            else:
                overrides.pop(item, None)
        children.append(child)
    restored = tuple(children)
    if restored == job.children:
        return job
    if overrides or before.request.effective_options.get("item_options") == {}:
        options["item_options"] = overrides
    request = replace(job.request, effective_options=options)
    if job == staged and request == before.request and restored == before.children:
        return before
    return replace(job, request=request, children=restored, state=derive_job_state(restored, paused=paused))


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


def episode_item(sonarr: str | None, episode: int) -> JobItemRequest:
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
            item = items[key] = episode_item(sonarr, episode)
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
        if prior.state in ("cancelled", "removed"):
            raise LegacyQueueConversionError(f"Cannot add work to {prior.state} job {prior.id}")
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
        return _merge_legacy(existing, convert_legacy_queue(source_path.read_bytes(), converted_at=converted_at))

    return store._update(merge, initialize=True)


def _merge_legacy(existing: StoreDocument, records: Sequence[DownstreamJob], *, live: bool = False) -> StoreDocument:
    _require(live or not existing.legacy_migrated, "Cannot stage a migrated store")
    converted = {job.id: job for job in records}
    unstaged = {job.id for job in existing.jobs if job.id not in existing.staged_job_ids}
    _require(unstaged.isdisjoint(converted), "Cannot overwrite an unstaged job")
    merged = {job.id: job for job in existing.jobs if job.id in converted or job.id in unstaged}
    for job_id, job in converted.items():
        merged[job_id] = _reconcile_staged_job(merged.get(job_id), job, existing.staged_baselines.get(job_id))
    baselines: dict[str, tuple[NormalizedJobRequest, JobState]] = {} if live else {
        job_id: (job.request, job.state) for job_id, job in converted.items()
    }
    return existing._replace(
        jobs=tuple(merged.values()),
        staged_job_ids=frozenset() if live else frozenset(converted),
        staged_baselines=MappingProxyType(baselines),
        paused_job_ids=tuple(job_id for job_id in existing.paused_job_ids if job_id in merged),
        legacy_migrated=live,
    )
