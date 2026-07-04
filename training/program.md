# Compliance Sentinel External Learning Program

이 파일은 AI-research-SKILLs의 self-evolving / agent-training 계열을 외부 실험실에서 사용할 때의 기본 지시서입니다.

## 원칙

- 운영 시스템을 직접 수정하지 않습니다.
- 외부 학습 결과는 `candidate JSONL`로만 반환합니다.
- `approved=false`가 기본이며, 승인된 candidate도 import 시 staging만 수행합니다.
- Memory는 직접 `project_brain.yaml`에 쓰지 않고 `.cs-brain/pending_patterns.yaml`로만 보냅니다.
- 원문 PII, credentials, 고객 식별자는 외부 학습 데이터에 포함하지 않습니다.

## 권장 루프

```text
cs-learning-lab export
→ 외부 학습/평가/정제
→ candidates.jsonl 생성
→ cs-learning-lab import-candidates
→ holdout/regression 검증
→ --stage-approved로 승인 후보만 주입
```

## Candidate JSONL 형식

```json
{"id":"CAND-001","target":"skill","text":"대출 광고에서 승인 보장 표현은 critical 후보로 본다.","source":"external-lab","approved":false,"score":0.84,"evidence":["eval:jb-capital-no-screening"]}
```

- `target`: `skill` | `rag` | `memory`
- `score`: 0.0~1.0
- `approved`: 운영 반영 승인 여부
- `evidence`: 평가 케이스, 로그 digest, 근거 문서 ID

## Agent-training 보상 설계

`agent_training_tasks.jsonl`의 `reward_spec`를 사용합니다.

- expected flag 탐지
- approval/human review routing 일치
- PII 미유출
- verifier/disclaimer 유지

훈련된 agent/model은 운영에 직접 연결하지 말고, 먼저 후보 Skill/RAG/Memory 개선안만 제출해야 합니다.
