"""ui_settings.py — encrypted secure settings + field validation + crypto round-trip."""
from __future__ import annotations

from pathlib import Path

import pytest

from compliance_sentinel.ui_settings import (
    ALLOWED_ENV_NAMES,
    FIXED_MODEL_BY_ENV,
    FLAG_FIELDS,
    KDF_ITERATIONS,
    MODEL_FIELDS,
    MODEL_ID_PATTERN,
    ROUTING_FIELDS,
    SECRET_FIELDS,
    SECTION_ALLOWED_ENV_NAMES,
    FlagField,
    ModelField,
    RoutingField,
    SecretField,
    _derive_key,
    _validate_payload,
    apply_settings_to_environment,
    default_settings,
    delete_encrypted_settings,
    has_encrypted_settings,
    load_encrypted_settings,
    model_route_summary_from_env,
    runtime_route_summary_from_env,
    save_encrypted_settings,
    secret_status,
    validate_model_settings,
    validate_routing_settings,
)


class TestModelIdPattern:
    @pytest.mark.parametrize("model", ["gpt-5.5", "claude-haiku-4-5", "anthropic:claude-opus-4-7"])
    def test_valid_models_match(self, model):
        assert MODEL_ID_PATTERN.match(model) is not None

    def test_invalid_short(self):
        assert MODEL_ID_PATTERN.match("a") is None

    def test_invalid_too_long(self):
        assert MODEL_ID_PATTERN.match("a" * 200) is None


class TestKdfIterations:
    def test_secure_iteration_count(self):
        assert KDF_ITERATIONS >= 100_000


class TestFieldsLists:
    def test_secret_fields_nonempty(self):
        assert len(SECRET_FIELDS) > 0
        for f in SECRET_FIELDS:
            assert isinstance(f, SecretField)

    def test_model_fields_nonempty(self):
        assert len(MODEL_FIELDS) > 0
        for f in MODEL_FIELDS:
            assert isinstance(f, ModelField)

    def test_flag_fields_nonempty(self):
        assert len(FLAG_FIELDS) > 0
        for f in FLAG_FIELDS:
            assert isinstance(f, FlagField)

    def test_routing_fields_nonempty(self):
        assert len(ROUTING_FIELDS) > 0
        for f in ROUTING_FIELDS:
            assert isinstance(f, RoutingField)


class TestFixedModelByEnv:
    def test_dict_with_defaults(self):
        assert "CS_MODEL_DEEP" in FIXED_MODEL_BY_ENV
        assert FIXED_MODEL_BY_ENV["CS_MODEL_DEEP"] == "claude-opus-4-8"


class TestSectionAllowedEnvNames:
    def test_has_4_sections(self):
        assert set(SECTION_ALLOWED_ENV_NAMES.keys()) == {"secrets", "models", "flags", "routing"}

    def test_allowed_env_names_union(self):
        assert "OPENAI_API_KEY" in ALLOWED_ENV_NAMES
        assert "CS_MODEL_DEEP" in ALLOWED_ENV_NAMES


class TestDefaultSettings:
    def test_returns_4_sections(self):
        result = default_settings()
        assert "secrets" in result
        assert "models" in result
        assert "flags" in result
        assert "routing" in result

    def test_secrets_default_empty(self):
        result = default_settings()
        for env, value in result["secrets"].items():
            assert value == ""

    def test_models_default_set(self):
        result = default_settings()
        assert result["models"]["CS_MODEL_DEEP"] == "claude-opus-4-8"


class TestHasEncryptedSettings:
    def test_missing_path_returns_false(self, tmp_path):
        assert has_encrypted_settings(tmp_path / "missing.enc") is False

    def test_existing_path_returns_true(self, tmp_path):
        path = tmp_path / "settings.enc"
        path.write_text("{}", encoding="utf-8")
        assert has_encrypted_settings(path) is True


class TestSecretStatus:
    def test_returns_bool_dict(self):
        settings = default_settings()
        status = secret_status(settings)
        assert all(isinstance(v, bool) for v in status.values())

    def test_empty_secrets_all_false(self):
        settings = default_settings()
        status = secret_status(settings)
        assert all(v is False for v in status.values())

    def test_with_set_secret(self):
        settings = default_settings()
        settings["secrets"]["OPENAI_API_KEY"] = "sk-test"
        status = secret_status(settings)
        assert status["OPENAI_API_KEY"] is True


class TestDeriveKey:
    def test_empty_password_raises(self):
        with pytest.raises(ValueError, match="마스터 비밀번호"):
            _derive_key("", b"\x00" * 16)

    def test_valid_password_returns_bytes(self):
        key = _derive_key("password123", b"\x00" * 16)
        assert isinstance(key, bytes)
        assert len(key) > 0

    def test_deterministic_same_salt(self):
        salt = b"\x01" * 16
        k1 = _derive_key("pwd", salt)
        k2 = _derive_key("pwd", salt)
        assert k1 == k2

    def test_different_salt_different_key(self):
        k1 = _derive_key("pwd", b"\x01" * 16)
        k2 = _derive_key("pwd", b"\x02" * 16)
        assert k1 != k2


class TestValidatePayload:
    def test_basic_payload(self):
        payload = default_settings()
        result = _validate_payload(payload)
        assert "secrets" in result
        assert "updated_at" in result

    def test_unknown_env_filtered(self):
        payload = default_settings()
        payload["secrets"]["UNKNOWN_KEY"] = "value"
        result = _validate_payload(payload)
        assert "UNKNOWN_KEY" not in result["secrets"]

    def test_non_dict_section_ignored(self):
        payload = default_settings()
        payload["secrets"] = "not a dict"
        result = _validate_payload(payload)
        # secrets는 default 유지
        assert isinstance(result["secrets"], dict)


class TestValidateModelSettings:
    def test_valid_defaults_pass(self):
        models = {field.env: field.default for field in MODEL_FIELDS}
        validate_model_settings(models)  # no raise

    def test_invalid_model_id_raises(self):
        models = {field.env: field.default for field in MODEL_FIELDS}
        models["CS_MODEL_DEEP"] = "!@#$%"  # invalid pattern
        with pytest.raises(ValueError, match="안전하지 않습니다"):
            validate_model_settings(models)

    def test_non_default_model_raises(self):
        models = {field.env: field.default for field in MODEL_FIELDS}
        models["CS_MODEL_DEEP"] = "gpt-3.5"  # valid pattern but not in fixed list
        with pytest.raises(ValueError, match="고정되어"):
            validate_model_settings(models)


class TestValidateRoutingSettings:
    def test_valid_defaults_pass(self):
        routing = {field.env: field.default for field in ROUTING_FIELDS}
        validate_routing_settings(routing)

    def test_invalid_select_option_raises(self):
        routing = {field.env: field.default for field in ROUTING_FIELDS}
        routing["CS_LIVE_REVIEW_PROFILE"] = "ultra"  # not in options
        with pytest.raises(ValueError, match="지원하지 않는"):
            validate_routing_settings(routing)

    def test_invalid_number_format_raises(self):
        routing = {field.env: field.default for field in ROUTING_FIELDS}
        routing["CS_LLM_PARALLELISM"] = "not_a_number"
        with pytest.raises(ValueError, match="숫자 설정"):
            validate_routing_settings(routing)

    def test_below_minimum_raises(self):
        routing = {field.env: field.default for field in ROUTING_FIELDS}
        routing["CS_LLM_PARALLELISM"] = "0"  # min=1
        with pytest.raises(ValueError, match="이상"):
            validate_routing_settings(routing)

    def test_above_maximum_raises(self):
        routing = {field.env: field.default for field in ROUTING_FIELDS}
        routing["CS_LLM_PARALLELISM"] = "999"  # max=32
        with pytest.raises(ValueError, match="이하"):
            validate_routing_settings(routing)


class TestEncryptedSettingsRoundTrip:
    def test_save_and_load(self, tmp_path):
        path = tmp_path / "settings.enc"
        original = default_settings()
        original["secrets"]["OPENAI_API_KEY"] = "sk-test-key"
        save_encrypted_settings(original, "password123", path=path)
        assert path.exists()
        loaded = load_encrypted_settings("password123", path=path)
        assert loaded["secrets"]["OPENAI_API_KEY"] == "sk-test-key"

    def test_load_with_wrong_password(self, tmp_path):
        path = tmp_path / "settings.enc"
        save_encrypted_settings(default_settings(), "password123", path=path)
        with pytest.raises(ValueError, match="복호화"):
            load_encrypted_settings("wrong-password", path=path)

    def test_load_nonexistent_returns_defaults(self, tmp_path):
        result = load_encrypted_settings("any", path=tmp_path / "missing.enc")
        assert "secrets" in result
        # default empty
        assert result["secrets"]["OPENAI_API_KEY"] == ""

    def test_save_uses_atomic_replace(self, tmp_path):
        path = tmp_path / "settings.enc"
        save_encrypted_settings(default_settings(), "pwd", path=path)
        # 임시파일 잔여 없음
        tmp_file = path.with_name(path.name + ".tmp")
        assert not tmp_file.exists()


class TestApplySettingsToEnvironment:
    def test_sets_env_vars(self, tmp_path, monkeypatch):
        settings = default_settings()
        settings["secrets"]["OPENAI_API_KEY"] = "sk-applied"
        apply_settings_to_environment(settings)
        import os
        assert os.environ.get("OPENAI_API_KEY") == "sk-applied"

    def test_empty_secret_removes_env(self, monkeypatch):
        import os
        monkeypatch.setenv("OPENAI_API_KEY", "old-value")
        settings = default_settings()  # empty secrets
        apply_settings_to_environment(settings)
        assert "OPENAI_API_KEY" not in os.environ

    def test_llm_disabled_forces_deterministic(self, monkeypatch):
        import os
        settings = default_settings()
        settings["flags"]["CS_ENABLE_LLM_RUNTIME"] = "0"
        apply_settings_to_environment(settings)
        assert os.environ.get("CS_ENABLE_LLM_RUNTIME") == "0"


class TestDeleteEncryptedSettings:
    def test_removes_file_if_exists(self, tmp_path):
        path = tmp_path / "settings.enc"
        save_encrypted_settings(default_settings(), "pwd", path=path)
        delete_encrypted_settings(path)
        assert not path.exists()

    def test_no_error_when_missing(self, tmp_path):
        delete_encrypted_settings(tmp_path / "missing.enc")  # no raise


class TestRouteSummaries:
    def test_model_route_summary(self):
        result = model_route_summary_from_env()
        assert "CS_MODEL_DEEP" in result

    def test_runtime_route_summary(self):
        result = runtime_route_summary_from_env()
        assert "CS_LIVE_REVIEW_PROFILE" in result
