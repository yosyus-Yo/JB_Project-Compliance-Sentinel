# AGENTS.md — JB_Project 작업 규칙

## 공통 원칙

- 항상 spec-first로 작업한다: `spec/spec.md` → `spec/plan.md` → `spec/tasks.md` 순서로 확인한다.
- 법령/보안/PII 관련 주장은 반드시 근거와 검증 수준을 남긴다.
- 실제 개인정보, API key, secret을 저장소에 커밋하지 않는다.
- 법률 자문 대체 표현을 금지한다. 준법 검토 보조/리스크 탐지로 표현한다.
- AgentCompiler는 MVP 통과 전 핵심 경로에 넣지 않는다.

## 작업 시작 체크리스트

1. `spec/tasks.md`에서 task ID 확인
2. `handoff/delegation-board.md`에서 owner와 acceptance criteria 확인
3. 관련 공식 reference 확인
4. 테스트/검증 방법 먼저 작성
5. 구현 후 evidence 기록

## 완료 선언 조건

- task acceptance criteria 충족
- 관련 test/eval 통과
- verifier/citation/PII/audit 관련 변경이면 failure case도 확인
- `handoff/delegation-board.md`에 결과 요약 추가

## 금지

- 법령 인용을 LLM 기억으로만 생성
- PII 원문을 LLM에 직접 전달
- 쓰기 권한 있는 금융/거래 도구 연결
- 검증 실패를 성공처럼 보고
- simulated 성능 수치를 실측처럼 표현
