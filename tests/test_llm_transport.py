import io
import urllib.error
from unittest.mock import patch

import build.generate_monthly as generator
import pytest


def _http_error(code: int, body: bytes = b"provider detail") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://provider.example/v1/chat/completions",
        code,
        "error",
        {},
        io.BytesIO(body),
    )


def test_chat_completions_url_accepts_root_and_full_endpoint():
    assert generator._chat_completions_url("https://provider.example/v1/") == (
        "https://provider.example/v1/chat/completions"
    )
    full = "https://provider.example/v1/chat/completions"
    assert generator._chat_completions_url(full) == full


def test_http_410_has_actionable_configuration_error(monkeypatch):
    monkeypatch.setattr(generator, "API_KEY", "test-key")
    monkeypatch.setattr(generator, "BASE_URL", "https://retired.example/v1")
    with (
        patch("urllib.request.urlopen", side_effect=_http_error(410)),
        pytest.raises(RuntimeError, match="endpoint is retired.*LLM_BASE_URL/LLM_MODEL"),
    ):
        generator.call_llm("system", "user")


def test_transient_http_error_is_retried(monkeypatch):
    monkeypatch.setattr(generator, "API_KEY", "test-key")
    monkeypatch.setattr(generator, "LLM_MAX_ATTEMPTS", 2)
    with patch("urllib.request.urlopen") as mocked, patch("time.sleep"):
        mocked.side_effect = [_http_error(503), _http_error(503)]
        with pytest.raises(RuntimeError, match="after 2 attempt"):
            generator.call_llm("system", "user")
        assert mocked.call_count == 2
