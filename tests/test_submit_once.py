"""Tests for submit_once with the Spectra Analyze API mocked out (no network)."""

from unittest.mock import MagicMock, patch

import pytest

import submit_once as so


def response(payload):
    r = MagicMock()
    r.json.return_value = payload
    return r


def status(value):
    return response({"hash_type": "sha1", "results": [{"hash_value": "x", "status": value}]})


def details(sandbox_status):
    return response({"results": [{so.SANDBOX_FIELD: {"results": [], "status": sandbox_status}}]})


@pytest.fixture
def sample(tmp_path, monkeypatch):
    monkeypatch.setenv("ANALYZE_URL", "https://analyze.example.com/")
    monkeypatch.setenv("ANALYZE_TOKEN", "test-token")
    so.in_flight.clear()
    path = tmp_path / "setup.exe"
    path.write_bytes(b"sample")
    return str(path)


def urls(post):
    return [c.args[0].removeprefix("https://analyze.example.com") for c in post.call_args_list]


def test_new_file_is_submitted(sample):
    with patch.object(so.requests, "post", side_effect=[status("not_found"), response({})]) as p:
        assert so.submit_once(sample)[1] == "submitted"
    assert urls(p) == ["/api/samples/status/", "/api/submit/file/"]


def test_duplicate_in_flight_is_skipped_without_api_calls(sample):
    with patch.object(so.requests, "post", side_effect=[status("not_found"), response({})]):
        so.submit_once(sample)
    with patch.object(so.requests, "post") as p:
        assert so.submit_once(sample)[1] == "skipped: already submitted by this wrapper"
    p.assert_not_called()


@pytest.mark.parametrize("value", ["Queued", "Processing", "Reanalyzing", "Reported"])
def test_existing_sandbox_status_is_skipped(sample, value):
    with patch.object(so.requests, "post", side_effect=[status("processed"), details(value)]) as p:
        assert so.submit_once(sample)[1] == "skipped: sandbox status is " + value
    assert urls(p) == ["/api/samples/status/", "/api/samples/v2/list/details/"]
    assert p.call_args.kwargs["json"]["skip_reanalysis"] == "true"


def test_existing_sample_never_sandboxed_is_submitted(sample):
    side_effect = [status("processed"), details(None), response({})]
    with patch.object(so.requests, "post", side_effect=side_effect) as p:
        assert so.submit_once(sample)[1] == "submitted"
    assert urls(p)[-1] == "/api/submit/file/"
