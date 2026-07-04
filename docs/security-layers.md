# Security Layers — Compliance Sentinel 8-Layer Defense-in-Depth

> **출처**: SEAS `.claude/rules/security-layers.md` 8-layer 모델 차용 (Hermes-inspired).
> **목적**: JB 환경에 맞춰 각 layer를 코드 위치 + 실제 정책에 매핑.
> 본 문서가 보안 정책의 single source — `behavioral-quality.md` Rule 6-4과 일관성 유지.

---

## 1. 8-Layer 매핑 표

| Layer | 이름 | JB 구현 위치 | 상태 | 비고 |
|:-:|---|---|:-:|---|
| L1 | 사용자 인증 | FastAPI JWT (`api.py`) | 🟡 skeleton | production에서 OAuth/SSO 통합 필요 |
| L2 | **입력 검증** | `pii.py` (PII 마스킹), `citation_extractor.py` (사용자 인용 추출+verifier) | ✅ | 한글 lookaround + 명시 인용 검증 |
| L3 | **격리 실행** | `langgraph_adapter.py` (StateGraph), workflow.py method 격리 | 🟡 부분 | LangGraph swap-in 준비, deterministic 기본 |
| L4 | **메타 인프라 보호** | `cs_brain.merge()` readonly 보호 (LP-CS-020/030) | ✅ | 자동 학습이 readonly 패턴 덮어쓰기 절대 금지 |
| L5 | **도메인 잠금** | `.cs-brain/` write 정책, `audit_logs/` append-only | ✅ | KB는 read-only, audit은 write-only |
| L6 | **출력 압축** | (P5+ deferred) LangSmith trace 활성 시 응답 trim | ⚪ | 현재 토큰 사용량 낮아 미적용 |
| L7 | **외부 검증 트리거** | `cross_model_verifier.py` (gpt-5.5 medium), critical 자동 부착 | ✅ | STRONG=auto-attach, ADVISORY=사용자 안내 |
| L8 | **에이전트 모델 가드** | `agent_model_guard.py` (LP-CS-030 OpenAI-only mini/nano/gpt-5.5 pin) | ✅ | 역할-모델 불일치 시 RuntimeError |

---

## 2. Layer별 상세

### L1: 사용자 인증

**현재 상태**: FastAPI `/analyze`, `/health`, `/verify-citation` 엔드포인트는 인증 없음 (MVP 단계). Production에서:

```python
# api.py 보강 예정 (P5+)
from fastapi.security import HTTPBearer
oauth2_scheme = HTTPBearer()

@app.post("/analyze", dependencies=[Depends(oauth2_scheme)])
def analyze(request: AnalyzeRequest, token: str = Depends(verify_jwt)) -> dict:
    ...
```

**Gap**: JWT 검증 함수 부재. 환경변수 `JB_AUTH_SECRET` 추가 필요.

### L2: 입력 검증 (PII + 인용)

**구현 완료**:
- `pii.py` — 4 패턴 (RRN/Phone/Email/Account) + 한글 인접 lookaround
- `citation_extractor.py` — 사용자 입력의 "제N조" 추출 → verifier 직접 입력
- `models.py` — Type hint로 입력 분류 (terms/advertisement/contract/transaction/unknown)

**테스트**:
- `test_redacts_pii_with_korean_adjacent_chars` (4 case)
- Demo Case B (가짜 법령 인용 차단)

### L3: 격리 실행

**현재**:
- `workflow.py`는 8개 method가 ComplianceState를 순차 변경 — 격리 일부 미흡
- `langgraph_adapter.py` (Phase 1 turn에서 추가)는 LangGraph StateGraph로 각 node를 격리 가능

**Production 활성화**:
```bash
pip install "langgraph>=0.2"
export USE_LANGGRAPH=1
```

### L4: 메타 인프라 보호 (Brain readonly)

**구현 완료** (Phase 8, T-807):
- `.cs-brain/project_brain.yaml`의 `readonly: true` 패턴 (LP-CS-020, LP-CS-030)은 `cs_brain.merge()`에서 절대 변경/삭제 안 함
- 단위 테스트 `test_merge_preserves_readonly_patterns` 통과

**확장 가능 영역**:
- `data/laws.json`, `data/jb_terms.json` 직접 편집 차단 (의도된 KB 추가만)
- `workflows/*.yaml` 자동 편집 금지

### L5: 도메인 잠금

| 디렉토리 | 권한 |
|---|---|
| `.cs-brain/` | append-only (capture/merge.log), schema 변경은 manual |
| `audit_logs/` | append-only |
| `data/` | read-only at runtime (ingestion은 별도 script) |
| `src/compliance_sentinel/system_prompts/` | read-only at runtime |

### L6: 출력 압축 (deferred)

토큰 비용이 임계점 미만이라 현재 미적용. P5+에서 응답 ≥10K 토큰 시 자동 요약.

### L7: 외부 검증 트리거 (Cross-Model)

**구현 완료** (Phase 7, T-704):
- `cross_model_verifier.py` — gpt-5.5 medium independent validation wrapper
- `model_router.py::CrossModelRecommendation` — STRONG/ADVISORY/NONE 자동 결정
- `quality=critical` → STRONG auto-attach (primary context blind-spot 검증)

### L8: 에이전트 모델 가드

**구현 완료** (Phase 7, T-705):
- `agent_model_guard.py::ModelGuard.check(role, model)`
- 빠른 작업은 `gpt-5.4-nano/mini`, 심층 주 작업과 검증/비평/독립 검증은 `gpt-5.5`만 허용
- 환경변수 `CS_BYPASS_MODEL_GUARD=1`로만 우회 (stderr 경고)

---

## 3. Critical 영역 추가 정책

다음 작업은 **사용자 명시 승인** 없이 자동 진행 금지 (`behavioral-quality.md` Rule 6-4 차용):

1. `.cs-brain/project_brain.yaml`의 readonly 패턴 수정/삭제
2. `data/laws.json` 직접 추가 (법령 원문은 항상 법령정보센터 API 또는 외부 검증)
3. 비가역 작업 — `rm -rf`, `git push --force`, audit_logs/ 삭제
4. 외부 API key 노출/포함
5. `--dangerously-skip-permissions` 모드에서 `.cs-brain/`, `src/`, `tests/` 편집

---

## 4. 검증 명령

```bash
# 8-layer 활성 상태 점검 (간단)
$ PYTHONPATH=src python3 -c "
from compliance_sentinel.agent_model_guard import ModelGuard, ModelGuardViolation
from compliance_sentinel.cross_model_verifier import is_enabled
from compliance_sentinel.budget_guard import BudgetGuard

print('L7 cross-model:', 'ENABLED' if is_enabled() else 'fallback (no API key)')
print('L8 model guard active:', not ModelGuard.from_env().bypass_allowed)
print('L6 budget guard:', BudgetGuard().summary())
"

# L4 readonly 보호 검증
$ cs-brain status   # readonly_pattern_count ≥ 1
```

---

## 5. 다음 단계 (Phase 5+)

| Layer | 보강 항목 |
|---|---|
| L1 | JWT/OAuth 실제 구현 |
| L3 | LangGraph activation + checkpointing |
| L6 | 출력 ≥10K 토큰 자동 요약 |
| 모든 layer | LangSmith/Phoenix trace로 layer fire 측정 |
