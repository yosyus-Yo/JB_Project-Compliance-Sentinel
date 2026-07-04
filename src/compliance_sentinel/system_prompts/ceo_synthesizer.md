# CEO Synthesizer System Prompt (alias for builder.md)

본 파일은 `builder.md`와 동일한 역할을 한다 — CEO Synthesizer = Builder/Primary Synthesizer. 별칭 유지 목적.

상세 내용은 [builder.md](builder.md) 참조.

## 모델 강제 (LP-CS-030 Hard Pin)

CEO Synthesizer는 비critical에서는 **standard tier (`CS_MODEL_STANDARD=gpt-5.4-mini`)**, critical에서는 **critical tier (`CS_MODEL_DEEP=gpt-5.5`)**로 호출된다. 검증/비평 역할은 별도 컨텍스트의 `CS_MODEL_CRITIC=gpt-5.5` 경로가 담당한다.

Quality-first runtime routing escalates CEO synthesis and validation roles to
`gpt-5.5` as soon as deterministic review reveals HIGH or CRITICAL risk, even
when the initial raw-input route started on standard tier. Classifier and
documenter remain on `gpt-5.4-nano`; board drafting remains on `gpt-5.4-mini`.

`agent_model_guard.py`가 런타임에 본 제약을 강제한다. 환경변수 `CS_BYPASS_MODEL_GUARD=1`로 일시 우회 가능하나, 운영 환경에서는 절대 금지.
