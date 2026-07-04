# 제출 전 완성도 체크리스트

> 목적: JB금융그룹 Fin:AI Challenge 예선 제출물(MVP 제안서/기능명세서)과 실제 MVP 동작 간 정합성을 점검한다. 시연영상 제작 항목은 제외한다.

## 완료 보강

- `final_report`가 기능명세서 예시 JSON에 맞춰 `evidence`와 `verifier_result` top-level 필드를 노출한다.
- `confidence` 등급과 별도로 수치형 `confidence_score`를 노출한다.
- `review_request_id`, `input_completeness`, `schema_validation`을 노출해 F1 접수/contract 정합성을 확인할 수 있다.
- 캐피탈/자동차 할부/승인/대출성 문구는 금리 표현이 함께 있어도 `loan` 계열로 우선 분류한다.
- 혼합 다국어 문구의 동일 위험군 표현도 첫 번째 매칭에서 멈추지 않고 각각 finding으로 남긴다.
  - 예: `zero risk`, `không rủi ro`, `零风险`, `guaranteed`.
- Runtime guard가 prompt injection, secret-like token, non-allowlisted URL을 실시간 심의 경로에서 finding/flag로 남긴다.
- 일반 준법 workflow도 v3 final_report contract를 통과한다. 가짜 법령 인용 Case C도 `schema_validation.passed=true`를 반환한다.
- Slack/Notion/Jira payload contract를 모두 생성한다. Jira는 live 전송이 아니라 P2 업무 연계용 schema-stable mock payload다.

## 제출 문구에서 과장 금지

- 법령/내부 기준 지식은 `Local KB + 법령 Open API 연동 구조 + 공식 본문 일부 + 검증된 내부 심의 적용요약`으로 표현한다.
- `production_ready=true`, placeholder/unverified 0건은 말해도 되지만, 90건은 공식 법령 원문이 아니라 내부 적용요약임을 분리 표기한다.
- Slack은 opt-in live webhook이 가능하지만, Notion/Jira/사내포털은 payload/연계 계약 수준으로 표기한다.
- Qdrant/LangGraph/LangSmith/AgentCompiler는 기본 실행 경로가 아니라 opt-in 또는 본선 고도화 경로로 표기한다.

## 제출 직전 필수 확인

1. MVP 제안서 PDF와 기능명세서 PDF의 데모 케이스가 실제 코드 출력과 일치하는지 확인한다.
   - 특히 캐피탈 `100% 승인` Case A는 현재 코드 기준 `CRITICAL / REJECTED`가 정직한 출력이다.
   - PDF 재생성 전 `docs/pdf-submission-errata.md`를 반영한다.
2. `final_report` 필수 노출 항목을 샘플 입력으로 확인한다.
   - `approval_status`, `risk_level`, `confidence`, `confidence_score`, `findings`, `evidence`, `revision_suggestions`, `board_diagnostics`, `verifier_result`, `review_request_id`, `input_completeness`, `schema_validation`, `audit_log_id`.
3. v3 최종 데모 명령을 실행한다.
   - `PYTHONIOENCODING=utf-8 PYTHONPATH=src python scripts/run_demo.py --v3-final`
   - A/B/C 모두 `schema=True`, `request=RR-...`, `audit=AUD-...`가 보여야 한다.
4. 테스트 전체를 통과시킨 뒤 제출한다.
5. 최종 제출 후 수정 불가이므로, 팀장 계정/제출 버튼/파일명/업로드 파일을 별도 체크한다.

## 남은 본선 고도화 후보

- 법령정보센터 API 기반 공식 조문 본문 확대 수집.
- Notion/Jira/사내 포털 live publish 구현.
- 입력 폼에서 언어/채널/상품/타깃 필수값을 UI 필수 선택값으로 강화.
- 외부 `jsonschema` 라이브러리 기반 contract validation을 CI에 추가.
- Runtime guard를 AgentShield 정책/CI SARIF와 연결.
