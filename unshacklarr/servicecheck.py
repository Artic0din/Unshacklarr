"""The daily check of each service a series uses, through Unshackle's HTTP API only (#319): a search, a listing
and the tracks of the latest listed episode. Nothing is downloaded and no licence is asked for: those endpoints
cannot start a pairing, so a session that needs a person comes back as a sign-in failure (AUTH_FAILED)."""

import json
import re
import sys
import threading
from datetime import datetime, timedelta, timezone

import requests

from unshacklarr import sync
from unshacklarr.files import no_credentials, read_json, write_atomic

CHECK_EVERY = timedelta(days=1)
RETRY_AFTER = 900  # seconds before a check held back by a running download looks again
SERIES_TRIED = 10  # series of a service tried before it is called failing: a title may be refused (not entitled, to buy) while the service is well
STAGE_TIMEOUT = 120  # seconds a stage may take, however its request behaves
STAGES = {"search": "Search", "list": "Listing", "tracks": "Tracks"}
SIGNED_OUT = ("AUTH_FAILED", "HTTP_401")  # the session needs a person, whatever the title
# a query after anything (an absolute URL, a relative one as in "url: /seg.mp4?...", a JSON-escaped one, a bare file
# name) and a fragment after a path: no_credentials leaves some signed queries (?hdnea=, #320)
URL_QUERY = re.compile(r"([^\s?#]+)\?\S*")
URL_FRAGMENT = re.compile(r"([^\s?#]*/[^\s?#]*)#\S*|([^\s?#]+)#\S*=\S*")  # after a path, or one that carries a value

_running = threading.Lock()


class BadReply(Exception):
    """A reply that is not the shape the endpoint documents."""
    error_code = "BAD_REPLY"


def failure(error: Exception) -> dict:
    """A failed stage as it is kept and shown: a code and a short summary, without credentials or a URL's query."""
    code = getattr(error, "error_code", "") or (f"HTTP_{error.status}" if getattr(error, "status", 0) else "ERROR")
    scrubbed = URL_FRAGMENT.sub(lambda m: m[1] or m[2], URL_QUERY.sub(r"\1", no_credentials(error)))
    return {"ok": False, "code": code, "message": scrubbed[:200]}


def attempt(work):
    """(value, None), or (None, a failed stage) when work raises or takes longer than STAGE_TIMEOUT. A request that
    never answers is left to end on its own, in a daemon thread that cannot hold up the shutdown."""
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = work()
        except Exception as e:  # one service's odd reply must not end the check of the others
            box["error"] = e

    thread = threading.Thread(target=run, name="service-check-stage", daemon=True)
    thread.start()
    thread.join(STAGE_TIMEOUT)
    if thread.is_alive():
        return None, {"ok": False, "code": "TIMEOUT", "message": f"No answer within {STAGE_TIMEOUT} s"}
    if "error" in box:
        return None, failure(box["error"])
    return box["value"], None


class Bounded:
    """A backend whose calls end within STAGE_TIMEOUT, whoever makes them (list_tracks makes its own)."""

    def __init__(self, backend):
        self.backend = backend

    def call(self, method: str, path: str, **kwargs):
        return self.backend.call(method, path, timeout=(5, min(60, STAGE_TIMEOUT)), **kwargs)

    def __getattr__(self, name: str):
        return getattr(self.backend, name)


def dicts(value, what: str) -> list[dict]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise BadReply(f"Unexpected {what} in the reply")
    return value


def listed(reply, key: str, what: str) -> list[dict]:
    if not isinstance(reply, dict):
        raise BadReply(f"Unexpected {what} in the reply")
    return dicts([] if reply.get(key) is None else reply[key], what)  # none listed is an empty list, not false or 0


def has_search(backend, tag: str) -> bool:
    """False only when the serve says the service has none: one that does not say (an older serve, or one that
    cannot be asked) is searched, and answers for itself."""
    told, _ = attempt(lambda: next((s.get("has_search") for s in backend.services() if s.get("tag") == tag), None))
    return told is not False


def check_series(backend, tag: str, control: dict, config: dict, query: str | None, search: bool) -> dict:
    """The stages of one series on its service: the search only when asked, then the listing and the tracks."""
    # never a relay: a relayed listing can open a session, and a pairing prompt, on the other server
    params, error = attempt(lambda: {k: v for k, v in sync.serve_params(control, config, backend).items() if k not in ("remote", "server")})
    if error:
        return {stage: error for stage in STAGES if search or stage != "search"}
    stages = {}
    if search:
        def look() -> dict:
            results = listed(backend.call("POST", "/api/search", json={**params, "service": tag, "query": query}), "results", "search results")
            found = any(str(r.get("url") or r.get("id")) == control["title"] or sync.title_key(r.get("title")) == sync.title_key(query)
                        for r in results)
            return {"ok": True, "count": len(results), "found": found}

        if not has_search(backend, tag):
            stages["search"] = {"ok": None, "code": "UNSUPPORTED", "message": "Not run: the service has no search"}
        elif query:
            looked, error = attempt(look)
            stages["search"] = error or looked
        else:  # Sonarr did not answer: that says nothing of the service
            stages["search"] = {"ok": None, "code": "SKIPPED", "message": "Not run: the series' name is unknown"}

    def titles_of() -> list[dict]:
        return listed(backend.call("POST", "/api/list-titles", json={**params, "service": tag, "title_id": control["title"]}), "titles", "titles")

    titles, error = attempt(titles_of)
    if not error and not titles:
        error = {"ok": False, "code": "EMPTY", "message": "The service listed no titles"}
    stages["list"] = error or {"ok": True, "count": len(titles)}

    def tracks() -> dict:
        episodes = [t for t in titles if t.get("type") == "episode"] or titles
        latest = max(episodes, key=lambda t: (int(t.get("season") or 0), int(t.get("number") or 0)))
        code = f"S{int(latest.get('season') or 0):02}E{int(latest.get('number') or 0):02}"
        parts = dicts(sync.list_tracks(control, config, {**params, "service": tag, "title_id": control["title"], "wanted": [code]}, backend=backend), "tracks")
        video, audio = (sum(len(dicts(p.get(kind) or [], "tracks")) for p in parts) for kind in ("video", "audio"))
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


def check_service(tag: str, serve, picks: list[tuple[int, dict]], ring: list[int], config: dict, now: datetime) -> dict:
    """A service's result from its picked series: the first whose listing and tracks pass stands for it; a sign-in
    failure ends the tries (it is the session, not the title) and its stages stand; else the first series' stages
    stand. A failure says which series tomorrow's probe is: the next in config order, the same after a sign-in failure."""
    backend, on = Bounded(serve), backend_name(serve)
    first = None
    for tried, (tvdb, control) in enumerate(picks, 1):
        stages = check_series(backend, tag, control, config, series_name(tvdb) if tried == 1 else None, search=tried == 1)
        first = first or (tvdb, stages)
        stands = {**first[1], **{stage: stages[stage] for stage in ("list", "tracks")}}
        if stages["list"]["ok"] and stages["tracks"]["ok"]:
            return result_of(now, tvdb, tried, stands, backend=on)
        if any(stage.get("code") in SIGNED_OUT for stage in stages.values()):
            return result_of(now, tvdb, tried, stands, probe=tvdb, backend=on)
    return result_of(now, first[0], tried, first[1], probe=ring[(ring.index(tvdb) + 1) % len(ring)], backend=on)


def backend_name(serve) -> str:
    """Which unshackle serve ("" the main one): a result is its backend's, on the page and as a failure kept."""
    return next((name for name, other in sync.BACKENDS.items() if other is serve), "")


def result_of(now: datetime, tvdb: int, tried: int, stages: dict, probe: int | None = None, backend: str = "") -> dict:
    failed = [stage for stage in STAGES if stages[stage]["ok"] is False]
    return {"checked": now.isoformat(), "ok": not failed, "failed": failed, "tvdb": tvdb, "tried": tried, "backend": backend, "stages": stages,
            **({"next": probe} if failed and probe is not None else {})}


def skipped(now: datetime, why: str, backend: str) -> dict:
    return {"checked": now.isoformat(), "ok": None, "failed": [], "skipped": why, "backend": backend, "stages": {}}


def picked_controls(config: dict, before: dict) -> dict[str, tuple[list[tuple[int, dict]], list[int], str]]:
    """Each service a series uses: the series (TVDB id and title) to try, in order, every series of it in config
    order, and why none can be tried. None is relayed (--remote). The order starts with the one that stood for the
    service last time; when its last result was a failure, with the one its probe named, and only that one is tried
    (so a service that is down is not asked ten times a day), else up to SERIES_TRIED. No series to try: every series
    of the service is relayed ("relay"), or its series are separate programmes found one episode at a time, with no
    title of their own to list ("programmes")."""
    every: dict[str, list[tuple[int, dict]]] = {}
    relayed = set()
    series = config.get("series") or {}
    for show in series.values() if isinstance(series, dict) else []:
        if isinstance(show, dict) and show.get("programmes") is True and show.get("service"):
            every.setdefault(show["service"], [])  # checked through a programme pasted for it, else told as skipped
    for tvdb, control in sync.configured_controls(config):
        tag = control.get("service")
        if not tag:
            continue
        every.setdefault(tag, [])
        if sync.stacked(control, config)[0].get("--remote"):
            relayed.add(tag)
        elif all(tvdb != seen for seen, _ in every[tag]):
            every[tag].append((tvdb, control))
    picked = {}
    for tag, series in every.items():
        last = before.get(tag) or {}
        failing = last.get("ok") is False
        ring = [tvdb for tvdb, _ in series]
        series = sorted(series, key=lambda pick: pick[0] != ((last.get("next") or last.get("tvdb")) if failing else last.get("tvdb")))  # stable
        picked[tag] = (series[: 1 if failing else SERIES_TRIED], ring, "relay" if tag in relayed else "programmes")
    return picked


def series_name(tvdb: int) -> str | None:
    try:
        return (sync.sonarr_series({tvdb}).get(tvdb) or {}).get("title")
    except (requests.RequestException, ValueError):
        return None


def read_results() -> dict:
    return read_json(sync.SERVICE_CHECKS_FILE, {})


def unresolved_of(last: dict) -> dict:
    kept = last.get("unresolved")
    return kept if isinstance(kept, dict) else {}


def settled(last: dict, result: dict) -> dict:
    """The result as it is kept: a stage that was failing and could not be checked now (it is skipped, the stage
    before it failed, or the whole service is skipped) keeps its failure, for it has not passed. So the page, the
    next run's baseline and the notifications agree. `unresolved` holds those failures by stage. A failure is its
    serve's: none is kept from the one the service was on before."""
    was = unresolved_of(last) if (last.get("backend") or "") == (result.get("backend") or "") else {}
    if result.get("skipped"):
        return {**result, "unresolved": was}
    unchecked = lambda stage: stage.get("code") in ("SKIPPED", "NOT_RUN")  # no name to search with, or the stage before it failed
    stages = {stage: was[stage] if stage in was and unchecked(result["stages"][stage]) else result["stages"][stage] for stage in STAGES}
    failed = [stage for stage in STAGES if stages[stage]["ok"] is False]
    return {**result, "stages": stages, "failed": failed, "ok": not failed, "unresolved": {stage: stages[stage] for stage in failed}}


def notify_changes(config: dict, before: dict, after: dict) -> None:
    """One message when a service's unresolved stages change (it fails, fails elsewhere, or recovers), none while
    they stay and none for a skipped service."""
    for tag, result in after.items():
        was, failing = list(unresolved_of(before.get(tag) or {})), list(result["unresolved"])
        if result.get("skipped") or failing == was:
            continue
        key = f"service-check:{tag}"  # the bell keeps one line a service: the newest replaces the one before
        if failing:
            lines = [f"{STAGES[stage]}: {result['unresolved'][stage]['message']}" for stage in failing]
            sync.notify(config.get("notifications") or {}, "error", f"{tag} failed its daily check", "\n".join(lines), key=key, service=tag)
        else:
            sync.notify(config.get("notifications") or {}, "success", f"{tag} passes its daily check again",
                        "Each stage that ran passed.", key=key, service=tag)


def run_check(now: datetime | None = None, reserved: bool = False) -> dict | None:
    """Check every service now, keep the results and the time of the run, and notify what changed. None when a
    check is already running (reserved: the caller took the lock, and this releases it)."""
    if not reserved and not _running.acquire(blocking=False):
        return None
    try:
        now = now or datetime.now(timezone.utc)
        config = sync.read_file()
        before = read_results().get("services") or {}
        results = {}
        for tag, (picks, ring, why) in picked_controls(config, before).items():
            on = (before.get(tag) or {}).get("backend") or ""  # the last known, should asking which serve fail
            try:
                serve = sync.backend_for(tag, config)
                on = backend_name(serve)
                results[tag] = check_service(tag, serve, picks, ring, config, now) if picks else skipped(now, why, on)
            except Exception as e:  # one service's unexpected failure must not stop the others or the save
                # a service with no series to try stays skipped: nothing of it ran, so nothing of it failed
                results[tag] = result_of(now, picks[0][0], 0, dict.fromkeys(STAGES, failure(e)), backend=on) if picks else skipped(now, why, on)
            results[tag] = settled(before.get(tag) or {}, results[tag])
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


def start() -> str:
    """A check on demand, in the background, under the daily run's gate. "" when it started, else why it did not."""
    if not _running.acquire(blocking=False):
        return "A check is already running"
    if downloading():
        _running.release()
        return "A download is running: check again when it ends"
    try:
        threading.Thread(target=run_check, kwargs={"reserved": True}, name="service-check", daemon=True).start()
    except RuntimeError:  # no thread to be had: said as it is, and the reservation freed
        _running.release()
        raise
    return ""


def state() -> dict:
    return {"last_run": None, "services": {}, **read_results(), "running": _running.locked()}
