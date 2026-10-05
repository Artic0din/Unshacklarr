import asyncio
import importlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import requests


@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSHACKLARR_DATA", str(tmp_path))
    import unshacklarr.sync
    import unshacklarr.web
    importlib.reload(unshacklarr.sync)
    return importlib.reload(unshacklarr.web)


@pytest.mark.parametrize("tag", ["HMAX", "MAX"])
def test_hbomax_domain_uses_the_installed_service(web, monkeypatch, tag):
    monkeypatch.setattr(web.UNSHACKLE, "services", lambda: [
        {"tag": tag, "url": "https://www.hbomax.com", "help": ""},
    ])
    assert web.service_for("https://play.hbomax.com/show/example", web.service_domains()) == tag


def test_hmax_fallback_works_when_help_names_max_com(web, monkeypatch):
    monkeypatch.setattr(web.UNSHACKLE, "services", lambda: [
        {"tag": "HMAX", "url": "https://www.max.com", "help": ""},
    ])
    domains = web.service_domains()
    assert web.service_for("https://play.hbomax.com/show/example", domains) == "HMAX"
    assert domains["m6.fr"] == "M6"


def test_localized_hmax_link_becomes_a_series_url(web, monkeypatch):
    response = requests.Response()
    response.status_code = 200
    response._content = (
        b'<a href="https://click.justwatch.com/a?r=https%3A%2F%2Fplay.hbomax.com'
        b'%2Fch%2Fen%2Fshow%2F8931dfbf-d113-43de-8ee2-43bb594330d1%2Fs1%2Fe1-test">Watch</a>'
    )
    monkeypatch.setattr(web, "tmdb_page", lambda url, params: response)
    assert web.tmdb_links(91183, "AU", {"hbomax.com": "HMAX"}) == [{
        "service": "HMAX", "country": "AU",
        "url": "https://play.hbomax.com/show/8931dfbf-d113-43de-8ee2-43bb594330d1",
    }]


def test_legacy_cache_refreshes_once_then_works_without_unshackle(web, monkeypatch):
    monkeypatch.setattr(web, "read_config", lambda: {"tmdb_countries": ["AU"]})
    checked = datetime.now(timezone.utc).isoformat()
    cached = {"countries": ["AU"], "checked": checked, "links": [{"service": "MAX", "url": "saved", "country": "AU"}]}
    web.TMDB_CACHE.write_text(json.dumps({"91183": cached}))
    monkeypatch.setattr(web, "service_domains", lambda: {"hbomax.com": "HMAX"})
    links = [{"service": "HMAX", "url": "saved", "country": "AU"}]
    monkeypatch.setattr(web, "tmdb_links", lambda *args: links)
    request = SimpleNamespace(match_info={"tmdb_id": "91183"}, query={})
    assert json.loads(asyncio.run(web.suggest(request)).body)["links"] == links

    def stalled():
        raise AssertionError("A fresh cache must not contact Unshackle")

    monkeypatch.setattr(web, "service_domains", stalled)
    assert json.loads(asyncio.run(web.suggest(request)).body)["links"] == links


def test_legacy_cache_is_kept_if_refresh_cannot_reach_unshackle(web, monkeypatch):
    monkeypatch.setattr(web, "read_config", lambda: {"tmdb_countries": ["AU"]})
    cached = {"countries": ["AU"], "checked": "2020-01-01T00:00:00+00:00", "links": [{"service": "MAX", "url": "saved", "country": "AU"}]}
    web.TMDB_CACHE.write_text(json.dumps({"91183": cached}))

    def unavailable():
        raise web.UnshackleError("unreachable")

    monkeypatch.setattr(web, "service_domains", unavailable)
    request = SimpleNamespace(match_info={"tmdb_id": "91183"}, query={})
    assert json.loads(asyncio.run(web.suggest(request)).body)["links"] == cached["links"]
