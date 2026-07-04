# Unit Tests — 13 모듈별 격리 테스트

> **목적**: JB Compliance Sentinel 9-step 워크플로우의 각 모듈을 **독립적으로** 테스트.
> LLM 호출 없음 · Qdrant 의존성 없음 · 빠른 실행 (전체 suite < 5초 목표).

---

## 📦 모듈 ↔ 테스트 파일 매핑

| 모듈 # | source | test 파일 | 핵심 검증 |
|---|---|---|---|
| M2 | `pii.py` | `test_pii.py` | 5종 정규식 + **Bug #1 회귀** (card 4-4-4-4) |
| M3 | `classification.py` | `test_classification.py` | terms/advertisement/contract/transaction/unknown rule |
| M4 | `runtime.py` | `test_runtime.py` | risk parse + build_runtime_plan + quality_first_routing |
| M5+M6 | `memory_rag.py` | `test_memory_rag.py` | RAGBundle + _rrf_merge + _should_capture_outcome |
| M7 | `board.py` | `test_board.py` | 6 personas deterministic + max_risk + diagnose_board |
| M8 | `synthesizer.py` | `test_synthesizer.py` | synthesize_opinion + issue_for/applicability_for/revision_for |
| M9 | `verifier.py` | `test_verifier.py` | 5 atomic claims + has_failures + scope_overlap |
| M10 | `cross_model_verifier.py` | `test_cross_model_verifier.py` | _default_cross_model + deterministic fallback |
| M11 | `marketing_workflow.py` | `test_marketing_workflow.py` | _confidence + _force_cross_model + ceo_draft |
| M12 | `reporting.py` | `test_reporting.py` | build_final_report + CONFIDENCE 5등급 + **Bug #2 회귀** |
| - | `audit.py` | `test_audit.py` | AuditStore JSONL + PII 절대 노출 차단 |
| M13 | `budget_guard.py` | `test_budget_guard.py` | estimate_cost + 4-tier (green/yellow/red/blocked) |
| S1 | `agent_model_guard.py` | `test_agent_model_guard.py` | hard pin + silent downgrade 차단 |

---

## ▶ 실행 방법

### 전체 unit suite (빠름, 외부 의존성 0건)

```bash
cd /Users/seohun/Documents/에이전트/infiniteAgent/JB_Project-Compliance-Sentinel
pytest tests/unit/ -v
```

### 단일 모듈

```bash
pytest tests/unit/test_pii.py -v
pytest tests/unit/test_board.py::TestSixPersonas -v
pytest tests/unit/test_pii.py::TestCardPattern::test_visa_card_4_4_4_4 -v
```

### 마커 활용

```bash
# unit 만 실행 (default — 모두 unit)
pytest -m unit

# integration 제외 (현재 unit 디렉토리는 모두 unit이라 동일)
pytest -m "not integration and not llm"

# 느린 테스트만 skip
pytest -m "not slow"
```

### 커버리지 (pip install pytest-cov 후)

```bash
pytest tests/unit/ --cov=src/compliance_sentinel --cov-report=term-missing
```

### 병렬 실행 (pip install pytest-xdist)

```bash
pytest tests/unit/ -n auto   # CPU 수만큼 병렬
```

---

## 🛡️ Mock 정책

| 외부 의존성 | 처리 방법 |
|---|---|
| **OpenAI LLM 호출** | `CS_ENABLE_LLM_RUNTIME=0` (conftest.py default) — deterministic mode |
| **Qdrant Vector DB** | `CS_DISABLE_QDRANT=1` — keyword-only retrieval |
| **OPENAI_API_KEY** | conftest의 `deterministic_env` fixture가 명시 제거 |
| **LawKnowledgeBase JSON** | unit test는 mock fixture / integration은 실파일 |
| **외부 file I/O** | pytest `tmp_path` fixture로 격리 |

→ **결과**: unit suite 전체가 네트워크 없이 실행 가능, 비용 0원.

---

## 🪝 conftest.py fixture

| Fixture | 용도 |
|---|---|
| `sample_law_article` | KB 검증용 가짜 LawArticle (개인정보보호법 제15조) |
| `sample_citation` | Citation 객체 |
| `sample_finding` | Finding 객체 |
| `sample_pii_finding` | PIIFinding 객체 (rrn type) |
| `sample_board_opinion` | BoardOpinion 객체 |
| `sample_state` | 비어있는 ComplianceState |
| `tmp_audit_dir` / `tmp_audit_path` | 임시 audit log 디렉토리 |
| `deterministic_env` | LLM 비활성 환경 강제 |
| `llm_runtime_enabled` | LLM 활성 환경 (mock 호출용) |

---

## 🐛 회귀 방지 Test

### Bug #1: 카드번호 마스킹 누락 (2026-05-28 fix)
**위치**: `test_pii.py::TestCardPattern`
- 4-4-4-4 카드번호가 3-segment account 패턴에 흡수되지 않는지 검증
- `PII_PATTERNS` 순서 검증 (card → account)

### Bug #2: API 응답에 pii_findings 누락 (2026-05-28 fix)
**위치**: `test_reporting.py::TestBuildFinalReport::test_pii_fields_exposed_bug2_regression`
- `build_final_report`가 `pii_findings` / `pii_count` / `redacted_text` 3 필드를 응답에 포함하는지 검증

---

## ➕ 새 모듈 test 추가 가이드

1. `tests/unit/test_<module>.py` 신설
2. `from compliance_sentinel.<module> import <function>` import
3. 외부 의존성 있으면 `@pytest.fixture` 또는 `monkeypatch` 사용
4. LLM 호출 함수면 conftest의 `deterministic_env` fixture 활용
5. 한 클래스당 하나의 함수 그룹화 (`class TestXxx`)
6. 마커: 빠른 unit이면 추가 마커 불필요 (default)

---

## 📋 잔여 작업 (별도 turn)

- [ ] `tests/integration/` 디렉토리에 9-step end-to-end test 이동 (현 monolithic `test_compliance_sentinel.py` 분할)
- [ ] LLM 활성 테스트 (`@pytest.mark.llm`) — opt-in
- [ ] cross-model verifier mock 패치 (deterministic 외 경로)
- [ ] coverage 80%+ 목표 (현재 측정 X)
