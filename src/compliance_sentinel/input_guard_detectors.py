"""Native semantic injection detectors (dependency-free, in-repo).

준법 심의 입력 가드의 semantic 탐지 계층을 **율리 자체 코드로 내부화**한 모듈이다.
과거에는 외부 AgentShield 툴(`agent_shield.detectors`)이 있어야 동작하던 부분을,
외부 의존 없이 율리 안에서 실시간으로 돌도록 native로 흡수했다.

- 코어 regex 가드(`agent_shield_bridge.high_confidence_injection`)를 **augment**한다.
- ML classifier가 아니라, 코어 single-pass regex가 놓치는 paraphrase/난독화 cue를
  잡는 heuristic이다 (정직 라벨). 한국어 cue를 포함해 비영어 콘텐츠 blind spot을 보강한다.
- zero-dependency: 표준 라이브러리 `re`만 사용.
"""
from __future__ import annotations

import re

# (reason, compiled pattern, score 0..1). score >= block_threshold → 차단 사유.
_SEMANTIC_CUES: list[tuple[str, "re.Pattern[str]", float]] = [
    ("semantic_role_override", re.compile(r"(?i)\b(from now on|as of now|going forward)\b.{0,40}\b(you|assistant)\b"), 0.6),
    ("semantic_exfiltration", re.compile(r"(?i)\b(send|forward|email|post|upload|leak)\b.{0,30}\b(secret|credential|api[_ ]?key|password|token|private)\b"), 0.8),
    ("semantic_filter_bypass", re.compile(r"(?i)\b(bypass|disable|turn off|ignore)\b.{0,20}\b(filter|guard|safety|rule|policy|moderation)\b"), 0.8),
    ("semantic_persona_jailbreak", re.compile(r"(?i)\b(no restrictions|unfiltered|do anything now|without (any )?(limits|rules|ethics))\b"), 0.7),
    ("semantic_instruction_smuggle", re.compile(r"(?i)\b(the following|below) (text|message|content)\b.{0,30}\b(is|are) (your )?(new )?(instructions|orders|commands)\b"), 0.7),
    # 한국어 paraphrase (영어 cue가 놓치는 비영어 blind spot 보강)
    ("semantic_role_override_ko", re.compile(r"(지금|이제)\s*부터[^\n]{0,12}(너|넌|당신|어시스턴트|봇)"), 0.6),
    ("semantic_exfiltration_ko", re.compile(r"(보내|전송|전달|유출|알려|공개)[^\n]{0,20}(비밀|자격\s*증명|api[_ ]?key|비밀번호|암호|토큰|시스템\s*프롬프트)"), 0.8),
    ("semantic_filter_bypass_ko", re.compile(r"(무시|해제|끄|우회|비활성)[^\n]{0,12}(필터|가드|안전|규칙|정책|검열|제한)|(필터|가드|안전\s*장치|규칙|정책|검열|제한)[^\n]{0,12}(무시|해제|우회|비활성)"), 0.8),
    # "이전/위 지시(명령/프롬프트)를 무시" 류 — filter/guard 키워드 없이도 지시 무효화 문형(한국어)을
    # 차단한다. 영어 전용 PROMPT_ATTACK_RE가 놓치는 비영어 인젝션 blind spot 보강.
    ("semantic_instruction_override_ko", re.compile(r"(이전|앞|위|모든|지금까지)\s*(의\s*)?(지시|명령|지침|프롬프트|설정)[^\n]{0,15}(무시|무효|잊)"), 0.8),
    ("semantic_persona_jailbreak_ko", re.compile(r"(제한\s*없|무엇이든|탈옥|규칙\s*없이|윤리\s*없이|검열\s*없)"), 0.7),
]

# 코어 regex가 확실히 잡는 semantic cue의 기본 차단 임계값.
DEFAULT_BLOCK_THRESHOLD = 0.7


class KeywordSemanticDetector:
    """Dependency-free heuristic detector: prompt-injection paraphrase 탐지.

    ``__call__(text) -> [(reason, score), ...]`` (Detector protocol).
    """

    def __call__(self, text: str) -> list[tuple[str, float]]:
        out: list[tuple[str, float]] = []
        for reason, pattern, score in _SEMANTIC_CUES:
            if pattern.search(text):
                out.append((reason, score))
        return out


def run_detectors(
    detectors: "list[KeywordSemanticDetector] | None",
    text: str,
    *,
    block_threshold: float = DEFAULT_BLOCK_THRESHOLD,
) -> tuple[list[str], list[str], float]:
    """모든 detector 실행 → (all_reasons, blocking_reasons, max_score)."""
    reasons: list[str] = []
    blocking: list[str] = []
    max_score = 0.0
    for detector in detectors or []:
        try:
            findings = detector(text)
        except Exception:  # 결함 있는 detector가 가드 전체를 죽이지 않도록
            continue
        for reason, score in findings:
            reasons.append(reason)
            max_score = max(max_score, score)
            if score >= block_threshold:
                blocking.append(reason)
    return reasons, blocking, max_score
