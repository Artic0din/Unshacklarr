"""Each support module on its own: cookie files, atomic writes, CDM devices and unshackle.yaml."""

import json
import os
import stat
import sys
import threading
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import cast

import pytest
import responses
import yaml

from unshacklarr.backend import Unshackle, UnshackleError
from unshacklarr.cdm import CdmError, NO_CDM, add, choose, delete, folders, read, remote_delete, remote_save, state
from unshacklarr.cookies import CookieError, from_json, list_all, normalise, parse, save
from unshacklarr.files import PRIVATE, no_credentials, shared_or_private, write_atomic
import time


def test_container_sources_are_immutable_and_identifiable():
    root = Path(__file__).parents[1]
    core_commit = "306f167b956265b47aada64eb3f273618dd5c17d"
    core = (root / "docker" / "unshackle.Dockerfile").read_text()
    app = (root / "Dockerfile").read_text()
    github = (root / ".github" / "workflows" / "ci.yml").read_text()
    forgejo = (root / ".forgejo" / "workflows" / "ci.yml").read_text()
    compose = (root / "docker-compose.example.yml").read_text()

    assert f"ARG UNSHACKLE_COMMIT={core_commit}" in core
    assert 'git -C /app fetch --depth 1 origin "$UNSHACKLE_COMMIT"' in core
    assert 'test "$(git -C /app rev-parse HEAD)" = "$UNSHACKLE_COMMIT"' in core
    assert "LABEL org.opencontainers.image.revision=$UNSHACKLE_COMMIT" in core
    assert f"UNSHACKLE_COMMIT: {core_commit}" in compose
    # the pin only counts when the build reads this repository's Dockerfile, which knows UNSHACKLE_COMMIT
    assert "context: https://github.com/Artic0din/Unshacklarr.git#main:docker" in compose
    assert "LABEL org.opencontainers.image.revision=$SOURCE_REVISION" in app
    assert "SOURCE_REVISION=${{ github.sha }}" in github
    assert 'SOURCE_REVISION="$GITHUB_SHA"' in forgejo


@responses.activate
@pytest.mark.parametrize("provider_failure", [False, True])
def test_authentication_errors_identify_the_server_or_provider(tmp_path, provider_failure):
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://backend:8786", "unshackle_api_key": "test-value"})
    payload = {"status": 401, "message": "Secret Key is Invalid."}
    if provider_failure:
        payload = {"error_code": "AUTH_FAILED", "message": "Authentication failed: Hayu playback failed: Invalid Token (ref ef1b9f)",
                   "details": {"service": "HAYU", "operation": "list_tracks"}, "ref": "ef1b9f"}
    responses.post("http://backend:8786/api/list-tracks", status=401, json=payload)
    with pytest.raises(UnshackleError) as caught:
        backend.call("POST", "/api/list-tracks", json={"service": "HAYU"})
    message = str(caught.value)
    assert caught.value.status == 401
    if provider_failure:
        assert caught.value.error_code == "AUTH_FAILED"
        assert "HAYU" in message and "Invalid Token" in message and "ef1b9f" in message
        assert "HTTP 401" in message
        assert message.count("ef1b9f") == 1
        assert "sign-in/session" in message and "refused the API key" not in message
    else:
        assert caught.value.error_code == ""
        assert "internal API key" in message and "Settings › Connections › Unshackle" in message


@responses.activate
@pytest.mark.parametrize("long_url", [False, True])
def test_provider_error_keeps_separate_reference_and_redacts_before_truncating(tmp_path, long_url):
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://backend:8786", "unshackle_api_key": "test-value"})
    message = "Hayu playback failed: Invalid Token"
    if long_url:
        message += " https://reader:" + "sensitive" * 80 + "@proxy.example.invalid/failure"
    responses.post("http://backend:8786/api/list-tracks", status=401,
                   json={"error_code": "AUTH_FAILED", "message": message, "ref": "ref-only",
                         "details": {"service": "HAYU"}})
    with pytest.raises(UnshackleError) as caught:
        backend.call("POST", "/api/list-tracks", json={"service": "HAYU"})
    displayed = str(caught.value)
    assert "ref-only" in displayed
    assert "reader" not in displayed and "sensitive" not in displayed
    if long_url:
        assert "proxy.example.invalid" in displayed


@responses.activate
def test_long_provider_error_keeps_reference(tmp_path):
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://unshackle.invalid", "unshackle_api_key": "server-key"})
    responses.get("http://unshackle.invalid/api/services", status=500,
                  json={"message": "Failure " + "x" * 600, "ref": "support-ref"})
    with pytest.raises(UnshackleError) as caught:
        backend.call("GET", "/api/services")
    displayed = str(caught.value)
    assert "support-ref" in displayed
    assert len(displayed.removeprefix("Unshackle: HTTP 500: ")) <= 500


@responses.activate
def test_provider_service_is_redacted_in_public_error(tmp_path):
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://unshackle.invalid", "unshackle_api_key": "server-key"})
    responses.get(
        "http://unshackle.invalid/api/services",
        status=500,
        json={"message": "Failure", "details": {"service": "https://reader:sensitive@provider.invalid"}},
    )
    with pytest.raises(UnshackleError) as caught:
        backend.call("GET", "/api/services")
    displayed = str(caught.value)
    assert "reader" not in displayed
    assert "sensitive" not in displayed


@responses.activate
@pytest.mark.parametrize("reason", ["Account is in a different region from yours", "requested CDM is not permitted for this account"])
def test_provider_authentication_reason_is_not_replaced_by_server_configuration_advice(tmp_path, reason):
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://backend:8786", "unshackle_api_key": "test-value"})
    responses.post("http://backend:8786/api/list-tracks", status=401,
                   json={"error_code": "AUTH_FAILED", "message": reason, "details": {"service": "HAYU"}})
    with pytest.raises(UnshackleError) as caught:
        backend.call("POST", "/api/list-tracks", json={"service": "HAYU"})
    assert caught.value.status == 401 and reason in str(caught.value)
    assert not backend.proxy_refused


@responses.activate
def test_provider_error_keeps_service_status_reason_and_reference(tmp_path):
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://backend:8786", "unshackle_api_key": "test-key"})
    responses.post(
        "http://backend:8786/api/list-tracks",
        status=403,
        json={
            "error_code": "GEOFENCE",
            "message": "This account is not available in Australia (ref region-1)",
            "details": {"service": "HAYU"},
            "ref": "region-1",
        },
    )
    with pytest.raises(UnshackleError) as caught:
        backend.call("POST", "/api/list-tracks", json={"service": "HAYU"})
    assert str(caught.value) == "HAYU through Unshackle: HTTP 403: This account is not available in Australia (ref region-1)"
    assert caught.value.status == 403


@responses.activate
@pytest.mark.parametrize("body", ["", "<html><h1>Bad gateway</h1></html>"])
def test_unshackle_error_does_not_show_an_empty_or_html_message(tmp_path, body):
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://backend:8786", "unshackle_api_key": "test-key"})
    responses.get("http://backend:8786/api/services", status=502, body=body)
    with pytest.raises(UnshackleError) as caught:
        backend.call("GET", "/api/services")
    assert str(caught.value) == "Unshackle: HTTP 502: Bad Gateway"


@responses.activate
def test_unshackle_error_keeps_safe_plain_text_detail(tmp_path):
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://backend:8786", "unshackle_api_key": "test-key"})
    responses.get("http://backend:8786/api/services", status=503, body="Maintenance in progress; retry in 10 minutes")
    with pytest.raises(UnshackleError) as caught:
        backend.call("GET", "/api/services")
    assert str(caught.value) == "Unshackle: HTTP 503: Maintenance in progress; retry in 10 minutes"


def test_public_errors_redact_sensitive_urls_and_headers():
    message = (
        "GET https://example.invalid/path?api_key=one&language=en&access_token=two "
        "Authorization: Bearer three X-Api-Key: four Cookie: session=five"
    )
    shown = no_credentials(message)
    assert "one" not in shown and "two" not in shown and "three" not in shown and "four" not in shown and "five" not in shown
    assert "language=en" in shown


def test_public_errors_redact_unshackle_secret_header():
    shown = no_credentials("X-Secret-Key: example-sensitive-value")
    assert shown == "X-Secret-Key: ***"


def test_cookie_files_are_read_saved_and_kept_in_their_folder(tmp_path):
    # formats, expiry, no path outside the folder
    netscape = "# Netscape HTTP Cookie File\n.molotov.tv\tTRUE\t/\tTRUE\t4102444800\ttoken\tabc\n#HttpOnly_.molotov.tv\tTRUE\t/\tTRUE\t0\tsid\tx\n"
    assert [c["name"] for c in parse(netscape)] == ["token", "sid"]
    js = json.dumps([{"domain": ".crave.ca", "name": "a", "value": "1", "expirationDate": 4102444800, "httpOnly": True, "secure": True}])
    assert parse(normalise(js))[0] == {"domain": "crave.ca", "name": "a", "expires": 4102444800}
    d = tmp_path
    folder = Path(d)
    save(folder, "MLT", "default", netscape)
    assert (folder / "MLT" / "default.txt").stat().st_mode & 0o077 == 0  # not for other users, nor its group here
    assert list_all(folder)["MLT"][0]["count"] == 2 and not list_all(folder)["MLT"][0]["expired"]
    rtl = "\n".join(["# Netscape HTTP Cookie File", ".rtlplay.be\tTRUE\t/\tTRUE\t0\t.AspNetCore.Cookies\tx",
                     ".rtlplay.be\tTRUE\t/\tTRUE\t1000\tak_bmsc\ty", ".dpgmedia.net\tTRUE\t/\tTRUE\t1000\tbm_sv\tz"])
    s = save(folder, "RTLP", "default", rtl)
    assert (s["expired"], s["session"], s["expires"]) == (False, 1, None)
    old = ".x.tv\tTRUE\t/\tTRUE\t1000\ttoken\tv"
    with pytest.raises(CookieError, match="expired"):
        save(folder, "OLD", "default", old)
    assert not (folder / "OLD").exists()
    (folder / "OLD.txt").write_text(old)
    assert list_all(folder)["OLD"][0]["expired"]
    for bad in (("../x", "default"), ("MLT", "../../etc"), ("MLT", "a/b")):
        try:
            save(folder, *bad, netscape)
            raise AssertionError(bad)
        except CookieError:
            pass
    try:
        save(folder, "MLT", "default", "hello")
        raise AssertionError("not cookies")
    except CookieError:
        pass


def test_atomic_writes_are_whole_and_keep_permissions(tmp_path):
    # whole files, their permissions, writers at once
    d = tmp_path
    folder = Path(d)
    f = folder / "a.json"
    write_atomic(f, "{}")
    assert f.read_text() == "{}" and stat.S_IMODE(f.stat().st_mode) == PRIVATE  # new: its owner only
    os.chmod(f, 0o644)
    write_atomic(f, b"[1]")
    assert f.read_bytes() == b"[1]" and stat.S_IMODE(f.stat().st_mode) == 0o644  # an existing file keeps its own
    write_atomic(f, "x", 0o600)
    assert stat.S_IMODE(f.stat().st_mode) == 0o600  # asked for: given
    threads = [threading.Thread(target=write_atomic, args=(f, chr(65 + i) * 1000)) for i in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(set(f.read_text())) == 1  # writers at once: one whole file, never a mix
    assert not list(folder.glob(".*.tmp"))  # and no leftover
    assert shared_or_private(folder) == PRIVATE


def test_cdm_devices_and_unshackle_yaml_are_edited_safely(tmp_path):
    # devices, unshackle.yaml rewritten with its comments, no path
    d = tmp_path
    base = Path(d)
    conf = base / "unshackle.yaml"
    conf.write_text("# my settings\ndirectories:\n  wvds: /config/unshackle/WVDs  # theirs\n  prds: /config/unshackle/PRDs\n"
                    "cdm:\n  default: tv_sl3000   # the usual one\n  NF: 'old_l1'\n  AMZN:\n    '>=1080': tv_sl3000\n    default: old_l1\n"
                    "remote_cdm:\n  - name: FAR\n    \"Device Type\": PLAYREADY\n    secret: s\n")
    os.chmod(conf, 0o664)
    wvds, prds = folders(conf)
    assert (wvds, prds) == (base / "WVDs", base / "PRDs")
    add(wvds, prds, "old_l1.wvd", b"WVD\x02\x02\x01\x00" + b"k" * 40)
    add(wvds, prds, "tv_sl3000.prd", b"PRD\x03" + b"k" * 40)
    (prds / "folder_sl2000").mkdir()
    s = state(conf, wvds, prds)
    assert [(x["name"], x["kind"], x["level"], x["type"]) for x in s["devices"]] == [
        ("old_l1", "Widevine", "L1", "Android"), ("folder_sl2000", "PlayReady", "SL2000", ""), ("tv_sl3000", "PlayReady", "SL3000", "")]
    assert next(x for x in s["devices"] if x["name"] == "old_l1")["used_by"] == ["AMZN", "NF"]
    assert s["map"]["AMZN"] == {"rule": ["old_l1", "tv_sl3000"]}
    assert s["remote"][0] == {"name": "FAR", "kind": "PlayReady", "type": "playready", "label": "PlayReady, remote", "editable": True,
                              "has_secret": True, "device_type": "PLAYREADY", "used_by": []}  # never its secret
    choose(conf, wvds, prds, "nf", "FAR")  # the existing key, whatever its case
    choose(conf, wvds, prds, "DSNP", "tv_sl3000")
    text = conf.read_text()
    assert "# my settings" in text and "# the usual one" in text and "NF: 'FAR'" in text and "DSNP: tv_sl3000" in text
    assert "remote_cdm:\n  - name: FAR\n" in text and text.count("\n") == 15  # one line added, nothing else moved
    choose(conf, wvds, prds, "DSNP", None)
    choose(conf, wvds, prds, "default", "old_l1")
    assert "DSNP" not in conf.read_text() and "  default: old_l1   # the usual one\n" in conf.read_text()
    assert stat.S_IMODE(conf.stat().st_mode) == 0o664  # its permissions kept
    for bad in (("AMZN", "old_l1"), ("default", None), ("DSNP", "nope"), ("../x", "old_l1")):
        try:
            choose(conf, wvds, prds, *bad)
            raise AssertionError(bad)
        except CdmError:
            pass
    for bad in (("x.txt", b"WVD"), ("x.wvd", b"PRD"), ("../x.wvd", b"WVD"), ("old_l1.wvd", b"WVD")):
        try:
            add(wvds, prds, *bad)
            raise AssertionError(bad)
        except CdmError:
            pass
    try:
        delete(conf, wvds, prds, "tv_sl3000", "PlayReady")  # DSNP uses it
        raise AssertionError("in use")
    except CdmError:
        pass
    delete(conf, wvds, prds, "folder_sl2000", "PlayReady")
    # no CDM for a service; never for the default
    choose(conf, wvds, prds, "YT", NO_CDM)
    assert "  YT: none\n" in conf.read_text()
    try:
        choose(conf, wvds, prds, "default", NO_CDM)
        raise AssertionError("default none")
    except CdmError:
        pass
    # remote CDMs: added, changed (its secret kept), refused when unsafe, deleted when unused
    before = conf.read_text().split("remote_cdm:")[0]
    remote_save(conf, {"name": "wv_api", "type": "widevine", "host": "https://cdm.example/", "secret": "k1", "device_name": "l1", "security_level": "1"}, None)
    wv = next(e for e in read(conf)["remote_cdm"] if e["name"] == "wv_api")
    assert wv == {"name": "wv_api", "device_type": "ANDROID", "system_id": 26830, "security_level": 1, "host": "https://cdm.example/", "secret": "k1", "device_name": "l1"}
    remote_save(conf, {"name": "wv_api", "type": "widevine", "host": "https://cdm.example/", "secret": "", "device_name": "l2"}, "wv_api")
    wv = next(e for e in read(conf)["remote_cdm"] if e["name"] == "wv_api")
    assert (wv["device_name"], wv["secret"]) == ("l2", "k1")  # an empty secret keeps the saved one, for the same server
    try:
        remote_save(conf, {"name": "wv_api", "type": "widevine", "host": "https://attacker.example/", "secret": "", "device_name": "l2"}, "wv_api")
        raise AssertionError("the saved secret followed a new address")
    except CdmError:
        pass
    remote_save(conf, {"name": "wv_api", "type": "widevine", "host": "https://cdm2.example/", "secret": "k2", "device_name": "l2"}, "wv_api")
    wv = next(e for e in read(conf)["remote_cdm"] if e["name"] == "wv_api")
    assert (wv["host"], wv["secret"]) == ("https://cdm2.example/", "k2")
    assert conf.read_text().split("remote_cdm:")[0] == before  # everything before it as it was
    for bad in ({"name": "x", "type": "playready", "host": "https://h/", "secret": "s"}, {"name": "old_l1", "type": "decrypt_labs"},
                {"name": "y", "type": "custom_api"}, {"name": "z", "type": "widevine", "host": "ftp://h", "secret": "s"}):
        try:
            remote_save(conf, bad, None)
            raise AssertionError(bad)
        except CdmError:
            pass
    try:
        remote_delete(conf, "FAR")  # NF uses it
        raise AssertionError("in use")
    except CdmError:
        pass
    remote_delete(conf, "wv_api")
    assert [e["name"] for e in read(conf)["remote_cdm"]] == ["FAR"]
    assert not (prds / "folder_sl2000").exists()
    assert (wvds / "old_l1.wvd").stat().st_mode & 0o077 == 0  # not for other users, nor its group here


def test_a_one_line_cdm_mapping_is_never_cut_down_to_one_service(tmp_path):
    conf = tmp_path / "unshackle.yaml"
    wvds, prds = folders(conf)
    add(wvds, prds, "l3.wvd", b"WVD\x02\x02\x03\x00" + b"k" * 40)
    for line in ("cdm: {default: l3, AMZN: l3}\n", "cdm: {default: l3, AMZN: l3, NF: l3}\n"):
        conf.write_text("# mine\n" + line + "dl:\n  sub_format: srt\n")
        before = conf.read_text()
        for service, device in (("NF", "l3"), ("AMZN", None), ("AMZN", NO_CDM), *([("NF", None)] if "NF: l3" in line else [])):
            try:
                choose(conf, wvds, prds, service, device)
                raise AssertionError((line, service, device))
            except CdmError:
                pass
            assert conf.read_text() == before  # refused, the file untouched
            assert read(conf)["cdm"] == yaml.safe_load(line)["cdm"]  # every service keeps its device
    conf.write_text("cdm:\n  default: l3\n  NF: l3\n  nf: l3\n")  # two spellings: removing one leaves the other in force
    with pytest.raises(CdmError):
        choose(conf, wvds, prds, "NF", None)
    conf.write_text("cdm:\n  default: l3\n  AMZN: l3\n")  # block style, as before
    choose(conf, wvds, prds, "NF", "l3")
    assert read(conf)["cdm"] == {"default": "l3", "AMZN": "l3", "NF": "l3"}


def test_odd_cookie_exports_are_refused_in_words(tmp_path):
    for cookie in ({"expirationDate": "abc"}, {"expirationDate": "inf"}, {"value": "a\tb"}):
        try:
            normalise(json.dumps([{"domain": ".x.tv", "name": "a", "value": "1", **cookie}]))
            raise AssertionError(cookie)
        except CookieError:
            pass


def test_a_device_named_in_capitals_can_be_deleted(tmp_path):
    conf = tmp_path / "unshackle.yaml"
    conf.write_text("cdm:\n  default: other\n")
    wvds, prds = folders(conf)
    wvds.mkdir()
    (wvds / "Dev.WVD").write_bytes(b"WVD\x02\x02\x01" + b"k" * 40)
    delete(conf, wvds, prds, "Dev", "Widevine")
    assert not list(wvds.iterdir())


def test_an_address_that_is_not_unshackle_serve_is_said_so(monkeypatch, tmp_path):
    import responses
    from unshacklarr.backend import Unshackle, UnshackleError
    u = Unshackle(tmp_path)
    u.configure({"unshackle_mode": "remote", "unshackle_url": "http://proxy.example", "unshackle_api_key": "k"})
    with responses.RequestsMock() as r:
        r.get("http://proxy.example/api/health", body="<html>Log in</html>", status=200)
        try:
            u.health()
            raise AssertionError("HTML taken for serve")
        except UnshackleError as e:
            assert "no JSON" in str(e)


def test_the_address_of_unshackle_serve_is_masked_when_it_does_not_answer_like_serve(tmp_path):
    import responses
    from unshacklarr.backend import Unshackle, UnshackleError
    u = Unshackle(tmp_path)
    u.configure({"unshackle_mode": "remote", "unshackle_url": "http://me:pw0rd@proxy.example", "unshackle_api_key": "k"})
    with responses.RequestsMock() as r:
        r.get("http://me:pw0rd@proxy.example/api/health", body="<html>Log in</html>", status=200)
        with pytest.raises(UnshackleError) as e:
            u.health()
    assert "pw0rd" not in str(e.value)
    assert "no JSON" in str(e.value)


def test_a_redirect_from_unshackle_serve_is_not_followed_and_names_the_new_host(tmp_path):
    import responses
    from unshacklarr.backend import Unshackle, UnshackleError
    u = Unshackle(tmp_path)
    u.configure({"unshackle_mode": "remote", "unshackle_url": "http://old.example", "unshackle_api_key": "k"})
    with responses.RequestsMock(assert_all_requests_are_fired=False) as r:
        r.get("http://old.example/api/health", status=302, headers={"Location": "http://me:pw0rd@new.example/api/health"})
        r.get("http://me:pw0rd@new.example/api/health", json={"status": "ok"})  # followed: the key goes there too
        with pytest.raises(UnshackleError) as e:
            u.health()
        assert [c.request.url for c in r.calls] == ["http://old.example/api/health"]
    assert "redirects to http://new.example:" in str(e.value) and "pw0rd" not in str(e.value)  # the address to type, with no route
    with responses.RequestsMock() as r:
        r.get("http://old.example/api/health", status=301, headers={"Location": "https://old.example/serve/api/health"})
        with pytest.raises(UnshackleError) as e:
            u.health()
    assert "redirects to https://old.example/serve:" in str(e.value)  # http to https behind a base path
    with responses.RequestsMock() as r:
        r.get("http://old.example/api/health", status=302, headers={"Location": "http://old.example/login"})
        with pytest.raises(UnshackleError) as e:
            u.health()
    assert "redirects to http://old.example/login, which is not" in str(e.value) and "use that address" not in str(e.value)


def test_a_linked_unshackle_yaml_or_a_folder_outside_it_is_refused(tmp_path):
    secret = tmp_path / "config.yaml"
    secret.write_text("auth: {secret: s3cr3t}\n")
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "unshackle.yaml").symlink_to(secret)  # planted by another user of the shared folder
    for call in (lambda: read(shared / "unshackle.yaml"), lambda: choose(shared / "unshackle.yaml", *folders(tmp_path / "x.yaml"), "NF", None)):
        try:
            call()
            raise AssertionError("read through a link")
        except CdmError:
            pass
    conf = tmp_path / "unshackle.yaml"
    conf.write_text("directories:\n  prds: ..\n")
    try:
        folders(conf)
        raise AssertionError("'..' taken as a folder")
    except CdmError:
        pass


def test_a_local_serve_gets_its_socket_and_key_without_the_command_line(tmp_path, monkeypatch):
    import sys
    from unshacklarr.backend import Local
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:1")
    pkg = tmp_path / "unshackle" / "core"
    pkg.mkdir(parents=True)
    (tmp_path / "unshackle" / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    (pkg / "config.py").write_text("class C:\n    serve = {}\nconfig = C()\n")
    # a stand-in for unshackle serve: what it was given, where serve itself would bind
    (pkg / "__main__.py").write_text(
        "import os, sys, json\nfrom aiohttp import web\nfrom unshackle.core.config import config\n"
        "def main(argv):\n"
        "    seen = {'argv': sys.argv, 'key': config.serve['api_secret'], 'env': [k for k in os.environ if k.startswith('UNSHACKLARR')],\n"
        "            'users': config.serve.get('users')}\n"
        "    app = web.Application()\n"
        "    app.router.add_get('/api/health', lambda r: web.json_response(seen) if r.headers.get('X-Secret-Key') == seen['key'] else web.json_response({'status': 401}, status=401))\n"
        "    app.router.add_get('/api/remote/logins', lambda r: web.json_response({'logins': []}))\n"
        "    web.run_app(app, host='127.0.0.1', port=1, print=None)\n")  # port 1: only the handed socket can serve
    command = tmp_path / ".venv" / "bin" / "unshackle"  # a git clone's: the launcher runs from the clone
    command.parent.mkdir(parents=True)
    command.write_text(f"#!{sys.executable}\n")
    command.chmod(0o755)
    local = Local(tmp_path / "serve.log")
    try:
        local.start(str(command))
        import requests
        seen = requests.get(
            f"{local.url}/api/health",
            headers={"X-Secret-Key": local.key},
            proxies={"http": None, "https": None, "all": None},
            timeout=5,
        ).json()
        assert seen["key"] == local.key and seen["env"] == []  # the key arrived, and left the environment
        assert str(local.url.rsplit(":", 1)[1]) not in " ".join(seen["argv"])  # nor the port on the command line
        # Unshackle 6 serves its proxies only to a key with server_proxy: this run's key has it (5.x reads no such field)
        mine = seen["users"][local.key]  # every right the unlisted admin key had: listed, it would lose them otherwise
        assert all(mine[k] is True for k in ("server_proxy", "admin", "server_cdm", "server_vault", "server_accounts"))
    finally:
        local.stop()


def test_a_local_serve_without_secure_approvals_is_rejected_before_use(tmp_path, monkeypatch):
    import sys
    import unshacklarr.backend as backend

    class Process:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    class Response:
        def __init__(self, status):
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise backend.requests.HTTPError(f"{self.status_code} response")

    monkeypatch.setattr(backend, "unshackle_python", lambda command: (sys.executable, tmp_path))
    monkeypatch.setattr(backend.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(
        backend.requests,
        "get",
        lambda url, **kwargs: Response(404 if url.endswith("/api/remote/logins") else 200),
    )
    local = backend.Local(tmp_path / "serve.log")

    with pytest.raises(UnshackleError, match="secure device approvals"):
        local.start("unshackle")

    assert local.process is None


def test_a_local_serve_retries_a_transient_secure_approval_check(tmp_path, monkeypatch):
    import sys
    import unshacklarr.backend as backend

    class Process:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    class Response:
        def __init__(self, status):
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise backend.requests.HTTPError(f"{self.status_code} response")

    approval_statuses = iter((503, 200))
    monkeypatch.setattr(backend, "unshackle_python", lambda command: (sys.executable, tmp_path))
    monkeypatch.setattr(backend.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(backend.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        backend.requests,
        "get",
        lambda url, **kwargs: Response(next(approval_statuses) if url.endswith("/api/remote/logins") else 200),
    )
    local = backend.Local(tmp_path / "serve.log")

    local.start("unshackle")

    assert local.process is not None


def test_a_local_serve_sends_its_secret_key_to_the_health_check(tmp_path, monkeypatch):
    import sys
    import unshacklarr.backend as backend

    class Process:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    class Response:
        def __init__(self, status):
            self.status_code = status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise backend.requests.HTTPError(f"{self.status_code} response")

    seen = []
    now = iter((0.0, 0.0, 91.0))
    monkeypatch.setattr(backend, "unshackle_python", lambda command: (sys.executable, tmp_path))
    monkeypatch.setattr(backend.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(backend.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(backend.time, "monotonic", lambda: next(now, 91.0))

    def fake_get(url, **kwargs):
        headers = kwargs.get("headers") or {}
        seen.append((url, headers, kwargs.get("allow_redirects"), kwargs.get("proxies")))
        if headers.get("X-Secret-Key") != local.key:
            return Response(401)
        return Response(200)

    monkeypatch.setattr(backend.requests, "get", fake_get)
    local = backend.Local(tmp_path / "serve.log")

    local.start("unshackle")
    expected_proxies = {"http": None, "https": None, "all": None}
    assert seen == [
        (f"{local.url}/api/health", {"X-Secret-Key": local.key}, False, expected_proxies),
        (f"{local.url}/api/remote/logins", {"X-Secret-Key": local.key}, False, expected_proxies),
    ]
    assert local.process is not None


def test_a_local_serve_rejects_a_redirect_from_the_health_check(tmp_path, monkeypatch):
    import sys
    import unshacklarr.backend as backend

    class Process:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

    class Response:
        def __init__(self, status):
            self.status_code = status

    now = iter((0.0, 0.0, 91.0))
    monkeypatch.setattr(backend, "unshackle_python", lambda command: (sys.executable, tmp_path))
    monkeypatch.setattr(backend.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(backend.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(backend.time, "monotonic", lambda: next(now, 91.0))
    monkeypatch.setattr(backend.requests, "get", lambda url, **kwargs: Response(302))
    local = backend.Local(tmp_path / "serve.log")

    with pytest.raises(UnshackleError, match="did not answer within 90 s"):
        local.start("unshackle")
    assert local.process is None


def broken_command(tmp_path):
    """An unshackle command whose Python (its shebang) is gone, as after the venv was removed or moved."""
    command = tmp_path / ".venv" / "bin" / "unshackle"
    command.parent.mkdir(parents=True)
    command.write_text(f"#!{tmp_path}/no-such-python\n")
    command.chmod(0o755)
    return str(command)


def test_a_local_serve_whose_python_is_missing_is_an_unshackle_error(tmp_path):
    from unshacklarr.backend import Local
    local = Local(tmp_path / "serve.log")
    with pytest.raises(UnshackleError, match="no-such-python"):
        local.start(broken_command(tmp_path))
    assert local.process is None


def test_local_serve_startup_error_redacts_credentials(tmp_path, monkeypatch):
    from unshacklarr.backend import Local
    local = Local(tmp_path / "serve.log")

    def boom(*args, **kwargs):
        raise OSError("cannot launch https://alice:super-secret@proxy.example/bin/python?token=tok123")

    monkeypatch.setattr("unshacklarr.backend.subprocess.Popen", boom)
    with pytest.raises(UnshackleError) as err:
        local.start(broken_command(tmp_path))
    message = str(err.value)
    assert "super-secret" not in message and "tok123" not in message
    assert "https://***@proxy.example/bin/python?token=***" in message
    assert local.process is None


def test_asking_where_unshackle_keeps_its_files_is_an_unshackle_error_when_it_cannot_run_or_hangs(tmp_path, monkeypatch):
    import subprocess
    from unshacklarr.backend import Local
    local = Local(tmp_path / "serve.log")
    command = broken_command(tmp_path)
    with pytest.raises(UnshackleError, match="no-such-python"):
        local.paths(command)

    def hangs(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr("unshacklarr.backend.subprocess.run", hangs)
    with pytest.raises(UnshackleError, match="did not answer"):
        local.paths(command)


# From #5, by Artic0din: serve's load_errors (Unshackle after 5.4.0)
@responses.activate
def test_a_service_that_failed_to_load_is_refused_before_the_job_others_go_on(tmp_path):
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://backend:8786", "unshackle_api_key": "test-api-secret"})
    responses.get("http://backend:8786/api/health", json={"status": "ok"})
    error = "AMZN: failed to import - ModuleNotFoundError: No module named 'tldextract'"
    responses.get("http://backend:8786/api/services", json={"services": [{"tag": "BINGE"}], "load_errors": [error]})
    responses.post("http://backend:8786/api/download", json={"job_id": "queued"})

    assert backend.health()["status"] == "ok"
    with pytest.raises(UnshackleError, match="AMZN.*tldextract.*is missing"):
        backend.download({"service": "AMZN"})
    assert not any(call.request.method == "POST" for call in responses.calls)
    assert backend.download({"service": "BINGE"}) == "queued"
    assert backend.download({"service": "AMZN", "remote": "box"}) == "queued"

    responses.replace(responses.GET, "http://backend:8786/api/services",
                      json={"services": [{"tag": "AMZN"}], "load_errors": []})
    assert backend.download({"service": "AMZN"}) == "queued"


@responses.activate
def test_a_load_error_s_own_words_stay_out_of_the_message(tmp_path):
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://backend:8786", "unshackle_api_key": "test-api-secret"})
    responses.get("http://backend:8786/api/services", json={"services": [],
                  "load_errors": ["AMZN: failed to import - RuntimeError: password=private-value"]})
    with pytest.raises(UnshackleError) as caught:
        backend.download({"service": "AMZN"})
    assert "private-value" not in str(caught.value)
    assert "startup log says why" in str(caught.value)


@responses.activate
def test_unshackle_6s_refused_proxy_and_its_limit_of_requests_are_said_plainly(tmp_path):
    # Unshackle 6 resolves a country code into its own proxies only for a key with server_proxy, and may cap a key's
    # requests per hour (429 with Retry-After): the first is told with what to do, the second carries its wait
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://backend:8786", "unshackle_api_key": "test-api-secret"})
    responses.post("http://backend:8786/api/download", status=400, json={"status": 400, "message":
                   "This server does not resolve country codes into proxies. Pass --proxy with a full proxy URI (http://, https:// or socks5://)."})
    responses.get("http://backend:8786/api/download/jobs/j1", status=429, json={"status": 429, "message": "Rate limit exceeded."},
                  headers={"Retry-After": "42"})
    try:
        backend.call("POST", "/api/download", json={"proxy": "au"})
        raise AssertionError("refused")
    except UnshackleError as e:
        assert "Settings › Connections › Unshackle" in str(e) and backend.proxy_refused
    try:
        backend.call("GET", "/api/download/jobs/j1")
        raise AssertionError("limited")
    except UnshackleError as e:
        assert e.retry_after == 42


@responses.activate
def test_a_cdm_named_for_the_download_is_sent_and_its_refusal_said(tmp_path):
    # Unshackle 6's --cdm (API: cdm) is taken only when unshackle.yaml allows it (serve: cdm_overrides); the options
    # 5.4 doesn't know say they need 6.0, since 5.4 drops them without a word
    from unshacklarr import options
    assert options.to_params({"--cdm": "my_l3", "--forced-subs-only": True}, options.dl_specs()) == {"cdm": "my_l3", "forced_subs_only": True}
    helps = {s["flag"]: s["help"] for s in options.dl_specs()}
    assert helps["--cdm"].endswith("Unshackle 6.0 or later.") and not helps["--quality"].endswith("6.0 or later.")
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://backend:8786", "unshackle_api_key": "test-api-secret"})
    responses.post("http://backend:8786/api/download", status=403, json={"status": 403, "message": "The requested CDM is not permitted for API downloads."})
    try:
        backend.call("POST", "/api/download", json={"cdm": "my_l3"})
        raise AssertionError("refused")
    except UnshackleError as e:
        assert "cdm_overrides" in str(e)


@responses.activate
def test_a_restarted_local_serve_is_asked_for_its_config_again(tmp_path, monkeypatch):
    # the config is kept 10 minutes: a restart that left it would go on refusing a download "No CDM" after a device was picked
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_mode": "local"})
    monkeypatch.setattr(backend.local, "endpoint", lambda command: ("http://backend:8786", "test-api-secret"))
    monkeypatch.setattr(backend.local, "restart", lambda command: None)
    config = responses.get("http://backend:8786/api/config", json={"config": {"cdm": {}}})
    assert backend.cdm_config() == {} and backend.cdm_config() == {}
    assert config.call_count == 1  # kept
    responses.replace(responses.GET, "http://backend:8786/api/config", json={"config": {"cdm": {"NF": "my_l3"}}})
    backend.restart()
    assert backend.cdm_config() == {"NF": "my_l3"}


def test_remote_services_are_asked_on_a_host_up_for_less_than_ten_minutes(tmp_path, monkeypatch):
    # time.monotonic counts from the host's boot: 100 s after it, the empty list it starts with is not a fresh answer
    from unshacklarr import backend as backend_module
    backend = Unshackle(tmp_path)
    asked = []
    monkeypatch.setattr(backend_module.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(backend, "config", lambda: {"remote_services": ["nas"]})
    monkeypatch.setattr(backend, "call", lambda method, path, **kw: asked.append((path, kw.get("params"))) or {"services": [{"tag": "NF"}]})
    assert backend.remote_services() == [{"name": "nas", "services": [{"tag": "NF"}]}]
    assert backend.remote_services() == [{"name": "nas", "services": [{"tag": "NF"}]}]
    assert asked == [("/api/services", {"remote": "nas"})]  # then kept 10 minutes


def test_remote_services_not_answered_are_asked_again_after_a_minute(tmp_path, monkeypatch):
    # serve still starting after a reboot: its failure is kept a minute, not the 10 minutes of an answer
    from unshacklarr import backend as backend_module
    backend = Unshackle(tmp_path)
    clock, answers = [100.0], [UnshackleError("unshackle serve is unreachable"), {"remote_services": ["nas"]}]
    monkeypatch.setattr(backend_module.time, "monotonic", lambda: clock[0])

    def config():
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(backend, "config", config)
    monkeypatch.setattr(backend, "call", lambda method, path, **kw: {"services": [{"tag": "NF"}]})
    assert backend.remote_services() == []
    clock[0] = 159.0
    assert backend.remote_services() == [] and len(answers) == 1  # within the minute: not asked again
    clock[0] = 161.0
    assert backend.remote_services() == [{"name": "nas", "services": [{"tag": "NF"}]}] and not answers


@responses.activate
def test_a_service_login_serve_could_not_finish_is_not_called_a_refused_key(tmp_path):
    # by mj23au (#25): serve answers 401 for two things: a wrong key ({"status": 401, "message": "Secret Key is Invalid."})
    # and a service whose login failed (AUTH_FAILED, with an error_code). The second was shown as "refused the API key"
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://backend:8786", "unshackle_api_key": "test-api-secret"})
    responses.post("http://backend:8786/api/search", status=401, json={"status": "error", "error_code": "AUTH_FAILED",
                   "message": "Authentication failed: This login needs the user, and only a download job or a remote session can reach the user"})
    responses.get("http://backend:8786/api/services", status=401, json={"status": 401, "message": "Secret Key is Invalid."})
    try:
        backend.call("POST", "/api/search", json={"service": "X", "query": "q"})
        raise AssertionError("login failed")
    except UnshackleError as e:
        assert "This login needs the user" in str(e) and "API key" not in str(e)
    try:
        backend.call("GET", "/api/services")
        raise AssertionError("key refused")
    except UnshackleError as e:
        assert "rejected the internal API key" in str(e)  # the fork's wording (#151)


def test_load_balancer_and_short_technical_cookies_say_nothing_of_the_login(tmp_path):
    # Crave's AWSALBTG lasts a week, Apple's utsdc an hour, whatever the login: a file of session cookies stays undated
    from unshacklarr import cookies
    soon = int(time.time()) + 3600
    path = tmp_path / "c.txt"
    path.write_text(f"# Netscape HTTP Cookie File\n.bellmedia.ca\tTRUE\t/\tTRUE\t{soon}\tAWSALBTG\tx\n"
                    f".apple.com\tTRUE\t/\tTRUE\t{soon}\tutsdc\tx\n.apple.com\tTRUE\t/\tTRUE\t0\tmyacinfo\tx\n")
    assert cookies.summary(path)["expires"] is None



def test_one_odd_cookie_file_does_not_hide_the_others(tmp_path, monkeypatch):
    # an "inf" expiry overflowed int(), and a file that can't be read raised: the whole Cookies list failed
    from unshacklarr import cookies
    good = "# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tTRUE\t0\tsid\tx\n"
    (tmp_path / "NF.txt").write_text(good)
    (tmp_path / "AMZN.txt").write_text(good + ".amazon.com\tTRUE\t/\tTRUE\tinf\tat-main\tx\n")
    (tmp_path / "DSNP.txt").write_text(good)
    read_text = Path.read_text
    def locked(self, *args, **kwargs):
        if self.name == "DSNP.txt":
            raise PermissionError(13, "Permission denied", str(self))  # left owned by root after a docker exec
        return read_text(self, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", locked)
    found = cookies.list_all(tmp_path)
    assert found["NF"][0]["count"] == 1 and not found["NF"][0].get("unreadable")
    assert found["AMZN"][0]["count"] == 1  # the inf line is skipped like any other bad date
    assert found["DSNP"] == [{"profile": "", "count": 0, "updated": None, "expires": None, "session": 0,
                              "expired": False, "unreadable": True}]


@responses.activate
def test_a_remote_servers_services_come_from_unshackles_own_api(tmp_path):
    # After 6.0.0: the names in /api/config, each server's services in /api/services?remote=; 6.0.0 has neither
    from responses import matchers
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://backend:8786", "unshackle_api_key": "test-api-secret"})
    responses.get("http://backend:8786/api/config", json={"config": {"dl": {}, "remote_services": ["community", "down"]}})
    nf = {"tag": "NF", "remote": "community", "cli_params": []}
    responses.get("http://backend:8786/api/services", match=[matchers.query_param_matcher({"remote": "community"})], json={"services": [nf]})
    responses.get("http://backend:8786/api/services", match=[matchers.query_param_matcher({"remote": "down"})], status=503, json={})
    assert backend.remote_services() == [{"name": "community", "services": [nf]}]  # the server down left out

    old = Unshackle(tmp_path)
    old.configure({"unshackle_url": "http://old:8786", "unshackle_api_key": "test-api-secret"})
    responses.get("http://old:8786/api/config", json={"config": {"dl": {}}})
    assert old.remote_services() == []  # 6.0.0: no names, nothing asked


@responses.activate
def test_remote_names_its_server_as_serve_takes_it(tmp_path):
    # dl's --remote [--server X] goes to serve as remote: "X"; the one server of remote_services when none is named
    import json
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://backend:8786", "unshackle_api_key": "test-api-secret"})
    responses.get("http://backend:8786/api/config", json={"config": {"remote_services": ["community"]}})
    responses.post("http://backend:8786/api/download", json={"job_id": "j"})
    backend.download({"service": "NF", "remote": True})
    backend.download({"service": "NF", "remote": True, "server": "other"})
    sent = [json.loads(c.request.body) for c in responses.calls if c.request.method == "POST"]
    assert sent == [{"service": "NF", "remote": "community"}, {"service": "NF", "remote": "other"}]
    responses.post("http://backend:8786/api/list-titles", json={"titles": []})  # a listing goes through it too
    backend.call("POST", "/api/list-titles", json={"service": "NF", "title_id": "1", "remote": True})
    assert json.loads(responses.calls[-1].request.body)["remote"] == "community"

    responses.replace(responses.GET, "http://backend:8786/api/config", json={"config": {"remote_services": ["a", "b"]}})
    backend._config = (0.0, {})
    with pytest.raises(UnshackleError, match="--server"):
        backend.download({"service": "NF", "remote": True})


@responses.activate
def test_serves_passing_errors_say_their_code_and_a_restart_waits_for_its_downloads(tmp_path, monkeypatch):
    # After 6.0.0 serve answers a network hitch with 424 and drains before a restart: both worth another try
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://backend:8786", "unshackle_api_key": "test-api-secret"})
    responses.post("http://backend:8786/api/list-titles", status=424, json={"error_code": "NETWORK_ERROR", "message": "Connection lost"})
    with pytest.raises(UnshackleError, match=r"Connection lost \(NETWORK_ERROR\)"):
        backend.call("POST", "/api/list-titles", json={"service": "NF", "title_id": "1"})

    responses.get("http://backend:8786/api/dashboard/status", json={"errors": {"NF": {"SERVICE_ERROR": 2}}})
    assert backend.dashboard("") is None and backend.dashboard("dash-key") == {"errors": {"NF": {"SERVICE_ERROR": 2}}}
    assert responses.calls[-1].request.headers["X-Secret-Key"] == "dash-key"  # the dashboard's own key, not the API's

    monkeypatch.setattr(Unshackle, "mode", property(lambda self: "local"))  # serve run by DownStream: restarted by it
    monkeypatch.setattr(backend, "endpoint", lambda: ("http://backend:8786", "test-api-secret"))
    responses.post("http://backend:8786/api/dashboard/drain", json={"jobs": {"downloading": 1}, "sessions": 0, "draining": True})
    responses.delete("http://backend:8786/api/dashboard/drain", json={"draining": False})
    with pytest.raises(UnshackleError, match="still downloading"):
        backend.restart("dash-key")
    assert responses.calls[-1].request.method == "DELETE"  # the drain called off: it takes new work again


def test_a_local_serve_that_failed_to_start_is_not_started_again_for_a_minute(tmp_path, monkeypatch):
    import unshacklarr.backend as backend

    starts, now = [], [1000.0]

    def failing_start(self, command):
        starts.append(command)
        raise UnshackleError("unshackle serve did not answer within 90 s: no output")

    monkeypatch.setattr(backend.Local, "start", failing_start)
    monkeypatch.setattr(backend.time, "monotonic", lambda: now[0])
    local = backend.Local(tmp_path / "serve.log")
    for _ in range(3):
        with pytest.raises(UnshackleError, match="did not answer within 90 s"):
            local.endpoint("unshackle")
    assert starts == ["unshackle"]  # the second and third caller were told, not made to wait for another start
    with pytest.raises(UnshackleError):
        local.endpoint("other-unshackle")
    assert starts == ["unshackle", "other-unshackle"]  # another command is another try
    now[0] += 61
    with pytest.raises(UnshackleError):
        local.endpoint("other-unshackle")
    assert starts == ["unshackle", "other-unshackle", "other-unshackle"]  # a minute later it is tried again

    other = Unshackle(tmp_path)  # a save of the settings clears the memory of a failed start
    other.local.failed = ("unshackle", now[0], UnshackleError("x"))
    other.configure({})
    assert other.local.failed is None


@responses.activate
@pytest.mark.parametrize("header, seconds", [("0", 1), ("7", 7), (None, 60), ("soon", 60)])
def test_a_busy_answer_always_asks_for_a_wait(tmp_path, header, seconds):
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://backend:8786", "unshackle_api_key": "test-key"})
    responses.get("http://backend:8786/api/download/jobs/j1", status=429, headers={"Retry-After": header} if header else {})
    with pytest.raises(UnshackleError) as caught:
        backend.call("GET", "/api/download/jobs/j1")
    assert caught.value.retry_after == seconds  # 0 would read as "no wait asked": a miss, then a cancelled download


@pytest.mark.parametrize("shebang", ["#!/usr/bin/env python3", "#!/usr/bin/env -S python3 -u"])
def test_a_launcher_that_asks_env_for_python_runs_that_python(tmp_path, shebang):
    import shutil
    import sys
    from unshacklarr.backend import unshackle_python
    here = tmp_path / "bin"
    here.mkdir()
    (here / "python3").symlink_to(sys.executable)
    command = here / "unshackle"
    command.write_text(f"{shebang}\n")
    command.chmod(0o755)
    path = os.environ["PATH"]
    os.environ["PATH"] = f"{here}{os.pathsep}{path}"
    try:
        python, _ = unshackle_python(str(command))
        assert python == shutil.which("python3")  # the interpreter env would find, not env itself
    finally:
        os.environ["PATH"] = path


def test_a_restart_makes_unshackle_say_again_where_its_folders_are(tmp_path, monkeypatch):
    import sys
    import types
    import unshacklarr.backend as backend

    folders = [f"/old/{n}" for n in ("config.yaml", "cookies", "wvds", "prds", "temp", "cache")]
    asked = []

    def run(argv, **kwargs):
        asked.append(list(folders))
        return types.SimpleNamespace(stdout="\n".join(folders), stderr="", returncode=0)

    monkeypatch.setattr(backend, "unshackle_python", lambda command: (sys.executable, tmp_path))
    monkeypatch.setattr(backend.subprocess, "run", run)
    monkeypatch.setattr(backend.Local, "start", lambda self, command: None)
    local = backend.Local(tmp_path / "serve.log")
    assert local.cookies_dir("unshackle") == Path("/old/cookies")
    local.paths("unshackle")
    assert len(asked) == 1  # asked once while it runs

    folders[:] = [f.replace("/old/", "/new/") for f in folders]  # directories: changed in unshackle.yaml
    local.restart("unshackle")
    assert local.cookies_dir("unshackle") == Path("/new/cookies")  # sign-ins are looked for where it keeps them now


def test_an_unshackle_with_no_config_file_still_says_where_its_folders_are(tmp_path, monkeypatch):
    # No unshackle.yaml yet: its first line is empty, and the five folders after it are still read
    import sys
    import types
    import unshacklarr.backend as backend

    out = "\n/c/cookies\n/c/wvds\n/c/prds\n/c/temp\n/c/cache\n"
    monkeypatch.setattr(backend, "unshackle_python", lambda command: (sys.executable, tmp_path))
    monkeypatch.setattr(backend.subprocess, "run", lambda argv, **kwargs: types.SimpleNamespace(stdout=out, stderr="", returncode=0))
    found = backend.Local(tmp_path / "serve.log").paths("unshackle")
    assert str(found["config"]) == "." and found["cookies"] == Path("/c/cookies") and found["cache"] == Path("/c/cache")


def test_a_restart_that_fails_is_not_started_again_by_the_callers_waiting_on_it(tmp_path, monkeypatch):
    import unshacklarr.backend as backend

    starts = []

    def failing_start(self, command):
        starts.append(command)
        raise UnshackleError("unshackle serve did not answer within 90 s: no output")

    monkeypatch.setattr(backend.Local, "start", failing_start)
    local = backend.Local(tmp_path / "serve.log")
    with pytest.raises(UnshackleError, match="did not answer within 90 s"):
        local.restart("unshackle")
    with pytest.raises(UnshackleError, match="did not answer within 90 s"):
        local.endpoint("unshackle")  # a caller that waited for the restart, or the next page load
    assert starts == ["unshackle"]


def test_a_failed_start_cleared_by_another_thread_mid_check_still_says_why(tmp_path):
    import unshacklarr.backend as backend
    local = backend.Local(tmp_path / "serve.log")

    class Clearing(tuple):  # a restart or a save clears the memory as soon as it is first read
        def __getitem__(self, index):
            local.failed = None
            return super().__getitem__(index)

    local.failed = Clearing(("unshackle", time.monotonic(), UnshackleError("did not start")))
    with pytest.raises(UnshackleError, match="did not start"):
        local.recent_failure("unshackle")


def test_the_new_names_keep_installs_from_before_the_rename_working(tmp_path, monkeypatch):
    from pathlib import Path
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text()
    assert 'downstream = "unshacklarr.web:main"' in pyproject
    assert 'unshacklarr = "unshacklarr.web:main"' in pyproject  # the old command still runs
    import unshacklarr.sync as sync
    monkeypatch.delenv("DOWNSTREAM_DATA", raising=False)
    monkeypatch.setenv("UNSHACKLARR_DATA", str(tmp_path / "old"))
    assert sync.env("DATA") == str(tmp_path / "old")  # an install that set the old name keeps its folder
    monkeypatch.setenv("DOWNSTREAM_DATA", str(tmp_path / "new"))
    assert sync.env("DATA") == str(tmp_path / "new")  # both set: the new name wins
    # outside Docker: the old folder, while there is no new one
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(sync.sys, "platform", "linux")
    monkeypatch.setattr(sync.os, "name", "posix")
    assert sync.default_data_dir() == tmp_path / "downstream"
    (tmp_path / "unshacklarr").mkdir()
    assert sync.default_data_dir() == tmp_path / "unshacklarr"
    (tmp_path / "downstream").mkdir()
    assert sync.default_data_dir() == tmp_path / "downstream"


def test_an_upgraded_container_keeps_the_data_folder_it_set_under_the_old_name(monkeypatch):
    import re
    import unshacklarr.sync as sync
    dockerfile = (Path(__file__).parents[1] / "Dockerfile").read_text()
    image_env = dict(re.findall(r"(\w+)=(\S+)", next(l for l in dockerfile.splitlines() if l.startswith("ENV ") and "DATA=" in l)))
    monkeypatch.delenv("DOWNSTREAM_DATA", raising=False)
    monkeypatch.delenv("UNSHACKLARR_DATA", raising=False)
    for name, value in image_env.items():
        monkeypatch.setenv(name, value)
    assert sync.env("DATA") == "/data"  # the image's own default
    monkeypatch.setenv("UNSHACKLARR_DATA", "/existing-config")  # set on the container before the rename
    assert sync.env("DATA") == "/existing-config"


def test_the_revealed_titles_move_to_the_new_browser_key_once():
    import shutil, subprocess
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    src = (Path(__file__).parents[1] / "unshacklarr" / "static" / "js" / "core.js").read_text()
    code = src[src.index("let revealed;"):src.index("const spoilerFree")]
    results = {}
    for storage in ("room", "full"):
        out = subprocess.run(["node", "-e", r"""
const vm = require("vm"), [code, full] = process.argv.slice(1), store = new Map([["unshacklarr.revealed", '["1-S01E01"]']]);
const localStorage = { getItem: (k) => store.has(k) ? store.get(k) : null, removeItem: (k) => store.delete(k),
  setItem: (k, v) => { if (full === "full") throw new Error("QuotaExceededError"); store.set(k, v); } };
const ctx = vm.createContext({ localStorage, JSON, Set });
vm.runInContext(code + "\nglobalThis.out = [...revealed];", ctx);
console.log(JSON.stringify({ revealed: ctx.out, keys: Object.fromEntries(store) }));
""", code, storage], capture_output=True, text=True)
        assert out.returncode == 0, out.stderr
        results[storage] = json.loads(out.stdout)
    assert results["room"] == {"revealed": ["1-S01E01"], "keys": {"downstream.revealed": '["1-S01E01"]'}}
    # storage full: still shown, and kept under the old key until it can move
    assert results["full"] == {"revealed": ["1-S01E01"], "keys": {"unshacklarr.revealed": '["1-S01E01"]'}}


_COOKIE_ROW = ".x.tv\tTRUE\t/\tFALSE\t0\tsid\tsynth-valid-1"
_JSON_COOKIE = {"domain": ".x.tv", "name": "sid", "value": "synth-valid-1"}


@pytest.mark.parametrize(("field", "replacement", "reason"), [
    (0, "", "invalid cookie domain"), (0, "x y", "invalid cookie domain"),
    (1, "true", "domain flag must be TRUE or FALSE"),
    (2, "path", "cookie path must start with '/'"), (2, "/a b", "cookie path must start with '/'"),
    (3, "no", "secure flag must be TRUE or FALSE"),
    *((4, expiry, "expiry date is not a valid timestamp") for expiry in ("?", "nan", "inf", "-1")),
    (5, " ", "missing cookie name"), (5, "", "missing cookie name"),
    (0, " #HttpOnly_.x.tv", "unexpected leading whitespace before #HttpOnly_"),
    (6, "two\tfields", "expected 7 tab-separated fields"),
    (None, "", "expected 7 tab-separated fields"),
])
def test_cookie_import_reports_source_line(field, replacement, reason):
    from unshacklarr import cookies
    fields = _COOKIE_ROW.split("\t")
    if field is not None:
        fields[field] = replacement
    bad = (" " if field is None else "\t").join(fields)
    text = "\r\n".join(("", "# Netscape HTTP Cookie File", "# comment", _COOKIE_ROW, bad))
    with pytest.raises(CookieError) as error:
        normalise(text)
    assert isinstance(error.value, cookies.CookieParseError)
    assert (error.value.line_number, error.value.reason) == (5, reason)
    assert str(error.value) == f"Line 5: {reason}"
    with pytest.raises(cookies.CookieParseError, match="Line 5"):
        parse(text, strict=True)
    assert parse(text) == parse(_COOKIE_ROW)


@pytest.mark.parametrize("text", ["{bad", "[1,", "{}", '{"cookies": "bad"}', '{"cookies": null}', '{"other": []}'])
def test_cookie_rejected_json_leaves_no_files(tmp_path, text):
    with pytest.raises(CookieError):
        save(tmp_path / "Cookies", "NF", "default", text)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("item", ["synth-never-echo-99", None, {"domain": ".x.tv"},
    {"domain": ".x.tv", "name": "sid"}, *({**_JSON_COOKIE, **change} for change in (
        {"value": 123}, {"httpOnly": "yes"}, {"expirationDate": True}, {"expirationDate": -50},
        {"value": "a\tb"}, {"expires": False, "expirationDate": 0}, {"expires": "inf"}, {"path": 123},
    ))], ids=["string", "null", "missing-name", "missing-value", "value-type", "flag-type",
              "expiry-bool", "expiry-negative", "tab", "second-expiry", "infinity", "path-type"])
def test_cookie_import_rejects_entire_malformed_json_array(item):
    with pytest.raises(CookieError, match=r"^Cookie #2:") as error:
        normalise(json.dumps([_JSON_COOKIE, item]))
    assert "synth-" not in str(error.value)


@pytest.mark.parametrize("name", ["cf_clearance", "__cf_bm", "ak_bmsc", "bm_sv", "_ga", "AWSALBTG", "utsdc"])
def test_cookie_import_requires_login_cookie(name):
    for expiry in ("0", "4102444800"):
        with pytest.raises(CookieError, match="No usable login cookies"):
            normalise(_COOKIE_ROW.replace("sid", name).replace("\t0\t", f"\t{expiry}\t"))


@pytest.mark.parametrize("text", [_COOKIE_ROW.rsplit("\t", 1)[0] + "\t", json.dumps([{**_JSON_COOKIE, "value": ""}])])
def test_cookie_import_empty_session_value(text):
    with pytest.raises(CookieError, match="No usable login cookies"):
        normalise(text)


@pytest.mark.parametrize("wrapped", [True, False])
def test_cookie_import_filters_expired_json(wrapped):
    rows = [{**_JSON_COOKIE, "expirationDate": 1000}, {**_JSON_COOKIE, "expires": -1, "session": True},
            {**_JSON_COOKIE, "expirationDate": None, "session": True}, {**_JSON_COOKIE, "expirationDate": 1001}]
    with pytest.raises(CookieError, match="expired"):
        normalise(json.dumps(rows[:1]), now=1000)
    result = normalise(json.dumps({"cookies": rows} if wrapped else rows), now=1000)
    assert result.startswith("# Netscape HTTP Cookie File\n")
    assert [r["expires"] for r in parse(result)] == [0, 0, 1001]


@pytest.mark.parametrize("expiration_date", [0, "0"], ids=["number", "string"])
def test_cookie_import_zero_expiration_date_uses_expires(tmp_path, expiration_date):
    save(tmp_path, "NF", "", _COOKIE_ROW)
    path = tmp_path / "NF.txt"
    original = path.read_bytes()
    cookie = {**_JSON_COOKIE, "expirationDate": expiration_date}
    text = json.dumps([{**cookie, "expires": 1}])
    with pytest.raises(CookieError, match="expired") as normalise_error:
        normalise(text, now=2)
    with pytest.raises(CookieError, match="expired") as save_error:
        save(tmp_path, "NF", "", text)
    for error in (normalise_error, save_error):
        assert _JSON_COOKIE["value"] not in str(error.value)
    assert path.read_bytes() == original
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    future = json.dumps([{**cookie, "expires": 4102444800}])
    assert parse(normalise(future, now=2))[0]["expires"] == 4102444800


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_cookie_import_rejects_nonstandard_json_constants(tmp_path, constant):
    save(tmp_path, "NF", "", _COOKIE_ROW)
    path = tmp_path / "NF.txt"
    original = path.read_bytes()
    text = json.dumps([{**_JSON_COOKIE, "extra": float(constant)}])
    with pytest.raises(CookieError, match="^Neither a Netscape cookie file nor a JSON export$"):
        save(tmp_path, "NF", "", text)
    assert path.read_bytes() == original
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize(("prefix", "suffix"), [
    ("[", r', "extra": "\uD800"}]'),
    ("[", r', "extra": "\uDC00"}]'),
    ("[", r', "\uD800": 1}]'),
    ("[", r', "extra": ["\uD800"]}]'),
    ("[", r', "extra": "\uD800", "extra": "ok"}]'),
    (r'{"meta": "\uD800", "cookies": [', "}]}"),
], ids=["high", "low", "key", "nested-list", "overwritten", "wrapper"])
def test_cookie_import_rejects_discarded_lone_surrogate(tmp_path, prefix, suffix):
    save(tmp_path, "NF", "", _COOKIE_ROW)
    path = tmp_path / "NF.txt"
    original = path.read_bytes()
    text = prefix + json.dumps(_JSON_COOKIE)[:-1] + suffix
    with pytest.raises(CookieError, match="^Neither a Netscape cookie file nor a JSON export$") as error:
        save(tmp_path, "NF", "", text)
    assert _JSON_COOKIE["value"] not in str(error.value)
    assert path.read_bytes() == original
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "text",
    [r'["\uD800"]', r'["\uDC00"]', r'"\uD800"', r'"\uDC00"'],
    ids=["array-high", "array-low", "string-high", "string-low"],
)
@pytest.mark.parametrize("operation", ["from_json", "normalise", "save"])
def test_cookie_import_rejects_lone_surrogate(tmp_path, text, operation):
    save(tmp_path, "NF", "", _COOKIE_ROW)
    path = tmp_path / "NF.txt"
    original = path.read_bytes()
    with pytest.raises(CookieError, match="^Neither a Netscape cookie file nor a JSON export$"):
        if operation == "from_json":
            from_json(text)
        elif operation == "normalise":
            normalise(text)
        else:
            save(tmp_path, "NF", "", text)
    assert path.read_bytes() == original
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_cookie_import_accepts_escaped_surrogate_pair(tmp_path):
    text = json.dumps([{**_JSON_COOKIE, "extra": "\U0001f600"}], ensure_ascii=True)
    save(tmp_path, "NF", "", text)
    assert (tmp_path / "NF.txt").read_text() == normalise(json.dumps([_JSON_COOKIE]))


def test_cookie_import_preserves_files_and_filters_expired_netscape(tmp_path):
    header = "# Netscape HTTP Cookie File"
    current = "#HttpOnly_" + _COOKIE_ROW.replace("\t0\t", "\t\t")
    old = _COOKIE_ROW.replace("\t0\t", "\t1000\t")
    text = "\ufeff\r\n" + "\r\n".join((header, "# comment", old, current))
    folder = tmp_path / "Cookies"
    with pytest.raises(CookieError, match="expired"):
        save(folder, "NF", "", old)
    assert not folder.exists()
    save(folder, "NF", "", text)
    path = folder / "NF.txt"
    content, mode = path.read_bytes(), path.stat().st_mode
    assert content.decode() == "\n".join((header, "# comment", current, ""))
    assert stat.S_IMODE(mode) == 0o600
    with pytest.raises(CookieError):
        save(folder, "NF", "", "invalid")
    assert path.read_bytes() == content and path.stat().st_mode == mode
    assert list(folder.iterdir()) == [path]
    folder.chmod(0o2770)
    inode = path.stat().st_ino
    save(folder, "NF", "", _COOKIE_ROW)
    assert path.stat().st_ino != inode and stat.S_IMODE(path.stat().st_mode) == 0o660


@pytest.mark.parametrize(("key", "expiry"), [("expires", 4102444800), ("expirationDate", 1),
                                             ("expires", 0.5)])
def test_cookie_session_conflicting_date(key, expiry):
    with pytest.raises(CookieError, match="session cookie cannot have an expiry date"):
        normalise(json.dumps([{**_JSON_COOKIE, "session": True, key: expiry}]))


@pytest.mark.parametrize("expiry", [None, -1, "-1", 0])
def test_cookie_session_sentinels(expiry):
    assert parse(normalise(json.dumps([{**_JSON_COOKIE, "session": True, "expirationDate": expiry}])))[0]["expires"] == 0


def test_cookie_playwright_session_sentinel(tmp_path):
    storage = json.dumps({"cookies": [{**_JSON_COOKIE, "path": "/", "expires": -1,
                                       "httpOnly": True, "secure": True, "sameSite": "Lax"}], "origins": []})
    expected = normalise(from_json(storage))
    cookie, = _load_cookie_jar(tmp_path, expected)
    assert parse(expected)[0]["expires"] == 0 and (cookie.name, cookie.value, cookie.expires) == ("sid", _JSON_COOKIE["value"], 0)
    save(tmp_path, "NF", "default", storage)
    path = tmp_path / "NF" / "default.txt"
    before = path.read_bytes()
    assert before == expected.encode() and stat.S_IMODE(path.stat().st_mode) == 0o600
    for variant in ({"expires": -1}, {"expires": -1.0}, {"expires": "-1"}, {"expirationDate": -1},
                    {"session": None, "expires": -1}):
        assert parse(normalise(json.dumps([{**_JSON_COOKIE, **variant}])))[0]["expires"] == 0
    bad_cases = [({"session": False, "expires": -1}, "expiry date must not be negative"),
                 ({"session": False, "expirationDate": -1}, "expiry date must not be negative"),
                 ({"session": False, "expires": "-1"}, "expiry date is not a valid timestamp"),
                 ({"expirationDate": 4102444800, "expires": -1}, "session cookie cannot have an expiry date"),
                 ({"expirationDate": -1, "expires": 4102444800}, "session cookie cannot have an expiry date"),
                 ({"expirationDate": 0.5, "expires": -1}, "session cookie cannot have an expiry date"),
                 ({"expires": -2}, "expiry date must not be negative")]
    for change, reason in bad_cases:
        with pytest.raises(CookieError, match=f"^Cookie #1: {reason}$") as error:
            save(tmp_path, "NF", "default", json.dumps([{**_JSON_COOKIE, **change}]))
        assert _JSON_COOKIE["value"] not in str(error.value)
    assert path.read_bytes() == before and stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("as_json", [False, True])
def test_cookie_fractional_epoch_is_dated(as_json):
    old = {**_JSON_COOKIE, "expires": 0.5, "name": "old"}
    row = _COOKIE_ROW.replace("\t0\tsid", "\t0.5\told")
    assert parse(row)[0]["expires"] == 1
    with pytest.raises(CookieError, match="expired"):
        normalise(json.dumps([old]) if as_json else row, now=2)
    mixed = json.dumps([old, _JSON_COOKIE]) if as_json else row + "\n" + _COOKIE_ROW
    assert parse(normalise(mixed, now=2)) == parse(_COOKIE_ROW)


@pytest.mark.parametrize(("domain", "flag"), [("example.org", "TRUE"), (".example.org", "FALSE")])
def test_cookie_domain_flag_mismatch(domain, flag):
    from unshacklarr.cookies import CookieParseError
    row = _COOKIE_ROW.replace(".x.tv\tTRUE", f"{domain}\t{flag}")
    assert parse(row)[0]["domain"] == "example.org"
    with pytest.raises(CookieParseError, match=r"^Line 3: domain flag must match leading dot$"):
        normalise("# comment\n\n" + row)
    assert parse(normalise(_COOKIE_ROW.replace(".x.tv\tTRUE", "example.org\tFALSE")))


@pytest.mark.parametrize("name", [" cf_clearance", "sid ", "a b", "sid=1", "sid;other"])
def test_cookie_invalid_name(tmp_path, name):
    from unshacklarr.cookies import CookieParseError
    with pytest.raises(CookieParseError, match="^Line 1: invalid cookie name$"):
        save(tmp_path, "NF", "default", _COOKIE_ROW.replace("sid", name))
    with pytest.raises(CookieError, match="^Cookie #1: missing or invalid domain or name$"):
        save(tmp_path, "NF", "default", json.dumps([{**_JSON_COOKIE, "name": name}]))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("surrogate", ["\ud800", "\udc00"], ids=["high", "low"])
@pytest.mark.parametrize("last_line", [_COOKIE_ROW, "# comment"], ids=["row", "comment"])
def test_cookie_surrogate_reports_physical_line(tmp_path, surrogate, last_line):
    from unshacklarr.cookies import CookieParseError

    folder = tmp_path / "Cookies"
    save(folder, "NF", "default", _COOKIE_ROW)
    path = folder / "NF" / "default.txt"
    before = path.read_bytes()
    text = "\n".join(("# Netscape HTTP Cookie File", _COOKIE_ROW, last_line + surrogate))
    for operation in (lambda: parse(text, strict=True), lambda: normalise(text),
                      lambda: save(folder, "NF", "default", text)):
        with pytest.raises(CookieParseError, match="^Line 3: invalid UTF-8 text$") as error:
            operation()
        assert error.value.line_number == 3
    assert path.read_bytes() == before
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("ensure_ascii", [True, False], ids=["escaped", "raw"])
def test_cookie_json_surrogate_preserves_file(tmp_path, ensure_ascii):
    folder = tmp_path / "Cookies"
    save(folder, "NF", "default", _COOKIE_ROW)
    path = folder / "NF" / "default.txt"
    before = path.read_bytes()
    text = json.dumps([{**_JSON_COOKIE, "value": "\ud800"}], ensure_ascii=ensure_ascii)
    for operation in (lambda: normalise(text), lambda: save(folder, "NF", "default", text)):
        with pytest.raises(CookieError, match="^Neither a Netscape cookie file nor a JSON export$"):
            operation()
    assert path.read_bytes() == before
    assert path.stat().st_mode & 0o777 == 0o600


def test_cookie_normalise_requires_text():
    with pytest.raises(CookieError, match="^Neither a Netscape cookie file nor a JSON export$"):
        normalise(cast(str, None))


def _load_cookie_jar(tmp_path: Path, text: str):
    jar_path = tmp_path / "jar.txt"
    jar_path.write_text(text, encoding="utf-8")
    jar = MozillaCookieJar(str(jar_path))
    jar.load(ignore_discard=True, ignore_expires=True)
    return list(jar)


@pytest.mark.parametrize("as_json", [False, True])
@pytest.mark.parametrize("scenario", ["empty-last", "valid-last", "expired-empty", "other-path"])
def test_cookie_duplicate_replacement(tmp_path, as_json, scenario):
    empty = {**_JSON_COOKIE, "value": "", "expires": 1 if scenario == "expired-empty" else 0,
             "path": "/other" if scenario == "other-path" else "/"}
    rows = [_JSON_COOKIE, empty]
    if scenario == "valid-last":
        rows.reverse()
    text = json.dumps(rows) if as_json else "\n".join(
        "\t".join((r["domain"], "TRUE", r.get("path", "/"), "FALSE", str(r.get("expires", 0)), r["name"], r["value"]))
        for r in rows)
    if scenario == "empty-last":
        with pytest.raises(CookieError, match="No usable login cookies"):
            normalise(text, now=2)
    else:
        cookies = _load_cookie_jar(tmp_path, normalise(text, now=2))
        assert [(c.path, c.value) for c in cookies if c.value] == [("/", _JSON_COOKIE["value"])]


@pytest.mark.parametrize("as_json", [False, True], ids=["netscape", "json"])
@pytest.mark.parametrize(("first", "last"), [("live", ""), ("", "live")])
def test_cookie_mixed_case_duplicate(tmp_path, as_json, first, last):
    rows = [(".EXAMPLE.ORG", first), (".example.org", last)]
    if as_json:
        text = json.dumps([{**_JSON_COOKIE, "domain": domain, "value": value} for domain, value in rows])
    else:
        text = "\n".join(f"{domain}\tTRUE\t/\tFALSE\t0\tsid\t{value}" for domain, value in rows)
    if last:
        cookie, = _load_cookie_jar(tmp_path, normalise(text))
        assert (cookie.domain, cookie.value) == (".example.org", last)
    else:
        with pytest.raises(CookieError, match="No usable login cookies"):
            normalise(text)


@pytest.mark.parametrize("as_json", [False, True], ids=["netscape", "json"])
@pytest.mark.parametrize(("blank", "duplicate"), [
    ("   ", False), ("\u00a0", False), ("&#32;", False), ('""', False), ('"   "', False),
    ("   ", True), ('""', True),
])
def test_cookie_blank_login_preserves_saved_profile(tmp_path, as_json, blank, duplicate):
    save(tmp_path, "NF", "default", _COOKIE_ROW)
    path = tmp_path / "NF" / "default.txt"
    before = path.read_bytes()
    rows = [(".X.TV", "synthetic-first")] if duplicate else []
    rows.append((".x.tv", blank))
    if as_json:
        text = json.dumps([{**_JSON_COOKIE, "domain": d, "value": v} for d, v in rows])
    else:
        text = "\n".join(f"{d}\tTRUE\t/\tFALSE\t0\tsid\t{v}" for d, v in rows)
    with pytest.raises(CookieError, match="No usable login cookies") as parsed:
        normalise(text)
    with pytest.raises(CookieError, match="No usable login cookies") as saved:
        save(tmp_path, "NF", "default", text)
    for error in (parsed, saved):
        assert all(value not in str(error.value) for _, value in rows)
        assert _JSON_COOKIE["value"] not in str(error.value)
    assert path.read_bytes() == before
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize(("prefix", "date", "expected"), [
    ("", "0.0", 0), ("", "4102444800.5", 4102444800), ("#HttpOnly_", "0.0", 0),
])
def test_cookie_fractional_expiry_round_trip(tmp_path, prefix, date, expected):
    row = prefix + _COOKIE_ROW
    result = normalise(row.replace("\t0\t", f"\t{date}\t"), now=2)
    assert result.splitlines()[1] == row.replace("\t0\t", f"\t{expected}\t")
    cookie, = _load_cookie_jar(tmp_path, result)
    assert (cookie.value, cookie.expires) == (_JSON_COOKIE["value"], expected)


@pytest.mark.parametrize("domain", [
    "$host", ".", "...", "example.org/", "example.org/path", "example.org:443", "https://example.org",
    "..example.org", "example..org", "example.org.", "-example.org", "example-.org", "localhost", ".localhost",
])
def test_cookie_rejects_unloadable_domain(domain):
    from unshacklarr.cookies import CookieParseError
    flag = "TRUE" if domain.startswith(".") else "FALSE"
    with pytest.raises(CookieParseError, match="Line 1: invalid cookie domain"):
        normalise(_COOKIE_ROW.replace(".x.tv\tTRUE", f"{domain}\t{flag}"))
    with pytest.raises(CookieError, match="Cookie #1: missing or invalid domain or name"):
        normalise(json.dumps([{**_JSON_COOKIE, "domain": domain}]))

@pytest.mark.parametrize("path", ["/path?a=1", "/path#frag", "/path;param"])
def test_cookie_rejects_invalid_path_before_write(tmp_path, path):
    from unshacklarr.cookies import CookieParseError
    with pytest.raises(CookieParseError, match="^Line 2: cookie path must start with '/'$"):
        save(tmp_path, "NF", "default", "\n" + _COOKIE_ROW.replace("\t/\t", f"\t{path}\t"))
    with pytest.raises(CookieError, match="^Cookie #1: invalid cookie path$"):
        save(tmp_path, "NF", "default", json.dumps([{**_JSON_COOKIE, "path": path}]))
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("field,invalid", [
    ("path", "/path\x80"), ("path", "/path\x9f"), ("name", "sid\x80"), ("name", "sid\x9f"),
])
@pytest.mark.parametrize("as_json", [False, True], ids=["netscape", "json"])
def test_cookie_c1_controls_preserve_saved_file(tmp_path, as_json, field, invalid):
    from unshacklarr.cookies import CookieParseError

    save(tmp_path, "NF", "default", _COOKIE_ROW)
    path = tmp_path / "NF" / "default.txt"
    before = path.read_bytes()
    if as_json:
        text = json.dumps([{**_JSON_COOKIE, field: invalid}])
        with pytest.raises(CookieError, match="^Cookie #1:") as error:
            save(tmp_path, "NF", "default", text)
        message = str(error.value)
        value = _JSON_COOKIE["value"]
    else:
        fields = _COOKIE_ROW.split("\t")
        fields[2 if field == "path" else 5] = invalid
        text = "# Netscape HTTP Cookie File\n\n" + "\t".join(fields)
        with pytest.raises(CookieParseError) as parse_error:
            save(tmp_path, "NF", "default", text)
        assert parse_error.value.line_number == 3
        message = str(parse_error.value)
        value = fields[6].rstrip("\n")
    assert value not in message
    assert path.read_bytes() == before
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("as_json", [False, True])
def test_cookie_invalid_domain_preserves_saved_file(tmp_path, as_json):
    save(tmp_path, "NF", "default", _COOKIE_ROW)
    path = tmp_path / "NF" / "default.txt"
    before = path.read_bytes()
    text = (json.dumps([{**_JSON_COOKIE, "domain": "example.org/"}]) if as_json
            else _COOKIE_ROW.replace(".x.tv\tTRUE", "example.org/\tFALSE"))
    with pytest.raises(CookieError) as error:
        save(tmp_path, "NF", "default", text)
    assert _JSON_COOKIE["value"] not in str(error.value)
    assert path.read_bytes() == before
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("domain", [".x.tv", "example.org", "127.0.0.1", ".xn--bcher-kva.example"])
@pytest.mark.parametrize("as_json", [False, True])
def test_cookie_valid_domain_reaches_request(tmp_path, domain, as_json):
    from urllib.request import Request
    flag = "TRUE" if domain.startswith(".") else "FALSE"
    expires = 4102444800
    text = (json.dumps([{**_JSON_COOKIE, "domain": domain, "expires": expires}]) if as_json
            else _COOKIE_ROW.replace(".x.tv\tTRUE", f"{domain}\t{flag}").replace("\t0\t", f"\t{expires}\t"))
    save(tmp_path, "NF", "default", text)
    jar = MozillaCookieJar(str(tmp_path / "NF" / "default.txt"))
    jar.load()
    request = Request(f"https://{domain.lstrip('.')}/")
    jar.add_cookie_header(request)
    assert request.get_header("Cookie") == f"sid={_JSON_COOKIE['value']}"


@pytest.mark.parametrize("field,invalid", [
    *(("value", "prefix" + separator + "suffix") for separator in (
        "\x85", "\u2028", "\u2029", "\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x00",
        "&#10;", "&#9;", "&#8232;", "&Tab;", "&NewLine;",
    )),
    *(("expires", date) for date in ("0\x0b", "4102444800\u2028", " 4102444800", "4102444800 ",
                                     "41_02444800", "+4102444800", "-4102444800")),
    *(("name", name) for name in ('a,b', 'a"b', 'a(b)', 'a/b', 'a:b', 'a?b', 'a@b',
                                  'a[b]', 'a\\b', 'a{b}', 'sid\u0100')),
    ("path", "/café"), ("path", '/a"b'),
    ("path", "/path&#63;query"), ("name", "sid&#61;extra"),
])
@pytest.mark.parametrize("as_json", [False, True], ids=["netscape", "json"])
def test_cookie_runtime_delimiters_preserve_saved_file(tmp_path, field, invalid, as_json):
    from unshacklarr.cookies import CookieParseError

    save(tmp_path, "NF", "default", _COOKIE_ROW)
    path = tmp_path / "NF" / "default.txt"
    before = path.read_bytes()
    fields = _COOKIE_ROW.rstrip("\n").split("\t")
    fields[{"path": 2, "expires": 4, "name": 5, "value": 6}[field]] = invalid
    text = (json.dumps([{**_JSON_COOKIE, field: invalid}]) if as_json
            else "# Netscape HTTP Cookie File\n" + "\t".join(fields))
    for operation in (from_json if as_json else lambda t: parse(t, strict=True),
                      normalise, lambda t: save(tmp_path, "NF", "default", t)):
        with pytest.raises(CookieError if as_json else CookieParseError,
                           match="^Cookie #1:" if as_json else "^Line 2:") as error:
            operation(text)
        if isinstance(error.value, CookieParseError):
            assert error.value.line_number == 2
        for fragment in ("prefix", "suffix", _JSON_COOKIE["value"]):
            assert fragment not in str(error.value)
    assert path.read_bytes() == before
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


_OVERSIZED_ENTITY = "&#" + "9" * (getattr(sys, "get_int_max_str_digits", lambda: 4300)() + 1) + ";"


@pytest.mark.parametrize("field", ["comment", "path", "name", "value"])
def test_cookie_netscape_decoder_error(tmp_path, field):
    from unshacklarr.cookies import CookieParseError

    save(tmp_path, "NF", "default", _COOKIE_ROW)
    path = tmp_path / "NF" / "default.txt"
    before = path.read_bytes()
    invalid = "synthetic-private" + _OVERSIZED_ENTITY
    fields = _COOKIE_ROW.split("\t")
    if field == "comment":
        line = "# " + invalid
    else:
        fields[{"path": 2, "name": 5, "value": 6}[field]] = ("/" if field == "path" else "") + invalid
        line = "\t".join(fields)
    text = _COOKIE_ROW + "\n" + line
    for operation in (lambda: parse(text, strict=True), lambda: normalise(text),
                      lambda: save(tmp_path, "NF", "default", text)):
        with pytest.raises(CookieParseError, match="^Line 2:") as error:
            operation()
        assert "synthetic-private" not in str(error.value)
    assert parse(text) == parse(_COOKIE_ROW)
    assert path.read_bytes() == before and stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("field", ["path", "name", "value"])
def test_cookie_json_decoder_error(tmp_path, field):
    save(tmp_path, "NF", "default", _COOKIE_ROW)
    path = tmp_path / "NF" / "default.txt"
    before = path.read_bytes()
    invalid = ("/" if field == "path" else "") + "synthetic-private" + _OVERSIZED_ENTITY
    text = json.dumps([_JSON_COOKIE, {**_JSON_COOKIE, field: invalid}])
    for operation in (from_json, normalise, lambda t: save(tmp_path, "NF", "default", t)):
        with pytest.raises(CookieError, match="^Cookie #2:") as error:
            operation(text)
        assert "synthetic-private" not in str(error.value)
    assert path.read_bytes() == before and stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("line", ["\t" * 6, "\t", "\x0b", "\x85", "\u2028", "\x85# comment"])
def test_cookie_strict_import_rejects_malformed_whitespace(tmp_path, line):
    from unshacklarr.cookies import CookieParseError

    save(tmp_path, "NF", "default", _COOKIE_ROW)
    path = tmp_path / "NF" / "default.txt"
    before = path.read_bytes()
    marker = "synthetic-whitespace-regression"
    valid = _COOKIE_ROW.rsplit("\t", 1)[0] + "\t" + marker
    text = valid + "\n" + line
    assert parse(text) == parse(valid)
    for operation in (lambda: parse(text, strict=True), lambda: normalise(text),
                      lambda: save(tmp_path, "NF", "default", text)):
        with pytest.raises(CookieParseError, match="^Line 2:") as error:
            operation()
        assert error.value.line_number == 2
        assert marker not in str(error.value)
    assert path.read_bytes() == before
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("line", ["   ", "  # comment", "\t# comment"])
def test_cookie_import_accepts_spaces_and_indented_comments(line):
    text = _COOKIE_ROW + "\n" + line
    assert parse(text, strict=True) == parse(_COOKIE_ROW)
    expected = normalise(_COOKIE_ROW) + (line + "\n" if "#" in line else "")
    assert normalise(text) == expected


def test_cookie_import_rejects_tab_before_httponly():
    from unshacklarr.cookies import CookieParseError

    with pytest.raises(CookieParseError, match="^Line 2: unexpected leading whitespace before #HttpOnly_"):
        normalise(_COOKIE_ROW + "\n\t#HttpOnly_" + _COOKIE_ROW)


@pytest.mark.parametrize("comment", ["# text\x85more", "# text\u2028more", "# text&#10;more", "#&#72;ttpOnly_"])
def test_cookie_runtime_comment_reports_physical_line(comment):
    from unshacklarr.cookies import CookieParseError

    with pytest.raises(CookieParseError, match="^Line 3: invalid comment line$") as error:
        parse("# Netscape HTTP Cookie File\n\n" + comment, strict=True)
    assert error.value.line_number == 3


@pytest.mark.parametrize("value,decoded", [("a=1&b=2", "a=1&b=2"), ("a&amp;b", "a&b"), ("a&#133;b", "a…b")])
@pytest.mark.parametrize("as_json", [False, True], ids=["netscape", "json"])
def test_cookie_benign_values_survive_runtime_decoding(tmp_path, value, decoded, as_json):
    import html

    fields = _COOKIE_ROW.rstrip("\n").split("\t")
    fields[-1] = value
    comment = "# col1\tcol2"
    text = (json.dumps([{**_JSON_COOKIE, "value": value}]) if as_json
            else comment + "\n" + "\t".join(fields))
    save(tmp_path, "NF", "default", text)
    rows = html.unescape((tmp_path / "NF" / "default.txt").read_text()).splitlines(keepends=False)
    assert rows[:-1] == (["# Netscape HTTP Cookie File"] if as_json else ["# Netscape HTTP Cookie File", comment])
    assert len(rows[-1].split("\t")) == 7
    assert rows[-1].split("\t")[-1] == decoded


@pytest.mark.parametrize("as_json", [False, True], ids=["netscape", "json"])
@pytest.mark.parametrize("rows,reason", [
    ([("/", "cf&#95;clearance", "present")], "No usable login cookies"),
    ([("/", "__cf&#95;bm", "present")], "No usable login cookies"),
    ([("/", "sid", "synth-valid-1"), ("/", "s&#105;d", "")], "No usable login cookies"),
    ([("/", "sid", "present"), ("/", "sid", "&#1;")], "No usable login cookies"),
    ([("/", "sid", "present"), ("/", "sid", "&#xfffe;")], "No usable login cookies"),
    ([("/&#1;", "sid", "present"), ("/", "sid", "")], "No usable login cookies"),
    ([("/", "sid", "&#1;")], "No usable login cookies"),
    ([("/", "sid", "&#xfffe;")], "No usable login cookies"),
    ([("/", "&#1;", "present")], "missing"),
], ids=["clearance", "bot-management", "duplicate-name", "duplicate-control", "duplicate-noncharacter",
        "duplicate-path", "empty-control", "empty-noncharacter", "empty-name"])
def test_cookie_save_validates_decoded_login(tmp_path, as_json, rows, reason):
    save(tmp_path, "NF", "default", _COOKIE_ROW)
    path = tmp_path / "NF" / "default.txt"
    before = path.read_bytes()
    if as_json:
        text = json.dumps([{**_JSON_COOKIE, "path": p, "name": n, "value": v} for p, n, v in rows])
    else:
        text = "\n".join("\t".join(("example.com", "FALSE", p, "FALSE", "0", n, v)) for p, n, v in rows)
    if reason == "missing":
        reason = "missing or invalid domain or name" if as_json else "missing cookie name"
    with pytest.raises(CookieError, match=reason) as error:
        save(tmp_path, "NF", "default", text)
    assert all(value not in str(error.value) for _, _, value in rows if value)
    assert _JSON_COOKIE["value"] not in str(error.value)
    assert path.read_bytes() == before
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("tab", ["&#9;", "&Tab;"])
def test_cookie_save_rejects_encoded_comment_tab(tmp_path, tab):
    from unshacklarr.cookies import CookieParseError

    save(tmp_path, "NF", "default", _COOKIE_ROW)
    path = tmp_path / "NF" / "default.txt"
    before = path.read_bytes()
    with pytest.raises(CookieParseError, match="invalid comment line") as error:
        save(tmp_path, "NF", "default", f"# Netscape HTTP Cookie File\n# col1{tab}col2\n" + _COOKIE_ROW)
    assert error.value.line_number == 2
    assert _COOKIE_ROW.rstrip("\n").split("\t")[-1] not in str(error.value)
    assert path.read_bytes() == before
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("as_json", [False, True], ids=["netscape", "json"])
@pytest.mark.parametrize("name,path,date", [
    (".AspNetCore.Cookies", "/%C3%A9", "0"),
    ("__Host-sid", "/api/v1", "0.0"),
    ("sid!#$%&'*+-.^_`|~", "/", "4102444800"),
    ("s&#105;d", "/a&amp;b", "4102444800.5"),
])
def test_cookie_save_accepts_valid_fields(tmp_path, as_json, name, path, date):
    fields = _COOKIE_ROW.rstrip("\n").split("\t")
    fields[2], fields[4], fields[5] = path, date, name
    text = json.dumps([{**_JSON_COOKIE, "name": name, "path": path, "expires": date}]) if as_json else "\t".join(fields)
    save(tmp_path, "NF", "default", text)
    saved = (tmp_path / "NF" / "default.txt").read_text().splitlines()[-1].split("\t")
    assert (saved[2], saved[4], saved[5]) == (path, str(int(float(date))), name)


def _expiry_export(form: str, date: str, *, session: bool = False) -> str:
    if form == "netscape":
        return "# Netscape HTTP Cookie File\n" + _COOKIE_ROW.replace("\t0\t", f"\t{date}\t")
    cookie = {**_JSON_COOKIE, "session": session, "expires": "EXPIRY"}
    return json.dumps([cookie]).replace('"EXPIRY"', json.dumps(date) if form == "string" else date)


@pytest.mark.parametrize("form", ["netscape", "string", "number"])
@pytest.mark.parametrize("date", ["1e-999", "0." + "0" * 400 + "1"], ids=["exponent", "fraction"])
def test_cookie_tiny_expiry_preserves_previous_import(tmp_path, form, date):
    text = _expiry_export(form, date)
    assert parse(normalise(text, now=0))[0]["expires"] == 1
    save(tmp_path, "NF", "", _COOKIE_ROW)
    path = tmp_path / "NF.txt"
    previous = path.read_bytes()
    with pytest.raises(CookieError, match="expired") as normalise_error:
        normalise(text, now=2)
    with pytest.raises(CookieError, match="expired") as save_error:
        save(tmp_path, "NF", "", text)
    for error in (normalise_error, save_error):
        assert _JSON_COOKIE["value"] not in str(error.value)
    assert path.read_bytes() == previous
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("form", ["netscape", "string", "number"])
@pytest.mark.parametrize("date", ["-1e-999", "1e500", "1e9999999", "-1e500"])
def test_cookie_invalid_extreme_expiry(form, date):
    from unshacklarr.cookies import CookieParseError

    reason = "expiry date must not be negative" if (form, date) == ("number", "-1e-999") else "expiry date is not a valid timestamp"
    location = "Line 2" if form == "netscape" else "Cookie #1"
    with pytest.raises(CookieParseError if form == "netscape" else CookieError, match=f"^{location}: {reason}$") as error:
        normalise(_expiry_export(form, date), now=2)
    assert _JSON_COOKIE["value"] not in str(error.value)


def test_cookie_tiny_session_expiry_conflict():
    with pytest.raises(CookieError, match="Cookie #1: session cookie cannot have an expiry date") as error:
        normalise(_expiry_export("number", "1e-999", session=True))
    assert _JSON_COOKIE["value"] not in str(error.value)
    assert parse(normalise(_expiry_export("number", "0.0", session=True)))[0]["expires"] == 0


def test_cookie_fractional_json_expiry_with_unicode_escape(tmp_path):
    text = json.dumps([{**_JSON_COOKIE, "expires": 4000000000.5, "value": "café"}])
    assert r"\u00e9" in text
    result = normalise(text)
    assert "\t4000000000\tsid\tcafé\n" in result
    save(tmp_path, "NF", "", text)
    assert (tmp_path / "NF.txt").read_text() == result
