# Plan — KB 100+ Ingest Pipeline

> 본 plan은 `spec/kb-ingest-100plus.md`(목표 spec)와 `spec/kb-ingest-100plus-tasks.md`(작업 분해)의 중간 layer다.
> 본 프로젝트의 `spec/plan.md` 패턴(Phase A/B/C/D)을 그대로 따른다.

## 1. 원칙

1. **기존 인프라 재사용** — `coverage_report()`, `LawOpenApiClient`, `knowledge_ingest.plan_document_ingest()` 모두 보유. 신규 구현 0건.
2. **데이터 운영 작업** — 코드 변경 최소 (data/ 디렉토리 + 회귀 테스트 3건만).
3. **감사 추적성 우선** — 모든 신규 article은 `source_url` 필수. `last_verified_at = today()` 명시.
4. **점진 ingest** — 공식 법령 → 내부 기준 → 외부 표준 순서. 각 단계 commit 단위 분리.
5. **실측 검증** — 매 Phase 종료 시 `coverage_report().article_count` 실측 + 회귀 테스트 통과.

## 2. 목표 구조

```text
data/
├── laws.json                    # 기존 32 → 102 articles
├── law_targets.yaml             # NEW: ingest 대상 정의 (105건 buffer)
└── internal_standards/          # NEW: 내부 기준 markdown
    ├── jb-marketing-review.md
    ├── jb-multilingual-guide.md
    └── ...

src/compliance_sentinel/
├── knowledge_base.py            # 변경 없음 (coverage_report 보유)
├── knowledge_ingest.py          # 변경 없음 (plan_document_ingest 보유)
└── law_open_api.py              # 변경 없음 (LawOpenApiClient 보유)

tests/
└── test_compliance_sentinel.py  # +3 회귀 테스트
```

## 3. 핵심 데이터 흐름

```text
data/law_targets.yaml
   ↓ LawOpenApiClient (배치 fetch)
data/laws.json (공식 법령 70+)
   ↑
data/internal_standards/*.md
   ↓ knowledge_ingest.plan_document_ingest()
data/laws.json (내부 기준 26+, source_type="internal_standard")
   ↓
LawKnowledgeBase.from_default().coverage_report()
   → production_ready: True
```

## 4. 압축 로드맵

### Phase A — 메타 정의 (1시간)
- `data/law_targets.yaml` 작성 (105건 buffer)
- 우선순위 라벨링 (P0: 금융소비자보호법 / P1: 자본시장법·표시광고법 / P2: PIPA·신용정보법)
- `LAW_OPEN_API_KEY` 발급 절차 문서화

### Phase B — 공식 법령 Ingest (30분 + API 응답 대기)
- `cs-knowledge-ingest --laws data/law_targets.yaml --merge` 실행
- API rate limit 대응 (backoff 확인)
- 응답 검증: 각 article의 `source_url`/`status_verified=True`/`last_verified_at=today()`

### Phase C — 내부 기준 Ingest (1시간)
- `docs/jb-internal/*.md` 5건 작성 또는 금감원 공개 가이드 PDF 대체
- `cs-knowledge-ingest --document <file> --source-type internal_standard --merge` 배치
- chunk 단위 → article 변환 확인

### Phase D — 검증 (30분)
- `LawKnowledgeBase.from_default().coverage_report()` 실행 → 모든 필드 실측
- 회귀 테스트 3건 추가 (production_ready / source_type balance / source_url 필수)
- `pytest -q` → 105 passed 확인
- `cs-router run --content "..."` 샘플 실행 → `pdf_requirement_alignment.law_currency_and_internal_standards_tracking.production_ready=true` 확인

## 5. 리스크와 완화

| 리스크 | 완화 |
|---|---|
| 법령정보센터 API key 발급 지연 | Phase C(내부 기준) 선행, API 의존 우회 |
| API rate limit / timeout | `law_open_api.py` backoff 활용 + 배치 fetch (10건 단위) |
| 조문 본문 누락 (응답 빈 값) | `_parse_article_response` 실패 시 skip + 로그, Phase A에서 buffer 5건 정의 |
| 내부 기준 문서 미보유 | 공개 금감원 가이드 PDF 5건 대체 (sample만 작성) |
| stale article 기준 180일 초과 | Phase B/C에서 `last_verified_at = today()` 명시 |
| 기존 32 articles `last_verified_at` 부재로 stale 판정 | 기존 데이터 일괄 `today()` backfill (1회 운영) |
| 회귀 테스트가 fixture 의존 → CI 깨짐 | mock 데이터 활용 또는 conftest.py로 KB instance 격리 |

## 6. 산출물 검증 매핑

| 산출물 | spec AC | 검증 명령 |
|---|---|---|
| `data/laws.json` (102 articles) | AC-KB-001 | `python -c "import json; print(len(json.load(open('data/laws.json'))))"` |
| stale=0, unverified=0 | AC-KB-002/003 | `pytest tests/test_compliance_sentinel.py::TestKBProductionReadiness -v` |
| production_ready=True | AC-KB-004 | 동일 |
| source_type balance | AC-KB-005 | 동일 |
| 회귀 무영향 | AC-KB-006 | `pytest -q` (105 passed) |
| source_url 100% | AC-KB-007 | 회귀 테스트 |

## 7. PDF 직접 대응 표

| PDF 요구 (line) | 본 plan 대응 |
|---|---|
| line 84 "최신 금융규제와 내부 기준을 자동으로 추적" | Phase B(공식 법령) + Phase C(내부 기준) 완료 시 production_ready=True |
| line 80 "리소스가 선형적으로 증가" | KB 확장으로 동일 자원에서 더 많은 콘텐츠 자동 심의 가능 |
| line 86 "근거 제공" | 모든 article `source_url` 보유 → audit trail |
