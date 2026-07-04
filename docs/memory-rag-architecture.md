# Compliance Sentinel Memory + RAG Architecture

AI-research-SKILLs 기반으로 런타임에 연결된 장단기 메모리와 RAG 구조입니다.

## 적용한 스킬 패턴

- `AI-research-SKILLs/15-rag`: keyword fallback, optional Qdrant+BGE-M3 dense retrieval, RRF merge.
- `AI-research-SKILLs/28-agent-memory`: 요청 단위 short-term memory + `.cs-brain` long-term pattern recall.
- `AI-research-SKILLs/36-self-evolving-learning-system`: runtime outcome을 pending Brain pattern으로 캡처.

## 데이터 흐름

```text
input
  → PII redaction
  → short-term memory state 초기화
  → long-term Brain recall (.cs-brain/project_brain.yaml)
  → law RAG retrieval (keyword fallback or Qdrant+BGE-M3)
  → board/review/synthesis/verifier
  → final report + audit log
  → redacted outcome capture (.cs-brain/pending_patterns.yaml)
```

## 구현 파일

- `src/compliance_sentinel/memory_rag.py`: 통합 어댑터.
- `src/compliance_sentinel/knowledge_ingest.py`: 문서 자동 분류 → Skill/RAG/Memory 저장 파이프라인.
- `src/compliance_sentinel/skill_injection.py`: 내부 에이전트 system prompt skill 주입.
- `src/compliance_sentinel/models.py`: `short_term_memory`, `long_term_memory`, `rag_metadata` 상태 필드.
- `src/compliance_sentinel/workflow.py`: 일반 준법 분석 경로 연결.
- `src/compliance_sentinel/marketing_workflow.py`: readonly Brain 패턴을 마케팅 critical finding으로 승격.
- `src/compliance_sentinel/langgraph_adapter.py`, `marketing_langgraph_adapter.py`: LangGraph 선택 경로 연결.
- `src/compliance_sentinel/audit.py`, `reporting.py`: 감사/리포트 표면에 메모리와 RAG metadata 노출.
- `agents/skills/financial_marketing_content_reviewer/SKILL.md`: ingest된 경험 지식이 내부 에이전트에 주입되는 project skill.

## Koala 4-Memory 대응

| Koala 유형 | Compliance Sentinel 구현 | 운영 경계 |
|---|---|---|
| Working Memory | `ComplianceState.short_term_memory`, trace, 현재 요청 state | 요청 단위 휘발성 상태. audit에는 redacted metadata만 남깁니다. |
| Semantic Memory | `LawKnowledgeBase`, `data/knowledge_rag/*.jsonl`, optional Qdrant | 최종 근거의 SSOT. 법령/내부 기준 원문과 provenance를 우선합니다. |
| Procedural Memory | `agents/skills/**`, `skill_injection.py` | 역할별 심의 절차와 수정 원칙. 법령 판단을 대체하지 않습니다. |
| Episodic Memory | `.cs-brain/project_brain.yaml`, `.cs-brain/pending_patterns.yaml` | 반복 위반/실패 경험. pending→승인→merge 경로를 거쳐야 합니다. |

## Memory Governance Gate

`scripts/memory_governance_report.py`는 기존 메모리 시스템을 새 저장소로 확장하지 않고, 운영 가능한지 점검하는 read-only gate입니다.

```bash
PYTHONPATH=src python scripts/memory_governance_report.py --out reports/memory_governance.json
PYTHONPATH=src python scripts/memory_governance_report.py --fail-on-blockers
```

검사 항목:

- `.cs-brain` active/pending pattern의 필수 필드, readonly 정책, stale 여부
- prompt-injection 문구, raw PII, secret-like token 잔존 여부
- pending memory 승인 대기열과 `needs-approval` 상태
- Skill 파일 수, document RAG chunk 수, Koala 4-memory alignment metadata

`--strict-pending`을 주면 pending queue가 비어 있지 않은 상태도 blocker로 취급합니다. 기본 모드는 pending을 warning으로 보고하므로, 운영팀이 승인/반려 큐를 유지하면서도 critical blocker만 CI에서 차단할 수 있습니다.

## 운영 설정

- 기본은 offline-first keyword RAG입니다.
- Qdrant+BGE-M3 활성화:

```bash
pip install -e ".[rag]"
export QDRANT_URL="http://localhost:6333"
```

- runtime learning capture 비활성화:

```bash
export CS_MEMORY_CAPTURE=0
```

## 안전 원칙

- 장기 메모리 캡처에는 `redacted_text`만 사용합니다.
- readonly Brain pattern은 `cs_brain.merge()` 보호 정책을 유지합니다.
- 메모리/RAG 실패는 분석 실패로 전파하지 않고 trace metadata에 기록합니다.
- clean LOW/MEDIUM pass 결과는 기본적으로 학습 캡처하지 않아 pending Brain 비대를 줄입니다.
- 동일 outcome digest는 중복 캡처하지 않습니다.
- 문서 RAG JSONL은 mtime/size 기반 캐시로 반복 검색 비용을 낮춥니다.
