# Traceability Matrix

| Requirement | Spec Section | Task IDs | Workflow Node | Eval Gate |
|---|---|---|---|---|
| 입력 분류 | FR-001 | T-202 | classify_input | demo-e2e |
| PII 탐지·마스킹 | FR-002 | T-203 | pii_guard | pii-redaction, pii-exfiltration |
| 법령/RAG 검색 | FR-003 | T-101, T-102, T-103, T-104, T-204 | retrieve_context | context-precision |
| 6인 보드 | FR-004 | T-205 | parallel_board_review | trace-visible |
| CEO 종합 판단 | FR-005 | T-206 | synthesize_opinion | demo-e2e |
| 원자적 검증 | FR-006 | T-105, T-207, T-208 | verify_atomic_claims, revise_opinion | citation-existence, citation-verbatim |
| 감사 로그 | FR-007 | T-302 | audit_log | audit-log-written |
| Human review | FR-008 | T-209 | human_review | overconfident-legal-advice |
| UI 시연 | AC-008 | T-301, T-405, T-406 | all | demo-e2e, trace-visible |
| Red-team | NFR Security | T-402 | all | fake-law-citation, prompt-injection-ignore-law |
| AgentCompiler spike | Phase 5 (deferred) | T-501, T-502, T-503 | optional backend | behavioral equivalence required |
| Request Router (5축 분류) | FR-009 | T-601~T-605 | router.classify → route | AC-009, AC-010, AC-011 (router 회귀 16 tests) |
| Model Router (4-tier) | FR-010 | T-701~T-706 | scripts/model_router.py | AC-012 (critical 시 codex 자동 부착) |
| Brain (자기진화) | FR-011 | T-801~T-807 | .cs-brain/ + capture/search/sync | AC-013, AC-014 (readonly 보호) |
| 다중에이전트 보드 강화 | FR-012 | T-702 + 기존 T-205 | board.py 강화 | trace-visible + brain_hits |
| RAG 인프라 | FR-013 | T-905, T-906 | retriever.py + law_open_api.py | context-precision, hybrid search |
| 관측성/보안/Eval | FR-014 | T-901~T-908 | 8-layer + LangSmith + DeepEval | AC-015 (L4 메타 보호) + eval-gates |

## Coverage Summary

- Functional requirements covered: 15/15 (FR-001~FR-015; FR-015 AgentCompiler는 deferred 명시)
- Acceptance criteria covered: 15/15 (AC-001~AC-015)
- Security/eval gates covered: yes
- Agent team owner assigned: yes
- Implementation blockers: 법령정보센터 API 인증값, Anthropic/Codex API 키, Qdrant cloud account, 실제 JB 자료 접근권한
- Phase 6-9 (Self-Evolving Infra) 진입 게이트: 사용자 phase별 명시 승인
