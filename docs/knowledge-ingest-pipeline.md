# Knowledge Ingest Pipeline: Skill + RAG + Memory

문서가 들어오면 금융 마케팅 콘텐츠 심의관 경험 지식을 자동 분류해 적절한 저장소로 보냅니다.

## 저장소 분리

| 분류 | 저장 위치 | 용도 |
|---|---|---|
| Skill | `agents/skills/financial_marketing_content_reviewer/SKILL.md` | 내부 에이전트 system prompt에 주입되는 절차/체크리스트/수정 원칙 |
| RAG | `data/knowledge_rag/financial_marketing_corpus.jsonl` | 법령, 내부 기준, 상품설명서, 필수 고지 등 원문 근거 검색 |
| Memory | `.cs-brain/pending_patterns.yaml` | 반복 사례, 과거 판정, JB 특화 경험 패턴. 기본은 승인 대기 |

## 예시 문서

전문가 지식 업로드 동작 검증용 샘플은 다음 위치에 있습니다.

```text
docs/examples/expert-knowledge-upload-example.md
```

이 예시는 하나의 문서가 동시에 다음 대상으로 분배되는지 확인합니다.

- Skill: 심의관 절차 체크리스트/수정 원칙
- RAG: 내부 기준 원문/필수 고지/위험 표현 근거
- Memory: 반복 반려 사례/readonly 승격 후보

## CLI

기본은 dry-run입니다.

```bash
PYTHONPATH=src python -m compliance_sentinel.knowledge_ingest docs/examples/expert-knowledge-upload-example.md --json
```

실제 저장:

```bash
PYTHONPATH=src python -m compliance_sentinel.knowledge_ingest docs/examples/expert-knowledge-upload-example.md --apply
```

준법/법무 승인된 경험 패턴으로 staging:

```bash
PYTHONPATH=src python -m compliance_sentinel.knowledge_ingest docs/examples/expert-knowledge-upload-example.md --apply --approve-memory
```

`--approve-memory`도 곧바로 `project_brain.yaml`에 병합하지 않습니다. `.cs-brain/pending_patterns.yaml`에 readonly 후보로 들어가며, `cs-brain merge` 단계에서 기존 readonly 보호 규칙을 유지합니다.

## 안전 게이트

- 저장 전 PII는 `pii.py`로 redaction합니다.
- API key, token, private key 형태의 secret-like 문자열이 있으면 해당 chunk는 저장하지 않습니다.
- Skill은 에이전트 행동 지침으로만 사용하고, 법령 원문은 RAG 근거로 확인합니다.
- Memory는 기본적으로 `needs-approval` 태그가 붙은 pending pattern으로 저장됩니다.

## 독립 훈련 결과 통합

LLM 모델 파인튜닝 없이 샌드박스/교사-학생 루프에서 나온 결과를 같은 저장소로 통합할 수 있습니다.

### Local-only peer training lab

Pi-to-Pi 방식은 운영 판단 경로가 아니라 **훈련/검증 랩**에서만 사용합니다. 랩 scaffold를 만들면 teacher/student/verifier/curator 프롬프트와 outputs 템플릿이 생성됩니다.

```bash
PYTHONPATH=src python -m compliance_sentinel.learning_lab create-peer-lab \
  --run-id peer-auto-loan-001 \
  --topic "자동차 할부 광고 교사-학생 검증" \
  --json
```

생성된 구조:

```text
training/peer-labs/<run-id>/
  manifest.json              # local-only, production_decision_path=false
  README.md                  # 실행/통합 가이드
  prompts/teacher.md
  prompts/student.md
  prompts/verifier.md
  prompts/curator.md
  outputs/candidates.jsonl   # 구조화 Skill/RAG/Memory 후보
  outputs/expert-summary.md  # 전문가 문서형 요약
```

peer lab 결과 통합:

```bash
PYTHONPATH=src python -m compliance_sentinel.learning_lab integrate-peer-lab \
  training/peer-labs/peer-auto-loan-001 \
  --stage-approved \
  --merge-patterns \
  --min-score 0.75 \
  --json
```

중요 경계:

- peer lab은 `production_decision_path=false`입니다.
- 네트워크 peer/coms-net은 기본 비활성 전제로 둡니다.
- peer 대화 결과는 `outputs/` 파일로만 남기고, 운영 저장소에는 `learning_lab` 통합 명령으로만 들어갑니다.
- memory는 먼저 pending에 들어가며, `--merge-patterns` 명시 시에만 Brain으로 통합됩니다.

### Training artifact inputs

지원 입력:

- `.jsonl` / `.json`: `target`, `text`, `approved`, `score`가 있는 구조화 후보
- `.md` / `.txt`: 전문가 지식 문서처럼 작성된 요약 문서

구조화 후보 예시는 다음 위치에 있습니다.

```text
docs/examples/teacher-student-training-candidates.jsonl
```

후보를 archive만 하고 운영 저장소에는 쓰지 않는 기본 모드:

```bash
PYTHONPATH=src python -m compliance_sentinel.learning_lab integrate-results docs/examples/teacher-student-training-candidates.jsonl --json
```

승인된 후보만 Skill/RAG/Memory pending에 staging:

```bash
PYTHONPATH=src python -m compliance_sentinel.learning_lab integrate-results docs/examples/teacher-student-training-candidates.jsonl --stage-approved --min-score 0.75 --json
```

staging된 memory 후보를 기존 Brain 학습 패턴에 병합:

```bash
PYTHONPATH=src python -m compliance_sentinel.learning_lab integrate-results docs/examples/teacher-student-training-candidates.jsonl --stage-approved --merge-patterns --min-score 0.75 --json
```

안전 규칙:

- `approved=true`이고 `score >= --min-score`인 후보만 staging합니다.
- Skill/RAG는 id 기반 upsert로 중복을 방지합니다.
- Memory는 `.cs-brain/pending_patterns.yaml`에 먼저 들어가고, `--merge-patterns`를 명시해야 기존 Brain으로 통합됩니다.
- `cs_brain.merge()`의 readonly 보호/중복 context 규칙을 그대로 사용합니다.
- secret-like token 또는 prompt-injection 문구가 있는 후보는 reject합니다.

## Runtime 연결

- `llm_client.load_system_prompt()`가 role에 맞는 project skill을 자동 주입합니다.
- `memory_rag.retrieve_context()`가 ingested document RAG chunk를 short-term memory metadata로 회수합니다.
- 마케팅 심의 agent는 문서 RAG chunk가 현재 문구와 같은 위험 표현을 명시할 때 `RAG_SOURCE_GUIDANCE_MATCH` finding 후보를 추가합니다.
- `ComplianceMemoryRAG.capture_outcome()`은 분석 결과를 redacted 상태로 Brain pending에 캡처합니다.

## 병목/간섭 방지

- `data/knowledge_rag/*.jsonl` 검색은 파일 mtime/size 기반 캐시를 사용합니다.
- clean LOW/MEDIUM 통과 결과는 기본적으로 memory capture하지 않습니다. 필요 시 `CS_MEMORY_CAPTURE_LOW_RISK=1`로 확장합니다.
- 동일 outcome digest가 pending에 이미 있으면 중복 capture를 건너뜁니다.
- Skill 주입은 `CS_ENABLE_SKILL_INJECTION=0`, memory capture는 `CS_MEMORY_CAPTURE=0`으로 각각 비활성화할 수 있습니다.
