import asyncio

import pytest
import requests
from aiohttp import web

from unshacklarr.files import no_credentials


@pytest.mark.parametrize("text", [
    'https://user:private-value@example.com/path',
    'https://example.com/path?access_token=private-value&season=2',
    'Authorization: Bearer private-value',
    '{"api_key": "private-value"}',
    'password=private-value',
    'Cookie: session=private-value; other=private-value',
])
def test_error_details_mask_credentials(text):
    assert "private-value" not in no_credentials(text)


def test_error_details_keep_the_provider_reason_and_reference():
    text = "HAYU: Invalid Token (ref ef1b9f), HTTP 401"
    assert no_credentials(text) == text


def test_failed_job_summary_keeps_the_reason_instead_of_a_python_traceback():
    from unshacklarr.sync import job_cause
    message = job_cause({"error_message": 'Traceback (most recent call last):\n  File "provider.py", line 10, in login\nValueError: HAYU Invalid Token (ref ef1b9f)'})
    assert "HAYU Invalid Token (ref ef1b9f)" in message
    assert "Traceback" not in message and "ValueError" not in message


def test_http_status_is_not_reported_as_an_unreachable_sonarr():
    from unshacklarr.files import error_message
    response = requests.Response()
    response.status_code = 403
    assert error_message(requests.HTTPError(response=response), "Sonarr") == "Sonarr returned HTTP 403."


def test_unexpected_errors_do_not_expose_python_internals():
    from unshacklarr.web import error_responses

    async def handler(request):
        raise KeyError("private-value")

    response = asyncio.run(error_responses(None, handler))
    assert response.status == 500
    assert "private-value" not in response.text
    assert "Unshacklarr" in response.text and "log" in response.text


def test_unexpected_error_log_keeps_a_sanitized_traceback(caplog):
    from unshacklarr.web import error_responses

    async def handler(request):
        raise ValueError("token=private-value")

    asyncio.run(error_responses(None, handler))
    assert "Traceback" in caplog.text and "in handler" in caplog.text
    assert "private-value" not in caplog.text


def test_expected_http_error_keeps_detail_but_masks_credentials():
    from unshacklarr.web import error_responses

    async def handler(request):
        raise web.HTTPBadGateway(text="HAYU: Invalid Token (ref ef1b9f), access_token=private-value")

    with pytest.raises(web.HTTPBadGateway) as caught:
        asyncio.run(error_responses(None, handler))
    assert "private-value" not in caught.value.text
    assert "Invalid Token (ref ef1b9f)" in caught.value.text


def test_nested_health_errors_are_masked_without_changing_settings():
    from unshacklarr.web import redact_error_fields
    data = {"error": "token=private-value", "pages": [{"why": "password=private-value"}], "settings": {"token": "keep"}}
    cleaned = redact_error_fields(data)
    assert "private-value" not in str(cleaned)
    assert cleaned["settings"] == data["settings"]


def test_http_details_are_kept_and_masked():
    from unshacklarr.files import error_message
    response = requests.Response()
    response.status_code = 422
    response._content = b'{"message": "Invalid selection, token=private-value"}'
    message = error_message(requests.HTTPError(response=response), "Sonarr")
    assert "HTTP 422" in message and "Invalid selection" in message
    assert "private-value" not in message


@pytest.mark.parametrize("status", [403, 500])
def test_provider_authentication_failure_keeps_its_owner_for_other_http_statuses(tmp_path, status):
    import responses
    from unshacklarr.backend import Unshackle, UnshackleError
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://backend:8786", "unshackle_api_key": "unit-test"})
    with responses.RequestsMock() as server:
        server.post("http://backend:8786/api/list-tracks", status=status,
                    json={"error_code": "AUTH_FAILED", "message": "Invalid Token", "ref": "auth-reference", "details": {"service": "HAYU"}})
        with pytest.raises(UnshackleError) as caught:
            backend.call("POST", "/api/list-tracks")
    message = str(caught.value)
    assert f"HTTP {status}" in message and "HAYU" in message
    assert "Invalid Token" in message and "auth-reference" in message
    assert "internal API key" not in message


def test_browser_errors_name_unshacklarr_and_hide_html():
    import json
    import shutil
    import subprocess
    from pathlib import Path
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    source = (Path(__file__).parents[1] / "unshacklarr/static/js/core.js").read_text()
    api = source[source.index("async function api("):source.index("/* Asking a service")]
    script = api + """
    (async () => {
      const results = [];
      for (const response of [
        { ok: false, status: 502, headers: new Headers({'Content-Type': 'text/html'}), text: async () => '<html>proxy error</html>' },
        { ok: true, json: async () => { throw new SyntaxError('private-value'); } },
      ]) {
        global.fetch = async () => response;
        try { await api('/api/test'); } catch (error) { results.push(error.message); }
      }
      console.log(JSON.stringify(results));
    })();
    """
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True)
    messages = json.loads(result.stdout)
    assert all("Unshacklarr" in message for message in messages)
    assert "HTTP 502" in messages[0] and "<html>" not in messages[0]
    assert "private-value" not in messages[1]


def test_translation_extraction_handles_long_error_messages():
    import subprocess
    import sys
    from pathlib import Path
    extractor = Path(__file__).parents[1] / "tools/i18n/extract.py"
    subprocess.run([sys.executable, "-c", "import runpy, sys; wanted = runpy.run_path(sys.argv[1])['wanted']; assert wanted('unshackle serve ' + 'a' * 100 + '. Check its log.')", str(extractor)],
                   check=True, capture_output=True, timeout=2)
