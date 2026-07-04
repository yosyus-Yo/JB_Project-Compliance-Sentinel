"""Encrypted UI settings for Streamlit.

Secrets are stored in an encrypted local file under `.local/` and are applied to
process environment variables only after the user unlocks them with a master
password. The plaintext values are never returned for display.
"""
from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECURE_SETTINGS_PATH = PROJECT_ROOT / ".local" / "secure_settings.json.enc"
KDF_ITERATIONS = 390_000
MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:/@+-]{2,128}$")


@dataclass(frozen=True)
class SecretField:
    env: str
    label: str
    help: str
    required: bool = False


@dataclass(frozen=True)
class ModelField:
    env: str
    label: str
    default: str
    help: str


@dataclass(frozen=True)
class FlagField:
    env: str
    label: str
    default: str
    help: str


@dataclass(frozen=True)
class RoutingField:
    env: str
    label: str
    default: str
    help: str
    kind: str = "text"
    options: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None


SECRET_FIELDS = [
    SecretField("OPENAI_API_KEY", "OpenAI API Key", "OpenAI 모델 또는 기본 OpenAI-compatible 라우트"),
    SecretField("CODEX_API_KEY", "Codex/OpenAI-compatible API Key", "Codex/OpenAI 호환 라우트"),
    SecretField("ANTHROPIC_API_KEY", "Anthropic API Key", "anthropic/claude-* 모델 라우트"),
    SecretField("GOOGLE_API_KEY", "Google/Gemini API Key", "google/gemini-* 모델 라우트"),
    SecretField("OPENROUTER_API_KEY", "OpenRouter API Key", "openrouter/... 모델 라우트"),
    SecretField("GROQ_API_KEY", "Groq API Key", "groq/... OpenAI-compatible 라우트"),
    SecretField("TOGETHER_API_KEY", "Together API Key", "together/... OpenAI-compatible 라우트"),
    SecretField("FIREWORKS_API_KEY", "Fireworks API Key", "fireworks/... OpenAI-compatible 라우트"),
    SecretField("DEEPSEEK_API_KEY", "DeepSeek API Key", "deepseek/... OpenAI-compatible 라우트"),
    SecretField("CS_LLM_API_KEY", "Custom LLM API Key", "CS_LLM_BASE_URL 사용 시 인증 키"),
    SecretField("CS_LLM_BASE_URL", "Custom OpenAI-compatible Base URL", "custom/... 모델 라우트 base URL"),
    SecretField("LAW_OPEN_API_KEY", "법령정보센터 API Key", "공식 법령 본문 조회"),
    SecretField("QDRANT_URL", "Qdrant URL", "hybrid RAG vector store endpoint"),
    SecretField("QDRANT_API_KEY", "Qdrant API Key", "Qdrant Cloud 인증이 필요한 경우"),
    SecretField("LANGSMITH_API_KEY", "LangSmith API Key", "trace/observability export"),
    SecretField("PHOENIX_ENDPOINT", "Phoenix Endpoint", "Phoenix observability endpoint"),
    SecretField("OTEL_EXPORTER_OTLP_ENDPOINT", "OTLP Endpoint", "OpenTelemetry trace endpoint"),
    SecretField("SLACK_WEBHOOK_URL", "Slack Webhook URL", "승인 워크플로우 live publish"),
    SecretField("NOTION_API_KEY", "Notion API Key", "Notion publish 준비"),
    SecretField("NOTION_DATABASE_ID", "Notion Database ID", "Notion publish 대상 DB"),
]

MODEL_FIELDS = [
    ModelField("CS_MODEL_SHALLOW", "간단한 작업 모델", "gpt-5.4-nano", "fixed classifier/documenter/shallow route"),
    ModelField("CS_MODEL_STANDARD", "일반 작업 모델", "gpt-5.4-mini", "fixed board/non-critical CEO/non-critical verifier route"),
    ModelField("CS_MODEL_DEEP", "복잡한 작업 모델", "gpt-5.5", "fixed critical CEO/deep route"),
    ModelField("CS_MODEL_CRITIC", "검증/비평 모델", "gpt-5.5", "fixed critical and cross-model validation route"),
]
FIXED_MODEL_BY_ENV = {field.env: field.default for field in MODEL_FIELDS}
CRITIC_PROVIDER_PREFIXES = ("openrouter/anthropic/", "anthropic/claude-")

FLAG_FIELDS = [
    FlagField("CS_ENABLE_LLM_RUNTIME", "라이브 LLM 호출", "1", "1이면 live LLM advisory 활성, 0이면 deterministic-safe fallback"),
    FlagField("CS_USE_LLM_BOARD_VERDICTS", "LLM 보드 verdict 반영", "0", "구조화된 risk signal만 반영"),
    FlagField("CS_EXTRA_VALIDATION_ADVISORY", "추가 독립 검증", "0", "cross-model advisory 검증 활성화"),
    FlagField("CS_ENABLE_WORKFLOW_PUBLISH", "Slack/Notion live publish", "0", "외부 워크플로우 전송 활성화"),
    FlagField("USE_LANGGRAPH", "LangGraph runtime", "0", "설치되어 있으면 StateGraph adapter 사용"),
]

ROUTING_FIELDS = [
    RoutingField(
        "CS_LIVE_REVIEW_PROFILE",
        "Live LLM 속도 프로파일",
        "turbo",
        "turbo는 저위험 호출을 줄이고, strict는 보수 검증을 유지합니다.",
        kind="select",
        options=("turbo", "fast", "balanced", "strict"),
    ),
    RoutingField(
        "CS_LIVE_REVIEW_EFFORT",
        "Live LLM effort",
        "",
        "Empty uses the selected profile default; override with none/low/medium/high.",
        kind="select",
        options=("", "none", "low", "medium", "high"),
    ),
    RoutingField("CS_LLM_PARALLELISM", "LLM 병렬 호출 수", "8", "동시 live advisory 호출 상한", kind="number", minimum=1, maximum=32),
    RoutingField("CS_REVIEW_MAX_IN_FLIGHT", "Review max in-flight", "3", "Concurrent Python review requests allowed by the React bridge.", kind="number", minimum=1, maximum=64),
    RoutingField("CS_REVIEW_QUEUE_TIMEOUT_MS", "Review queue timeout(ms)", "2000", "How long a saturated review request may wait before HTTP 503.", kind="number", minimum=0, maximum=120_000),
    RoutingField("CS_REVIEW_CACHE_TTL_MS", "리뷰 캐시 TTL(ms)", "300000", "동일 요청 캐시 유지 시간. 0이면 비활성화. 최대 7일(604800000ms)", kind="number", minimum=0, maximum=604_800_000),
    RoutingField("CS_REVIEW_CACHE_MAX", "리뷰 캐시 최대 건수", "64", "서버 메모리 캐시 최대 항목 수. 0이면 비활성화", kind="number", minimum=0, maximum=1_000),
    RoutingField("CS_PYTHON_TIMEOUT_MS", "Python bridge timeout(ms)", "60000", "subprocess bridge 최대 대기 시간", kind="number", minimum=1_000, maximum=300_000),
    RoutingField("CS_PYTHON_WORKER_TIMEOUT_MS", "Python worker timeout(ms)", "60000", "FastAPI worker 요청 최대 대기 시간", kind="number", minimum=1_000, maximum=300_000),
    RoutingField("CS_PYTHON_WORKER_STARTUP_MS", "Python worker startup(ms)", "20000", "worker 자동 시작 최대 대기 시간", kind="number", minimum=1_000, maximum=120_000),
]

SECTION_ALLOWED_ENV_NAMES = {
    "secrets": {field.env for field in SECRET_FIELDS},
    "models": {field.env for field in MODEL_FIELDS},
    "flags": {field.env for field in FLAG_FIELDS},
    "routing": {field.env for field in ROUTING_FIELDS},
}
ALLOWED_ENV_NAMES = set().union(*SECTION_ALLOWED_ENV_NAMES.values())


def default_settings() -> dict[str, Any]:
    return {
        "secrets": {field.env: "" for field in SECRET_FIELDS},
        "models": {field.env: os.environ.get(field.env, field.default) for field in MODEL_FIELDS},
        "flags": {field.env: os.environ.get(field.env, field.default) for field in FLAG_FIELDS},
        "routing": {field.env: os.environ.get(field.env, field.default) for field in ROUTING_FIELDS},
        "updated_at": "",
    }


def has_encrypted_settings(path: Path = SECURE_SETTINGS_PATH) -> bool:
    return path.exists()


def secret_status(settings: dict[str, Any]) -> dict[str, bool]:
    return {field.env: bool((settings.get("secrets") or {}).get(field.env)) for field in SECRET_FIELDS}


def _derive_key(master_password: str, salt: bytes) -> bytes:
    if not master_password:
        raise ValueError("마스터 비밀번호를 입력해 주세요.")
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=KDF_ITERATIONS,
    )
    return base64.urlsafe_b64encode(kdf.derive(master_password.encode("utf-8")))


def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    clean = default_settings()
    for section in ("secrets", "models", "flags", "routing"):
        values = payload.get(section) or {}
        if not isinstance(values, dict):
            continue
        allowed = SECTION_ALLOWED_ENV_NAMES[section]
        for key, value in values.items():
            if key not in allowed:
                continue
            clean[section][key] = str(value or "").strip()
    clean["updated_at"] = str(payload.get("updated_at") or "")
    validate_model_settings(clean["models"])
    validate_routing_settings(clean["routing"])
    return clean


def validate_model_settings(models: dict[str, str]) -> None:
    for field in MODEL_FIELDS:
        value = str(models.get(field.env) or field.default).strip()
        if not MODEL_ID_PATTERN.fullmatch(value):
            raise ValueError(f"모델 ID 형식이 안전하지 않습니다: {field.env}")
        expected = FIXED_MODEL_BY_ENV[field.env]
        if field.env == "CS_MODEL_CRITIC" and (value == expected or value.startswith(CRITIC_PROVIDER_PREFIXES)):
            continue
        if value != expected:
            raise ValueError(
                f"{field.env}는 {expected}로 고정되어 있습니다. "
                "허용 모델은 gpt-5.5, gpt-5.4-mini, gpt-5.4-nano뿐입니다."
            )


def validate_routing_settings(routing: dict[str, str]) -> None:
    for field in ROUTING_FIELDS:
        value = str(routing.get(field.env) or field.default).strip()
        if field.options and value not in field.options:
            raise ValueError(f"지원하지 않는 라우팅 옵션입니다: {field.env}={value}")
        if field.kind == "number":
            try:
                number = int(value)
            except ValueError as exc:
                raise ValueError(f"숫자 설정이어야 합니다: {field.env}") from exc
            if field.minimum is not None and number < field.minimum:
                raise ValueError(f"{field.env}는 {field.minimum} 이상이어야 합니다.")
            if field.maximum is not None and number > field.maximum:
                raise ValueError(f"{field.env}는 {field.maximum} 이하이어야 합니다.")


def load_encrypted_settings(master_password: str, path: Path = SECURE_SETTINGS_PATH) -> dict[str, Any]:
    if not path.exists():
        return default_settings()
    envelope = json.loads(path.read_text(encoding="utf-8"))
    salt = base64.urlsafe_b64decode(envelope["salt"].encode("ascii"))
    token = envelope["token"].encode("ascii")
    try:
        plain = Fernet(_derive_key(master_password, salt)).decrypt(token)
    except InvalidToken as exc:
        raise ValueError("설정 파일을 복호화할 수 없습니다. 마스터 비밀번호를 확인해 주세요.") from exc
    return _validate_payload(json.loads(plain.decode("utf-8")))


def save_encrypted_settings(settings: dict[str, Any], master_password: str, path: Path = SECURE_SETTINGS_PATH) -> None:
    clean = _validate_payload(settings)
    clean["updated_at"] = datetime.now(timezone.utc).isoformat()
    salt = os.urandom(16)
    token = Fernet(_derive_key(master_password, salt)).encrypt(
        json.dumps(clean, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    envelope = json.dumps(
        {
            "version": 1,
            "kdf": "PBKDF2HMAC-SHA256",
            "iterations": KDF_ITERATIONS,
            "salt": base64.urlsafe_b64encode(salt).decode("ascii"),
            "token": token.decode("ascii"),
        },
        ensure_ascii=False,
        indent=2,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(envelope, encoding="utf-8")
    tmp_path.replace(path)


def apply_settings_to_environment(settings: dict[str, Any]) -> None:
    clean = _validate_payload(settings)
    for section in ("secrets", "models", "flags", "routing"):
        for key, value in clean[section].items():
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
    # LLM off means deterministic-safe, but do not force CS_DETERMINISTIC_MODE=1 so
    # users can still override from the shell when needed.
    if clean["flags"].get("CS_ENABLE_LLM_RUNTIME") != "1":
        os.environ["CS_ENABLE_LLM_RUNTIME"] = "0"


def delete_encrypted_settings(path: Path = SECURE_SETTINGS_PATH) -> None:
    if path.exists():
        path.unlink()


def model_route_summary_from_env() -> dict[str, str]:
    return {field.env: os.environ.get(field.env, field.default) for field in MODEL_FIELDS}


def runtime_route_summary_from_env() -> dict[str, str]:
    return {field.env: os.environ.get(field.env, field.default) for field in ROUTING_FIELDS}
