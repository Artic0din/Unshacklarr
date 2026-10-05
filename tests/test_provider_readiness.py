import pytest
import responses

from unshacklarr.backend import Unshackle, UnshackleError


@responses.activate
def test_healthy_api_rejects_broken_provider_and_allows_others_and_recovery(tmp_path):
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://backend:8786", "unshackle_api_key": "test-api-secret"})
    responses.get("http://backend:8786/api/health", json={"status": "ok"})
    error = "AMZN: failed to import - ModuleNotFoundError: No module named 'tldextract'"
    responses.get("http://backend:8786/api/services", json={"services": [{"tag": "BINGE"}], "load_errors": [error]})
    responses.post("http://backend:8786/api/download", json={"job_id": "queued"})

    assert backend.health()["status"] == "ok"
    with pytest.raises(UnshackleError, match="AMZN.*tldextract"):
        backend.download({"service": "AMZN"})
    assert not any(call.request.method == "POST" for call in responses.calls)
    assert backend.download({"service": "BINGE"}) == "queued"
    assert backend.download({"service": "AMZN", "remote": True}) == "queued"

    responses.replace(responses.GET, "http://backend:8786/api/services",
                      json={"services": [{"tag": "AMZN"}], "load_errors": []})
    assert backend.download({"service": "AMZN"}) == "queued"


@responses.activate
def test_import_error_secrets_are_not_forwarded(tmp_path):
    backend = Unshackle(tmp_path)
    backend.configure({"unshackle_url": "http://backend:8786", "unshackle_api_key": "test-api-secret"})
    responses.get("http://backend:8786/api/services", json={"services": [],
                  "load_errors": ["AMZN: failed to import - RuntimeError: password=private-value"]})
    with pytest.raises(UnshackleError) as caught:
        backend.download({"service": "AMZN"})
    assert "private-value" not in str(caught.value)
    assert "startup log" in str(caught.value)
