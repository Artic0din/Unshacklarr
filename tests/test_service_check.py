"""The daily check of each service through Unshackle's HTTP API (#319), against a faked Unshackle."""
import asyncio
import importlib
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

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
        self.by_title = {}  # (path, title_id) -> a reply for that series only

    def services(self):
        return [{"tag": "RTLP", "cli_params": []}, {"tag": "MLT", "cli_params": []}]

    def call(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs.get("json")))
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
    monkeypatch.setattr(sync, "sonarr_series", lambda wanted, keep=3600: {tvdb: {"title": "Show"} for tvdb in (111, 112, 222, 333)})
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


def test_a_service_fails_when_three_series_fail_and_keeps_the_first_ones_stages(check, tmp_path):
    several(tmp_path, (111, ", season_pages: {1: {url: show-111b}}"), (112, ""), (113, ""), (114, ""))
    for tvdb in (111, 112, 113, 114):
        check.serve.by_title[("/api/list-tracks", f"show-{tvdb}")] = UnshackleError(f"refused {tvdb}")

    result = check.run_check(NOW)["services"]["RTLP"]

    assert (result["ok"], result["failed"], result["tvdb"], result["tried"]) == (False, ["tracks"], 111, 3)
    assert "refused 111" in result["stages"]["tracks"]["message"]
    asked = {(c[2] or {}).get("title_id") for c in check.serve.calls}
    assert asked >= {"show-111", "show-112", "show-113"} and not asked & {"show-111b", "show-114"}  # one series is one try
    assert [(level, title) for level, title, _ in check.sent] == [("error", "RTLP failed its daily check")]


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

    started = threading.Event()
    release = threading.Event()

    def slow(*args):
        with check._running:
            started.set()
            release.wait(5)
    monkeypatch.setattr(check, "run_check", slow)
    try:
        response = asyncio.run(web.start_service_check(None))
        assert response.status == 202
        assert started.wait(5)
        with pytest.raises(web.web.HTTPConflict):
            asyncio.run(web.start_service_check(None))
    finally:
        release.set()
