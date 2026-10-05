import asyncio
import importlib
import json
from types import SimpleNamespace

import pytest
from aiohttp import client_exceptions

RESET_ERRORS = [ConnectionResetError]
if hasattr(client_exceptions, "ClientConnectionResetError"):
    RESET_ERRORS.append(client_exceptions.ClientConnectionResetError)


@pytest.mark.parametrize("mode", ["run", "batch"])
@pytest.mark.parametrize("failure", [*RESET_ERRORS, RuntimeError, asyncio.CancelledError, None])
def test_terminal_disconnect_preserves_job_and_other_errors(tmp_path, monkeypatch, mode, failure):
    monkeypatch.setenv("UNSHACKLARR_DATA", str(tmp_path))
    import unshacklarr.sync
    import unshacklarr.web
    importlib.reload(unshacklarr.sync)
    web = importlib.reload(unshacklarr.web)
    run_id = "20261005-000000-123456-1-S01E01"
    batch = "20261005-000000-abcdef"
    web.sonarr_sync.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (web.sonarr_sync.RUNS_DIR / f"{run_id}.log").write_bytes(b"fixture progress\n")
    (web.sonarr_sync.RUNS_DIR / f"{run_id}.json").write_text(json.dumps({"ended": "fixture"}))
    active = {run_id: object()}
    monkeypatch.setattr(web.sonarr_sync.EpisodeRun, "active", active)
    monkeypatch.setattr(web, "run_cards", lambda: [{"id": run_id, "batch": batch,
        "series": "Fixture", "sxxeyy": "S01E01", "outcome": "completed"}])

    class Socket:
        closed = False

        def __init__(self):
            self.sent = []

        async def prepare(self, request):
            pass

        async def send_bytes(self, data):
            if failure:
                raise failure("fixture transport or application failure")
            self.sent.append(data)

        async def close(self):
            self.closed = True

    socket = Socket()
    monkeypatch.setattr(web.web, "WebSocketResponse", lambda **kwargs: socket)
    request = SimpleNamespace(headers={"Origin": "http://localhost"}, host="localhost",
                              query={"run": run_id} if mode == "run" else {"batch": batch})
    if failure in (RuntimeError, asyncio.CancelledError):
        with pytest.raises(failure):
            asyncio.run(web.terminal(request))
    else:
        assert asyncio.run(web.terminal(request)) is socket
        if failure is None:
            assert b"fixture progress\n" in socket.sent
            assert socket.closed
    assert web.sonarr_sync.EpisodeRun.active is active
    assert run_id in active
