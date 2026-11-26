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
    with pytest.raises(jobs.JobStoreError):
        store.save([first])
    assert store.load() == (newer,)


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX directory sync")
def test_store_syncs_parent_directory_after_atomic_rename(
    store: jobs.JobStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_atomic, fsync, open_fd = jobs.write_atomic, os.fsync, os.open
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

    def deny_open(path: str | bytes | os.PathLike[str] | os.PathLike[bytes], flags: int, mode: int = 0o777) -> int:
        if os.fspath(path) == os.fspath(store.path.parent):
            raise PermissionError(errno.EACCES, "unreadable directory")
        return open_fd(path, flags, mode)

    calls.clear()
    monkeypatch.setattr(os, "open", deny_open)
    with pytest.raises(jobs.JobStoreError):
        store.save([replace(JOB, state="paused")])
    assert "renamed" not in calls and store.load() == (JOB,)


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
    monkeypatch.setattr(sync, "JOBS_FILE", store.path)
    monkeypatch.setattr(sync, "batch_jobs", {})
    started: list[object] = []
    monkeypatch.setattr(web, "run_sync", lambda ids, **kwargs: started.append(kwargs["numbering"]))
    expected = {"episode_offset": 1, "season_offset": 2, "file_name": "7"}
    assert web.resume_queue() == 1
    assert started == [expected]
    sync.save_queue()
    assert json.loads(source.read_bytes()) == {BATCH: entry}
    job, = store.load()
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


def test_restaging_pause_preserves_live_request_and_new_episode_reopens_terminal(
    source: Path, store: jobs.JobStore
) -> None:
    first, _ = jobs.convert_legacy_queue_file(source, store, converted_at=CONVERTED)
    live_request = replace(first.request, service="crunchyroll", title_id="show-1",
                           effective_options={**first.request.effective_options, "custom": "live"})
    live = replace(first, state="paused", request=live_request, children=tuple(
        replace(child, request=item) for child, item in zip(first.children, live_request.items, strict=True)
    ))
    store.save([live])

    source.write_text(json.dumps({BATCH: {**LEGACY[BATCH], "paused": False}}))
    toggled, = jobs.convert_legacy_queue_file(source, store, converted_at=CONVERTED + timedelta(hours=1))
    assert toggled.state == "waiting" and toggled.request == live_request and toggled.children == live.children

    done = replace(toggled, state="completed", children=tuple(replace(c, state="completed") for c in toggled.children))
    store.save([done])
    source.write_text(json.dumps({BATCH: {**LEGACY[BATCH], "paused": False, "episodes": [3, 4, 5]}}))
    reopened, = jobs.convert_legacy_queue_file(source, store, converted_at=CONVERTED + timedelta(hours=2))
    assert reopened.state == "waiting"
    assert [child.state for child in reopened.children] == ["completed", "completed", "waiting"]
    terminal_states: tuple[jobs.JobState, ...] = ("cancelled", "removed")
    for terminal in terminal_states:
        blocked = replace(reopened, state=terminal)
        store.save([blocked])
        source.write_text(json.dumps({BATCH: {**LEGACY[BATCH], "paused": False, "episodes": [3, 4, 5, 6]}}))
        with pytest.raises(jobs.LegacyQueueConversionError):
            jobs.convert_legacy_queue_file(source, store, converted_at=CONVERTED + timedelta(hours=3))
        assert store.load() == (blocked,)


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


def test_legacy_option_edit_keeps_staged_ids(source: Path, store: jobs.JobStore) -> None:
    staged = jobs.convert_legacy_queue_file(source, store)
    options = {"options": {"--a-lang": "en"}, "service_options": {}}
    source.write_text(json.dumps({**LEGACY, BATCH: {**LEGACY[BATCH], "options": options}}))

    updated, later = jobs.convert_legacy_queue_file(source, store)
    assert later == staged[1] and staged[0].id == updated.id == BATCH
    assert [child.id for child in updated.children] == [child.id for child in staged[0].children]
    assert updated.request.effective_options["options"] == options
    assert json.loads(store.path.read_bytes())["staged_job_ids"] == [BATCH, LATER_BATCH]


def test_live_option_edit_preserves_migrated_job_and_child_ids(source: Path, store: jobs.JobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNSHACKLARR_DATA", str(source.parent))
    from unshacklarr import sync, web

    sync, web = importlib.reload(sync), importlib.reload(web)
    started: list[tuple[list[int], object]] = []
    monkeypatch.setattr(web, "run_sync", lambda ids, **kwargs: started.append((ids, kwargs["replace"])))
    staged = jobs.convert_legacy_queue_file(source, store)
    assert not started
    assert web.resume_queue() == 3 and started == [([3, 4], True), ([7], False)]
    sync.save_queue()
    assert sync.QUEUE_FILE.read_bytes() == OLD_QUEUE
    document = json.loads(store.path.read_bytes())
    assert "staged_job_ids" not in document and "staged_baselines" not in document
    assert store.load() == staged

    monkeypatch.setattr(web, "known_services", lambda: None)
    sync.running_jobs[BATCH] = {"episodes": [], "stubs": {}}
    sync.batch_jobs[BATCH] = [sync.running_jobs[BATCH]]
    body = {"options": {"--a-lang": "en"}}
    request = SimpleNamespace(method="POST", match_info={"batch": BATCH}, json=AsyncMock(return_value=body))
    assert asyncio.run(web.job_options(request)).status == 200
    sync.save_queue()
    updated, later = store.migrate_legacy_queue(source)
    assert later == staged[1] and staged[0].id == updated.id == BATCH
    assert [child.id for child in updated.children] == [child.id for child in staged[0].children]
    assert updated.request.effective_options["options"] == {**body, "service_options": {}}


def test_durable_admission_outcomes(store: jobs.JobStore) -> None:
    assert store.admit(REQUEST, job_id=BATCH, now=CREATED).outcome == "added"
    assert store.admit(REQUEST).outcome == "already_queued"
    overlap = replace(REQUEST, effective_options={"replace": True})
    refusal = store.admit(overlap)
    assert isinstance(refusal, jobs.Refused) and refusal.code == "partial_overlap"
    store.complete_child(BATCH, ITEM.id)
    assert store.admit(overlap).outcome == "added"


def test_live_migration_ignores_legacy_after_cutover(source: Path, store: jobs.JobStore) -> None:
    source.write_bytes(OLD_QUEUE)
    records = store.migrate_legacy_queue(source, converted_at=CONVERTED)
    assert source.read_bytes() == OLD_QUEUE
    source.write_bytes(b"broken")
    assert store.migrate_legacy_queue(source) == records


def test_live_migration_reads_queue_after_empty_staging(source: Path, store: jobs.JobStore) -> None:
    source.write_text("{}")
    assert jobs.convert_legacy_queue_file(source, store) == ()
    assert store.path.is_file()
    source.write_text(json.dumps({BATCH: LEGACY[BATCH]}))

    migrated, = store.migrate_legacy_queue(source, converted_at=CONVERTED)
    assert migrated.id == BATCH
    assert [child.request.sonarr_episode_id for child in migrated.children] == [3, 4]
    source.write_text(json.dumps({LATER_BATCH: LEGACY[LATER_BATCH]}))
    assert jobs.JobStore(store.path).migrate_legacy_queue(source) == (migrated,)


def test_missing_legacy_source_promotes_staged_records_and_keeps_pause(
    source: Path, store: jobs.JobStore,
) -> None:
    first, later = jobs.convert_legacy_queue_file(source, store)
    store.set_job_paused(later.id, True)
    store.pause_all()
    paused_first = store.get_job(first.id)
    assert paused_first is not None
    store.save([paused_first])
    staged = json.loads(store.path.read_bytes())
    assert staged["staged_job_ids"] == [first.id]
    assert set(staged["staged_baselines"]) == {first.id}
    assert "paused_job_ids" not in staged and staged["paused_all"] is True

    source.unlink()
    assert store.migrate_legacy_queue(source) == (paused_first,)
    assert store.pause_state() == (True, ())
    live = json.loads(store.path.read_bytes())
    assert "staged_job_ids" not in live and "staged_baselines" not in live


def test_missing_attempt_is_recovered_once(store: jobs.JobStore) -> None:
    store.admit(REQUEST, job_id=BATCH, now=CREATED)
    for attempt in ("first", "second"):
        store.start_child_attempt(BATCH, ITEM.id, attempt)
        records = store.reconcile_startup(lambda job, child: "missing")
    child = records[0].children[0]
    assert (child.state, child.interruption_count, child.attempt_job_id) == ("failed", 2, None)


@pytest.mark.parametrize("document", [
    b'{"schema_version": 1, "jobs": [], "jobs": []}',
    b'{"schema_version": 1, "jobs": [], "paused_all": 1}',
])
def test_durable_store_rejects_ambiguous_documents(store: jobs.JobStore, document: bytes) -> None:
    store.path.write_bytes(document)
    with pytest.raises(jobs.JobStoreError):
        store.load()
    assert store.path.read_bytes() == document


def test_active_failure_points_to_failed_child_and_retry_preserves_terminal_siblings(store: jobs.JobStore) -> None:
    request = jobs.NormalizedJobRequest(None, None, tuple(jobs.episode_item(None, index) for index in range(1, 6)), {})
    assert store.admit(request, job_id=BATCH) == jobs.Added(BATCH)
    one, two, three, four, five = request.items
    store.complete_child(BATCH, one.id)
    store.cancel_child(BATCH, two.id)
    store.fail_child(BATCH, three.id, SHARED_FAILURE)
    failed = store.fail_child(BATCH, four.id, jobs.FailureClassification("child", "mux"))
    assert failed.state == "paused"
    refusal = store.admit(replace(request, items=(three,)))
    assert isinstance(refusal, jobs.Refused)
    assert (refusal.code, refusal.job_id, refusal.child_id) == ("active_failed_child", BATCH, failed.children[2].id)
    retried = store.retry_item(BATCH, three.id)
    assert [child.state for child in retried.children] == ["completed", "cancelled", "waiting", "failed", "waiting"]
    retried = store.retry_failed(BATCH)
    assert [child.state for child in retried.children] == ["completed", "cancelled", "waiting", "waiting", "waiting"]
    assert retried.state == "paused"
    for item in (three, four, five):
        finished = store.complete_child(BATCH, item.id)
    assert finished.state == "completed_with_errors"
    assert isinstance(store.admit(request), jobs.Added)


def test_retry_failed_refuses_completed_child_of_another_active_job(store: jobs.JobStore) -> None:
    first, second = (jobs.episode_item(None, episode_id) for episode_id in (1, 2))
    request = jobs.NormalizedJobRequest(None, None, (first,), {})
    assert store.admit(request, job_id=BATCH) == jobs.Added(BATCH)
    failed = store.fail_child(BATCH, first.id, jobs.FailureClassification("child", "download"))
    assert store.admit(replace(request, items=(first, second)), job_id=LATER_BATCH) == jobs.Added(LATER_BATCH)
    active = store.complete_child(LATER_BATCH, first.id)
    assert [child.state for child in active.children] == ["completed", "waiting"]

    with pytest.raises(jobs.JobStoreError, match="Cannot save job store"):
        store.retry_failed(BATCH)
    assert store.load() == (failed, active)


def test_startup_observes_attempts_without_rewriting_unchanged_records(store: jobs.JobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    assert store.admit(REQUEST, job_id=BATCH) == jobs.Added(BATCH)
    queued = store.start_child_attempt(BATCH, ITEM.id, "serve-job")
    assert queued.state == "running"
    with monkeypatch.context() as patch:
        patch.setattr(jobs, "write_atomic", lambda *args, **kwargs: pytest.fail("Should avoid writing unchanged records"))
        assert store.reconcile_startup(lambda job, child: "unreachable") == (queued,)
        assert store.reconcile_startup(lambda job, child: "queued") == (queued,)
    observed, = store.reconcile_startup(lambda job, child: "completed")
    assert observed.children[0].state == "downloading"
    assert observed.children[0].attempt_job_id == "serve-job"
    assert store.complete_child(BATCH, ITEM.id).state == "completed"


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX directory sync")
def test_failed_migration_sync_restores_staged_destination(source: Path, store: jobs.JobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    jobs.convert_legacy_queue_file(source, store)
    staged = store.path.read_bytes()
    original = source.read_bytes()

    sync = jobs._fsync_directory_fd

    def fail_sync(fd: int) -> None:
        if store.path.read_bytes() != staged:
            raise OSError("directory sync failed")
        sync(fd)

    monkeypatch.setattr(jobs, "_fsync_directory_fd", fail_sync)
    with pytest.raises(jobs.JobStoreError):
        store.migrate_legacy_queue(source)
    assert store.path.read_bytes() == staged
    assert source.read_bytes() == original


@pytest.mark.parametrize(("reason", "scope", "code"), [
    ("Login failed", "shared", "provider_access"),
    ("No CDM", "shared", "cdm_route"),
    ("proxy check failed", "shared", "proxy"),
    ("No space left on device", "shared", "storage"),
    ("Permission denied writing downloads", "shared", "output_path"),
    ("this is another episode, by its title", "child", "title"),
    ("list-tracks failed", "child", "manifest"),
    ("Widevine rejected the licence", "child", "licence"),
    ("mp4decrypt failed", "child", "decrypt"),
    ("mkvmerge failed", "child", "mux"),
    ("ffprobe failed", "child", "decode"),
])
def test_download_failure_classification(reason: str, scope: str, code: str) -> None:
    classified = jobs.classify_failure(reason)
    assert (classified.scope, classified.code) == (scope, code)


def test_files_403_do_not_pause_the_parent() -> None:
    result = jobs.classify_failure("403 download failed (authentication required)", error_code="FILES_REFUSED")
    assert result == jobs.FailureClassification("child", "download")


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX directory sync")
@pytest.mark.parametrize("existing", [False, True])
def test_review_admission_rolls_back_after_rename(store: jobs.JobStore, monkeypatch: pytest.MonkeyPatch,
                                                existing: bool) -> None:
    if existing:
        store.save([JOB])
    prior = store.path.read_bytes() if existing else None

    sync = jobs._fsync_directory_fd

    def fail_sync(fd: int) -> None:
        if store.path.exists() and store.path.read_bytes() != prior:
            raise OSError("directory sync failed")
        sync(fd)

    monkeypatch.setattr(jobs, "_fsync_directory_fd", fail_sync)
    other = replace(REQUEST, items=(jobs.episode_item(None, 42),))
    assert store.admit(other) == jobs.ADMISSION_PERSISTENCE_FAILURE
    assert (store.path.read_bytes() if store.path.exists() else None) == prior


@pytest.mark.parametrize("unreadable", [False, True])
def test_review_mutation_rolls_back_after_failed_readback(store: jobs.JobStore, monkeypatch: pytest.MonkeyPatch,
                                                          unreadable: bool) -> None:
    store.admit(REQUEST, job_id=BATCH)
    original = store.path.read_bytes()
    read = jobs._read_bytes
    calls = 0

    def read_once_incorrectly(target: Path) -> bytes | None:
        nonlocal calls
        calls += 1
        if unreadable and calls >= 3:
            raise OSError("read-back unavailable")
        return b"invalid read-back" if calls == 3 else read(target)

    monkeypatch.setattr(jobs, "_read_bytes", read_once_incorrectly)
    with pytest.raises(jobs.JobStoreError):
        store.complete_child(BATCH, ITEM.id)
    assert store.path.read_bytes() == original


def test_review_completed_item_still_belongs_to_active_parent(store: jobs.JobStore) -> None:
    request = replace(REQUEST, items=(ITEM, jobs.episode_item(None, 4)))
    store.admit(request, job_id=BATCH)
    store.complete_child(BATCH, ITEM.id)
    assert store.admit(request) == jobs.AlreadyQueued(BATCH)
    overlap = store.admit(REQUEST)
    assert isinstance(overlap, jobs.Refused) and overlap.code == "partial_overlap"


def test_review_legacy_queue_rejects_duplicate_json_keys() -> None:
    with pytest.raises(jobs.LegacyQueueConversionError):
        jobs.convert_legacy_queue(f'{{"{BATCH}":{{"episodes":[3],"episodes":[4]}}}}')


def test_review_explicit_pause_survives_running_child(store: jobs.JobStore) -> None:
    request = replace(REQUEST, items=(ITEM, jobs.episode_item(None, 4)))
    store.admit(request, job_id=BATCH)
    store.start_child_attempt(BATCH, ITEM.id, "attempt")
    store.set_job_paused(BATCH, True)
    assert store.mark_child_downloading(BATCH, ITEM.id).state == "running"
    store = jobs.JobStore(store.path)
    finished = store.complete_child(BATCH, ITEM.id)
    assert finished.state == "paused"
    assert json.loads(store.path.read_bytes())["paused_job_ids"] == [BATCH]
    store.resume_all()
    assert "paused_job_ids" not in json.loads(store.path.read_bytes())


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX directory sync")
@pytest.mark.parametrize(("operation", "fallback"), [
    ("admit", "empty"), ("admit", "in_place"), ("admit", "replace"),
    ("admit", "backup"), ("pause", "replace"),
])
def test_admission_double_fault_never_leaves_candidate(
    store: jobs.JobStore, monkeypatch: pytest.MonkeyPatch, operation: str, fallback: str,
) -> None:
    if fallback != "empty":
        assert store.admit(REQUEST, job_id=BATCH) == jobs.Added(BATCH)
    prior = store.load()
    original = store.path.read_bytes() if prior else None
    write = jobs.write_atomic
    sync = jobs._fsync_directory_fd
    candidate_written = False

    def fail_rollback(target: Path, data: str | bytes, *, mode: int) -> None:
        nonlocal candidate_written
        if data == original:
            raise OSError("atomic rollback failed")
        write(target, data, mode=mode)
        if target == store.path:
            candidate_written = True

    def fail_sync(fd: int) -> None:
        if candidate_written:
            raise OSError("directory sync failed")
        sync(fd)

    opened = Path.open

    def open_target(path: Path, mode: str = "r", *args: object, **kwargs: object):
        if path == store.path and mode == "r+b" and fallback != "in_place":
            raise OSError("in-place rollback failed")
        return opened(path, mode)

    backup = store.path.with_name(f"{store.path.name}.bak")
    atomic_replace = os.replace

    def fail_backup_replace(source: str | Path, target: str | Path) -> None:
        if Path(source) == backup and Path(target) == store.path:
            raise OSError("backup rename failed")
        atomic_replace(source, target)

    monkeypatch.setattr(jobs, "_fsync_directory_fd", fail_sync)
    monkeypatch.setattr(jobs, "write_atomic", fail_rollback)
    monkeypatch.setattr(Path, "open", open_target)
    if fallback == "backup":
        monkeypatch.setattr(os, "replace", fail_backup_replace)

    other = replace(REQUEST, items=(jobs.episode_item(None, 42),))
    if operation == "admit":
        assert store.admit(other) == jobs.ADMISSION_PERSISTENCE_FAILURE
    else:
        with pytest.raises(jobs.JobStoreError):
            store.pause_all()
    assert store.load() == prior
    assert jobs.JobStore(store.path).load() == prior
    if fallback == "backup":
        assert not store.path.exists() and backup.read_bytes() == original
        monkeypatch.undo()
        assert isinstance(store.admit(other), jobs.Added)
        assert jobs.JobStore(store.path).load()[0] == prior[0] and not backup.exists()
    elif prior:
        assert store.path.read_bytes() == original and not backup.exists()
    else:
        assert not store.path.exists() and not backup.exists()


def direct_request(*selectors: str | None) -> jobs.DirectDownloadRequest:
    return jobs.DirectDownloadRequest("TEST", "title", tuple(
        jobs.DirectItemRequest(str(index), selector, f"Item {index}") for index, selector in enumerate(selectors)
    ))


@pytest.mark.parametrize("selectors", [(), (None, None), (None, "S01E01"), ("",), ("S01",), ("S01E01-E02",),
                                       ("S01E01,S01E02",), ("s1e1", "S1E1"), ("S01E01\n",)])
def test_direct_invalid_selection(tmp_path, selectors):
    with pytest.raises(jobs.DirectRequestValidationError):
        direct_request(*selectors).to_normalized_request(tmp_path)


@pytest.mark.parametrize(("field", "value"), [
    ("service", "EXAMPLE"), ("service", "a b"), ("title_id", "-option"), ("title_id", "https://u:p@host/title"),
    ("title_id", "file:///movie"), ("title_id", "http:movie"), ("title_id", "https://host/"),
    ("title_id", "/absolute"), ("title_id", "a/../b"), ("title_id", "a\\b"), ("title_id", "a b"),
    ("output_dir", "relative"), ("output_dir", "/outside"),
])
def test_direct_invalid_field(tmp_path, field, value):
    with pytest.raises(jobs.DirectRequestValidationError):
        replace(direct_request(None), **{field: value}).to_normalized_request(tmp_path)


def test_direct_path_symlink_and_traversal(tmp_path):
    link = tmp_path / "link"
    link.symlink_to(tmp_path)
    for path in (link / "nested", tmp_path / ".." / tmp_path.name):
        with pytest.raises(jobs.DirectRequestValidationError):
            replace(direct_request(None), output_dir=str(path)).to_normalized_request(tmp_path)


def test_direct_admission_isolation_and_retry(store, tmp_path):
    req = direct_request(" s01e01 ", "S01E02.1").to_normalized_request(tmp_path)
    first = req.items[0]
    assert (first.selector, first.id) == ("S01E01", "direct:TEST:title:0")
    added = store.admit(req)
    assert isinstance(added, jobs.Added)
    assert store.admit(req) == jobs.AlreadyQueued(added.job_id)
    other = replace(req, items=(replace(first, id="direct:TEST:title:renamed"),))
    assert store.admit(other).code == "partial_overlap"
    store.start_child_attempt(added.job_id, "0", "attempt")
    store.fail_child(added.job_id, "0", jobs.classify_failure())
    assert store.admit(other).code == "active_failed_child"
    with pytest.raises(ValueError):
        store.start_child_attempt(added.job_id, "1", "attempt")
    with pytest.raises(ValueError):
        store.reconcile_child_attempt(added.job_id, "1", None, jobs.AttemptObservation("queued", attempt_id="attempt"))
    store.retry_items(added.job_id, ["0"])
    for item in req.items:
        store.complete_child(added.job_id, item.id)
    assert store.get_job(added.job_id).children[0].attempt_history == ("attempt",)
    assert isinstance(store.admit(other), jobs.Added)


def test_direct_retry_cannot_overlap_identical_new_job(tmp_path, store):
    req = direct_request(None).to_normalized_request(tmp_path)
    first = store.admit(req)
    store.fail_child(first.job_id, "0", jobs.classify_failure())
    second = store.admit(req)
    refusal = store.stage_activity_retry(first.job_id, req, reserve=lambda: None)
    assert refusal == jobs.Refused("partial_overlap", f"Already in active job {second.job_id}: Item 0. "
                                  "Change the selection or wait for that job to finish.", second.job_id)


def test_direct_startup_cannot_claim_attempt_twice(tmp_path, store):
    req = direct_request("S1E1", "S1E2").to_normalized_request(tmp_path)
    batch = store.admit(req).job_id
    submission = jobs.Submission("", "TEST", "title", str(tmp_path), (), CREATED)
    for item in req.items:
        store.set_child_submission(batch, item.id, submission)
    job, = store.reconcile_startup(lambda *_: jobs.AttemptObservation("completed", attempt_id="claimed"))
    assert all(c.attempt_job_id is None and c.submission == submission for c in job.children)
    store.start_child_attempt(batch, "0", "current")
    with pytest.raises(ValueError):
        store.reconcile_child_attempt(batch, "0", "current", jobs.AttemptObservation("completed", attempt_id="wrong"))
    with pytest.raises(ValueError):
        store.reconcile_child_attempt(batch, "0", None, "completed")


def test_direct_store_prefers_qualified_child_identity(tmp_path, store):
    first, second = direct_request("S1E1", "S1E2").items
    req = replace(direct_request(None), items=(replace(first, id="direct:TEST:title:1"), second)).to_normalized_request(tmp_path)
    batch = store.admit(req).job_id
    job = store.complete_child(batch, req.items[1].id)
    assert [c.state for c in job.children] == ["waiting", "completed"]


@pytest.mark.parametrize("item", [
    jobs.DirectItemRequest("", None, "Film"), jobs.DirectItemRequest("has space", None, "Film"),
    jobs.DirectItemRequest("id" * 65, None, "Film"), jobs.DirectItemRequest("id", None, ""),
    jobs.DirectItemRequest("id", None, "label" * 52), jobs.DirectItemRequest("id", None, "x\ny"),
    jobs.DirectItemRequest("id", None, "Bearer private"), jobs.DirectItemRequest("id", None, "x" * 32),
])
def test_direct_invalid_item_identity_and_label(tmp_path, item):
    with pytest.raises(jobs.DirectRequestValidationError):
        replace(direct_request(None), items=(item,)).to_normalized_request(tmp_path)


def test_direct_duplicate_trimmed_ids(tmp_path):
    items = (jobs.DirectItemRequest(" x", "S1E1", "One"), jobs.DirectItemRequest("x ", "S1E2", "Two"))
    with pytest.raises(jobs.DirectRequestValidationError):
        replace(direct_request(None), items=items).to_normalized_request(tmp_path)


@pytest.mark.parametrize("title", [
    "550e8400-e29b-41d4-a716-446655440000",
    "https://www.disneyplus.com/movies/the-lord-of-the-rings-the-fellowship-of-the-ring/550e8400-e29b-41d4-a716-446655440000",
    "https://www.stan.com.au/watch/everything-everywhere-all-at-once-2022",
])
def test_direct_public_title_ids(tmp_path, title):
    assert replace(direct_request(None), title_id=title).to_normalized_request(tmp_path).title_id == title


@pytest.mark.parametrize("title", ["https://example.org/a/../b", "https://example.org/a/%2e%2e/b", "a/%2e%2e/b",
                                   "https://example.org/a%5Cb", "a%20b", "eyJheader.payload.signature",
                                   *["https://example.org/a?" + k + "=x" for k in
                                     ("key", "sig", "signature", "session", "auth", "credential", "jwt", "passwd")]])
def test_direct_unsafe_title_ids(tmp_path, title):
    with pytest.raises(jobs.DirectRequestValidationError):
        replace(direct_request(None), title_id=title).to_normalized_request(tmp_path)


def test_direct_output_inside_aliased_ancestor(tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path)
    root = alias / "downloads"
    root.mkdir()
    for selected in (None, str(root / "movie"), str(root.resolve() / "movie")):
        assert jobs.direct_output_path(selected, root) == (Path(selected) if selected else root).resolve()
    (root / "linked").symlink_to(root)
    with pytest.raises(jobs.DirectRequestValidationError):
        jobs.direct_output_path(str(root / "linked" / "movie"), root)


def test_direct_selector_padding(tmp_path, store):
    with pytest.raises(jobs.DirectRequestValidationError):
        direct_request("S1E1", "S01E01").to_normalized_request(tmp_path)
    req = direct_request("S1E1.01").to_normalized_request(tmp_path)
    assert req.items[0].selector == "S01E01.1"
    store.admit(req)
    other = replace(direct_request(None), items=(jobs.DirectItemRequest("other", "S01E01.1", "Other"),))
    assert store.admit(other.to_normalized_request(tmp_path)).code == "partial_overlap"


def test_reconciliation_cannot_restore_ended_attempt(store, tmp_path):
    batch = store.admit(direct_request(None).to_normalized_request(tmp_path)).job_id
    store.start_child_attempt(batch, "0", "prior")
    store.clear_child_attempt(batch, "0", "prior")
    submission = jobs.Submission("", "TEST", "title", str(tmp_path), (), CREATED)
    store.set_child_submission(batch, "0", submission)
    observed = jobs.AttemptObservation("queued", attempt_id="prior")
    with pytest.raises(jobs.AttemptConflict):
        store.reconcile_child_attempt(batch, "0", None, observed)
    job, = store.reconcile_startup(lambda *_: observed)
    assert job.children[0].submission == submission
    assert job.children[0].attempt_job_id is None


def test_direct_stored_selector_normalizes_on_read():
    item = jobs.JobItemRequest.from_dict({"id": "direct:TEST:title:old", "label": "Episode",
                                          "sonarr_episode_id": None, "selector": "S1E1.01"})
    assert item.selector == "S01E01.1"
