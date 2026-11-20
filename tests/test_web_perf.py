"""Regression tests for web backend concurrency, event-loop I/O, and Sonarr/cache performance (#356)."""

import asyncio
import concurrent.futures
import copy
import importlib
import json
import time
from types import SimpleNamespace

import aiohttp
import pytest


def _reload_web(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSHACKLARR_DATA", str(tmp_path))
    import unshacklarr.sync
    import unshacklarr.web

    importlib.reload(unshacklarr.sync)
    return importlib.reload(unshacklarr.web)


def test_networks_concurrent_preserves_cache_deduplicates_and_does_not_starve_busy(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    web.write_config({"settings": {"country": "AU"}, "auth": {}, "series": {}})
    web.PROVIDERS_CACHE.write_text(json.dumps({"AU": {"checked": "2099-01-01T00:00:00+00:00", "logos": {}}}))
    web.tmdb_key = lambda: "fake-key"
    web.service_domains = lambda: {}
    web.UNSHACKLE.logins = lambda: []
    web.sonarr_sync.authentication_setups = lambda: []

    calls = []

    def slow_tmdb(tid):
        calls.append(tid)
        time.sleep(0.25)
        return {"name": f"Net{tid}", "logo": None, "network_country": "US", "providers": {"AU": []}}

    monkeypatch.setattr(web, "tmdb_network", slow_tmdb)

    async def run():
        loop = asyncio.get_running_loop()
        # Simulate a small 2-core NAS executor (6 workers) to ensure TMDB concurrency stays bounded below it.
        prev = getattr(loop, "_default_executor", None)
        small = concurrent.futures.ThreadPoolExecutor(max_workers=6)
        loop.set_default_executor(small)
        try:
            app = aiohttp.web.Application()
            app.router.add_get("/api/networks", web.networks)
            app.router.add_get("/api/busy", web.busy)
            app.router.add_get("/api/log", web.sync_log)
            runner = aiohttp.web.AppRunner(app)
            await runner.setup()
            site = aiohttp.web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port = site._server.sockets[0].getsockname()[1]
            base = f"http://127.0.0.1:{port}"
            try:
                async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=30)) as sess:
                    async def timed(path, delay=0.0):
                        if delay:
                            await asyncio.sleep(delay)
                        t0 = time.perf_counter()
                        async with sess.get(base + path) as resp:
                            body = await resp.json()
                            return resp.status, round((time.perf_counter() - t0) * 1000, 1), body

                    # Overlapping IDs 10..14 test singleflight deduplication; disjoint IDs test lost-update race.
                    r1, r2, r_busy, r_log = await asyncio.gather(
                        timed("/api/networks?tmdb=" + ",".join(str(i) for i in range(1, 15)), 0.0),
                        timed("/api/networks?tmdb=" + ",".join(str(i) for i in range(10, 21)), 0.03),
                        timed("/api/busy", 0.08),
                        timed("/api/log", 0.10),
                    )
                    assert r1[0] == 200 and r2[0] == 200
                    assert r_busy[0] == 200 and r_log[0] == 200
                    assert r_busy[1] < 200, f"/api/busy starved on threadpool: {r_busy[1]}ms"
                    assert r_log[1] < 150, f"/api/log stalled on event loop: {r_log[1]}ms"
            finally:
                await runner.cleanup()
        finally:
            loop._default_executor = prev
            small.shutdown(wait=True)

    asyncio.run(run())

    saved = json.loads(web.NETWORKS_CACHE.read_text())
    expected_ids = {str(i) for i in range(1, 21)}
    assert set(saved) == expected_ids, f"lost cache entries: missing={expected_ids - set(saved)}"
    # Singleflight: each of the 20 IDs should have been queried only once despite overlap on 10..14.
    assert len(calls) == 20, f"expected 20 deduplicated TMDB calls, got {len(calls)}"


def test_runs_live_skips_scanning_completed_history_files(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    web.sonarr_sync.RUNS_DIR.mkdir(parents=True)
    for i in range(10):
        (web.sonarr_sync.RUNS_DIR / f"20261120-{i:04d}.json").write_text(
            json.dumps({"id": f"20261120-{i:04d}", "outcome": "downloaded", "ended": "2026-11-20T00:01:00Z"})
        )
    (web.sonarr_sync.RUNS_DIR / "20261120-9999.json").write_text(
        json.dumps({"id": "20261120-9999", "series": "Live Show", "outcome": None, "ended": None})
    )
    monkeypatch.setattr(web, "cards_on_disk", lambda: pytest.fail("?live=1 must not scan completed history"))

    # Idle: returns empty without touching disk.
    web.sonarr_sync.EpisodeRun.active = {}
    web.sonarr_sync.waiting = {}
    res_idle = asyncio.run(web.runs(SimpleNamespace(query={"live": "1"})))
    assert json.loads(res_idle.text) == []

    # Active + queued: returns both with outcome == "running".
    web.sonarr_sync.EpisodeRun.active = {"20261120-9999": object()}
    web.sonarr_sync.waiting = {42: {"id": "queued-42", "series": "Queued Show", "outcome": "running"}}
    res_live = asyncio.run(web.runs(SimpleNamespace(query={"live": "1"})))
    ids = [c["id"] for c in json.loads(res_live.text)]
    assert ids == ["queued-42", "20261120-9999"]


def test_cookie_state_caches_unwritable_files_and_invalidates_on_write(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    cookies_dir = tmp_path / "Cookies"
    cookies_dir.mkdir(parents=True)
    monkeypatch.setattr(web, "cookies_folder", lambda: cookies_dir)
    monkeypatch.setattr(web, "cache_folder", lambda: tmp_path / "Cache")
    monkeypatch.setattr(web.UNSHACKLE, "services", lambda: [])
    monkeypatch.setattr(web.sonarr_sync, "all_services", lambda: [])

    walks = 0

    def fake_unwritable(folder, most=20):
        nonlocal walks
        walks += 1
        return []

    monkeypatch.setattr(web, "unwritable_files", fake_unwritable)

    assert web.cookie_state()["unwritable"] == []
    assert web.cookie_state()["unwritable"] == []
    assert walks == 1, f"expected cached unwritable_files walk, got {walks}"

    # Config save invalidates the unwritable_files cache.
    web.write_config(web.read_config())
    assert web.cookie_state()["unwritable"] == []
    assert walks == 2


def test_sonarr_series_caches_briefly_and_invalidates(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    calls = 0

    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"id": 1, "tvdbId": 100, "title": f"Show v{calls}", "monitored": True, "statistics": {}}]

    def fake_get(url, **kwargs):
        nonlocal calls
        calls += 1
        return Resp()

    monkeypatch.setattr(web.requests, "get", fake_get)

    first = web.sonarr_series()
    second = web.sonarr_series()
    assert calls == 1
    assert first[0]["title"] == "Show v1" and second[0]["title"] == "Show v1"

    web.write_config(web.read_config())
    third = web.sonarr_series()
    assert calls == 2
    assert third[0]["title"] == "Show v2"


def test_missing_of_managed_skips_zero_missing_only_when_stats_are_fresh_and_complete(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    now = web.datetime(2026, 10, 7, tzinfo=web.timezone.utc)
    (tmp_path / "config.yaml").write_text(
        "series:\n"
        "  1: {service: NF, title: a}\n"
        "  2: {service: NF, title: b}\n"
        "  3: {service: NF, title: c}\n"
        "  4: {service: NF, title: d}\n"
        "  5: {service: NF, title: e}\n"
    )
    library_calls = 0
    episode_queries = []

    def fresh_library():
        return [
            # Complete zero-missing stats -> safe to skip episode query.
            {"id": 11, "tvdbId": 1, "title": "Complete", "monitored": True,
             "statistics": {"episodeCount": 8, "episodeFileCount": 8},
             "seasons": [{"seasonNumber": 1, "monitored": True, "statistics": {"episodeCount": 8, "episodeFileCount": 8}}]},
            # Has 1 missing episode -> must query episodes.
            {"id": 12, "tvdbId": 2, "title": "MissingOne", "monitored": True,
             "statistics": {"episodeCount": 8, "episodeFileCount": 7}},
            # Absent statistics -> must NOT skip.
            {"id": 13, "tvdbId": 3, "title": "NoStats", "monitored": True},
            # Mixed monitored/unmonitored: season stats contradict series stats -> must NOT skip.
            {"id": 14, "tvdbId": 4, "title": "SeasonGap", "monitored": True,
             "statistics": {"episodeCount": 4, "episodeFileCount": 4},
             "seasons": [{"seasonNumber": 2, "monitored": False, "statistics": {"episodeCount": 2, "episodeFileCount": 1}}]},
            # Unmonitored series -> already skipped by monitored check.
            {"id": 15, "tvdbId": 5, "title": "Unmonitored", "monitored": False,
             "statistics": {"episodeCount": 4, "episodeFileCount": 0}},
        ]

    # Seed a STALE (120s old) cache containing all 5 managed TVDB IDs claiming show 2 has zero missing episodes.
    web.sonarr_sync._series_by_tvdb[""] = (
        time.monotonic() - 120.0,
        {
            i: {"id": 10 + i, "tvdbId": i, "title": f"Stale{i}", "monitored": True,
                "statistics": {"episodeCount": 8, "episodeFileCount": 8}}
            for i in range(1, 6)
        },
    )

    def fake_sonarr_get(path, **params):
        nonlocal library_calls
        if path == "series":
            library_calls += 1
            return fresh_library()
        if path == "episode":
            sid = params["seriesId"]
            episode_queries.append(sid)
            return [{"id": sid * 100 + 1, "seasonNumber": 1, "episodeNumber": 1,
                     "airDateUtc": "2026-10-05T10:00:00Z", "monitored": True, "hasFile": False, "title": "Ep 1"}]
        raise AssertionError(f"unexpected sonarr_get({path!r})")

    monkeypatch.setattr(web.sonarr_sync, "sonarr_get", fake_sonarr_get)

    items = web.missing_of_managed(30, now)
    assert library_calls == 1, "stale 1h library cache must be refreshed before skipping zero-missing series"
    assert sorted(episode_queries) == [12, 13, 14]
    assert [i["tvdbId"] for i in items] == [2, 3, 4]


def test_password_required_avoids_deepcopy_and_caches_logged_out(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    web.write_config({
        **web.read_config(),
        "auth": {"password": web.hash_password("secret123"), "secret": "s1"},
        "series": {i: {"service": "NF", "title": f"t{i}"} for i in range(1, 50)},
    })
    cookie = web.session_value({"secret": "s1"})
    web.LOGGED_OUT_FILE.write_text("{}")

    read_json_calls = 0
    real_read_json = web.read_json

    def counting_read_json(path, default):
        nonlocal read_json_calls
        if path == web.LOGGED_OUT_FILE:
            read_json_calls += 1
        return real_read_json(path, default)

    monkeypatch.setattr(web, "read_json", counting_read_json)
    monkeypatch.setattr(copy, "deepcopy", lambda obj: pytest.fail("password_required must not deepcopy config"))

    req = SimpleNamespace(path="/api/log", cookies={web.SESSION_COOKIE: cookie}, headers={}, remote="127.0.0.1")

    async def ok(_req):
        return aiohttp.web.json_response({"ok": True})

    asyncio.run(web.password_required(req, ok))
    asyncio.run(web.password_required(req, ok))
    assert read_json_calls == 1, f"expected LOGGED_OUT_FILE to be cached, read {read_json_calls} times"

    # Logging out that session must immediately invalidate the cache and reject the cookie.
    web.forget_session(cookie)
    with pytest.raises(aiohttp.web.HTTPUnauthorized):
        asyncio.run(web.password_required(req, ok))
