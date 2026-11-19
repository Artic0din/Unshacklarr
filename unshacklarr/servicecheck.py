"""The daily check of each service a series uses, through Unshackle's HTTP API only (#319): a search, a listing
and the tracks of the latest listed episode. Nothing is downloaded and no licence is asked for: those endpoints
cannot start a pairing, so a session that needs a person comes back as a sign-in failure (AUTH_FAILED)."""

import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as StageTimeout
from datetime import datetime, timedelta, timezone

import requests

from unshacklarr import sync
from unshacklarr.files import no_credentials, read_json, write_atomic

CHECK_EVERY = timedelta(days=1)
RETRY_AFTER = 900  # seconds before a check held back by a running download looks again
STAGE_TIMEOUT = 120  # seconds a stage may take, however its request behaves
STAGES = {"search": "Search", "list": "Listing", "tracks": "Tracks"}
URL_QUERY = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s?#]+)[?#]\S*", re.IGNORECASE)  # no_credentials leaves some signed queries (?hdnea=, #320)

_running = threading.Lock()


def failure(error: Exception) -> dict:
    """A failed stage as it is kept and shown: a code and a short summary, without credentials or a URL's query."""
    code = getattr(error, "error_code", "") or (f"HTTP_{error.status}" if getattr(error, "status", 0) else "ERROR")
    return {"ok": False, "code": code, "message": URL_QUERY.sub(r"\1", no_credentials(error))[:200]}


def attempt(work):
    """(value, None), or (None, a failed stage) when work raises or takes longer than STAGE_TIMEOUT. A request that
    never answers is left to end on its own: its thread cannot be stopped."""
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(work).result(timeout=STAGE_TIMEOUT), None
    except StageTimeout:
        return None, {"ok": False, "code": "TIMEOUT", "message": f"No answer within {STAGE_TIMEOUT} s"}
    except Exception as e:  # one service's odd reply must not end the check of the others
        return None, failure(e)
    finally:
        pool.shutdown(wait=False)


def check_service(tag: str, control: dict, config: dict, query: str | None, now: datetime) -> dict:
    backend = sync.backend_for(tag, config)
    # never a relay: a relayed listing can open a session, and a pairing prompt, on the other server
    params, error = attempt(lambda: {k: v for k, v in sync.serve_params(control, config, backend).items() if k not in ("remote", "server")})
    if error:
        stages = dict.fromkeys(STAGES, error)
    else:
        def search() -> list[dict]:
            if not query:
                raise ValueError("Sonarr did not give the series' name")
            return backend.call("POST", "/api/search", json={**params, "service": tag, "query": query}).get("results") or []

        results, error = attempt(search)
        found = any(str(r.get("url") or r.get("id")) == control["title"] or sync.title_key(r.get("title")) == sync.title_key(query)
                    for r in results or [])
        stages = {"search": error or {"ok": True, "count": len(results), "found": found}}

        titles, error = attempt(lambda: backend.call("POST", "/api/list-titles", json={**params, "service": tag, "title_id": control["title"]})["titles"])
        if not error and not titles:
            error = {"ok": False, "code": "EMPTY", "message": "The service listed no titles"}
        stages["list"] = error or {"ok": True, "count": len(titles)}

        def tracks() -> dict:
            episodes = [t for t in titles if t.get("type") == "episode"] or titles
            latest = max(episodes, key=lambda t: (int(t.get("season") or 0), int(t.get("number") or 0)))
            code = f"S{int(latest.get('season') or 0):02}E{int(latest.get('number') or 0):02}"
            parts = sync.list_tracks(control, config, {**params, "service": tag, "title_id": control["title"], "wanted": [code]}, backend=backend)
            video, audio = (sum(len(p.get(kind) or []) for p in parts) for kind in ("video", "audio"))
            found = {"episode": code, "video": video, "audio": audio}  # audio not required: 10 Play embeds it in the video
            if video:
                return {"ok": True, **found}
            return {"ok": False, "code": "NO_TRACKS", "message": f"{code} has no video track", **found}

        if error:
            stages["tracks"] = {"ok": False, "code": "NOT_RUN", "message": "No title was listed to ask the tracks of"}
        else:
            counted, error = attempt(tracks)
            stages["tracks"] = error or counted
    failed = [stage for stage in STAGES if not stages[stage]["ok"]]
    return {"checked": now.isoformat(), "ok": not failed, "failed": failed, "stages": stages}


def skipped(now: datetime) -> dict:
    return {"checked": now.isoformat(), "ok": None, "failed": [], "skipped": "relay", "stages": {}}


def first_controls(config: dict) -> dict[str, tuple[int, dict] | None]:
    """Each service a series uses, with the series (TVDB id) and title that stand for it: one that is not relayed
    (--remote); None for a service whose every title is."""
    first: dict[str, tuple[int, dict] | None] = {}
    for tvdb, control in sync.configured_controls(config):
        tag = control.get("service")
        if tag and not first.get(tag):
            first[tag] = None if sync.stacked(control, config)[0].get("--remote") else (tvdb, control)
    return first


def series_name(tvdb: int) -> str | None:
    try:
        return (sync.sonarr_series({tvdb}).get(tvdb) or {}).get("title")
    except (requests.RequestException, ValueError):
        return None


def read_results() -> dict:
    return read_json(sync.SERVICE_CHECKS_FILE, {})


def notify_changes(config: dict, before: dict, after: dict) -> None:
    """One message when a service's failing stages change (it fails, fails elsewhere, or recovers), none while they stay."""
    for tag, result in after.items():
        if result["failed"] == (before.get(tag) or {}).get("failed", []):
            continue
        key = f"service-check:{tag}"  # the bell keeps one line a service: the newest replaces the one before
        if result["failed"]:
            lines = [f"{STAGES[stage]}: {result['stages'][stage]['message']}" for stage in result["failed"]]
            sync.notify(config.get("notifications") or {}, "error", f"{tag} failed its daily check", "\n".join(lines), key=key, service=tag)
        else:
            sync.notify(config.get("notifications") or {}, "success", f"{tag} passes its daily check again",
                        "It searches, lists and has tracks again.", key=key, service=tag)


def run_check(now: datetime | None = None) -> dict | None:
    """Check every service now, keep the results and the time of the run, and notify what changed. None when a
    check is already running."""
    if not _running.acquire(blocking=False):
        return None
    try:
        now = now or datetime.now(timezone.utc)
        config = sync.read_file()
        results = {}
        for tag, pick in first_controls(config).items():
            results[tag] = skipped(now) if pick is None else check_service(tag, pick[1], config, series_name(pick[0]), now)
        before = read_results().get("services") or {}
        done = {"last_run": now.isoformat(), "services": results}
        try:
            write_atomic(sync.SERVICE_CHECKS_FILE, json.dumps(done))
        except OSError as e:  # told, not lost: the notifications below still go out
            print(f"Service check: results not kept: {no_credentials(e)}", file=sys.stderr, flush=True)
        notify_changes(config, before, results)
        return done
    finally:
        _running.release()


def downloading() -> bool:
    return bool(sync.slot_active or sync.EpisodeRun.active)


def run_if_due(now: datetime | None = None) -> float:
    """Run the check when a day has passed since the last completed one and no download runs; the seconds to wait
    before looking again."""
    now = now or datetime.now(timezone.utc)
    last = read_results().get("last_run")
    if last and (wait := datetime.fromisoformat(last) + CHECK_EVERY - now) > timedelta(0):
        return wait.total_seconds()
    if downloading():
        return RETRY_AFTER
    run_check(now)
    return CHECK_EVERY.total_seconds()


def start() -> bool:
    """A check on demand, in the background; False when one is already running."""
    if _running.locked():
        return False
    threading.Thread(target=run_check, name="service-check", daemon=True).start()
    return True


def state() -> dict:
    return {"last_run": None, "services": {}, **read_results(), "running": _running.locked()}
