import asyncio
import errno
import importlib.util
import json
import os
import select
import socket
import stat
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path
from types import MappingProxyType, ModuleType, SimpleNamespace
from typing import NoReturn
from unittest.mock import AsyncMock

import pytest

from unshacklarr import jobs

BATCH = "20261021-121217-33d6d0"
LATER_BATCH = "20261021-121218-44d6d0"
CREATED = datetime(2026, 10, 21, 12, 12, 17, tzinfo=timezone.utc)
CONVERTED = CREATED + timedelta(days=1)
LEGACY = {
    LATER_BATCH: {"episodes": [7], "paused": False, "kind": "manual", "numbering": {}},
    BATCH: {"episodes": [3, 4], "paused": True, "replace": True, "kind": "retry", "sonarr": "4K",
            "proxy": "nordvpn:fr", "options": {"options": {"--a-lang": ["fr"]}},
            "video": {"vcodec": "H.265", "quality": 2160}, "numbering": {"season_map": {"2": 1}}},
}
OLD_QUEUE = json.dumps(LEGACY).encode()
ITEM = jobs.JobItemRequest(" item ", " Episode ", sonarr_episode_id=3)
REQUEST = jobs.NormalizedJobRequest(None, None, (ITEM,), {"numbering": {"season_map": {"2": 1}}})
CHILD = jobs.JobChild("child", ITEM)
JOB = jobs.DownstreamJob(1, "preexisting", REQUEST, (CHILD,), "waiting", CREATED, CONVERTED)
SHARED_FAILURE = jobs.FailureClassification("shared", "storage")

LOCK_CONTENTION_SCRIPT = """
import fcntl
import json
import sys
from pathlib import Path
from unshacklarr.jobs import DownstreamJob, JobStore

lockf = fcntl.lockf

def report_contention(fd, operation):
    if operation != fcntl.LOCK_EX:
        lockf(fd, operation)
        return
    try:
        lockf(fd, operation | fcntl.LOCK_NB)
    except BlockingIOError:
        print("blocked", flush=True)
        lockf(fd, operation)
        assert [job.id for job in store.load()] == sys.argv[3:]

fcntl.lockf = report_contention
input()
store = JobStore(Path(sys.argv[1]))
store.save([DownstreamJob.from_dict(json.loads(sys.argv[2]))])
print("saved", flush=True)
"""


@pytest.fixture
def store(tmp_path: Path) -> jobs.JobStore:
    return jobs.JobStore(tmp_path / "jobs.json")


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "queue.json"
    path.write_bytes(OLD_QUEUE)
    return path


def test_records_normalize_and_round_trip() -> None:
    assert ITEM == jobs.JobItemRequest("item", "Episode", sonarr_episode_id=3)
    assert REQUEST.effective_options["numbering"] == {"season_map": {2: 1}}
    assert jobs.FailureClassification("child", "manifest").scope == "child"
    failed = replace(CHILD, state="failed", attempt_job_id="attempt", interruption_count=2, failure=SHARED_FAILURE)
    assert failed.failure_scope == "shared"
    for record in (JOB, replace(JOB, state="failed", children=(failed,))):
        assert jobs.DownstreamJob.from_dict(record.to_dict()) == record


def test_request_options_are_copied_and_deeply_immutable() -> None:
    langs = ["fr"]
    request = replace(REQUEST, effective_options={"nested": {"langs": langs}})
    langs.append("en")
    nested = request.effective_options["nested"]
    assert isinstance(nested, MappingProxyType) and nested["langs"] == ("fr",)
    with pytest.raises(TypeError):
        nested["langs"] = ()  # type: ignore[index]


@pytest.mark.parametrize("construct", [
    lambda: jobs.FailureClassification("child", "storage"),
    lambda: jobs.FailureClassification.from_dict({"scope": "child", "code": "raw upstream error"}),
    lambda: replace(ITEM, id=" "), lambda: replace(ITEM, sonarr_episode_id=True),
    lambda: replace(REQUEST, items=(ITEM, ITEM)), lambda: replace(REQUEST, effective_options={"quality": float("inf")}),
    lambda: replace(CHILD, interruption_count=True), lambda: replace(CHILD, state="completed", failure=SHARED_FAILURE),
    lambda: replace(JOB, children=()), lambda: replace(JOB, children=(jobs.JobChild("other", jobs.JobItemRequest("a", "A")),)),
    lambda: replace(JOB, created_at=CREATED.replace(tzinfo=None)),
    lambda: replace(JOB, created_at=CONVERTED, updated_at=CREATED), lambda: replace(JOB, schema_version=True),
])
def test_records_reject_invalid_fields(construct: Callable[[], object]) -> None:
    with pytest.raises(ValueError):
        construct()


def test_store_round_trip_replaces_public_mode_with_private_mode(store: jobs.JobStore) -> None:
    proxy = replace(REQUEST, effective_options={"proxy": "http://user:fixture@proxy.invalid"})
    first = replace(JOB, id="z-job", request=proxy, children=(replace(CHILD, id="z-child"),))
    assert store.load() == ()
    store.save([JOB])
    store.path.chmod(0o644)
    assert store.save([first, JOB]) == store.load() == (first, JOB)
    if os.name != "nt":
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    assert json.loads(store.path.read_bytes()) == {"schema_version": 1, "jobs": [first.to_dict(), JOB.to_dict()]}


@pytest.mark.parametrize("document", [
    b"\xff", b"{", b"[]", b'{"schema_version":true,"jobs":[]}',
    b'{"schema_version":2,"jobs":[]}', b'{"schema_version":1,"jobs":[{}]}',
    b'{"schema_version":2,"schema_version":1,"jobs":[]}',
    *(json.dumps({"schema_version": 1, "jobs": [JOB.to_dict()], "staged_job_ids": ids}).encode()
      for ids in (None, [True], ["missing"], [JOB.id, JOB.id])),
    *(json.dumps({
        "schema_version": 1, "jobs": [JOB.to_dict()], "staged_job_ids": [JOB.id], "staged_baselines": baselines,
    }).encode() for baselines in (
        None, [], {"missing": {"request": REQUEST.to_dict(), "state": "waiting"}},
        {JOB.id: []}, {JOB.id: {"request": {}, "state": "waiting"}},
        {JOB.id: {"request": REQUEST.to_dict(), "state": "unknown"}},
    )),
])
def test_store_fails_closed_on_bad_documents(store: jobs.JobStore, document: bytes) -> None:
    store.path.write_bytes(document)
    with pytest.raises(jobs.JobStoreError):
        store.load()
    with pytest.raises(jobs.JobStoreError):
        store.save([JOB])
    assert store.path.read_bytes() == document


@pytest.mark.parametrize("duplicate", [JOB, replace(JOB, id="distinct-parent")])
def test_store_fails_closed_on_duplicate_ids(store: jobs.JobStore, duplicate: jobs.DownstreamJob) -> None:
    with pytest.raises(jobs.JobStoreError):
        store.save([JOB, duplicate])
    assert not store.path.exists()
    store.path.write_text(json.dumps({"schema_version": 1, "jobs": [JOB.to_dict(), duplicate.to_dict()]}))
    with pytest.raises(jobs.JobStoreError):
        store.load()


@pytest.mark.parametrize("failure, error", [
    ("corrupt", jobs.LegacyQueueConversionError), ("naive timestamp", jobs.LegacyQueueConversionError),
    ("crash", KeyboardInterrupt), ("io", jobs.JobStoreError), ("mismatch", jobs.JobStoreError),
    ("corrupt target", jobs.JobStoreError),
])
def test_stage_failure_is_atomic(
    source: Path, store: jobs.JobStore, monkeypatch: pytest.MonkeyPatch, failure: str, error: type[BaseException]
) -> None:
    store.save([JOB])
    if failure == "corrupt":
        source.write_bytes(b'{"truncated":')
    elif failure == "corrupt target":
        store.path.write_bytes(b"corrupt")
    elif failure == "mismatch":
        encode = jobs.DownstreamJob.to_dict
        altered = replace(JOB, state="paused").to_dict()
        monkeypatch.setattr(jobs.DownstreamJob, "to_dict", lambda self: altered if self.id == JOB.id else encode(self))
    original = source.read_bytes(), store.path.read_bytes()

    def interrupted_replace(src: str, dst: Path) -> None:
        assert dst == store.path
        if failure == "crash":
            raise KeyboardInterrupt
        if failure == "io":
            raise OSError("interrupted before rename")
        pytest.fail("Save published an unverified payload")

    monkeypatch.setattr(os, "replace", interrupted_replace)
    with pytest.raises(error):
        when = CONVERTED.replace(tzinfo=None) if failure == "naive timestamp" else None
        jobs.convert_legacy_queue_file(source, store, converted_at=when)
    assert (source.read_bytes(), store.path.read_bytes()) == original
    assert set(source.parent.iterdir()) == {source, store.path, store.path.parent / f".{store.path.name}.lock"}


def test_store_keeps_a_concurrent_save_after_rename(store: jobs.JobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    first, newer = replace(JOB, state="paused"), replace(JOB, state="running")
    rename = os.replace

    def save_after_replace(source: str, target: Path) -> None:
        rename(source, target)
        monkeypatch.setattr(os, "replace", rename)
        assert store.save([newer]) == (newer,)

    monkeypatch.setattr(os, "replace", save_after_replace)
    assert store.save([first]) == (first,)
    assert store.load() == (newer,)


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX directory sync")
def test_store_syncs_parent_directory_after_atomic_rename(
    store: jobs.JobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_atomic, fsync = jobs.write_atomic, os.fsync
    parent_stat = store.path.parent.stat()
    calls: list[str] = []
    fail_with = errno.EINVAL

    def record_write(path: Path, data: bytes, mode: int | None = None) -> None:
        write_atomic(path, data, mode=mode)
        calls.append("renamed")

    def sync_or_reject(fd: int) -> None:
        info = os.fstat(fd)
        if stat.S_ISDIR(info.st_mode) and (info.st_dev, info.st_ino) == (parent_stat.st_dev, parent_stat.st_ino):
            calls.append("synced parent")
            raise OSError(fail_with, "directory sync failure")
        fsync(fd)

    monkeypatch.setattr(jobs, "write_atomic", record_write)
    monkeypatch.setattr(os, "fsync", sync_or_reject)
    assert store.save([JOB]) == store.load() == (JOB,)
    assert calls == ["renamed", "synced parent"]
    fail_with = errno.EIO
    with pytest.raises(jobs.JobStoreError):
        store.save([JOB])


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX directory sync")
def test_first_save_syncs_ancestors_across_retry_and_precreated_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_atomic, fsync = jobs.write_atomic, os.fsync
    root = tmp_path / "root"
    root.mkdir()
    root_id = (root.stat().st_dev, root.stat().st_ino)
    events: list[tuple[int, int] | str] = []
    fail_on: tuple[int, int] | None = root_id

    def record_write(path: Path, data: bytes, mode: int | None = None) -> None:
        write_atomic(path, data, mode=mode)
        events.append("renamed")

    def track_sync(fd: int) -> None:
        info = os.fstat(fd)
        if stat.S_ISDIR(info.st_mode):
            identity = (info.st_dev, info.st_ino)
            if identity == fail_on:
                raise OSError(errno.EIO, "ancestor sync failed")
            events.append(identity)
        fsync(fd)

    monkeypatch.setattr(jobs, "write_atomic", record_write)
    monkeypatch.setattr(os, "fsync", track_sync)
    nested = jobs.JobStore(root / "nested" / "sub" / "jobs.json")
    for _ in range(2):
        with pytest.raises(jobs.JobStoreError):
            nested.save([JOB])
        assert nested.path.parent.is_dir() and not nested.path.exists()
    fail_on = None
    precreated = root / "other" / "sub"
    precreated.mkdir(parents=True)
    for target_dir in (nested.path.parent, precreated):
        events.clear()
        current = jobs.JobStore(target_dir / "jobs.json")
        assert current.save([JOB]) == current.load() == (JOB,)
        renamed = events.index("renamed")
        mid, leaf = target_dir.parent.stat(), target_dir.stat()
        assert events[renamed - 2 : renamed + 2] == [
            root_id, (mid.st_dev, mid.st_ino), "renamed", (leaf.st_dev, leaf.st_ino),
        ]


def test_windows_locking_fallback_works_without_fcntl(
    store: jobs.JobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    msvcrt = ModuleType("msvcrt")
    lock, unlock = 1, 0
    operations: list[int] = []

    def locking(fd: int, operation: int, length: int) -> None:
        assert os.lseek(fd, 0, os.SEEK_CUR) == 0 and length == 1
        operations.append(operation)
        os.lseek(fd, 1, os.SEEK_SET)
        if operations == [lock]:
            raise OSError(errno.EACCES, "busy")

    vars(msvcrt).update(LK_LOCK=lock, LK_UNLCK=unlock, locking=locking)
    spec = importlib.util.spec_from_file_location("windows_jobs_test", jobs.__file__)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with monkeypatch.context() as patch:
        patch.setattr(sys, "platform", "win32")
        patch.setitem(sys.modules, "fcntl", None)
        patch.setitem(sys.modules, "msvcrt", msvcrt)
        patch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
        windows_store = module.JobStore(store.path)
        windows_job = module.DownstreamJob.from_dict(JOB.to_dict())
        assert windows_store.save([windows_job]) == windows_store.load() == (windows_job,)
    assert operations == [lock, lock, unlock]


def test_staging_and_other_process_serialize_via_file_lock(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("fcntl")
    parent_tmp, child_tmp = tmp_path / "parent_tmp", tmp_path / "child_tmp"
    parent_tmp.mkdir()
    child_tmp.mkdir()
    monkeypatch.setenv("TMPDIR", str(parent_tmp))
    monkeypatch.setattr(tempfile, "tempdir", None)
    target, alias = tmp_path / "sub" / "jobs.json", tmp_path / "alias.json"
    alias.symlink_to(target)
    store = jobs.JobStore(alias)
    write_atomic = jobs.write_atomic
    with subprocess.Popen(
        [sys.executable, "-c", LOCK_CONTENTION_SCRIPT, str(target), json.dumps(JOB.to_dict()), BATCH, LATER_BATCH],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={**os.environ, "TMPDIR": str(child_tmp)},
    ) as saver:
        assert saver.stdin is not None and saver.stdout is not None
        start, output = saver.stdin, saver.stdout

        def write_while_saver_waits(path: Path, data: bytes, mode: int | None = None) -> None:
            start.write("save\n")
            start.flush()
            assert select.select([output], [], [], 10)[0], "The other process did not reach its save"
            assert output.readline().strip() == "blocked"
            assert store.load() == ()
            write_atomic(path, data, mode=mode)

        monkeypatch.setattr(jobs, "write_atomic", write_while_saver_waits)
        try:
            staged = jobs.convert_legacy_queue_file(source, store)
            stdout, stderr = saver.communicate(timeout=10)
            assert saver.returncode == 0, stderr
            assert stdout.strip() == "saved"
        finally:
            if saver.poll() is None:
                saver.kill()
    assert [job.id for job in staged] == [BATCH, LATER_BATCH]
    assert alias.is_symlink()
    assert store.load() == jobs.JobStore(target).load() == (JOB,)
    assert set(target.parent.iterdir()) == {target, target.parent / ".jobs.json.lock"}
    assert not any(parent_tmp.iterdir()) and not any(child_tmp.iterdir())


if sys.platform != "win32":
    @pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
    def test_staging_and_forked_writer_serialize_via_file_lock(
        source: Path, store: jobs.JobStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fcntl = pytest.importorskip("fcntl")
        write_atomic, lockf = jobs.write_atomic, fcntl.lockf
        child_pid, wait_status = 0, None
        def fork_before_write(path: Path, data: bytes, mode: int | None = None) -> None:
            nonlocal child_pid
            read_fd, write_fd = os.pipe()

            def report_contention(fd: int, operation: int) -> None:
                if operation == fcntl.LOCK_EX:
                    with pytest.raises(BlockingIOError):
                        lockf(fd, operation | fcntl.LOCK_NB)
                    os.write(write_fd, b"blocked")
                lockf(fd, operation)
                if operation == fcntl.LOCK_EX:
                    assert [job.id for job in store.load()] == [BATCH, LATER_BATCH]

            child_pid = os.fork()
            if child_pid == 0:
                os.close(read_fd)
                exit_code = 1
                try:
                    monkeypatch.setattr(jobs, "write_atomic", write_atomic)
                    monkeypatch.setattr(fcntl, "lockf", report_contention)
                    assert jobs.JobStore(store.path).save([JOB]) == (JOB,)
                    exit_code = 0
                finally:
                    os._exit(exit_code)
            os.close(write_fd)
            with os.fdopen(read_fd, "rb", buffering=0) as signal:
                assert select.select([signal], [], [], 10)[0], "The forked writer did not reach its save"
                assert signal.read(7) == b"blocked", "The forked writer bypassed the file lock"
            write_atomic(path, data, mode=mode)

        monkeypatch.setattr(jobs, "write_atomic", fork_before_write)
        try:
            staged = jobs.convert_legacy_queue_file(source, store)
        finally:
            if child_pid:
                _, wait_status = os.waitpid(child_pid, 0)
        assert wait_status == 0
        assert [job.id for job in staged] == [BATCH, LATER_BATCH]
        assert store.load() == (JOB,)


    def _try_lock(lock: Callable[[int, int], object], fd: int, operation: int) -> None:
        fcntl = pytest.importorskip("fcntl")
        if operation == fcntl.LOCK_EX:
            operation |= fcntl.LOCK_NB
        lock(fd, operation)


    def _save_after_lock_owner_exits(
        store: jobs.JobStore, start_fd: int, result_fd: int, patch: pytest.MonkeyPatch
    ) -> NoReturn:
        fcntl = pytest.importorskip("fcntl")
        result = b"failed"
        try:
            patch.undo()
            assert select.select([start_fd], [], [], 10)[0]
            assert os.read(start_fd, 1) == b"1"
            for name in ("flock", "lockf"):
                patch.setattr(fcntl, name, partial(_try_lock, getattr(fcntl, name)))
            assert jobs.JobStore(store.path).save([JOB]) == (JOB,)
            result = b"saved"
        except jobs.JobStoreError as error:
            if isinstance(error.__cause__, BlockingIOError):
                result = b"blocked"
        finally:
            os.write(result_fd, result)
            os._exit(0 if result == b"saved" else 1)


    def _exit_during_conversion(source: Path, store: jobs.JobStore, start_fd: int, result_fd: int) -> NoReturn:
        lock_path = store.path.resolve().with_name(f".{store.path.name}.lock")
        open_file = os.open
        patch = pytest.MonkeyPatch()

        def open_then_fork(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes], flags: int, mode: int = 0o777,
            *, dir_fd: int | None = None,
        ) -> int:
            fd = open_file(path, flags, mode, dir_fd=dir_fd)
            if path == lock_path and os.fork() == 0:
                _save_after_lock_owner_exits(store, start_fd, result_fd, patch)
            return fd

        try:
            patch.setattr(os, "open", open_then_fork)
            patch.setattr(os, "replace", lambda src, dst: os._exit(0))
            jobs.convert_legacy_queue_file(source, store)
        finally:
            os._exit(1)


    @pytest.mark.skipif(not hasattr(os, "fork"), reason="fork unavailable")
    def test_fork_during_lock_open_releases_on_parent_exit(source: Path, store: jobs.JobStore) -> None:
        pytest.importorskip("fcntl")
        start_read, start_write = os.pipe()
        result_read, result_write = os.pipe()
        helper_pid = os.fork()
        if helper_pid == 0:
            os.close(start_write)
            os.close(result_read)
            _exit_during_conversion(source, store, start_read, result_write)
        os.close(start_read)
        os.close(result_write)
        try:
            _, wait_status = os.waitpid(helper_pid, 0)
            assert os.waitstatus_to_exitcode(wait_status) == 0
            assert store.load() == ()
            os.write(start_write, b"1")
            assert select.select([result_read], [], [], 10)[0], "The grandchild did not report its save result"
            assert os.read(result_read, 7) == b"saved"
        finally:
            os.close(start_write)
            os.close(result_read)
        assert store.load() == (JOB,)


def test_converts_both_queue_formats_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny_side_effect(*args: object, **kwargs: object) -> None:
        pytest.fail("Offline conversion started work or performed I/O")

    manual = {"episodes": [3], "proxy": "nordvpn:fr"}
    retry = {"episodes": [4], "paused": True, "replace": True, "kind": "retry", "audio": "fr",
             "sonarr": "4K", "numbering": {"season_map": {"2": 1}}}
    for obj, name in ((socket, "socket"), (threading.Thread, "start"), (Path, "read_bytes"), (Path, "read_text")):
        monkeypatch.setattr(obj, name, deny_side_effect)
    first, second = jobs.convert_legacy_queue(OLD_QUEUE, converted_at=CONVERTED)
    entries = {batch: [entry] for batch, entry in LEGACY.items()}
    assert jobs.convert_legacy_queue(entries, converted_at=CONVERTED) == (first, second)
    active, = jobs.convert_legacy_queue(
        {BATCH: [manual, retry, {**manual, "episodes": [5, 4]}, {**retry, "episodes": [4, 4]}]},
        converted_at=CONVERTED,
    )
    assert [job.id for job in (first, second)] == [BATCH, LATER_BATCH]
    assert (first.state, first.request.sonarr, first.created_at, first.updated_at) == ("paused", "4K", CREATED, CONVERTED)
    assert [(item.id, item.label) for item in first.request.items] == [
        ("sonarr:4K:3", "4K Episode 3"), ("sonarr:4K:4", "4K Episode 4"),
    ]
    assert first.request.effective_options == {
        "kind": "retry", "replace": True, "options": {"options": {"--a-lang": ("fr",)}},
        "proxy": "nordvpn:fr", "video": {"vcodec": "H.265", "quality": 2160}, "numbering": {"season_map": {2: 1}},
    }
    assert second.request.effective_options["numbering"] == {}
    assert active.state == "paused" and active.id == BATCH
    assert [child.id for child in active.children] == [f"{BATCH}:sonarr:{ep}" for ep in (3, "4K:4", 5, 4)]
    assert [item.label for item in active.request.items] == ["Episode 3", "4K Episode 4", "Episode 5", "Episode 4"]
    assert active.request.effective_options == {
        "kind": "manual", "replace": False, "proxy": "nordvpn:fr", "item_options": {
            "sonarr:4K:4": {"kind": "retry", "replace": True, "audio": "fr", "sonarr": "4K",
                            "numbering": {"season_map": {2: 1}}},
        },
    }


@pytest.mark.parametrize("instance, escaped", [("4K", "4K"), ("4K:/%", "4K%3A%2F%25")])
def test_episode_identity_is_scoped_to_its_sonarr_instance(instance: str, escaped: str) -> None:
    main = {"sonarr": "", "episodes": [3], "audio": "en"}
    named = {"sonarr": instance, "episodes": [3], "audio": "fr"}
    named_id = f"sonarr:{escaped}:3"
    job, = jobs.convert_legacy_queue({BATCH: [main, named]})
    assert [child.id for child in job.children] == [f"{BATCH}:sonarr:3", f"{BATCH}:{named_id}"]
    assert [item.label for item in job.request.items] == ["Episode 3", f"{instance} Episode 3"]
    assert job.request.effective_options["item_options"] == {
        named_id: {"kind": "manual", "replace": False, "sonarr": instance, "audio": "fr"},
    }
    remaining, = jobs.convert_legacy_queue({BATCH: named})
    assert remaining.children == (job.children[1],)
    reversed_job, = jobs.convert_legacy_queue({BATCH: [named, main]})
    assert reversed_job.children == tuple(reversed(job.children))
    assert reversed_job.request.effective_options["item_options"] == {
        "sonarr:3": {"kind": "manual", "replace": False, "sonarr": None, "audio": "en"},
    }


@pytest.mark.parametrize("when", [None, CONVERTED.astimezone(timezone(timedelta(hours=11)))])
def test_invalid_batch_calendar_uses_utc_fallback(when: datetime | None) -> None:
    job, = jobs.convert_legacy_queue({"20261321-121217-33d6d0": {"episodes": [3]}}, converted_at=when)
    expected = datetime(1970, 1, 1, tzinfo=timezone.utc) if when is None else CONVERTED
    assert job.created_at == job.updated_at == expected and job.created_at.tzinfo is timezone.utc


def test_coalesces_syncs_with_canonical_numbering_in_episode_order() -> None:
    numbering = {"season_map": {"2": "1"}, "episode_map": {" s2e3 ": "s1e2.2"}, "episode_offset": "-1",
                 "season_offset": "1", "season_offset_from": "3", "parts": "2", "join_parts": False,
                 "episode_name": "always", "file_name": " Title "}
    options = {"quality": 2160, "langs": ["fr"]}
    entry = {"episodes": [5, 3, 5], "sonarr": "4K", "options": options, "numbering": numbering}
    equivalent = {**entry, "episodes": [3, 4, 5], "options": dict(reversed(tuple(options.items()))),
                  "numbering": {**numbering, "season_map": {2: 1}}}
    job, = jobs.convert_legacy_queue({BATCH: [entry, equivalent]})
    assert [child.request.sonarr_episode_id for child in job.children] == [5, 3, 4]
    for sync in (entry, equivalent):
        assert jobs.convert_legacy_queue({BATCH: {**sync, "episodes": [5, 3, 4]}}) == (job,)
    assert job.request.effective_options["numbering"] == {
        **numbering, "season_map": {2: 1}, "episode_map": {"S02E03": "S01E02.2"}, "episode_offset": -1,
        "season_offset": 1, "season_offset_from": 3, "parts": 2, "file_name": "Title",
    }


@pytest.mark.parametrize("parts, name", [(0, "joined"), (None, None), ("", ""), (False, False)])
def test_legacy_numbering_omits_defaults(parts: int | str | None, name: str | bool | None) -> None:
    numbering = {"parts": parts, "episode_offset": "0", "season_offset": 0, "season_offset_from": "9",
                 "join_parts": True, "episode_name": name, "file_name": "  "}
    job, = jobs.convert_legacy_queue({BATCH: {"episodes": [3], "numbering": numbering}})
    assert job.request.effective_options["numbering"] == {}


@pytest.mark.parametrize("case", [
    {"parts": 0.0}, {"episode_map": False}, {"season_map": False},
    {"join_parts": 0}, {"join_parts": 1}, {"join_parts": "no"}, {"file_name": False},
    {"season_offset_from": "unused"}, {"season_offset": 0, "season_offset_from": "unused"},
    {"episode_name": 0}, {"episode_name": False}, {"extra": "ignored"},
    {"episode_offset": True, "season_offset": 2.0, "file_name": 7},
    {"season_map": {"2": True, "3": 1.0, "04": "4"}},
    {"season_offset": 1, "season_offset_from": True},
    {"season_offset": 1, "season_offset_from": 3.0},
    {"season_map": {"2": "1"}, "episode_map": {" s2e3 ": "s1e2.2"}, "episode_offset": "-1",
     "season_offset": "1", "season_offset_from": "3", "parts": "2", "join_parts": False,
     "episode_name": "always", "file_name": " Title ", "extra": "ignored"},
])
def test_legacy_numbering_matches_web(case: dict[str, object]) -> None:
    from unshacklarr import web

    job, = jobs.convert_legacy_queue({BATCH: {"episodes": [3], "numbering": case}})
    assert job.request.effective_options["numbering"] == web.check_numbering(case, "job")


def test_legacy_numbering_matches_resaved_queue(source: Path, store: jobs.JobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    from unshacklarr import sync, web

    entry = {"episodes": [3], "numbering": {"episode_offset": True, "season_offset": 2.0, "file_name": 7}}
    source.write_text(json.dumps({BATCH: entry}))
    monkeypatch.setattr(sync, "QUEUE_FILE", source)
    monkeypatch.setattr(sync, "restoring", {})
    monkeypatch.setattr(sync, "batch_jobs", {})
    started: list[object] = []
    monkeypatch.setattr(web, "run_sync", lambda ids, **kwargs: started.append(kwargs["numbering"]))
    expected = {"episode_offset": 1, "season_offset": 2, "file_name": "7"}
    assert web.resume_queue() == 1
    assert started == [expected]
    sync.save_queue()
    assert json.loads(source.read_bytes()) == {BATCH: [entry]}
    job, = jobs.convert_legacy_queue_file(source, store)
    assert job.request.effective_options["numbering"] == expected


def test_legacy_numbering_accepts_falsy_fields_in_read_only_snapshots() -> None:
    numbering = MappingProxyType({
        "parts": False, "episode_offset": False, "season_offset": False, "episode_name": False, "file_name": False,
        "season_offset_from": False, "join_parts": None, "season_map": None, "episode_map": None,
    })
    mapped = MappingProxyType({
        "episode_offset": "", "season_offset": "1", "season_offset_from": 0,
        "season_map": MappingProxyType({2: 1}), "episode_map": MappingProxyType({"s2e3": "s1e2.2"}),
    })
    first = MappingProxyType({"episodes": (3,), "options": MappingProxyType({"langs": ("fr",)}), "numbering": numbering})
    second = MappingProxyType({"episodes": (4,), "numbering": mapped})
    job, = jobs.convert_legacy_queue(MappingProxyType({BATCH: (first, second)}))
    assert job.request.effective_options == {
        "kind": "manual", "replace": False, "options": {"langs": ("fr",)}, "numbering": {},
        "item_options": {"sonarr:4": {"kind": "manual", "replace": False, "numbering": {
            "season_offset": 1, "season_map": {2: 1}, "episode_map": {"S02E03": "S01E02.2"},
        }}},
    }


@pytest.mark.parametrize("raw", [b"\xff", '{"broken":', "null", "[]", {"bad-batch": {"episodes": [3]}},
                                 f'{{"{BATCH}":{{"episodes":[3]}},"{BATCH}":{{"episodes":[4]}}}}',
                                 f'{{"{BATCH}":{{"episodes":[3],"options":{{"quality":720,"quality":1080}}}}}}',
                                 {BATCH: []}, {BATCH: [None]}, {BATCH: {"episodes": []}},
                                 {BATCH: {"episodes": [True]}}, {BATCH: {"episodes": [-1]}}])
def test_rejects_invalid_legacy_queue(raw: bytes | str | Mapping[str, object]) -> None:
    with pytest.raises(jobs.LegacyQueueConversionError):
        jobs.convert_legacy_queue(raw)


@pytest.mark.parametrize("fields", [
    {"paused": 1}, {"kind": ""}, {"replace": 1}, {"sonarr": False}, {"options": []}, {"service_options": False},
    {"proxy": ""}, {"video": []}, {"audio": 1}, {"numbering": None},
    *({"numbering": {key: value}} for key, value in (
        ("episode_offset", "x"), ("season_offset", "x"), ("season_offset", float("inf")),
        ("season_map", {"2": "x"}), ("season_map", [1]), ("episode_map", [1]),
        ("episode_map", {"S02E03": "wrong"}), ("parts", True), ("parts", "0"), ("parts", "02"),
        ("parts", 2.0), ("parts", 5), ("episode_name", "raw"))),
    *({"numbering": {"season_offset": 1, "season_offset_from": bad}} for bad in ("unused", float("nan"))),
])
def test_rejects_damaged_legacy_options(fields: dict[str, object]) -> None:
    with pytest.raises(jobs.LegacyQueueConversionError):
        jobs.convert_legacy_queue({BATCH: {"episodes": [3], **fields}})


def test_file_staging_reconciles_the_whole_snapshot(source: Path, store: jobs.JobStore) -> None:
    retry = {"episodes": [9], "kind": "retry", "numbering": {"season_map": {"2": 1}}}
    original = json.dumps({**LEGACY, BATCH: [{"episodes": [3]}, retry]}).encode()
    source.write_bytes(original)
    unowned = replace(JOB, id="20261021-121219-55d6d0")
    store.save([unowned])
    initial = jobs.convert_legacy_queue_file(source, store, converted_at=CONVERTED)
    assert [job.id for job in initial] == [unowned.id, BATCH, LATER_BATCH]
    next_day = CONVERTED + timedelta(days=1)
    assert jobs.convert_legacy_queue_file(source, store.path, converted_at=next_day) == initial
    assert source.read_bytes() == original
    _, active, later = initial
    earlier = CREATED - timedelta(days=1)
    store.save([unowned, replace(active, created_at=earlier), later])
    assert json.loads(store.path.read_bytes())["staged_job_ids"] == [BATCH, LATER_BATCH]
    source.write_text(json.dumps({BATCH: [retry]}))
    _, updated = jobs.convert_legacy_queue_file(source, store, converted_at=next_day)
    assert updated.id == BATCH and updated.updated_at == next_day and updated.created_at == earlier
    assert [child.id for child in updated.children] == [f"{BATCH}:sonarr:9"]
    assert store.load() == (unowned, updated)
    source.write_bytes(b"{}")
    assert jobs.convert_legacy_queue_file(source, store) == store.load() == (unowned,)
    assert set(json.loads(store.path.read_bytes())) == {"schema_version", "jobs"}
    assert source.read_bytes() == b"{}"


@pytest.mark.parametrize("state", ["running", "waiting"])
def test_restaging_preserves_saved_job_and_child_progress(
    source: Path, store: jobs.JobStore, state: jobs.JobState
) -> None:
    first, later = jobs.convert_legacy_queue_file(source, store, converted_at=CONVERTED)
    failed = replace(
        first.children[0], state="failed", attempt_job_id="attempt-1", interruption_count=2,
        failure=jobs.FailureClassification("child", "download"),
    )
    saved = replace(
        first, state=state, children=(failed, *first.children[1:]),
        created_at=CREATED - timedelta(days=1), updated_at=CONVERTED + timedelta(days=1),
    )
    store.save([saved, later])
    assert jobs.convert_legacy_queue_file(
        source, store, converted_at=CONVERTED + timedelta(days=2),
    ) == store.load() == (saved, later)

    revised_options = {"options": {"--a-lang": ["de"]}}
    source.write_text(json.dumps({**LEGACY, BATCH: {**LEGACY[BATCH], "options": revised_options}}))
    updated, untouched = jobs.convert_legacy_queue_file(source, store, converted_at=CONVERTED)
    assert updated.request.effective_options["options"] == {"options": {"--a-lang": ("de",)}}
    assert updated.children == saved.children and updated.state == state
    assert (updated.created_at, updated.updated_at) == (saved.created_at, saved.updated_at)
    assert untouched == later and store.load() == (updated, later)


def test_first_restage_of_pre_baseline_store_preserves_saved_parent_state(
    source: Path, store: jobs.JobStore
) -> None:
    source.write_text(json.dumps({BATCH: {**LEGACY[BATCH], "paused": True}}))
    incoming, = jobs.convert_legacy_queue(source.read_bytes())
    saved = replace(incoming, state="waiting")
    store.path.write_text(json.dumps({
        "schema_version": 1, "jobs": [saved.to_dict()], "staged_job_ids": [BATCH],
    }))
    assert store.load() == (saved,)

    assert jobs.convert_legacy_queue_file(source, store) == store.load() == (saved,)
    baselines = json.loads(store.path.read_bytes())["staged_baselines"]
    assert baselines == {BATCH: {"request": incoming.request.to_dict(), "state": "paused"}}


@pytest.mark.parametrize(("paused", "saved_state", "expected_state"), [
    (False, "waiting", "paused"),
    (True, "paused", "waiting"),
    (False, "running", "running"),
    (True, "running", "running"),
])
def test_restaging_applies_source_pause_changes_only_to_waiting_or_paused_parents(
    source: Path, store: jobs.JobStore, paused: bool, saved_state: jobs.JobState, expected_state: jobs.JobState
) -> None:
    source.write_text(json.dumps({BATCH: {**LEGACY[BATCH], "paused": paused}}))
    initial, = jobs.convert_legacy_queue_file(source, store)
    store.save([replace(initial, state=saved_state)])

    source.write_text(json.dumps({BATCH: {**LEGACY[BATCH], "paused": not paused}}))
    updated, = jobs.convert_legacy_queue_file(source, store)
    assert updated.state == expected_state
    assert store.load() == (updated,)


def test_overlapping_staging_publishes_in_lock_order(
    source: Path, store: jobs.JobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    source.write_text(json.dumps({BATCH: {"episodes": [101]}}))
    latest = json.dumps({BATCH: {"episodes": [102]}}).encode()
    reached_lock, release = threading.Event(), threading.Event()
    acquire_lock = jobs._acquire_lock
    caller = threading.current_thread()

    def wait_before_lock(target: Path) -> AbstractContextManager[None]:
        if threading.current_thread() is not caller:
            reached_lock.set()
            assert release.wait(timeout=10), "The first conversion was never released"
        return acquire_lock(target)

    monkeypatch.setattr(jobs, "_acquire_lock", wait_before_lock)
    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(jobs.convert_legacy_queue_file, source, store)
        try:
            assert reached_lock.wait(timeout=10), "The first conversion did not reach the lock"
            source.write_bytes(latest)
            second, = jobs.convert_legacy_queue_file(source, store)
            assert [child.request.sonarr_episode_id for child in second.children] == [102]
        finally:
            release.set()
        staged, = first.result(timeout=10)

    assert [child.request.sonarr_episode_id for child in staged.children] == [102]
    assert source.read_bytes() == latest
    assert store.load() == (second,)


def test_file_conversion_refuses_source_alias(tmp_path: Path) -> None:
    source, alias = tmp_path / "legacy.json", tmp_path / "alias.json"
    source.write_bytes(OLD_QUEUE)
    targets = [source, tmp_path / "queue.json"]
    try:
        alias.symlink_to(source)
    except (OSError, NotImplementedError):
        if os.name != "nt":
            raise
    else:
        targets.append(alias)
    for target in targets:
        with pytest.raises(ValueError):
            jobs.convert_legacy_queue_file(source, target)
    assert source.read_bytes() == OLD_QUEUE


def test_staging_cannot_claim_an_unstaged_job(source: Path, store: jobs.JobStore) -> None:
    running = replace(JOB, id=BATCH, state="running")
    store.save([running])
    original = store.path.read_bytes()
    with pytest.raises(jobs.JobStoreError):
        jobs.convert_legacy_queue_file(source, store)
    assert store.path.read_bytes() == original
    assert store.load() == (running,)
    source.write_bytes(b"{}")
    assert jobs.convert_legacy_queue_file(source, store) == store.load() == (running,)


def test_staging_distinguishes_boolean_integer_and_float_options(source: Path, store: jobs.JobStore) -> None:
    def sync(episode: int, flag: bool | int | float) -> dict[str, object]:
        return {"episodes": [episode], "service_options": {"-B": flag}}

    source.write_text(json.dumps({BATCH: [sync(3, True), sync(4, 1), sync(5, 1.0)]}))
    initial, = jobs.convert_legacy_queue_file(source, store)
    source.write_text(json.dumps({BATCH: [sync(3, 1), sync(4, True), sync(5, 1.0)]}))
    updated, = jobs.convert_legacy_queue_file(source, store, converted_at=CONVERTED)
    saved, = store.load()
    assert updated == saved and updated != initial
    base = saved.request.effective_options["service_options"]
    assert isinstance(base, Mapping) and base["-B"] == 1 and type(base["-B"]) is int
    overrides = saved.request.effective_options["item_options"]
    assert isinstance(overrides, Mapping)
    assert overrides["sonarr:4"]["service_options"]["-B"] is True
    flag = overrides["sonarr:5"]["service_options"]["-B"]
    assert type(flag) is float and flag == 1.0
    encoded = saved.to_dict()["request"]
    assert isinstance(encoded, dict)
    assert set(encoded) == {"service", "title_id", "items", "effective_options", "sonarr"}


def test_store_rejects_option_type_changes_during_encoding(store: jobs.JobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    original = replace(JOB, request=replace(REQUEST, effective_options={"service_options": {"-B": True}}))
    store.save([original])
    altered = replace(original, request=replace(REQUEST, effective_options={"service_options": {"-B": 1}})).to_dict()
    monkeypatch.setattr(jobs.DownstreamJob, "to_dict", lambda self: altered)
    with pytest.raises(jobs.JobStoreError):
        store.save([original])
    assert store.load() == (original,)


def test_staging_keeps_an_interleaved_save(source: Path, store: jobs.JobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    original = json.dumps({f"{key[:16]}{index:06x}": entry for key, entry in LEGACY.items() for index in range(10)}).encode()
    source.write_bytes(original)
    store.save([])
    read_bytes = Path.read_bytes

    def read_then_save(path: Path) -> bytes:
        snapshot = read_bytes(path)
        if path == store.path:
            monkeypatch.setattr(Path, "read_bytes", read_bytes)
            jobs.JobStore(path.resolve()).save([JOB])
        return snapshot

    monkeypatch.setattr(Path, "read_bytes", read_then_save)
    extra, *converted = jobs.convert_legacy_queue_file(source, store)
    assert extra == JOB and len(converted) == 20
    assert len({child.id for job in converted for child in job.children}) == 30
    assert store.load() == jobs.convert_legacy_queue_file(source, store) == (extra, *converted)
    assert source.read_bytes() == original


def test_legacy_option_edit_keeps_staged_ids(source: Path, store: jobs.JobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNSHACKLARR_DATA", str(source.parent))
    from unshacklarr import sync, web

    sync, web = importlib.reload(sync), importlib.reload(web)
    started: list[tuple[list[int], object]] = []
    monkeypatch.setattr(web, "run_sync", lambda ids, **kwargs: started.append((ids, kwargs["replace"])))
    staged = jobs.convert_legacy_queue_file(source, store)
    assert not started
    assert web.resume_queue() == 3 and started == [([3, 4], True), ([7], False)]
    sync.save_queue()
    assert json.loads(sync.QUEUE_FILE.read_bytes()) == {batch: [entry] for batch, entry in LEGACY.items()}
    assert store.load() == staged

    monkeypatch.setattr(web, "known_services", lambda: None)
    sync.running_jobs[BATCH] = {"episodes": [], "stubs": {}}
    sync.batch_jobs[BATCH] = [sync.running_jobs[BATCH]]
    body = {"options": {"--a-lang": "en"}}
    request = SimpleNamespace(method="POST", match_info={"batch": BATCH}, json=AsyncMock(return_value=body))
    assert asyncio.run(web.job_options(request)).status == 200
    sync.save_queue()
    updated, later = jobs.convert_legacy_queue_file(source, store)
    assert later == staged[1] and staged[0].id == updated.id == BATCH
    assert [child.id for child in updated.children] == [child.id for child in staged[0].children]
    assert updated.request.effective_options["options"] == {**body, "service_options": {}}
