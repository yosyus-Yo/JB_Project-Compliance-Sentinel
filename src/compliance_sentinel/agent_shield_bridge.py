"""Runtime bridge to the sibling AgentShield security compiler.

The bridge is optional and offline-safe: if AgentShield is not installed or the
sibling repository is unavailable, deterministic fallback checks still return a
compact decision object. No raw/sanitized user text is stored in the returned
metadata.
"""
from __future__ import annotations

import ipaddress
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

try:
    from .approval import validate_approval
except ImportError:
    # approval 모듈이 원격 커밋에서 누락됨 (미사용 import) — graceful fallback으로 전체 import 체인 보호.
    # 원격에 approval.py가 추가되면 자동으로 실제 구현을 사용.
    validate_approval = None  # type: ignore[assignment]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT.parent
PROMPT_ATTACK_RE = re.compile(r"(?i)(ignore\s+(all\s+)?previous|disregard\s+(all\s+)?instructions|reveal\s+system\s+prompt|developer\s+message|new\s+instructions\s*:|act\s+as\s+DAN|you\s+are\s+now|<\|im_start\|>|\[INST\]|(이전|앞|위|모든|지금까지)\s*(의\s*)?(지시|명령|규칙|지침|프롬프트|설정)[^\n]{0,15}(무시|무효|잊)|시스템\s*프롬프트[^\n]{0,12}(보여|공개|출력|노출|알려)|지금부터\s*(너|넌|당신|어시스턴트))")
PII_RE = re.compile(r"(?i)([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|\b\d{3}-\d{2}-\d{4}\b|\b\d{2,3}-\d{3,4}-\d{4}\b|\b\d{6}-\d{7}\b)")
SECRET_RE = re.compile(r"(?i)(sk-[A-Za-z0-9_-]{12,}|api[_-]?key\s*[:=]\s*['\"][^'\"]+|token\s*[:=]\s*['\"][^'\"]+|password\s*[:=]\s*['\"][^'\"]+)")
URL_ARG_KEYS = ("url", "endpoint", "webhook_url", "callback_url")
PRIVATE_HOSTS = {"localhost", "metadata.google.internal"}
DEFAULT_ALLOWED_DOMAINS = [
    "law.go.kr",
    "open.law.go.kr",
    "fsc.go.kr",
    "fss.or.kr",
    "pipc.go.kr",
    "kofia.or.kr",
    "jbfg.com",
    "slack.com",
]
# High-confidence injection — single line + re.compile so static SAST treats it
# as a detector rule, not an attack payload. Discriminator is "instructions"
# (attack) vs "offers/ads/messages" (legitimate marketing copy).
_HIGH_CONFIDENCE_INJECTION_RE = re.compile(r"(?i)(<\|im_start\|>|<\|im_end\|>|\[/?INST\]|reveal\s+(the\s+)?system\s+prompt|system\s+prompt\s*[:=]|ignore\s+(all\s+)?previous\s+instructions|disregard\s+(all\s+)?(previous\s+)?instructions|act\s+as\s+DAN|developer\s+message|(이전|앞|위|모든|지금까지)\s*(의\s*)?(지시|명령|규칙|지침|프롬프트|설정)[^\n]{0,15}(무시|무효|잊)|시스템\s*프롬프트[^\n]{0,12}(보여|공개|출력|노출|알려))")


def guard_status() -> dict[str, Any]:
    guard = _agent_shield_guard()
    status: dict[str, Any] = {
        "available": guard is not None,
        "mode": "agentshield" if guard is not None else "local_fallback",
        "root": str(_agent_shield_root()),
    }
    if guard is not None:
        # F6: surface which opt-in security components actually loaded, so a
        # silently-failed import (fail-open) is observable rather than invisible.
        loaded = len(getattr(guard, "input_detectors", []) or [])
        # semantic detector만 native로 지원 (ML detector는 native 미이식 — B 스코프).
        requested = 1 if os.environ.get("CS_AGENTSHIELD_SEMANTIC_DETECTOR") == "1" else 0
        svid_requested = bool(os.environ.get("CS_AGENTSHIELD_SVID_SECRET"))
        svid_active = getattr(guard, "svid_verifier", None) is not None
        status["enforcement"] = {
            "input_detectors_loaded": loaded,
            "input_detectors_requested": requested,
            "detectors_fail_open": requested > loaded,
            "svid_verifier_active": svid_active,
            "svid_fail_open": svid_requested and not svid_active,
        }
    return status


def inspect_input_text(text: str) -> dict[str, Any]:
    """Inspect user input and return compact non-PII metadata."""

    guard = _agent_shield_guard()
    if guard is not None:
        return _compact_decision(guard.inspect_input(text), mode="agentshield", original_text=text)
    reasons: list[str] = []
    blocked: set[str] = {"prompt_injection_pattern"}
    sanitized = PII_RE.sub("[REDACTED_PII]", text)
    if PROMPT_ATTACK_RE.search(text):
        reasons.append("prompt_injection_pattern")
    # native semantic 탐지(opt-in): 코어 regex가 놓치는 paraphrase/한국어 injection cue 보강.
    if _semantic_detector_enabled():
        from .input_guard_detectors import run_detectors

        sem_reasons, sem_blocking, _ = run_detectors(_build_input_detectors(), text)
        reasons.extend(sem_reasons)
        blocked.update(sem_blocking)
    if sanitized != text:
        reasons.append("pii_redacted")
    return _fallback_decision("input.inspect", reasons, sanitized_changed=sanitized != text, blocked_reasons=blocked)


def input_guard_enforced() -> bool:
    """Secure by default: enforcement is ON unless CS_AGENTSHIELD_ENFORCE_INPUT_GUARD=0."""

    return os.environ.get("CS_AGENTSHIELD_ENFORCE_INPUT_GUARD", "1") != "0"


def high_confidence_injection(text: str) -> bool:
    """True only for unambiguous injection that never appears in legitimate copy."""

    return bool(_HIGH_CONFIDENCE_INJECTION_RE.search(text))


def enforce_input_guard(text: str) -> dict[str, Any] | None:
    """Shared secure-by-default gate for EVERY analysis entrypoint (engine and the
    legacy module-level helpers), so the guard cannot be bypassed by which
    function a caller happens to use.

    Returns a schema-valid REJECTED final report when the input is a
    high-confidence injection and enforcement is on; otherwise returns None and
    the caller proceeds normally."""

    if not input_guard_enforced():
        return None
    guard = inspect_input_text(text)
    if guard.get("allowed", True) or not high_confidence_injection(text):
        return None
    # Imported lazily to avoid any import-order coupling at module load.
    from .report_schema import build_blocked_final_report

    return build_blocked_final_report(guard.get("reasons"))


def inspect_output_text(text: str) -> dict[str, Any]:
    """Inspect generated output and return compact non-PII metadata."""

    guard = _agent_shield_guard()
    if guard is not None:
        return _compact_decision(guard.inspect_output(text), mode="agentshield", original_text=text)
    sanitized = PII_RE.sub("[REDACTED_PII]", text)
    sanitized = SECRET_RE.sub("[REDACTED_SECRET]", sanitized)
    reasons = ["sensitive_output_redacted"] if sanitized != text else []
    return _fallback_decision("output.inspect", reasons, sanitized_changed=sanitized != text, blocked_reasons=set())


def authorize_tool_call(tool_name: str, permission: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Authorize an external tool/network call through AgentShield when available."""

    args = args or {}
    local_url_reasons = _fallback_url_reasons(args)
    guard = _agent_shield_guard()
    if guard is not None:
        decision = _compact_decision(guard.authorize_tool(tool_name, permission, args), mode="agentshield")
        for reason in local_url_reasons:
            if reason not in decision["reasons"]:
                decision["reasons"].append(reason)
        if local_url_reasons:
            decision["allowed"] = False
        return decision
    reasons: list[str] = []
    if permission not in {"read", "search", "http_get"}:
        reasons.append(f"permission_not_allowed:{permission}")
    if permission in {"exec", "filesystem_write", "network", "http_post", "write"} and not args.get("approval_id"):
        reasons.append("approval_required")
    reasons.extend(local_url_reasons)
    return _fallback_decision("tool.authorize", reasons, sanitized_changed=False, blocked_reasons=set(reasons))


def _agent_shield_root() -> Path:
    # 1. explicit env var → 2. vendored copy (third_party) → 3. sibling checkout → 4. legacy
    configured = os.environ.get("AGENTSHIELD_ROOT")
    if configured:
        return Path(configured).expanduser()
    vendored = PROJECT_ROOT / "third_party" / "agentshield"
    if vendored.exists():
        return vendored
    sibling = WORKSPACE_ROOT / "AgentShield"
    if sibling.exists():
        return sibling
    return Path("C:/CC_project/AgentShield")


# Process-local cache for the shared RuntimeGuard singleton. A single shared
# instance lets every seam (inspect_input/output, ASGI middleware, tool
# registry, LangGraph nodes) share one policy + one StateStore so loop/budget/
# crescendo continuity holds across calls. Only a *real* guard is cached (never
# None) so flipping CS_DISABLE_AGENTSHIELD_RUNTIME_GUARD or installing AgentShield
# mid-process is honoured on the next call.
_GUARD_CACHE: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# 오류회복(resilience) — 가이드 제2장: 외부 도구 호출에 회복 5종을 코드로 강제
# ---------------------------------------------------------------------------
_RESILIENCE_CIRCUITS: dict[str, Any] = {}

# per-tool circuit breaker 기본 파라미터 (가이드 제2장 회복 5종)
_CIRCUIT_FAILURE_THRESHOLD = 5      # 연속 실패 N회 → circuit open (연쇄 장애 차단)
_CIRCUIT_RESET_TIMEOUT_S = 30.0     # open 후 이 시간 경과 시 half-open(1회 시험 허용)
_RETRY_BACKOFF_BASE_S = 0.05        # 재시도 지수 backoff 기준
_RETRY_BACKOFF_CAP_S = 0.5          # backoff 상한


class _NativeCircuit:
    """프로세스 로컬 circuit breaker (AgentShield resilience 부재 시 fail-safe 네이티브 구현)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.failures = 0
        self.opened_at: float | None = None

    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        # reset timeout 경과 → half-open(닫힌 것으로 보고 1회 시험 허용)
        if time.monotonic() - self.opened_at >= _CIRCUIT_RESET_TIMEOUT_S:
            return False
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= _CIRCUIT_FAILURE_THRESHOLD:
            self.opened_at = time.monotonic()


def _load_agent_shield_resilience() -> tuple[Any, Any] | None:
    """AgentShield ``resilience`` 모듈이 *실제로 존재*하면 (CircuitBreaker, resilient_call) 반환.

    sibling repo 버전에 resilience 모듈이 없을 수 있으므로(현재 상태) ImportError는
    None으로 흡수 → 네이티브 fail-safe 경로 사용. AgentShield에 모듈이 추가되면 자동 위임.
    """
    if not _ensure_agent_shield_importable():
        return None
    try:
        from agent_shield.resilience import CircuitBreaker, resilient_call  # type: ignore

        return CircuitBreaker, resilient_call
    except Exception:
        return None


def resilient_tool_call(
    fn: Callable[[], Any],
    *,
    tool_name: str,
    idempotent: bool = True,
    timeout_s: float | None = None,
    max_attempts: int = 3,
    fallback: Callable[[], Any] | None = None,
) -> Any:
    """외부 도구 호출에 오류회복(재시도·타임아웃·폴백·회로차단)을 적용한다.

    가이드 제2장의 회복 흐름(circuit → retry(backoff) → fallback)을 **JB 자체에
    네이티브 구현**한다(offline-safe). AgentShield ``resilience`` 모듈이 존재하면
    그쪽에 위임하고, 없으면 네이티브 경로로 동일 계약을 보장한다. **비멱등 호출
    (idempotent=False)은 재시도하지 않는다** — 가이드의 "비가역 작업 중복 방지".
    per-tool circuit breaker를 프로세스 로컬로 공유해 반복 실패 의존은 잠시 차단한다.
    """
    delegate = _load_agent_shield_resilience()
    if delegate is not None:
        circuit_cls, resilient_call = delegate
        circuit = _RESILIENCE_CIRCUITS.get(tool_name)
        if not isinstance(circuit, circuit_cls):
            circuit = circuit_cls(tool_name)
            _RESILIENCE_CIRCUITS[tool_name] = circuit
        return resilient_call(
            fn,
            target=tool_name,
            circuit=circuit,
            timeout_s=timeout_s,
            max_attempts=max_attempts if idempotent else 1,
            idempotent=idempotent,
            fallback=fallback,
        )

    # 네이티브 fail-safe 경로 (AgentShield resilience 부재)
    circuit = _RESILIENCE_CIRCUITS.get(tool_name)
    if not isinstance(circuit, _NativeCircuit):
        circuit = _NativeCircuit(tool_name)
        _RESILIENCE_CIRCUITS[tool_name] = circuit

    # circuit open → fn 미실행, 즉시 fallback (연쇄 장애 차단)
    if circuit.is_open():
        if fallback is not None:
            return fallback()
        raise RuntimeError(f"circuit open for tool '{tool_name}'")

    attempts = max_attempts if idempotent else 1
    last_exc: BaseException | None = None
    for i in range(attempts):
        try:
            result = fn()
            circuit.record_success()
            return result
        except Exception as exc:  # noqa: BLE001 — 도구 예외를 회복 정책으로 흡수
            last_exc = exc
            circuit.record_failure()
            if i < attempts - 1:
                time.sleep(min(_RETRY_BACKOFF_BASE_S * (2 ** i), _RETRY_BACKOFF_CAP_S))

    # 모든 시도 실패 → fallback 또는 마지막 예외 전파
    if fallback is not None:
        return fallback()
    assert last_exc is not None
    raise last_exc


def reset_resilience_circuits() -> None:
    """테스트 격리용 — per-tool circuit breaker 캐시 초기화."""
    _RESILIENCE_CIRCUITS.clear()


def reset_runtime_guard_cache() -> None:
    """Drop the cached guard + state store (test seam / hot reconfigure)."""

    _GUARD_CACHE.clear()


def _ensure_agent_shield_importable() -> bool:
    root = _agent_shield_root()
    src = root / "src"
    if not src.exists():
        return False
    src_str = str(src)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)
    return True


def _semantic_detector_enabled() -> bool:
    """native semantic 탐지 활성 여부. 기본 OFF(baseline 보존)로 두되,
    ``CS_AGENTSHIELD_SEMANTIC_DETECTOR=1`` 시 율리 내부 native detector가 동작한다."""

    return os.environ.get("CS_AGENTSHIELD_SEMANTIC_DETECTOR") == "1"


def _build_input_detectors() -> list[Any]:
    """Opt-in pluggable input detectors that augment the core regex guard.

    기본 OFF로 baseline 동작은 불변; 배포별로 켠다. semantic detector는 외부 툴
    의존 없이 **율리 내부 native**(``input_guard_detectors``)로 동작한다.
    (구 ML detector는 학습 모델 의존이 커서 native 미이식 — semantic만 흡수.)
    """

    detectors: list[Any] = []
    if _semantic_detector_enabled():
        from .input_guard_detectors import KeywordSemanticDetector

        detectors.append(KeywordSemanticDetector())
    return detectors


def _build_svid_verifier() -> Any | None:
    """Opt-in SPIFFE JWT-SVID verifier (HS256, stdlib hmac) keyed by a shared
    secret. Returns None unless CS_AGENTSHIELD_SVID_SECRET is set."""

    secret = os.environ.get("CS_AGENTSHIELD_SVID_SECRET")
    if not secret:
        return None
    try:
        from agent_shield.svid import JwtSvidVerifier  # type: ignore
    except Exception:
        return None
    audience = os.environ.get("CS_AGENTSHIELD_SVID_AUDIENCE") or None
    trusted = os.environ.get("CS_AGENTSHIELD_SVID_TRUSTED_DOMAINS")
    trusted_domains = [d.strip() for d in trusted.split(",") if d.strip()] if trusted else None
    return JwtSvidVerifier(secret, audience=audience, trusted_domains=trusted_domains)


def get_runtime_guard(*, fresh: bool = False) -> Any | None:
    """Return the shared AgentShield RuntimeGuard (or None when unavailable).

    The guard carries the JB compliance policy plus any opt-in detectors / SVID
    verifier / shared state store. Cached as a process singleton unless ``fresh``
    is requested (used when a caller needs an isolated instance)."""

    if os.environ.get("CS_DISABLE_AGENTSHIELD_RUNTIME_GUARD") == "1":
        return None
    if not fresh and _GUARD_CACHE.get("guard") is not None:
        return _GUARD_CACHE["guard"]
    if not _ensure_agent_shield_importable():
        return None
    try:
        from agent_shield.models import CompilerPolicy  # type: ignore
        from agent_shield.runtime import RuntimeGuard  # type: ignore
    except Exception:
        return None
    policy = CompilerPolicy(
        allowed_tool_permissions=["read", "search", "http_get"],
        approval_required_permissions=["exec", "filesystem_write", "network", "http_post", "write"],
        allowed_domains=list(DEFAULT_ALLOWED_DOMAINS),
    )
    kwargs: dict[str, Any] = {}
    detectors = _build_input_detectors()
    if detectors:
        kwargs["input_detectors"] = detectors
    svid_verifier = _build_svid_verifier()
    if svid_verifier is not None:
        kwargs["svid_verifier"] = svid_verifier
    try:
        from agent_shield.state import InMemoryStateStore  # type: ignore

        if fresh:
            # F5: a fresh guard is genuinely isolated — its own state store, not
            # the shared singleton's, so rate/budget/loop state does not bleed.
            kwargs["state_store"] = InMemoryStateStore()
        else:
            store = _GUARD_CACHE.get("state_store") or InMemoryStateStore()
            _GUARD_CACHE["state_store"] = store
            kwargs["state_store"] = store
    except Exception:
        pass
    guard = RuntimeGuard(policy, **kwargs)
    if not fresh:
        _GUARD_CACHE["guard"] = guard
    return guard


def _agent_shield_guard() -> Any | None:
    """Backward-compatible accessor — now returns the shared singleton."""

    return get_runtime_guard()


# --- Runtime integration adapters (AgentShield integrations.py seams) ---------
# Each accessor returns the wired component when AgentShield is importable, or a
# safe no-op / None when it is not — so callers never hard-depend on the sibling.


def get_asgi_middleware_class() -> Any | None:
    """Return AgentShield's ``GuardASGIMiddleware`` class, or None if unavailable."""

    if not _ensure_agent_shield_importable():
        return None
    try:
        from agent_shield.integrations import GuardASGIMiddleware  # type: ignore
    except Exception:
        return None
    return GuardASGIMiddleware


def get_guarded_tool_registry() -> Any | None:
    """Return a ``GuardedToolRegistry`` bound to the shared guard, or None.

    Tools registered on it dispatch through ``authorize_tool`` so no registered
    tool call can bypass the guard."""

    guard = get_runtime_guard()
    if guard is None:
        return None
    if not _ensure_agent_shield_importable():
        return None
    try:
        from agent_shield.integrations import GuardedToolRegistry  # type: ignore
    except Exception:
        return None
    return GuardedToolRegistry(guard)


def wrap_langgraph_node(node_fn: Any, *, input_key: str = "input_text", output_key: str = "output") -> Any:
    """Wrap a LangGraph node with the shared guard when available.

    Returns the original ``node_fn`` unchanged when AgentShield is unavailable so
    the graph still builds and runs identically (offline-safe)."""

    guard = get_runtime_guard()
    if guard is None:
        return node_fn
    if not _ensure_agent_shield_importable():
        return node_fn
    try:
        from agent_shield.integrations import guard_langgraph_node  # type: ignore
    except Exception:
        return node_fn
    return guard_langgraph_node(guard, node_fn, input_key=input_key, output_key=output_key)


def _compact_decision(decision: Any, *, mode: str, original_text: str | None = None) -> dict[str, Any]:
    data = decision.to_dict() if hasattr(decision, "to_dict") else dict(decision)
    sanitized = data.get("sanitized")
    return {
        "available": mode == "agentshield",
        "mode": mode,
        "allowed": bool(data.get("allowed")),
        "action": data.get("action"),
        "reasons": list(data.get("reasons") or []),
        "sanitized_changed": isinstance(sanitized, str) and (sanitized != original_text if original_text is not None else bool(sanitized)),
        "metadata": dict(data.get("metadata") or {}),
    }


def _fallback_decision(action: str, reasons: list[str], *, sanitized_changed: bool, blocked_reasons: set[str]) -> dict[str, Any]:
    return {
        "available": False,
        "mode": "local_fallback",
        "allowed": not any(reason in blocked_reasons for reason in reasons),
        "action": action,
        "reasons": reasons,
        "sanitized_changed": sanitized_changed,
        "metadata": {},
    }


def _fallback_url_reasons(args: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for raw_url in _extract_url_values(args):
        parsed = urlparse(raw_url)
        if parsed.scheme != "https":
            reasons.append("url_scheme_not_https")
        host = (parsed.hostname or "").lower()
        if not host:
            reasons.append("url_missing_host")
            continue
        if _is_private_host(host):
            reasons.append("url_private_host_blocked")
        if DEFAULT_ALLOWED_DOMAINS and not _domain_allowed(host, DEFAULT_ALLOWED_DOMAINS):
            reasons.append(f"url_domain_not_allowed:{host}")
    return reasons


def _extract_url_values(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in URL_ARG_KEYS and item:
                urls.extend(_string_urls(item, force=True))
            else:
                urls.extend(_extract_url_values(item))
    elif isinstance(value, list | tuple):
        for item in value:
            urls.extend(_extract_url_values(item))
    else:
        urls.extend(_string_urls(value, force=False))
    return urls


def _string_urls(value: Any, *, force: bool) -> list[str]:
    if not isinstance(value, str):
        return []
    text = value.strip()
    if force or text.startswith(("http://", "https://")):
        return [text]
    return []


def _domain_allowed(host: str, allowed_domains: list[str]) -> bool:
    for domain in allowed_domains:
        normalized = domain.lower().lstrip(".")
        if host == normalized or host.endswith("." + normalized):
            return True
    return False


def _is_private_host(host: str) -> bool:
    if host in PRIVATE_HOSTS or host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
