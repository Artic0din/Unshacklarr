"""The daily check of each service through Unshackle's HTTP API (#319), against a faked Unshackle."""
import asyncio
import importlib
import json
import threading
import types
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import pytest
import responses

from test_sync import load
from unshacklarr.backend import UnshackleError

NOW = datetime(2026, 11, 19, 3, 0, tzinfo=timezone.utc)
ALLOWED = {"/api/search", "/api/list-titles", "/api/list-tracks"}
TITLES = [{"type": "episode", "season": 1, "number": 9, "name": "Old"}, {"type": "episode", "season": 2, "number": 3, "name": "Latest"},
          {"type": "episode", "season": 2, "number": 1, "name": "Earlier"}]
TRACKS = {"video": [{"height": 1080}], "audio": [{"language": "en"}], "subtitles": []}


class Serve:
    """unshackle serve: each path answers from `replies` (a value, or an exception to raise), and is recorded."""
    settings: dict = {}

    def __init__(self, replies=None):
        self.replies = {"/api/search": {"results": [{"title": "Show", "id": "show-1"}, {"title": "Other", "id": "o"}]},
                        "/api/list-titles": {"titles": TITLES}, "/api/list-tracks": TRACKS, **(replies or {})}
        self.calls = []
        self.timeouts = []
        self.by_title = {}  # (path, title_id) -> a reply for that series only

    def services(self):
        return [{"tag": "RTLP", "cli_params": []}, {"tag": "MLT", "cli_params": []}]

    def call(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs.get("json")))
        self.timeouts.append(kwargs.get("timeout"))
        reply = self.by_title.get((path, (kwargs.get("json") or {}).get("title_id")), self.replies[path])
        if isinstance(reply, Exception):
            raise reply
        if callable(reply):
            return reply()
        return reply

    def paths(self):
        return [path for _, path, _ in self.calls]


@pytest.fixture
def check(tmp_path, monkeypatch):
    sync = load(tmp_path, monkeypatch)
    (tmp_path / "config.yaml").write_text("series:\n  111: {service: RTLP, title: show-1}\n  222: {service: MLT, title: show-2}\n"
                                         "notifications: {urls: []}\n")
    from unshacklarr import servicecheck
    module = importlib.reload(servicecheck)
    module.serve = Serve()
    module.sent = []
    monkeypatch.setattr(sync, "backend_for", lambda tag, config=None: module.serve)
    monkeypatch.setattr(sync, "sonarr_series", lambda wanted, keep=3600: {tvdb: {"title": "Show"} for tvdb in wanted})
    monkeypatch.setattr(sync, "notify", lambda settings, level, title, message, **kw: module.sent.append((level, title, message)) or True)
    monkeypatch.setattr(sync, "slot_active", {})
    return module


def test_a_service_passes_when_each_stage_answers(check):
    results = check.run_check(NOW)["services"]

    assert results["RTLP"]["ok"] is True and results["RTLP"]["failed"] == []
    assert results["RTLP"]["stages"]["search"] == {"ok": True, "count": 2, "found": True}
    assert results["RTLP"]["stages"]["list"] == {"ok": True, "count": 3}
    assert results["RTLP"]["stages"]["tracks"] == {"ok": True, "episode": "S02E03", "video": 1, "audio": 1}
    assert results["RTLP"]["checked"] == NOW.isoformat()
    listed = [c for c in check.serve.calls if c[1] == "/api/list-tracks"][0][2]
    assert (listed["service"], listed["title_id"], listed["wanted"]) == ("RTLP", "show-1", ["S02E03"])  # the latest listed episode
    searched = [c for c in check.serve.calls if c[1] == "/api/search"][0][2]
    assert searched["query"] == "Show"
    assert check.sent == []


def test_no_licence_download_or_session_request_is_made(check):
    check.run_check(NOW)
    check.serve.replies["/api/list-tracks"] = UnshackleError("boom")
    check.run_check(NOW + timedelta(days=1))

    assert set(check.serve.paths()) == ALLOWED


def test_search_records_when_the_series_is_not_among_the_results_without_failing(check):
    check.serve.replies["/api/search"] = {"results": [{"title": "Other", "id": "o"}]}

    result = check.run_check(NOW)["services"]["RTLP"]

    assert result["ok"] is True and result["stages"]["search"] == {"ok": True, "count": 1, "found": False}
    assert check.sent == []


def test_a_failed_search_does_not_skip_the_listing_or_the_tracks(check):
    check.serve.replies["/api/search"] = UnshackleError("search is down")

    result = check.run_check(NOW)["services"]["RTLP"]

    assert result["failed"] == ["search"]
    assert result["stages"]["search"]["code"] == "ERROR" and "search is down" in result["stages"]["search"]["message"]
    assert result["stages"]["list"]["ok"] and result["stages"]["tracks"]["ok"]


def test_a_failed_listing_fails_its_tracks_and_leaves_the_search_alone(check):
    check.serve.replies["/api/list-titles"] = UnshackleError("no listing")

    result = check.run_check(NOW)["services"]["RTLP"]

    assert result["failed"] == ["list", "tracks"]
    assert result["stages"]["search"]["ok"] is True
    assert result["stages"]["tracks"]["code"] == "NOT_RUN"
    assert "/api/list-tracks" not in check.serve.paths()


def test_an_empty_listing_and_tracks_without_video_fail(check):
    check.serve.replies["/api/list-titles"] = {"titles": []}
    assert check.run_check(NOW)["services"]["RTLP"]["stages"]["list"]["code"] == "EMPTY"

    check.serve.replies["/api/list-titles"] = {"titles": TITLES}
    check.serve.replies["/api/list-tracks"] = {"video": [], "audio": [{"language": "en"}], "subtitles": []}
    tracks = check.run_check(NOW)["services"]["RTLP"]["stages"]["tracks"]
    assert tracks["ok"] is False and tracks["code"] == "NO_TRACKS" and (tracks["video"], tracks["audio"]) == (0, 1)


def test_tracks_pass_with_video_and_no_audio_list(check):
    check.serve.replies["/api/list-tracks"] = {"video": [{"height": 1080}], "audio": [], "subtitles": []}  # 10 Play: audio inside the video

    result = check.run_check(NOW)["services"]["RTLP"]

    assert result["ok"] is True and result["stages"]["tracks"] == {"ok": True, "episode": "S02E03", "video": 1, "audio": 0}


def several(tmp_path, *lines):
    (tmp_path / "config.yaml").write_text("series:\n" + "".join(f"  {tvdb}: {{service: RTLP, title: show-{tvdb}{extra}}}\n" for tvdb, extra in lines))


def test_another_series_stands_in_when_the_first_is_not_the_services_problem(check, tmp_path):
    several(tmp_path, (111, ""), (112, ""))
    check.serve.by_title[("/api/list-tracks", "show-111")] = UnshackleError("not entitled to this title")

    result = check.run_check(NOW)["services"]["RTLP"]

    assert (result["ok"], result["failed"], result["tvdb"], result["tried"]) == (True, [], 112, 2)
    assert result["stages"]["tracks"]["ok"] and result["stages"]["list"]["ok"]
    assert [c[1] for c in check.serve.calls].count("/api/search") == 1  # asked for the first series only
    assert check.sent == [] and set(check.serve.paths()) == ALLOWED


def test_a_sign_in_failure_stops_at_once_it_is_the_session_not_the_title(check, tmp_path):
    several(tmp_path, (111, ""), (112, ""))
    error = UnshackleError("HTTP 401: session expired")
    error.status, error.error_code = 401, "AUTH_FAILED"
    check.serve.by_title[("/api/list-tracks", "show-111")] = error

    result = check.run_check(NOW)["services"]["RTLP"]

    assert (result["ok"], result["failed"], result["tvdb"], result["tried"]) == (False, ["tracks"], 111, 1)
    assert result["stages"]["tracks"]["code"] == "AUTH_FAILED"
    assert "show-112" not in [(c[2] or {}).get("title_id") for c in check.serve.calls]
    assert set(check.serve.paths()) == ALLOWED


def refuse(check, *tvdbs):
    for tvdb in tvdbs:
        check.serve.by_title[("/api/list-tracks", f"show-{tvdb}")] = UnshackleError(f"refused {tvdb}")


def asked_of(check, path, tvdb):
    return [c for c in check.serve.calls if c[1] == path and (c[2] or {}).get("title_id") == f"show-{tvdb}"]


def test_a_service_fails_when_ten_series_fail_and_keeps_the_first_ones_stages(check, tmp_path):
    several(tmp_path, (111, ", season_pages: {1: {url: show-111b}}"), *[(tvdb, "") for tvdb in range(112, 123)])
    refuse(check, *range(111, 123))

    result = check.run_check(NOW)["services"]["RTLP"]

    assert (result["ok"], result["failed"], result["tvdb"], result["tried"]) == (False, ["tracks"], 111, 10)
    assert "refused 111" in result["stages"]["tracks"]["message"]
    asked = {(c[2] or {}).get("title_id") for c in check.serve.calls}
    assert asked >= {"show-111", "show-120"} and not asked & {"show-111b", "show-121", "show-122"}  # one series is one try
    assert [(level, title) for level, title, _ in check.sent] == [("error", "RTLP failed its daily check")]


def test_a_playable_series_further_down_the_config_stands_for_the_service(check, tmp_path):
    several(tmp_path, *[(tvdb, "") for tvdb in (111, 112, 113, 114)])
    refuse(check, 111, 112, 113)

    result = check.run_check(NOW)["services"]["RTLP"]

    assert (result["ok"], result["tvdb"], result["tried"]) == (True, 114, 4)
    assert check.sent == []  # a title refused is not the service failing


def test_the_next_run_starts_with_the_series_that_passed(check, tmp_path):
    several(tmp_path, *[(tvdb, "") for tvdb in (111, 112, 113, 114)])
    refuse(check, 111, 112, 113)
    check.run_check(NOW)
    check.serve.calls.clear()

    result = check.run_check(NOW + timedelta(days=1))["services"]["RTLP"]

    assert (result["ok"], result["tvdb"], result["tried"]) == (True, 114, 1)
    assert len(asked_of(check, "/api/list-titles", 114)) == len(asked_of(check, "/api/list-tracks", 114)) == 1
    assert [c for c in check.serve.calls if c[1] == "/api/list-tracks"] == asked_of(check, "/api/list-tracks", 114)


def test_a_failing_service_is_probed_with_one_series_and_told_once(check, tmp_path):
    several(tmp_path, *[(tvdb, "") for tvdb in (111, 112, 113)])
    refuse(check, 111, 112, 113)
    first = check.run_check(NOW)["services"]["RTLP"]
    assert (first["ok"], first["tried"]) == (False, 3) and len(check.sent) == 1
    check.serve.calls.clear()

    second = check.run_check(NOW + timedelta(days=1))["services"]["RTLP"]

    assert (second["ok"], second["tried"], second["tvdb"]) == (False, 1, 111)
    assert len([c for c in check.serve.calls if c[1] == "/api/list-tracks"]) == 1
    assert len(check.sent) == 1  # the same failure is not told again
    assert set(check.serve.paths()) == ALLOWED


def test_a_failing_service_that_passes_its_one_probe_is_told_it_recovered(check, tmp_path):
    several(tmp_path, *[(tvdb, "") for tvdb in (111, 112)])
    refuse(check, 111, 112)
    check.run_check(NOW)
    del check.serve.by_title[("/api/list-tracks", "show-111")]

    result = check.run_check(NOW + timedelta(days=1))["services"]["RTLP"]

    assert (result["ok"], result["tvdb"], result["tried"]) == (True, 111, 1)
    assert [(level, title) for level, title, _ in check.sent] == [("error", "RTLP failed its daily check"), ("success", "RTLP passes its daily check again")]


def test_a_stored_series_that_left_the_config_falls_back_to_config_order(check, tmp_path):
    several(tmp_path, *[(tvdb, "") for tvdb in (111, 112)])
    refuse(check, 111)
    assert check.run_check(NOW)["services"]["RTLP"]["tvdb"] == 112
    several(tmp_path, *[(tvdb, "") for tvdb in (111, 113)])

    result = check.run_check(NOW + timedelta(days=1))["services"]["RTLP"]

    assert (result["ok"], result["tvdb"], result["tried"]) == (True, 113, 2)


def test_a_search_that_cannot_run_is_skipped_not_failed(check, monkeypatch):
    def down(wanted, keep=3600):
        raise check.requests.ConnectionError("sonarr is down")
    monkeypatch.setattr(check.sync, "sonarr_series", down)

    result = check.run_check(NOW)["services"]["RTLP"]

    assert result["ok"] is True and result["failed"] == []
    assert result["stages"]["search"]["ok"] is None and result["stages"]["search"]["message"]
    assert result["stages"]["list"]["ok"] and result["stages"]["tracks"]["ok"]
    assert "/api/search" not in check.serve.paths() and check.sent == []


def test_a_relayed_series_is_never_asked_through_its_relay(check, tmp_path):
    (tmp_path / "config.yaml").write_text(
        "series:\n  111: {service: RTLP, title: relayed-1, options: {--remote: true, --server: far}}\n"
        "  112: {service: RTLP, title: local-1}\n  222: {service: MLT, title: relayed-2, options: {--remote: true}}\n"
        "  333: {service: CRAVE, title: show-3}\nservice_defaults: {CRAVE: {options: {--remote: true}}}\n")

    results = check.run_check(NOW)["services"]

    assert results["RTLP"]["ok"] is True and results["MLT"]["skipped"] == "relay" and results["CRAVE"]["skipped"] == "relay"
    assert results["MLT"]["ok"] is None and results["MLT"]["failed"] == [] and results["MLT"]["stages"] == {}
    sent = [payload for _, _, payload in check.serve.calls]
    assert sent and {p["service"] for p in sent} == {"RTLP"} and {p["title_id"] for p in sent if "title_id" in p} == {"local-1"}  # the relay-only services were not asked at all
    assert all("remote" not in p and "server" not in p for p in sent)
    assert (results["RTLP"]["tvdb"], results["RTLP"]["tried"]) == (112, 1)  # the relayed one is not counted
    assert check.sent == []  # skipped is not a failure


def test_a_session_that_needs_a_person_is_a_sign_in_failure(check):
    error = UnshackleError("RTLP through Unshackle: HTTP 401: session expired")
    error.status, error.error_code = 401, "AUTH_FAILED"
    check.serve.replies["/api/list-tracks"] = error

    result = check.run_check(NOW)["services"]["RTLP"]

    assert result["failed"] == ["tracks"] and result["stages"]["tracks"]["code"] == "AUTH_FAILED"
    assert set(check.serve.paths()) == ALLOWED  # no pairing started


def test_a_stage_that_does_not_answer_times_out_and_the_others_still_run(check, monkeypatch):
    monkeypatch.setattr(check, "STAGE_TIMEOUT", 0.2)
    stuck = threading.Event()
    check.serve.replies["/api/list-titles"] = lambda: stuck.wait(10) or {"titles": TITLES}

    try:
        result = check.run_check(NOW)["services"]["RTLP"]
    finally:
        stuck.set()

    assert result["stages"]["list"]["code"] == "TIMEOUT" and result["stages"]["search"]["ok"]
    assert result["stages"]["tracks"]["code"] == "NOT_RUN"


def test_each_service_has_its_own_result(check):
    answers = iter([UnshackleError("x"), TRACKS])

    def tracks():
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer
    check.serve.replies["/api/list-tracks"] = tracks

    results = check.run_check(NOW)["services"]

    assert {tag: r["ok"] for tag, r in results.items()} == {"RTLP": False, "MLT": True}


def test_the_check_waits_while_a_download_runs_and_tries_later_the_same_day(check, monkeypatch):
    monkeypatch.setattr(check.sync, "slot_active", {"job": 1})

    assert check.run_if_due(NOW) == check.RETRY_AFTER
    assert check.serve.calls == [] and check.read_results() == {}

    monkeypatch.setattr(check.sync, "slot_active", {})
    assert check.run_if_due(NOW + timedelta(seconds=check.RETRY_AFTER)) == check.CHECK_EVERY.total_seconds()
    assert check.serve.calls


def test_results_and_the_last_run_survive_a_restart(check):
    check.run_if_due(NOW)
    asked = len(check.serve.calls)

    restarted = importlib.reload(check)  # what a restart loses: everything in memory

    saved = restarted.read_results()
    assert saved["last_run"] == NOW.isoformat() and saved["services"]["RTLP"]["ok"] is True
    assert restarted.run_if_due(NOW + timedelta(hours=5)) == timedelta(hours=19).total_seconds()  # not again the same day
    assert len(check.serve.calls) == asked
    restarted.run_if_due(NOW + restarted.CHECK_EVERY)
    assert len(check.serve.calls) == asked * 2


def test_a_change_is_notified_once_and_an_unchanged_failure_never_again(check):
    check.run_check(NOW)
    assert check.sent == []  # first run, all well

    check.serve.replies["/api/list-tracks"] = UnshackleError("token 1 refused")
    check.run_check(NOW + timedelta(days=1))
    assert [(level, title) for level, title, _ in check.sent] == [("error", "RTLP failed its daily check"), ("error", "MLT failed its daily check")]

    check.serve.replies["/api/list-tracks"] = UnshackleError("token 2 refused")  # another words, the same failure
    check.run_check(NOW + timedelta(days=2))
    assert len(check.sent) == 2

    check.serve.replies["/api/list-tracks"] = TRACKS
    check.run_check(NOW + timedelta(days=3))
    assert [(level, title) for level, title, _ in check.sent[2:]] == [("success", "RTLP passes its daily check again"),
                                                                     ("success", "MLT passes its daily check again")]
    check.run_check(NOW + timedelta(days=4))
    assert len(check.sent) == 4


def test_a_first_run_that_fails_is_notified(check):
    check.serve.replies["/api/search"] = UnshackleError("search is down")

    check.run_check(NOW)

    assert [(level, title) for level, title, _ in check.sent] == [("error", "RTLP failed its daily check"), ("error", "MLT failed its daily check")]


def test_stored_and_sent_errors_hold_no_credentials_or_url_query(check, tmp_path):
    check.serve.replies["/api/list-titles"] = UnshackleError(
        "RTLP: GET https://rtl.example/show?token=SECRET-1&x=2 failed. X-Secret-Key: SECRET-2 via http://user:SECRET-3@proxy:8080 "
        "then (https://cdn.example/seg.mp4?hdnea=fixture) and https://cdn.example/a.m3u8#frag-fixture")

    check.run_check(NOW)

    saved = (tmp_path / "service_checks.json").read_text()
    for text in (saved, *(message for _, _, message in check.sent)):
        assert "SECRET" not in text and "?token" not in text and "x=2" not in text
        assert "hdnea" not in text and "fixture" not in text
    messages = [stage["message"] for r in json.loads(saved)["services"].values() for stage in r["stages"].values() if "message" in stage]
    assert messages and all("?" not in m and "#" not in m for m in messages)
    assert "https://rtl.example/show" in saved and "https://cdn.example/seg.mp4" in saved


def test_the_service_checks_endpoints_return_the_results_and_start_a_run(check, monkeypatch):
    import unshacklarr.web
    web = importlib.reload(unshacklarr.web)
    web.servicecheck = check
    check.run_check(NOW)

    shown = json.loads(asyncio.run(web.service_checks(None)).text)
    assert shown["last_run"] == NOW.isoformat() and shown["running"] is False and shown["services"]["MLT"]["ok"] is True

    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def slow(now=None, reserved=False):
        assert reserved  # the lock was taken before the answer
        started.set()
        release.wait(5)
        check._running.release()
        finished.set()
    monkeypatch.setattr(check, "run_check", slow)
    try:
        assert asyncio.run(web.start_service_check(None)).status == 202
        with pytest.raises(web.web.HTTPConflict) as refused:  # at once, before the run's thread need have started
            asyncio.run(web.start_service_check(None))
        assert "already running" in refused.value.text
        assert started.wait(5)
    finally:
        release.set()
        assert finished.wait(5)  # the run's thread is done before the next test reloads the module


def test_the_watcher_runs_the_check_and_waits_as_long_as_it_says(check, monkeypatch):
    import unshacklarr.web
    web = importlib.reload(unshacklarr.web)
    web.servicecheck = check
    waits, answers = [], [900.0, RuntimeError("Sonarr is down"), 86400.0]

    async def sleep(seconds):
        waits.append(seconds)
        if len(waits) == 4:
            raise asyncio.CancelledError

    def due():
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(web.asyncio, "sleep", sleep)
    monkeypatch.setattr(web, "read_config", lambda: {"auth": {"password": "set"}})
    monkeypatch.setattr(web.sonarr_sync, "SONARR", "http://sonarr")
    monkeypatch.setattr(check, "run_if_due", due)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(web.watch_service_checks())

    # not at start; then as long as each look says, and the retry wait after a look that failed
    assert waits == [600, 900.0, check.RETRY_AFTER, 86400.0] and answers == []


def test_a_service_only_a_season_page_uses_is_checked_too(check, tmp_path):
    (tmp_path / "config.yaml").write_text("series:\n  111: {service: RTLP, title: show-1, season_pages: {2: {url: page-2, service: MLT}}}\n"
                                         "notifications: {urls: []}\n")

    done = check.run_check(NOW)

    assert {tag: result["ok"] for tag, result in done["services"].items()} == {"RTLP": True, "MLT": True}
    assert ("/api/list-titles", "page-2") in [(path, (asked or {}).get("title_id")) for _, path, asked in check.serve.calls]
    assert set(check.serve.paths()) <= ALLOWED


def test_a_check_on_demand_waits_for_the_downloads_like_the_daily_one(check, monkeypatch):
    import unshacklarr.web
    web = importlib.reload(unshacklarr.web)
    web.servicecheck = check
    monkeypatch.setattr(check.sync, "slot_active", {"job": 1})

    with pytest.raises(web.web.HTTPConflict) as refused:
        asyncio.run(web.start_service_check(None))

    assert "download is running" in refused.value.text
    assert check.serve.calls == [] and check.state()["running"] is False  # nothing started, nothing left locked


def test_a_dead_series_does_not_keep_the_service_failing_for_good(check, tmp_path):
    several(tmp_path, *[(tvdb, "") for tvdb in range(111, 122)])  # eleven series: the first ten refused, the eleventh plays
    refuse(check, *range(111, 121))
    first = check.run_check(NOW)["services"]["RTLP"]
    assert (first["ok"], first["tried"], first["next"]) == (False, 10, 121)
    check.serve.calls.clear()

    second = check.run_check(NOW + timedelta(days=1))["services"]["RTLP"]

    assert (second["ok"], second["tvdb"], second["tried"]) == (True, 121, 1)
    assert [(level, title) for level, title, _ in check.sent] == [("error", "RTLP failed its daily check"), ("success", "RTLP passes its daily check again")]


def test_the_probe_of_a_failing_service_moves_on_each_day_and_wraps_without_telling_again(check, tmp_path):
    several(tmp_path, *[(tvdb, "") for tvdb in (111, 112, 113)])
    refuse(check, 111, 112, 113)
    check.run_check(NOW)
    probed = []
    for day in (1, 2):
        check.serve.calls.clear()
        result = check.run_check(NOW + timedelta(days=day))["services"]["RTLP"]
        probed.append((result["tvdb"], result["ok"], result["tried"]))
    assert probed == [(111, False, 1), (112, False, 1)] and len(check.sent) == 1
    del check.serve.by_title[("/api/list-tracks", "show-113")]

    result = check.run_check(NOW + timedelta(days=3))["services"]["RTLP"]

    assert (result["ok"], result["tvdb"], result["tried"]) == (True, 113, 1)
    assert [title for _, title, _ in check.sent] == ["RTLP failed its daily check", "RTLP passes its daily check again"]


def test_a_probe_that_fails_to_sign_in_asks_the_same_series_again(check, tmp_path):
    several(tmp_path, *[(tvdb, "") for tvdb in (111, 112)])
    error = UnshackleError("HTTP 401: session expired")
    error.status, error.error_code = 401, "AUTH_FAILED"
    check.serve.by_title[("/api/list-tracks", "show-111")] = error
    assert check.run_check(NOW)["services"]["RTLP"]["next"] == 111

    result = check.run_check(NOW + timedelta(days=1))["services"]["RTLP"]

    assert (result["tvdb"], result["tried"], result["next"]) == (111, 1, 111)
    assert "show-112" not in [(c[2] or {}).get("title_id") for c in check.serve.calls]


def test_the_sign_in_failure_of_a_later_series_is_the_result(check, tmp_path):
    several(tmp_path, *[(tvdb, "") for tvdb in (111, 112)])
    refuse(check, 111)
    error = UnshackleError("HTTP 401: session expired")
    error.status, error.error_code = 401, "AUTH_FAILED"
    check.serve.by_title[("/api/list-tracks", "show-112")] = error

    result = check.run_check(NOW)["services"]["RTLP"]

    assert (result["ok"], result["tvdb"], result["tried"], result["failed"]) == (False, 112, 2, ["tracks"])
    assert result["stages"]["tracks"]["code"] == "AUTH_FAILED" and result["stages"]["search"]["count"] == 2  # the first series' search
    assert "session expired" in check.sent[0][2]


def test_a_bare_401_ends_the_tries_too(check, tmp_path):
    several(tmp_path, *[(tvdb, "") for tvdb in (111, 112)])
    error = UnshackleError("unauthorised")
    error.status = 401
    check.serve.by_title[("/api/list-tracks", "show-111")] = error

    result = check.run_check(NOW)["services"]["RTLP"]

    assert (result["tried"], result["stages"]["tracks"]["code"]) == (1, "HTTP_401")


@pytest.mark.parametrize("path, reply, stage", [
    ("/api/search", {"results": [None]}, "search"), ("/api/search", ["unexpected"], "search"),
    ("/api/list-titles", {"titles": ["unexpected"]}, "list"), ("/api/list-titles", ["unexpected"], "list"),
    ("/api/list-tracks", ["unexpected"], "tracks"), ("/api/list-tracks", {"video": [None], "audio": []}, "tracks")])
def test_a_malformed_reply_fails_its_stage_and_the_other_services_are_still_checked(check, tmp_path, path, reply, stage):
    check.serve.replies[path] = reply

    done = check.run_check(NOW)

    assert done["services"]["RTLP"]["stages"][stage]["code"] == "BAD_REPLY" and stage in done["services"]["RTLP"]["failed"]
    assert set(done["services"]) == {"RTLP", "MLT"} and check.read_results() == done  # the next service ran, and the day is kept


def test_an_unexpected_exception_in_one_service_leaves_the_others_and_the_save(check, monkeypatch):
    real = check.check_series

    def boom(backend, tag, *args, **kwargs):
        if tag == "RTLP":
            raise KeyError("odd")
        return real(backend, tag, *args, **kwargs)
    monkeypatch.setattr(check, "check_series", boom)

    done = check.run_check(NOW)

    assert done["services"]["RTLP"]["failed"] == ["search", "list", "tracks"] and done["services"]["MLT"]["ok"] is True
    assert check.read_results() == done


def test_a_failing_service_that_is_skipped_or_cannot_search_is_not_announced_as_recovered(check, tmp_path, monkeypatch):
    check.serve.by_title[("/api/search", None)] = UnshackleError("search is down")
    check.serve.replies["/api/search"] = UnshackleError("search is down")
    check.run_check(NOW)
    told = len(check.sent)  # RTLP and MLT failed their search
    assert told == 2

    def down(wanted, keep=3600):
        raise check.requests.ConnectionError("sonarr is down")
    monkeypatch.setattr(check.sync, "sonarr_series", down)
    check.run_check(NOW + timedelta(days=1))  # a failing stage that is skipped now has not passed
    assert len(check.sent) == told

    several(tmp_path, (111, ", options: {--remote: true}"))  # RTLP only relayed now
    monkeypatch.setattr(check.sync, "sonarr_series", lambda wanted, keep=3600: {t: {"title": "Show"} for t in wanted})
    results = check.run_check(NOW + timedelta(days=2))["services"]
    assert results["RTLP"]["skipped"] == "relay" and len(check.sent) == told  # skipping tells nothing


def test_a_failure_stays_unresolved_through_skips_and_its_recovery_is_told_once(check, tmp_path, monkeypatch):
    check.serve.replies["/api/search"] = UnshackleError("search is down")
    check.run_check(NOW)
    assert len(check.sent) == 2  # RTLP and MLT failed their search

    def down(wanted, keep=3600):
        raise check.requests.ConnectionError("sonarr is down")
    monkeypatch.setattr(check.sync, "sonarr_series", down)
    kept = check.run_check(NOW + timedelta(days=1))["services"]  # the search is skipped: neither failed nor passed
    assert kept["RTLP"]["failed"] == [] and kept["RTLP"]["unresolved"] == ["search"] and len(check.sent) == 2

    several(tmp_path, (111, ", options: {--remote: true}"))  # RTLP only relayed now: skipped, its failure still unresolved
    kept = check.run_check(NOW + timedelta(days=2))["services"]
    assert kept["RTLP"]["skipped"] == "relay" and kept["RTLP"]["unresolved"] == ["search"] and len(check.sent) == 2

    several(tmp_path, (111, ""))
    check.serve.replies["/api/search"] = {"results": [{"title": "Show", "id": "show-1"}]}
    monkeypatch.setattr(check.sync, "sonarr_series", lambda wanted, keep=3600: {t: {"title": "Show"} for t in wanted})
    passed = check.run_check(NOW + timedelta(days=3))["services"]
    assert passed["RTLP"]["ok"] is True and passed["RTLP"]["unresolved"] == []
    assert [(level, title) for level, title, _ in check.sent[2:]] == [("success", "RTLP passes its daily check again")]
    check.run_check(NOW + timedelta(days=4))
    assert len(check.sent) == 3  # told once


def test_a_service_only_programmes_series_use_is_shown_as_skipped_not_left_out(check, tmp_path):
    (tmp_path / "config.yaml").write_text("series:\n  111: {service: RTLP, title: show-1}\n  222: {service: IP, programmes: true}\n"
                                         "notifications: {urls: []}\n")

    results = check.run_check(NOW)["services"]

    assert results["RTLP"]["ok"] is True
    assert results["IP"]["skipped"] == "programmes" and results["IP"]["ok"] is None and results["IP"]["stages"] == {}
    assert {payload["service"] for _, _, payload in check.serve.calls} == {"RTLP"} and check.sent == []


@pytest.mark.parametrize("text", [
    "Max retries exceeded with url: /seg.mp4?hdnea=exp=1~hmac=SECRET",
    r'{"url":"https:\/\/cdn.example\/a.m3u8?hdnea=SECRET"}',
    "failed /manifest?hdnea=fixture#fixture"])
def test_every_shape_of_url_loses_its_query_and_fragment(check, tmp_path, text):
    check.serve.replies["/api/list-titles"] = UnshackleError(text)

    check.run_check(NOW)

    saved = (tmp_path / "service_checks.json").read_text()
    for kept in (saved, *(message for _, _, message in check.sent)):
        assert "SECRET" not in kept and "fixture" not in kept and "hdnea" not in kept and "exp=1" not in kept


def test_a_stage_that_never_answers_leaves_no_thread_that_holds_up_the_shutdown(check, monkeypatch):
    monkeypatch.setattr(check, "STAGE_TIMEOUT", 0.2)
    stuck = threading.Event()
    check.serve.replies["/api/list-titles"] = lambda: stuck.wait(10) or {"titles": TITLES}
    try:
        check.run_check(NOW)
        stages = [t for t in threading.enumerate() if t.name == "service-check-stage" and t.is_alive()]
        assert stages and all(t.daemon for t in stages)
    finally:
        stuck.set()


def test_every_request_is_bounded_by_the_stage_timeout(check, monkeypatch):
    monkeypatch.setattr(check, "STAGE_TIMEOUT", 30)

    check.run_check(NOW)

    assert check.serve.timeouts and all(connect <= 5 and read <= 30 for connect, read in check.serve.timeouts)  # list-tracks included


def test_remote_and_server_are_taken_out_of_every_request(check):
    control = {"service": "RTLP", "title": "show-1", "options": {"--remote": True, "--server": "far"}}
    config = check.sync.read_file()
    assert check.sync.serve_params(control, config, check.serve)["remote"] is True  # the series does ask for a relay

    stages = check.check_series(check.serve, "RTLP", control, config, "Show", True)

    assert all(stage["ok"] for stage in stages.values())
    assert check.serve.calls and all("remote" not in p and "server" not in p for _, _, p in check.serve.calls)


@responses.activate
def test_a_full_run_makes_only_the_documented_requests_to_a_cold_real_client(tmp_path, monkeypatch):
    sync = load(tmp_path, monkeypatch)
    (tmp_path / "config.yaml").write_text("series:\n  111: {service: RTLP, title: show-1}\n  222: {service: MLT, title: show-2}\nnotifications: {urls: []}\n")
    from unshacklarr import servicecheck
    check = importlib.reload(servicecheck)
    monkeypatch.setattr(sync.UNSHACKLE, "services", types.MethodType(sync.Unshackle.services, sync.UNSHACKLE))  # not load()'s fake
    sync.UNSHACKLE.configure({"unshackle_mode": "remote", "unshackle_url": "http://serve:8888", "unshackle_api_key": "k" * 40})
    monkeypatch.setattr(sync, "sonarr_series", lambda wanted, keep=3600: {t: {"title": "Show"} for t in wanted})
    monkeypatch.setattr(sync, "notify", lambda *a, **k: True)
    monkeypatch.setattr(sync, "slot_active", {})
    responses.add(responses.GET, "http://serve:8888/api/services", json={"services": [{"tag": "RTLP", "cli_params": []}, {"tag": "MLT", "cli_params": []}]})
    responses.add(responses.POST, "http://serve:8888/api/search", json={"results": [{"title": "Show", "id": "show-1"}]})
    responses.add(responses.POST, "http://serve:8888/api/list-titles", json={"titles": TITLES})
    responses.add(responses.POST, "http://serve:8888/api/list-tracks", json=TRACKS)

    done = check.run_check(NOW)

    assert {tag: r["ok"] for tag, r in done["services"].items()} == {"RTLP": True, "MLT": True}
    asked = {(call.request.method, urlparse(call.request.url).path) for call in responses.calls}
    assert asked == {("GET", "/api/services"), ("POST", "/api/search"), ("POST", "/api/list-titles"), ("POST", "/api/list-tracks")}
    assert not [path for _, path in asked if path.startswith(("/api/session", "/api/download", "/api/remote", "/api/cdm"))]
