from datetime import datetime, timezone
from unittest import mock

import pytest
import requests

from unshacklarr import offsite


def test_a_backup_is_encrypted_and_opens_with_its_passphrase_only():
    sealed = offsite.encrypt("series: {}\n", "correct horse")
    assert offsite.is_encrypted(sealed) and "series" not in sealed
    assert offsite.decrypt(sealed, "correct horse") == "series: {}\n"
    with pytest.raises(ValueError):
        offsite.decrypt(sealed, "wrong")


def test_s3_is_signed_as_aws_signs_it():
    # the signature checked against botocore's own S3SigV4Auth for the same request and time
    seen = {}
    ok = mock.Mock(status_code=200, raise_for_status=lambda: None)
    with mock.patch.object(requests, "put", lambda url, data, timeout, headers: seen.update(url=url, headers=headers) or ok):
        offsite.s3_put("https://s3.eu-west-3.amazonaws.com", "my-bucket/unshacklarr", "eu-west-3", "AKIDEXAMPLE",
                       "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY", "unshacklarr-2026-10-08-1200 a.yaml.enc", b"hello",
                       datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc))
    assert seen["url"] == "https://s3.eu-west-3.amazonaws.com/my-bucket/unshacklarr/unshacklarr-2026-10-08-1200%20a.yaml.enc"
    assert seen["headers"]["Authorization"].endswith("Signature=f7e72728e18db900ab7a32433b4e18c36cf68b714f8ad8c3192b55ce466ffa4d")


def _put_s3(endpoint):
    seen = {}
    ok = mock.Mock(status_code=200, raise_for_status=lambda: None)
    with mock.patch.object(requests, "put", lambda url, data, timeout, headers: seen.update(url=url, headers=headers) or ok):
        offsite.s3_put(endpoint, "bucket", "us-east-1", "AKID", "secret", "a b.enc", b"hello",
                       datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc))
    return seen


def _signature(canonical_path, host):
    # the signature a service computes from the request it received
    stamp, day, payload = "20261008T120000Z", "20261008", offsite.hashlib.sha256(b"hello").hexdigest()
    canonical = f"PUT\n{canonical_path}\n\nhost:{host}\nx-amz-content-sha256:{payload}\nx-amz-date:{stamp}\n\nhost;x-amz-content-sha256;x-amz-date\n{payload}"
    scope = f"{day}/us-east-1/s3/aws4_request"
    to_sign = f"AWS4-HMAC-SHA256\n{stamp}\n{scope}\n{offsite.hashlib.sha256(canonical.encode()).hexdigest()}"
    key = b"AWS4secret"
    for part in (day, "us-east-1", "s3", "aws4_request"):
        key = offsite._sign(key, part)
    return offsite.hmac.new(key, to_sign.encode(), offsite.hashlib.sha256).hexdigest()


def test_s3_signs_the_endpoints_own_path():
    seen = _put_s3("https://nas.example/s3/")
    assert seen["url"] == "https://nas.example/s3/bucket/a%20b.enc"
    assert seen["headers"]["Authorization"].endswith("Signature=" + _signature("/s3/bucket/a%20b.enc", "nas.example"))


def test_s3_signs_the_path_as_requests_sends_it():
    seen = _put_s3("https://nas.example/storage%7Ebackup")  # requests sends %7E as ~
    sent = requests.Request("PUT", seen["url"]).prepare().url
    assert sent == seen["url"]
    assert seen["headers"]["Authorization"].endswith("Signature=" + _signature(offsite.urlsplit(sent).path, "nas.example"))


def test_s3_signs_the_host_the_client_sends():
    # requests sends no :443 for https, and a lower-case name
    seen = _put_s3("https://NAS.example:443")
    assert seen["headers"]["Authorization"].endswith("Signature=" + _signature("/bucket/a%20b.enc", "nas.example"))
    seen = _put_s3("https://nas.example:9000")
    assert seen["headers"]["Authorization"].endswith("Signature=" + _signature("/bucket/a%20b.enc", "nas.example:9000"))


def test_nothing_leaves_without_a_passphrase():
    with pytest.raises(ValueError):
        offsite.send({"backup_remote": "webdav", "backup_remote_url": "https://dav.example"}, "b.yaml", "series: {}")


@pytest.mark.parametrize("bucket", ["bucket/folder/../archive", "bucket/./archive"])
def test_s3_refuses_a_folder_a_url_would_rewrite(bucket):
    # a URL drops "." and "..", so the backup would land under another key than the one in Settings
    put = mock.Mock()
    with mock.patch.object(requests, "put", put), pytest.raises(ValueError, match="cannot hold"):
        offsite.s3_put("https://nas.example", bucket, "", "AKID", "secret", "a.enc", b"hello")
    put.assert_not_called()


def _webdav(status, location=""):
    # requests follows a redirect unless told not to: behind forward-auth the login page then answers 200
    def put(url, data, auth, timeout, allow_redirects=True):
        if status in (301, 302, 303, 307, 308) and allow_redirects:
            return mock.Mock(status_code=200, url=location, raise_for_status=lambda: None)
        return mock.Mock(status_code=status, url=url, headers={"Location": location} if location else {},
                         raise_for_status=lambda: None)
    return mock.patch.object(requests, "put", put)


@pytest.mark.parametrize("status", [200, 201, 204])
def test_webdav_takes_a_stored_file_as_sent(status):
    with _webdav(status):
        offsite.webdav_put("https://dav.example/backups", "u", "p", "b.enc", b"x")


@pytest.mark.parametrize("location", ["https://auth.example/login?rd=x", "/login"])
def test_a_webdav_redirect_is_a_failed_backup(location):
    with _webdav(302, location), pytest.raises(requests.HTTPError, match="redirected") as e:
        offsite.webdav_put("https://user:secret@dav.example/backups", "u", "p", "b.enc", b"x")
    assert ("auth.example" if location.startswith("https") else "dav.example") in str(e.value)
    assert "secret" not in str(e.value)


def test_a_webdav_answer_that_stored_nothing_is_a_failed_backup():
    with _webdav(207), pytest.raises(requests.HTTPError, match="207"):
        offsite.webdav_put("https://dav.example/backups", "u", "p", "b.enc", b"x")
