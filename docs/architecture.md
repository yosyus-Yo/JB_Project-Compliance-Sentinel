# Architecture — Compliance Sentinel

## 1. 핵심 구조

Compliance Sentinel은 `판단 → 행동 → 검증 → 감사` 파이프라인을 가진 agentic workflow입니다.

```text
Input
  → PII Guard
  → RAG / Law Retrieval
  → 6-Agent Compliance Board
  → CEO Synthesizer
  → Atomic Claim Verifier
  → Revision Loop or Human Review
  → Final Report
  → Audit Log
```

## 2. 6인 컴플라이언스 보드

| Agent | 관점 | 주요 질문 | 보강된 지침 소스 |
|---|---|---|---|
| Legal Counsel | 전자금융/계약/금소법 | 이 조항은 어떤 법령과 충돌하는가? | role-specific prompt + `agents/skills/compliance_board_personas/legal_counsel.md` |
| PIPA Expert | 개인정보/신용정보 | 동의, 보유기간, 제3자 제공이 적법한가? | role-specific prompt + `agents/skills/compliance_board_personas/pipa_credit_info.md` |
| Consumer Protection | 설명의무/광고/약관 | 소비자 오인·불공정 조항이 있는가? | role-specific prompt + `agents/skills/compliance_board_personas/consumer_protection.md` |
| AML/Operational Risk | AML/CFT/운영리스크 | 이상 거래/내부통제 리스크가 있는가? | role-specific prompt + `agents/skills/compliance_board_personas/operational_risk.md` |
| Business Practicality | 실무 적용성 | 과잉 해석인가, 실제 업무에 적용 가능한가? | role-specific prompt + `agents/skills/compliance_board_personas/business_practicality.md` |
| Contrarian | 반대 의견 | 이 위반 판단이 틀렸을 가능성은? | role-specific prompt + `agents/skills/compliance_board_personas/contrarian.md` |

6개 보드 persona는 `agency-agents`의 전문 에이전트 원칙(역할, mission, critical rules, deliverables)과 `AI-research-SKILLs`의 agent/prompt/RAG/safety/evaluation 원칙을 반영해 개별 prompt profile로 렌더링됩니다. live LLM advisory를 켠 경우에도 6개 보드 persona가 모두 호출되며, 기본 deterministic mode에서는 같은 role coverage를 fallback trace로 남깁니다.

## 3. 검증자 루프

Verifier는 CEO가 만든 판단을 다음 클레임으로 분해합니다.

```text
Claim 1: 법령명과 조항이 존재하는가?
Claim 2: 인용문이 원문과 일치하는가?
Claim 3: 입력 문장에 해당 조항을 적용하는 논리가 타당한가?
Claim 4: 시행일/최신성이 맞는가?
Claim 5: 해당 금융업무 범위에 적용되는가?
```

검증 결과가 실패하면 CEO Synthesizer로 피드백을 보내고 최대 3회 수정합니다.

## 4. 보안/권한 모델

- 모든 외부 tool은 read-only를 기본값으로 한다.
- `write_audit_log`만 append-only write를 허용한다.
- LLM 입력에는 `redacted_text`만 사용한다.
- 고위험 결론은 human review interrupt를 거친다.
- 법률 자문 대체가 아닌 준법 검토 보조 문구를 최종 보고서에 포함한다.

## 5. RAG 설계

법령 검색은 keyword exact matching과 semantic matching이 모두 필요합니다.

- 조문 번호/법령명: sparse/BM25 또는 metadata filter
- 의미상 유사한 조항: dense embedding
- 최종 정렬: hybrid score + reranker
- verifier: 반드시 원문 조회 API 또는 로컬 canonical text로 검증

## 6. LangGraph / AgentCompiler 위치

`engine.py`가 실행 엔진을 선택합니다. `USE_LANGGRAPH=1`이고 `langgraph`가 설치된 환경에서는 LangGraph StateGraph를 primary path로 사용하고, 미설치/실패 시 deterministic `workflow.py` baseline으로 fallback합니다. 이 구조는 Pi-style verifier/security 패턴을 LangGraph node/tool/state 안에 유지해 향후 AgentCompiler가 전체 워크플로를 볼 수 있게 하기 위한 준비 단계입니다.

AgentCompiler는 다음 조건을 만족하면 추가합니다.

1. baseline workflow가 안정적으로 동작
2. 6인 보드가 latency/cost 병목으로 확인
3. AgentCompiler output이 behavioral equivalence를 통과
4. 실측 성능 개선이 충분함

즉, AgentCompiler는 **제품 정체성**이 아니라 **추론 최적화 레이어**입니다.
