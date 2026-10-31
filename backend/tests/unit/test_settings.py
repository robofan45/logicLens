import pytest
from pydantic import ValidationError

from app.settings import Settings

KEY_A = "a" * 24
KEY_B = "b" * 32


def test_defaults_are_safe_and_documented():
    s = Settings()
    assert s.engine == "auto"
    assert s.cors_origins == ["http://localhost:5173"]
    assert s.api_keys == []
    assert s.auth_enabled is False
    assert s.max_upload_mb == 8
    assert s.upload_cap_bytes == 8 * 1024 * 1024
    assert s.max_json_kb == 256
    assert s.max_image_pixels == 40_000_000
    assert s.max_image_side == 8000
    assert s.vision_model == s.explain_model == s.chat_model == "claude-sonnet-5-5"
    assert s.deep_model == "claude-opus-5-5"
    assert s.llm_enabled is False
    assert s.redis_url is None
    assert s.rate_limit_per_min > s.llm_rate_limit_per_min > 0
    assert s.docs is False


def test_cors_origins_are_comma_separated_and_normalised(monkeypatch):
    monkeypatch.setenv("LOGICLENS_CORS_ORIGINS", " https://app.example.com/ ,http://localhost:5173,, ")
    assert Settings().cors_origins == ["https://app.example.com", "http://localhost:5173"]


@pytest.mark.parametrize("bad", ["ftp://x.example", "app.example.com", "https://x.example/path", "https://"])
def test_invalid_cors_origin_is_rejected(monkeypatch, bad):
    monkeypatch.setenv("LOGICLENS_CORS_ORIGINS", bad)
    with pytest.raises(ValidationError):
        Settings()


def test_api_keys_parse_and_never_appear_in_repr(monkeypatch):
    monkeypatch.setenv("LOGICLENS_API_KEYS", f"{KEY_A}, {KEY_B}")
    s = Settings()
    assert [k.get_secret_value() for k in s.api_keys] == [KEY_A, KEY_B]
    assert s.auth_enabled is True
    assert KEY_A not in repr(s) and KEY_B not in str(s)


def test_short_api_key_is_rejected(monkeypatch):
    monkeypatch.setenv("LOGICLENS_API_KEYS", "short-key")
    with pytest.raises(ValidationError, match="at least 16"):
        Settings()


def test_unknown_engine_fails_fast(monkeypatch):
    monkeypatch.setenv("LOGICLENS_ENGINE", "magic")
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("var", ["ANTHROPIC_API_KEY", "LOGICLENS_ANTHROPIC_API_KEY"])
def test_anthropic_key_enables_llm_from_either_variable(monkeypatch, var):
    monkeypatch.setenv(var, "sk-ant-test-0000000000")
    s = Settings()
    assert s.llm_enabled is True
    assert "sk-ant-test" not in repr(s)


def test_redis_url_is_read_without_prefix_and_kept_secret(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://:hunter2@redis:6379/0")
    s = Settings()
    assert s.redis_url.get_secret_value() == "redis://:hunter2@redis:6379/0"
    assert "hunter2" not in repr(s)


def test_numbers_are_bounded(monkeypatch):
    monkeypatch.setenv("LOGICLENS_MAX_UPLOAD_MB", "0")
    with pytest.raises(ValidationError):
        Settings()


def test_model_ids_are_configurable(monkeypatch):
    monkeypatch.setenv("LOGICLENS_CHAT_MODEL", "claude-haiku-5-5")
    assert Settings().chat_model == "claude-haiku-5-5"


def test_init_kwargs_override_env_for_tests(monkeypatch):
    monkeypatch.setenv("LOGICLENS_ENGINE", "yolo")
    assert Settings(engine="stub").engine == "stub"
    assert Settings(anthropic_api_key="sk-x").llm_enabled is True


def test_cost_and_accuracy_knobs_have_bounded_defaults(monkeypatch):
    s = Settings()
    assert s.llm_max_program_chars == 60_000 and s.ocr_passes == 5 and s.inference_concurrency == 1
    monkeypatch.setenv("LOGICLENS_OCR_PASSES", "9")
    with pytest.raises(ValidationError):
        Settings()
