import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, database_url="sqlite://", **overrides)  # type: ignore[arg-type]


def test_parses_allowed_origins() -> None:
    settings = _settings(allowed_origins=" http://a.test , https://b.test ,")
    assert settings.allowed_origins_list == ["http://a.test", "https://b.test"]


def test_production_requires_api_key() -> None:
    with pytest.raises(ValidationError, match="API_KEY must be set"):
        _settings(environment="production", api_key="")


def test_production_rejects_wildcard_cors() -> None:
    with pytest.raises(ValidationError, match="Wildcard CORS"):
        _settings(environment="production", api_key="secret", allowed_origins="*")


def test_accepts_legacy_groq_variable_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_legacy")
    monkeypatch.setenv("OPENAI_API_BASE", "https://example.test/v1")
    settings = _settings()
    assert settings.llm_api_key.get_secret_value() == "gsk_legacy"
    assert settings.llm_base_url == "https://example.test/v1"


def test_secrets_are_masked_in_repr() -> None:
    assert "supersecret" not in repr(_settings(api_key="supersecret"))


def test_pricing_and_feature_flags_parse_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PRICING", '{"my-model": {"input": 0.5, "output": 1.5}}')
    monkeypatch.setenv("VERIFICATION_MODE", "heuristic")
    monkeypatch.setenv("RETRIEVAL_RERANK", "false")
    settings = Settings()
    assert settings.llm_pricing["my-model"].output == 1.5
    assert settings.verification_mode == "heuristic"
    assert settings.retrieval_rerank is False


def test_invalid_structured_output_mode_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_STRUCTURED_OUTPUT", "xml")
    with pytest.raises(ValidationError):
        Settings()
