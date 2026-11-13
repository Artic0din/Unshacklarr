"""Each support module on its own: cookie files, atomic writes, CDM devices and unshackle.yaml."""

import json
import os
import stat
import threading
from pathlib import Path

import pytest
import responses
import yaml

from unshacklarr.backend import Unshackle, UnshackleError
from unshacklarr.cdm import CdmError, NO_CDM, add, choose, delete, folders, read, remote_delete, remote_save, state
from unshacklarr.cookies import CookieError, list_all, normalise, parse, save
from unshacklarr.files import PRIVATE, no_credentials, shared_or_private, write_atomic


def test_container_sources_are_immutable_and_identifiable():
    root = Path(__file__).parents[1]
    core_commit = "f147c23b667c8a61c3aeb579ca1c22b00560641e"
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
        assert "login/session" in message and "refused the API key" not in message
    else:
        assert caught.value.error_code == ""
        assert "internal API key" in message and "Settings, Unshackle" in message


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
    js = json.dumps([{"domain": ".crave.ca", "name": "a", "value": "1", "expirationDate": 1, "httpOnly": True, "secure": True}])
    assert parse(normalise(js))[0] == {"domain": "crave.ca", "name": "a", "expires": 1}
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
    assert save(folder, "OLD", "default", old)["expired"]  # a dated login, past, no session: expired
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


def test_a_local_serve_gets_its_socket_and_key_without_the_command_line(tmp_path):
    import sys
    from unshacklarr.backend import Local
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
        "    app.router.add_get('/api/health', lambda r: web.json_response(seen))\n"
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
        seen = requests.get(f"{local.url}/api/health", timeout=5).json()
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
    assert backend.download({"service": "AMZN", "remote": True}) == "queued"

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
        assert "Settings, Unshackle" in str(e) and backend.proxy_refused
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
