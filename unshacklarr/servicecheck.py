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
SERIES_TRIED = 10  # series of a service tried before it is called failing: a title may be refused (not entitled, to buy) while the service is well
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


def check_series(backend, tag: str, control: dict, config: dict, query: str | None, search: bool) -> dict:
    """The stages of one series on its service: the search only when asked, then the listing and the tracks."""
    # never a relay: a relayed listing can open a session, and a pairing prompt, on the other server
    params, error = attempt(lambda: {k: v for k, v in sync.serve_params(control, config, backend).items() if k not in ("remote", "server")})
    if error:
        return {stage: error for stage in STAGES if search or stage != "search"}
    stages = {}
    if search:
        def look() -> list[dict]:
            return backend.call("POST", "/api/search", json={**params, "service": tag, "query": query}).get("results") or []

        if query:
            results, error = attempt(look)
            found = any(str(r.get("url") or r.get("id")) == control["title"] or sync.title_key(r.get("title")) == sync.title_key(query)
                        for r in results or [])
            stages["search"] = error or {"ok": True, "count": len(results), "found": found}
        else:  # Sonarr did not answer: that says nothing of the service
            stages["search"] = {"ok": None, "code": "SKIPPED", "message": "Not run: the series' name is unknown"}

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
    return stages


def check_service(tag: str, picks: list[tuple[int, dict]], config: dict, now: datetime) -> dict:
    """A service's result from its picked series: the first whose listing and tracks pass stands for it; a sign-in
    failure ends the tries (it is the session, not the title); else the first series' stages stand."""
    backend = sync.backend_for(tag, config)
    first = None
    for tried, (tvdb, control) in enumerate(picks, 1):
        stages = check_series(backend, tag, control, config, series_name(tvdb) if tried == 1 else None, search=tried == 1)
        first = first or (tvdb, stages)
        if stages["list"]["ok"] and stages["tracks"]["ok"]:
            stages = {**first[1], **{stage: stages[stage] for stage in ("list", "tracks")}}
            return result_of(now, tvdb, tried, stages)
        if any(stage.get("code") == "AUTH_FAILED" for stage in stages.values()):
            break
    return result_of(now, first[0], tried, first[1])


def result_of(now: datetime, tvdb: int, tried: int, stages: dict) -> dict:
    failed = [stage for stage in STAGES if stages[stage]["ok"] is False]
    return {"checked": now.isoformat(), "ok": not failed, "failed": failed, "tvdb": tvdb, "tried": tried, "stages": stages}


def skipped(now: datetime) -> dict:
    return {"checked": now.isoformat(), "ok": None, "failed": [], "skipped": "relay", "stages": {}}


def picked_controls(config: dict, before: dict) -> dict[str, list[tuple[int, dict]]]:
    """Each service a series uses, with the series (TVDB id and title) to try, in order: the one that stood for it
    last time, then the others in config order, none relayed (--remote). Up to SERIES_TRIED; one when its last
    result was a failure (a probe, so a service that is down is not asked ten times a day). An empty list for a
    service whose every series is relayed."""
    every: dict[str, list[tuple[int, dict]]] = {}
    for tvdb, control in sync.configured_controls(config):
        tag = control.get("service")
        if not tag:
            continue
        every.setdefault(tag, [])
        if all(tvdb != seen for seen, _ in every[tag]) and not sync.stacked(control, config)[0].get("--remote"):
            every[tag].append((tvdb, control))
    picked = {}
    for tag, series in every.items():
        last = before.get(tag) or {}
        series.sort(key=lambda pick: pick[0] != last.get("tvdb"))  # stable: the rest stay in config order
        picked[tag] = series[: 1 if last.get("ok") is False else SERIES_TRIED]
    return picked


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
        before = read_results().get("services") or {}
        results = {}
        for tag, picks in picked_controls(config, before).items():
            results[tag] = check_service(tag, picks, config, now) if picks else skipped(now)
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
