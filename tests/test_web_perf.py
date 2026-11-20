"""Regression tests for web backend concurrency, event-loop I/O, and Sonarr/cache performance (#356)."""

import asyncio
import concurrent.futures
import copy
import importlib
import json
import threading
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import aiohttp
import pytest


def _reload_web(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSHACKLARR_DATA", str(tmp_path))
    import unshacklarr.sync
    import unshacklarr.web

    importlib.reload(unshacklarr.sync)
    return importlib.reload(unshacklarr.web)


def test_executor_scales_worker_count_with_cpus(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    monkeypatch.setattr(web.os, "cpu_count", lambda: 16)

    async def run():
        async with asynccontextmanager(web.configure_executor)(None):
            assert asyncio.get_running_loop()._default_executor._max_workers == 64

    asyncio.run(run())


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
        # Exercise the production executor's minimum size on a 2-core NAS.
        monkeypatch.setattr(web.os, "cpu_count", lambda: 2)
        executor = web.configure_executor(None)
        await anext(executor)
        try:
            app = aiohttp.web.Application()
            app.cleanup_ctx.append(web.flush_networks_on_cleanup)
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
            await executor.aclose()

    asyncio.run(run())

    saved = json.loads(web.NETWORKS_CACHE.read_text())
    expected_ids = {str(i) for i in range(1, 21)}
    assert set(saved) == expected_ids, f"lost cache entries: missing={expected_ids - set(saved)}"
    # Singleflight: each of the 20 IDs should have been queried only once despite overlap on 10..14.
    assert len(calls) == 20, f"expected 20 deduplicated TMDB calls, got {len(calls)}"


def test_networks_persists_lookup_when_request_is_cancelled(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    monkeypatch.setattr(web, "tmdb_key", lambda: "fake-key")
    release = threading.Event()

    async def run():
        loop = asyncio.get_running_loop()
        started = asyncio.Event()

        def fetch(tmdb_id):
            loop.call_soon_threadsafe(started.set)
            assert release.wait(5), "TMDB lookup was never released"
            return {"name": "Network", "network_country": "US", "providers": {}}

        monkeypatch.setattr(web, "tmdb_network", fetch)
        async with asynccontextmanager(web.flush_networks_on_cleanup)(None):
            request = asyncio.create_task(web.networks(SimpleNamespace(query={"tmdb": "1"})))
            try:
                await asyncio.wait_for(started.wait(), timeout=5)
                request.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await request
            finally:
                release.set()
            await web._network_lookups[loop].inflight[1]

    asyncio.run(run())
    assert web.NETWORKS_CACHE.exists(), "cancelled request lost the completed TMDB lookup"
    assert json.loads(web.NETWORKS_CACHE.read_text())["1"]["name"] == "Network"


def test_networks_cleanup_cancels_queued_lookups_and_saves_completed(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    release = threading.Event()
    lock = threading.Lock()
    calls = []
    slots = web.TMDB_CONCURRENCY

    async def run():
        loop = asyncio.get_running_loop()
        saturated = asyncio.Event()

        def fetch(tmdb_id):
            with lock:
                calls.append(tmdb_id)
                if len(calls) == slots + 1:
                    loop.call_soon_threadsafe(saturated.set)
            if tmdb_id > 1:
                assert release.wait(5), "TMDB lookups were never released"
            return {"name": f"Net{tmdb_id}", "network_country": "US", "providers": {}}

        monkeypatch.setattr(web, "tmdb_network", fetch)
        async with asynccontextmanager(web.configure_executor)(None):
            cleanup = asynccontextmanager(web.flush_networks_on_cleanup)(None)
            await cleanup.__aenter__()
            lookups = web._network_lookups[loop] = web._NetworkLookups()
            try:
                await lookups.lookup(1)
                lookups.inflight.update({i: asyncio.create_task(lookups.lookup(i)) for i in range(2, 201)})
                await asyncio.wait_for(saturated.wait(), timeout=5)
            finally:
                try:
                    await asyncio.wait_for(cleanup.__aexit__(None, None, None), timeout=1)
                finally:
                    release.set()

    asyncio.run(run())
    assert sorted(calls) == list(range(1, slots + 2))
    saved = json.loads(web.NETWORKS_CACHE.read_text())
    assert set(saved) == {"1"}
    assert saved["1"]["name"] == "Net1"


def test_networks_older_batch_does_not_overwrite_newer_lookup(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    monkeypatch.setattr(web, "tmdb_key", lambda: "fake-key")
    monkeypatch.setattr(web, "brand_logos", lambda country: {})
    monkeypatch.setattr(web, "service_domains", lambda: {})
    release = threading.Event()
    calls = 0

    async def run():
        loop = asyncio.get_running_loop()
        slow_started = asyncio.Event()

        def fetch(tmdb_id):
            nonlocal calls
            if tmdb_id == 2:
                loop.call_soon_threadsafe(slow_started.set)
                assert release.wait(5), "slow TMDB lookup was never released"
                name = "Slow"
            else:
                calls += 1
                name = "Old" if calls == 1 else "New"
            return {"name": name, "network_country": "US", "providers": {}}

        monkeypatch.setattr(web, "tmdb_network", fetch)
        async with asynccontextmanager(web.flush_networks_on_cleanup)(None):
            older = asyncio.create_task(web.networks(SimpleNamespace(query={"tmdb": "1,2"})))
            try:
                await asyncio.wait_for(slow_started.wait(), timeout=5)
                lookups = web._network_lookups[loop]
                owner = lookups.inflight.get(1)
                if owner is not None:
                    await owner
                await lookups.flush_task
                # Expire ID 1 while the original batch is still waiting for ID 2.
                web.NETWORKS_CACHE.write_text(json.dumps({"1": {"checked": ""}}))
                newer = await web.networks(SimpleNamespace(query={"tmdb": "1"}))
                assert json.loads(newer.text)["1"]["name"] == "New"
            finally:
                release.set()
                await older

    asyncio.run(run())
    saved = json.loads(web.NETWORKS_CACHE.read_text())
    assert saved["1"]["name"] == "New"
    assert saved["2"]["name"] == "Slow"


def test_networks_newer_lookup_survives_in_progress_cache_write(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    names = iter(("Old", "New"))
    monkeypatch.setattr(web, "tmdb_network", lambda tid: {
        "name": next(names), "network_country": "US", "providers": {},
    })
    release = threading.Event()
    write_atomic = web.write_atomic

    async def run():
        loop = asyncio.get_running_loop()
        writing_old = asyncio.Event()

        def gated_write(path, content):
            if json.loads(content)["1"]["name"] == "Old":
                loop.call_soon_threadsafe(writing_old.set)
                assert release.wait(5), "old cache write was never released"
            write_atomic(path, content)

        monkeypatch.setattr(web, "write_atomic", gated_write)
        async with asynccontextmanager(web.flush_networks_on_cleanup)(None):
            lookups = web._network_lookups[loop] = web._NetworkLookups()
            await lookups.lookup(1)
            try:
                await asyncio.wait_for(writing_old.wait(), timeout=5)
                await lookups.lookup(1)
                assert (await lookups.read_cache())["1"]["name"] == "New"
            finally:
                release.set()
            await lookups.flush_task

    asyncio.run(run())
    assert json.loads(web.NETWORKS_CACHE.read_text())["1"]["name"] == "New"


@pytest.mark.parametrize("failure", ["lookup", "cache-write"])
def test_networks_error_does_not_drop_successful_lookups(tmp_path, monkeypatch, failure):
    web = _reload_web(tmp_path, monkeypatch)
    monkeypatch.setattr(web, "tmdb_key", lambda: "fake-key")
    monkeypatch.setattr(web, "brand_logos", lambda country: {})
    monkeypatch.setattr(web, "service_domains", lambda: {})

    def fetch(tmdb_id):
        if failure == "lookup" and tmdb_id == 1:
            raise ValueError("unexpected TMDB response")
        return {"name": "Network", "network_country": "US", "providers": {}}

    monkeypatch.setattr(web, "tmdb_network", fetch)
    if failure == "cache-write":
        def denied(*args):
            raise PermissionError("network cache not writable")

        monkeypatch.setattr(web, "write_atomic", denied)
    async def run():
        async with asynccontextmanager(web.flush_networks_on_cleanup)(None):
            return await web.networks(SimpleNamespace(query={"tmdb": "1,2"}))

    response = asyncio.run(run())
    assert response.status == 200
    assert set(json.loads(response.text)) == ({"2"} if failure == "lookup" else {"1", "2"})


def test_networks_cold_batch_starts_eight_lookups_at_once(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    monkeypatch.setattr(web, "tmdb_key", lambda: "fake-key")
    monkeypatch.setattr(web, "brand_logos", lambda country: {})
    monkeypatch.setattr(web, "service_domains", lambda: {})
    started, release = threading.Event(), threading.Event()
    lock = threading.Lock()
    active = 0

    def fetch(tmdb_id):
        nonlocal active
        with lock:
            active += 1
            if active == 8:
                started.set()
        assert release.wait(5), "TMDB lookups were never released"
        return {"name": "Network", "network_country": "US", "providers": {}}

    monkeypatch.setattr(web, "tmdb_network", fetch)

    async def run():
        executor = web.configure_executor(None)
        await anext(executor)
        try:
            pending = asyncio.create_task(web.networks(SimpleNamespace(query={"tmdb": "1,2,3,4,5,6,7,8"})))
            try:
                assert await asyncio.to_thread(started.wait, 2), "fewer than eight TMDB lookups started"
            finally:
                release.set()
                response = await pending
            assert len(json.loads(response.text)) == 8
        finally:
            await executor.aclose()

    asyncio.run(run())


def test_networks_coalesces_cold_cache_writes(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    monkeypatch.setattr(web, "tmdb_key", lambda: "fake-key")
    monkeypatch.setattr(web, "brand_logos", lambda country: {})
    monkeypatch.setattr(web, "service_domains", lambda: {})
    monkeypatch.setattr(web, "tmdb_network", lambda tid: {"name": f"Net{tid}", "network_country": "US", "providers": {}})
    ids = {str(i) for i in range(1, 21)}
    writes = 0
    write_atomic = web.write_atomic

    def count_write(path, content):
        nonlocal writes
        if path == web.NETWORKS_CACHE:
            writes += 1
        write_atomic(path, content)

    monkeypatch.setattr(web, "write_atomic", count_write)

    async def run():
        response = await web.networks(SimpleNamespace(query={"tmdb": ",".join(sorted(ids))}))
        assert set(json.loads(response.text)) == ids

        async def wait_for_cache():
            while set(web.read_json(web.NETWORKS_CACHE, {})) != ids:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_cache(), timeout=5)

    asyncio.run(run())
    assert writes <= 2, f"20 cold lookups rewrote the cache {writes} times"


def test_networks_retries_failed_write_without_another_request(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    monkeypatch.setattr(web, "NETWORKS_RETRY_DELAY", 0.01)
    monkeypatch.setattr(web, "tmdb_key", lambda: "fake-key")
    monkeypatch.setattr(web, "brand_logos", lambda country: {})
    monkeypatch.setattr(web, "service_domains", lambda: {})
    monkeypatch.setattr(web, "tmdb_network", lambda tid: {"name": "Network", "network_country": "US", "providers": {}})
    write_atomic = web.write_atomic
    attempts = 0

    async def run():
        loop = asyncio.get_running_loop()
        written = asyncio.Event()

        def fail_once(path, content):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise PermissionError("network cache temporarily not writable")
            write_atomic(path, content)
            loop.call_soon_threadsafe(written.set)

        monkeypatch.setattr(web, "write_atomic", fail_once)
        async with asynccontextmanager(web.flush_networks_on_cleanup)(None):
            response = await web.networks(SimpleNamespace(query={"tmdb": "1"}))
            assert json.loads(response.text)["1"]["name"] == "Network"
            await asyncio.wait_for(written.wait(), timeout=1)
            assert json.loads(web.NETWORKS_CACHE.read_text())["1"]["name"] == "Network"

    asyncio.run(run())
    assert attempts == 2


def test_networks_retries_cache_merge_after_read_failure(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    monkeypatch.setattr(web, "NETWORKS_RETRY_DELAY", 0.01)
    monkeypatch.setattr(web, "tmdb_key", lambda: "fake-key")
    monkeypatch.setattr(web, "brand_logos", lambda country: {})
    monkeypatch.setattr(web, "service_domains", lambda: {})
    monkeypatch.setattr(web, "tmdb_network", lambda tid: {"name": f"Net{tid}", "network_country": "US", "providers": {}})
    path = web.NETWORKS_CACHE
    existing = {"1": {"name": "Existing"}}
    path.write_text(json.dumps(existing))
    assert web.read_json_cached(path, {}) == existing
    read_text = type(path).read_text
    failed_read = threading.Event()
    readable = False

    def read_cache(target, *args, **kwargs):
        if target == path and not readable:
            failed_read.set()
            raise OSError("temporary NAS read failure")
        return read_text(target, *args, **kwargs)

    monkeypatch.setattr(type(path), "read_text", read_cache)

    async def run():
        nonlocal readable
        response = await web.networks(SimpleNamespace(query={"tmdb": "2"}))
        assert json.loads(response.text)["2"]["name"] == "Net2"
        assert await asyncio.to_thread(failed_read.wait, 5), "cache merge never tried to read the file"
        assert json.loads(read_text(path)) == existing, "failed read wiped existing cache entries"
        readable = True

        response = await web.networks(SimpleNamespace(query={"tmdb": "3"}))
        assert json.loads(response.text)["3"]["name"] == "Net3"

        async def wait_for_cache():
            while set(json.loads(path.read_text())) != {"1", "2", "3"}:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_cache(), timeout=5)

    asyncio.run(run())
    assert json.loads(path.read_text())["2"]["name"] == "Net2"


def test_suggest_prefers_pending_network_over_disk_cache(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    monkeypatch.setattr(web, "service_domains", lambda: {"bbc.co.uk": "iP"})
    link = {"service": "iP", "url": "https://www.bbc.co.uk/iplayer/episodes/show",
            "country": "GB", "kind": "native", "found_by": "homepage"}
    web.TMDB_CACHE.write_text(json.dumps({"1": {
        "countries": web.read_config()["tmdb_countries"],
        "checked": web.datetime.now(web.timezone.utc).isoformat(),
        "map": web.SUGGEST_MAP,
        "links": [link],
    }}))
    web.NETWORKS_CACHE.write_text(json.dumps({"1": {"name": "PBS"}}))

    async def run():
        lookups = web._network_lookups[asyncio.get_running_loop()] = web._NetworkLookups()
        lookups.pending["1"] = {"name": "BBC One"}
        return await web.suggest(SimpleNamespace(match_info={"tmdb_id": "1"}, query={}))

    response = asyncio.run(run())
    assert json.loads(response.text)["links"] == [link]


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
    cards = json.loads(res_live.text)
    assert [c["id"] for c in cards] == ["queued-42", "20261120-9999"]
    assert [c["outcome"] for c in cards] == ["running", "running"]


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


def test_unwritable_scan_started_before_clear_cannot_repopulate_cache(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    started, release = threading.Event(), threading.Event()

    def scan(folder, most):
        if not started.is_set():
            started.set()
            assert release.wait(5), "old scan was never released"
            return ["old-cookie.txt"]
        return []

    monkeypatch.setattr(web, "unwritable_files", scan)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        old_scan = pool.submit(web.cached_unwritable_files, tmp_path)
        try:
            assert started.wait(5), "old scan never started"
            web.clear_unwritable_cache()
            assert web.cached_unwritable_files(tmp_path) == []
        finally:
            release.set()
        assert old_scan.result(timeout=5) == ["old-cookie.txt"]

    assert web.cached_unwritable_files(tmp_path) == []


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

    key, _, entries = web._sonarr_series_cache
    expired = time.monotonic() - web.SONARR_SERIES_TTL - 1
    monkeypatch.setattr(web, "_sonarr_series_cache", (key, expired, entries))
    third = web.sonarr_series()
    assert calls == 2
    assert third[0]["title"] == "Show v2"

    web.write_config(web.read_config())
    fourth = web.sonarr_series()
    assert calls == 3
    assert fourth[0]["title"] == "Show v3"


def test_hand_edited_config_invalidates_sonarr_library_and_inflight_fetch(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    web.write_config({"settings": {"sonarr_url": "http://sonarr.test", "sonarr_api_key": "old-key"}})
    web.read_config()  # Load the initial stamp before editing the file by hand.
    started, release = threading.Event(), threading.Event()
    old_calls = 0

    def fake_get(url, *, headers, **kwargs):
        nonlocal old_calls
        if headers["X-Api-Key"] == "old-key":
            old_calls += 1
            if old_calls == 2:
                started.set()
                assert release.wait(5), "old fetch was never released"
            show = {"id": 1, "tvdbId": 100, "title": "Old Library", "seasonType": "dvd"}
        else:
            assert headers["X-Api-Key"] == "replacement-key"
            show = {"id": 2, "tvdbId": 100, "title": "Fresh Library"}
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: [show])

    monkeypatch.setattr(web.requests, "get", fake_get)
    assert web.sonarr_series()[0]["title"] == "Old Library"
    assert web.known_order(100) == "dvd"
    monkeypatch.setattr(web, "SONARR_SERIES_TTL", 0)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        old_fetch = pool.submit(web.sonarr_series)
        try:
            assert started.wait(5), "old fetch never started"
            web.SERIES_FILE.write_text("settings: {sonarr_url: 'http://sonarr.test', sonarr_api_key: replacement-key}")
            assert web.read_config()["settings"]["sonarr_api_key"] == "replacement-key"
            assert web.known_order(100) == "official"
        finally:
            release.set()
        assert old_fetch.result(timeout=5)[0]["title"] == "Old Library"

    assert web.known_order(100) == "official"
    assert web.sonarr_series()[0]["title"] == "Fresh Library"


@pytest.mark.parametrize("save_settings", [False, True], ids=["clear", "settings-save"])
def test_sonarr_series_inflight_fetch_cannot_repopulate_caches(tmp_path, monkeypatch, save_settings):
    web = _reload_web(tmp_path, monkeypatch)
    old_url, new_url = "http://old-sonarr.test", "http://new-sonarr.test"
    old_settings = {"sonarr_url": old_url, "sonarr_api_key": "old-key"}
    web.write_config({"settings": old_settings})
    started, release = threading.Event(), threading.Event()

    def fake_get(url, *, headers, **kwargs):
        if not started.is_set():
            assert (url, headers["X-Api-Key"]) == (f"{old_url}/api/v3/series", "old-key")
            started.set()
            assert release.wait(5), "old fetch was never released"
            title = "Old Library"
        else:
            expected_url, expected_key = (new_url, "new-key") if save_settings else (old_url, "old-key")
            assert (url, headers["X-Api-Key"]) == (f"{expected_url}/api/v3/series", expected_key)
            title = "Fresh Library"
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: [{"id": 1, "tvdbId": 100, "title": title}])

    monkeypatch.setattr(web.requests, "get", fake_get)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        def start_old_fetch():
            fetch = pool.submit(web.sonarr_series)
            assert started.wait(5), "old fetch never started"
            return fetch

        try:
            if save_settings:
                original_write = web.write_atomic

                def write_during_fetch(*args):
                    nonlocal old_fetch
                    old_fetch = start_old_fetch()
                    original_write(*args)

                old_fetch = None
                monkeypatch.setattr(web, "write_atomic", write_during_fetch)
                web.write_config({"settings": {"sonarr_url": new_url, "sonarr_api_key": "new-key"}})
                assert old_fetch is not None
            else:
                old_fetch = start_old_fetch()
                web.clear_sonarr_series_cache()
            assert web.sonarr_series()[0]["title"] == "Fresh Library"
        finally:
            release.set()
        assert old_fetch.result(timeout=5)[0]["title"] == "Old Library"

    assert web.sonarr_sync.sonarr_series({100})[100]["title"] == "Fresh Library"
    assert web.sonarr_series()[0]["title"] == "Fresh Library"


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


def test_json_cache_stat_error_uses_default(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    path = web.NETWORKS_CACHE
    path.write_text('{"1": "Network"}')
    assert web.read_json_cached(path, {}) == {"1": "Network"}
    original_stat = type(path).stat

    def stat(target, *args, **kwargs):
        if target == path:
            raise PermissionError("cache stat denied")
        return original_stat(target, *args, **kwargs)

    monkeypatch.setattr(type(path), "stat", stat)
    default = {}
    assert web.read_json_cached(path, default) is default


def test_a_malformed_revocation_file_keeps_revoked_sessions_out(tmp_path, monkeypatch):
    web = _reload_web(tmp_path, monkeypatch)
    auth = {"secret": "test-session-secret"}
    cookie = web.session_value(auth)
    req = SimpleNamespace(cookies={web.SESSION_COOKIE: cookie})
    web.forget_session(cookie)
    assert not web.logged_in(req, auth)
    web.LOGGED_OUT_FILE.write_text("{")  # torn or hand-edited: the list of revoked sessions can't be read
    with pytest.raises(OSError, match="Invalid JSON"):
        web.logged_in(req, auth)  # fails closed: the revoked cookie is not accepted again
    with pytest.raises(OSError, match="Invalid JSON"):
        web.forget_session(cookie)  # and a logout does not replace the list it could not read
    # other state read for a write keeps healing itself: a malformed file is read as empty and written anew
    other = tmp_path / "state.json"
    other.write_text("{")
    assert web.read_json(other, {}, strict=True) == {}
    assert web.read_json_cached(other, {}, strict=True) == {}


@pytest.mark.parametrize("operation", ["stat", "read_text"])
def test_unreadable_revocation_file_fails_closed(tmp_path, monkeypatch, operation):
    web = _reload_web(tmp_path, monkeypatch)
    auth = {"secret": "test-session-secret"}
    cookie = web.session_value(auth)
    req = SimpleNamespace(cookies={web.SESSION_COOKIE: cookie})
    assert web.logged_in(req, auth), "a missing revocation file is valid"
    web.forget_session(cookie)
    with monkeypatch.context() as patch:
        path_type = type(web.LOGGED_OUT_FILE)
        original = getattr(path_type, operation)

        def denied(path, *args, **kwargs):
            if path == web.LOGGED_OUT_FILE:
                raise PermissionError("revocation file unreadable")
            return original(path, *args, **kwargs)

        patch.setattr(path_type, operation, denied)
        with pytest.raises(PermissionError, match="revocation file unreadable"):
            web.logged_in(req, auth)
        if operation == "read_text":
            with pytest.raises(PermissionError, match="revocation file unreadable"):
                web.forget_session(cookie)


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

    def counting_read_json(path, default, strict=False, **kwargs):
        nonlocal read_json_calls
        if path == web.LOGGED_OUT_FILE:
            read_json_calls += 1
        return real_read_json(path, default, strict=strict, **kwargs)

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
