# PDF 지정주제 2 최적화 계획

목표: `[데이콘] JB금융그룹 Fin AI Challenge 상세주제 안내.pdf`의 지정주제 2 Compliance AI 요구에 가장 직접 대응하는 순서로 운영 갭을 줄인다.

## 우선순위

1. **KB/법령/내부 기준 100+ 확장**
   - 이유: PDF의 “최신 금융규제와 내부 기준 자동 추적”에 가장 직접 대응.
   - 현재: `data/laws.json` baseline + `law_open_api.py` + Qdrant adapter + document ingest.
   - 보강: `kb_coverage.article_count`, source type, freshness, `status_verified`, production readiness를 runtime report에 노출.
   - 운영 완료 기준: 100+ official/internal articles, stale/unverified 0, Qdrant 또는 API fetch 계약 테스트.

2. **콘텐츠 심의 품질 강화**
   - 이유: “위반 가능성, 표현 리스크, 자동 수정안”에 직접 대응.
   - 보강: claim taxonomy summary를 최종 report에 노출하고 non-puffery claim은 substantiation 필요로 표시.

3. **승인 workflow 실제화**
   - 이유: “마케팅 및 제작 프로세스 자동 연계”에 직접 대응.
   - 보강: Slack/Notion payload에 `publish_plan`을 추가하여 mock/live optional 상태, route, required env를 명시.

4. **Error Cascade 방어**
   - 이유: 심의 품질 편차와 휴먼에러 축소의 운영 안정성 보강.
   - 다음 작업: board contradiction detection, minority report, high-disagreement verifier escalation.

5. **MCP/API 표준화**
   - 이유: 외부 에이전트/업무 시스템 연계 표준화.
   - 선행 조건: internal API contract(`compliance_review`, `kb_search`, `audit_log`) 안정화.

## Acceptance Criteria

- AC-PDF-001: marketing final report에 `pdf_requirement_alignment`가 포함된다.
- AC-PDF-002: RAG metadata에 `kb_coverage`와 retrieved law provenance가 포함된다.
- AC-PDF-003: report에 `claim_taxonomy_summary`가 포함되고, 실증 필요 claim이 구분된다.
- AC-PDF-004: Slack/Notion payload에 `publish_plan`이 포함된다.
- AC-PDF-005: 기존 deterministic demo/test가 깨지지 않는다.
