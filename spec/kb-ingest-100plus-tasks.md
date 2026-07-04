# Tasks — KB 100+ Ingest

> 본 프로젝트의 `spec/tasks.md` 형식을 그대로 따른다. ID prefix: `KB-`.
> Phase A=001-099, Phase B=101-199, Phase C=201-299, Phase D=301-399.

## Phase A — 메타 정의

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| KB-001 | `data/law_targets.yaml` 스키마 정의 | todo | law_name/article_no/source_type/priority 4 필드 + buffer 5건 포함 (총 105건) |
| KB-002 | 공식 법령 70+ 항목 정의 (금융소비자보호법 20, 자본시장법 10, 표시광고법 8, PIPA 12, 신용정보법 10, 은행법 5, 보험업법 5) | todo | `law_targets.yaml`에 70+ entry 작성 |
| KB-003 | 내부 기준 26+ 항목 정의 (금감원 가이드라인 18, JB 내부 8) | todo | `law_targets.yaml` 또는 `data/internal_standards/INDEX.md`에 26+ entry |
| KB-004 | 외부 표준 6+ 항목 정의 (KIDI 3, 협회 자율규제 3) | todo | 동일 |
| KB-005 | `LAW_OPEN_API_KEY` 발급 절차 README 작성 | todo | `docs/law-open-api-setup.md` 작성, 발급 사이트 URL 명시 |
| KB-006 | 기존 32 articles의 `last_verified_at` backfill 정책 결정 | todo | `today()` 일괄 vs `original_published_date` 유지 — `data/laws.json` migration 스크립트 |

## Phase B — 공식 법령 Ingest

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| KB-101 | `LawOpenApiClient` rate limit / backoff 동작 검증 | todo | 10건 연속 fetch 시 timeout/throttle 없음, `law_open_api.py` 코드 재확인 |
| KB-102 | `cs-knowledge-ingest --laws data/law_targets.yaml --merge` 배치 실행 | todo | 70+ 공식 법령 article이 `data/laws.json`에 추가됨 |
| KB-103 | 응답 누락 article 재시도 / 수동 보완 | todo | `_parse_article_response` 실패 항목 0건 또는 수동 데이터로 보완 |
| KB-104 | 각 신규 article 메타 검증 (source_url, status_verified=True, last_verified_at=today) | todo | jq로 100% 필드 충족 확인 |
| KB-105 | source_type="official_or_external" 일관 표기 | todo | 공식 법령 70+ 모두 official_or_external 라벨 |

## Phase C — 내부 기준 Ingest

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| KB-201 | `data/internal_standards/` 디렉토리 생성 + INDEX.md | todo | 디렉토리 + 26+ entry 인덱스 |
| KB-202 | 금감원 공개 가이드라인 18건 markdown 작성 (또는 공개 PDF chunk 인용) | todo | 각 파일에 출처 URL + 발행일 명시 |
| KB-203 | JB 내부 기준 sample 8건 작성 (마케팅 콘텐츠 5 + 다국어 3) | todo | 데모용 sample, 실 운영 시 보안 검토 별도 |
| KB-204 | `cs-knowledge-ingest --document <file> --source-type internal_standard --merge` 배치 실행 | todo | 26+ chunk가 article로 변환되어 `data/laws.json`에 추가됨 |
| KB-205 | source_type="internal_standard" 일관 표기 | todo | 내부 기준 26+ 모두 internal_standard 라벨 |
| KB-206 | 외부 표준 6+ 추가 ingest (KIDI / 협회) | todo | 동일 — 단 source_type은 official_or_external (외부 발행) |

## Phase D — 검증

| ID | 작업 | 상태 | Acceptance Criteria |
|---|---|---|---|
| KB-301 | 회귀 테스트 추가: `test_kb_reaches_production_ready_threshold` | todo | article_count≥100, stale=0, unverified=0, production_ready=True |
| KB-302 | 회귀 테스트 추가: `test_kb_source_type_balance` | todo | official_or_external≥70, internal_standard≥20 |
| KB-303 | 회귀 테스트 추가: `test_all_articles_have_source_url` | todo | 모든 article의 source_url 비어있지 않음 |
| KB-304 | `pytest -q` 회귀 통과 | todo | 105 passed (기존 102 + 신규 3) |
| KB-305 | 샘플 실행: `cs-router run --content "..."` | todo | `pdf_requirement_alignment.law_currency_and_internal_standards_tracking.production_ready==True` |
| KB-306 | `docs/jb-pdf-compliance-scorecard.md` 업데이트 | todo | KB 100+ 도달 명시 + 시점 기록 |
| KB-307 | `handoff/delegation-board.md` 결과 요약 추가 (AGENTS.md L24) | todo | 작업 완료 요약 + Phase별 산출물 링크 |

## Deferred (본 spec 범위 외)

- 자동 갱신 cron / scheduled re-verification (180일 stale 자동 알림)
- 다국어 법령 번역본 ingest (영어/중국어/베트남어)
- Qdrant 인덱스 reindex (현재 BM25 fallback으로 충분)
- 신용정보법 시행령/시행규칙까지 확장 (P3, 별도 spec)

## Definition of Done

1. **AC 7건 모두 충족** (`spec/kb-ingest-100plus.md` §4)
2. **`pytest -q` 105 passed** + 기존 102 회귀 없음
3. **`coverage_report().production_ready == True` 실측** (data/laws.json에서 직접 로드)
4. **마케팅 샘플 실행 시 `pdf_requirement_alignment` 필드의 production_ready=True 노출**
5. **`docs/jb-pdf-compliance-scorecard.md` 업데이트 + `handoff/delegation-board.md` 요약 추가**
6. **모든 신규 article의 `source_url` 존재** (감사 추적성)
