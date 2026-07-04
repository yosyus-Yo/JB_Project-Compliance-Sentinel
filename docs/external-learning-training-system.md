# External Learning + Agent Training System

`JB_Project-Compliance-Sentinel`의 학습된 패턴/지식을 외부 학습 환경에서 정제·훈련·평가한 뒤 안전하게 다시 주입하는 시스템입니다.

## 왜 외부에서 학습하는가

금융 준법 시스템은 운영 중 판단 기준이 자동으로 바뀌면 안 됩니다. 따라서 운영 시스템은 안정적으로 심의하고, 학습/훈련은 외부에서 수행한 뒤 결과만 candidate로 되가져옵니다.

```text
JB runtime artifacts
  → sanitized export
External Learning Lab / Agent Training
  → candidate JSONL
JB import gate
  → candidate archive
  → approved staging only
  → tests / holdout / human approval
```

## CLI

### 1. Export

```bash
PYTHONPATH=src python -m compliance_sentinel.learning_lab export --out training/exports/run-001 --json
```

생성 파일:

- `brain_patterns.jsonl`
- `pending_patterns.jsonl`
- `skill_notes.jsonl`
- `rag_chunks.jsonl`
- `eval_cases.jsonl`
- `agent_training_tasks.jsonl`
- `program.md`
- `manifest.json`

### 2. External training/evaluation

외부 환경에서 AI-research-SKILLs의 `29-agent-training`, `36-self-evolving-learning-system` 패턴을 사용합니다.

- Agent Lightning/GRPO: `agent_training_tasks.jsonl` 소비
- Self-evolving evaluation: Brain/Skill/RAG 후보 정제
- Contradiction/staleness check: 후보 반려 사유 생성

### 3. Candidate import

```bash
PYTHONPATH=src python -m compliance_sentinel.learning_lab import-candidates candidates.jsonl --json
```

승인된 후보만 staging:

```bash
PYTHONPATH=src python -m compliance_sentinel.learning_lab import-candidates candidates.jsonl --stage-approved --min-score 0.75
```

## Candidate schema

```json
{"id":"CAND-001","target":"memory","text":"JB우리캐피탈 자동차 할부 광고의 '무심사'는 critical 후보로 본다.","source":"agent-lightning-run-001","approved":true,"score":0.91,"readonly":true,"evidence":["eval:jb-capital-no-screening"]}
```

## Safety gates

- Export는 redacted text와 raw hash만 포함합니다.
- Import는 `target`, `text`, `score`를 검증합니다.
- 기본 import는 candidate archive에만 저장합니다.
- `--stage-approved`도 approved + min-score 통과 후보만 staging합니다.
- Memory 후보는 `.cs-brain/pending_patterns.yaml`로만 들어가며, `cs-brain merge` 보호 정책을 거칩니다.
- Skill/RAG 후보는 project-local 파일에 staging되며 tests/holdout 검증 후 커밋해야 합니다.

## 운영 권장

1. 주간 export 생성
2. 외부 학습 랩에서 후보 생성
3. candidate import
4. holdout eval + regression test
5. 승인 후보만 stage
6. `pytest`, `cs-brain status`, 수동 리뷰
7. 커밋/배포
