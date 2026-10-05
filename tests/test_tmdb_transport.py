import importlib

import pytest
import requests


@pytest.fixture
def tmdb(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSHACKLARR_DATA", str(tmp_path))
    import unshacklarr.sync
    import unshacklarr.web
    importlib.reload(unshacklarr.sync)
    web = importlib.reload(unshacklarr.web)

    def blocked(*args, **kwargs):
        response = requests.Response()
        response.status_code = 403
        response.raise_for_status()

    monkeypatch.setattr(web.requests, "get", blocked)
    return web


class BrowserResponse:
    def __init__(self, status=200, headers=None):
        self.status_code = status
        self.headers = {k.encode(): v.encode() for k, v in (headers or {}).items()}
        self.url = "https://www.themoviedb.org/tv/83867-andor/watch?locale=AU"

    def bytes(self):
        return b'<a href="https://click.justwatch.com/a?r=https%3A%2F%2Fwww.disneyplus.com%2Fbrowse%2Fentity-example">Watch</a>'


class BrowserClient:
    def __init__(self, responses):
        self.responses = iter(responses)

    def get(self, url, **kwargs):
        assert kwargs["query"] == [("locale", "AU")]
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_tmdb_links_work_when_plain_http_is_challenged(tmdb, monkeypatch):
    monkeypatch.setattr(tmdb, "TMDB_CLIENT", BrowserClient([BrowserResponse()]), raising=False)
    assert tmdb.tmdb_links(83867, "AU", {"disneyplus.com": "DSNP"}) == [
        {"service": "DSNP", "url": "https://www.disneyplus.com/browse/entity-example", "country": "AU"}
    ]


def test_browser_http_errors_keep_the_tmdb_error_message(tmdb, monkeypatch):
    monkeypatch.setattr(tmdb, "TMDB_CLIENT", BrowserClient([BrowserResponse(403)]), raising=False)
    with pytest.raises(requests.HTTPError) as error:
        tmdb.tmdb_page("https://www.themoviedb.org/tv/83867/watch", {"locale": "AU"})
    assert tmdb.tmdb_error(error.value) == "TMDB answered 403"


def test_browser_rate_limits_still_retry(tmdb, monkeypatch):
    monkeypatch.setattr(tmdb, "TMDB_CLIENT", BrowserClient([
        BrowserResponse(429, {"Retry-After": "1"}), BrowserResponse()
    ]), raising=False)
    monkeypatch.setattr(tmdb.time, "sleep", lambda _: None)
    assert tmdb.tmdb_links(83867, "AU", {"disneyplus.com": "DSNP"})[0]["service"] == "DSNP"


def test_browser_timeouts_are_reported_as_request_failures(tmdb, monkeypatch):
    from rnet.exceptions import TimeoutError
    monkeypatch.setattr(tmdb, "TMDB_CLIENT", BrowserClient([TimeoutError("timed out")]), raising=False)
    with pytest.raises(requests.Timeout):
        tmdb.tmdb_page("https://www.themoviedb.org/tv/83867/watch", {"locale": "AU"})
