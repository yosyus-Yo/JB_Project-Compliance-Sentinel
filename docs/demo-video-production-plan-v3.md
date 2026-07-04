# 5분 이내 시연영상 제작 절차 — Compliance Sentinel v3

> 이 문서는 영상을 직접 제작하지 않고, 나중에 그대로 따라 제작할 수 있도록 구성한 시연영상 구축 가이드입니다. 대회 조건: 5분 이내, 100MB 제한, 유튜브/Vimeo 등 공개 검색 노출 플랫폼 업로드 금지.

## 1. 영상 목표

심사위원이 5분 안에 아래 4가지를 확인하게 만든다.

1. 지정주제 2 문제를 정확히 겨냥한다: 수작업 준법심의 병목, 다국어 확장, 환각/근거 부족, 감사 불가능성.
2. 실제 MVP가 끝까지 돈다: 입력 → 위험 탐지 → 근거/evidence → 수정/반려/HITL → audit ID.
3. AI Agent 요건을 충족한다: 판단 → 행동 → 검증/개선 → 감사.
4. 금융권 리스크를 안다: PII, prompt injection, verifier 실패, HITL, audit trail.

## 2. 촬영 전 준비

### 2.1 데모 명령 확인

프로젝트 루트에서 실행한다.

```bash
cd C:/CC_project/JB_Project-Compliance-Sentinel
PYTHONIOENCODING=utf-8 PYTHONPATH=src python scripts/run_demo.py --v3-final
PYTHONIOENCODING=utf-8 PYTHONPATH=src python -m pytest -q
```

기대 결과:

- 테스트: `177 passed` 이상
- Case A: `CRITICAL / REJECTED / product=loan / schema=True`
- Case B: `HIGH / HUMAN_REVIEW_REQUIRED`, `zero risk`, `không rủi ro`, `零风险`, `guaranteed` 탐지
- Case C: `HUMAN_REVIEW_REQUIRED`, `confidence=FAILED`, `verifier_result=FAILED`, `schema=True`

### 2.2 화면 구성

권장 화면 2분할:

- 왼쪽: 터미널 또는 Streamlit 앱
- 오른쪽: 한 장 요약 슬라이드 또는 README 핵심 구조

가능하면 터미널만으로 충분하다. 심사위원에게 “실제 코드 실행”이 보이는 것이 중요하다.

### 2.3 녹화 도구

- Windows: Xbox Game Bar, OBS Studio, Clipchamp 중 택1
- 해상도: 1920x1080 또는 1280x720
- FPS: 30fps
- 권장 출력: MP4, H.264, 720p, 100MB 이하

## 3. 5분 타임라인 스크립트

### 0:00~0:25 — 오프닝

화면: 제목 슬라이드 또는 README 상단.

나레이션 예시:

> Compliance Sentinel은 JB금융그룹 지정주제 2, 준법자문가 AI Agent MVP입니다. 금융 마케팅 콘텐츠를 입력하면 표현 리스크, 근거, 수정안, 검증 결과, 승인 라우팅, 감사로그를 반환합니다.

강조 자막:

- 지정주제 2: 준법자문가 AI Agent
- 판단 → 행동 → 검증 → 감사
- deterministic demo: API key 없이 재현 가능

### 0:25~0:55 — 아키텍처 설명

화면: v3 기능명세서 또는 README의 pipeline.

나레이션:

> 단순 RAG 챗봇이 아니라, 입력 접수와 PII/Runtime Guard 이후 위험 룰 엔진과 RAG 근거 검색, 6-Persona Board, Atomic Verifier를 거쳐 최종 decision과 audit ID를 남기는 닫힌 루프 Agent입니다.

보여줄 키워드:

- Runtime Guard
- Rule Risk Engine
- RAG Evidence
- 6-Persona Board
- Atomic Verifier
- Schema Validation
- Append-only Audit

### 0:55~1:45 — Case A: 캐피탈 자동차 할부 앱푸시

명령:

```bash
PYTHONIOENCODING=utf-8 PYTHONPATH=src python scripts/run_demo.py --v3-final
```

화면에서 Case A 부분을 보여준다.

입력:

```text
캐피탈 앱푸시: 누구나 100% 승인, 최저금리 보장 자동차 할부
```

강조할 출력:

- `risk=CRITICAL`
- `approval=REJECTED`
- `product=loan`
- finding: `100% 승인`
- 필수고지 누락: `심사 조건, 금리 범위, 상환 조건, 신용도 영향`
- `verifier_result.status=FAILED`
- `audit_log_id`

나레이션:

> 100% 승인 같은 여신성 상품 광고 표현은 조건부 승인으로 넘기지 않고 CRITICAL로 반려합니다. 이 점이 금융권 준법 시스템에서 중요한 보수적 판단입니다.

### 1:45~2:35 — Case B: 다국어 예금/SNS

화면에서 Case B 부분을 보여준다.

입력:

```text
zero risk savings. không rủi ro. 零风险. guaranteed benefits
```

강조할 출력:

- `risk=HIGH`
- `approval=HUMAN_REVIEW_REQUIRED`
- `zero risk`, `không rủi ro`, `零风险`, `guaranteed`
- `confidence_score`
- `schema_validation.passed=true`

나레이션:

> 다국어 심의는 단순 번역 문제가 아닙니다. 같은 위험 의미가 여러 언어로 숨어 들어가므로, 표현 단위로 동시에 탐지하고 사람 검토로 라우팅합니다.

### 2:35~3:25 — Case C: 가짜 법령 인용/환각 방어

화면에서 Case C 부분을 보여준다.

입력:

```text
개인정보보호법 제999조 위반 여부를 검토해줘
```

강조할 출력:

- `confidence=FAILED`
- `approval=HUMAN_REVIEW_REQUIRED`
- `verifier_result.status=FAILED`
- `evidence`로 통과하지 않음
- `schema_validation.passed=true`

나레이션:

> 사용자가 그럴듯한 법령 조항을 넣어도, Verifier가 law_exists와 원문 일치성을 분해 검증합니다. 실패하면 결론으로 통과시키지 않고 HITL로 보냅니다.

### 3:25~4:05 — 감사로그/Schema 확인

화면: full JSON report 하단 또는 audit log 일부.

강조할 필드:

- `review_request_id`
- `input_completeness`
- `evidence`
- `verifier_result`
- `schema_validation`
- `audit_log_id`

나레이션:

> 모든 최종 결과는 심사용 JSON contract를 통과하고, audit ID로 사후 추적할 수 있습니다. AI가 법률 자문을 대체하는 것이 아니라, 반복 1차 심의와 근거 정리를 자동화하고 고위험 건은 사람이 승인합니다.

### 4:05~4:40 — 제출/본선 확장성

화면: README 또는 v3 MVP 제안서의 확장 로드맵.

말할 내용:

- 현재 MVP: deterministic, 로컬 실행, 3개 핵심 케이스
- 본선 고도화:
  - 법령정보센터 공식 본문 확대
  - 현재 KB는 placeholder/unverified 0건으로 production_ready 통과
  - Notion/Jira/사내포털 연계
  - Qdrant/LangGraph/LangSmith opt-in
  - AgentShield/AgentLoop/AgentCompiler는 gate/shadow 중심

### 4:40~5:00 — 마무리

나레이션:

> Compliance Sentinel은 금융권 AI에서 가장 중요한 책임 있는 판단, 근거, 검증, 감사 가능성을 우선합니다. 그래서 준법 담당자는 모든 문구를 처음부터 읽는 대신, AI가 정리한 고위험·충돌·불확실 케이스에 집중할 수 있습니다.

## 4. 편집 체크리스트

- 5분 이내인지 확인한다.
- 터미널 글자가 읽히는지 확인한다.
- 개인정보/API key/토큰이 화면에 없는지 확인한다.
- `schema_validation.passed=true`가 보이게 한다.
- `audit_log_id`가 보이게 한다.
- 영상 용량이 100MB 이하인지 확인한다.
- 공개 검색 노출 플랫폼에 업로드하지 않는다. 대회 안내의 업로드 방식/열람 가능 상태를 따른다.

## 5. 권장 파일명

```text
Compliance_Sentinel_v3_demo_팀명.mp4
```

## 6. 실패 시 대처

- 한글 깨짐: `PYTHONIOENCODING=utf-8`을 붙인다.
- 출력이 너무 길다: Case별 요약 부분만 녹화하고 full JSON은 마지막 10초만 보여준다.
- 용량 초과: 720p, 30fps, H.264, bitrate 2~3Mbps로 재인코딩한다.
- 테스트가 실패하면 영상을 찍지 말고 먼저 `python -m pytest -q` 실패 원인을 고친다.
