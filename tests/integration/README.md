# Integration Tests

> **외부 API/SDK가 실제로 동작하는지 검증**. 환경변수 없으면 자동 skip → CI default 안전.

## 구조

```
tests/
├── unit/              # 1160 tests, 86% cov, 외부 의존성 0
└── integration/       # 외부 API 실제 호출
    ├── conftest.py    # require_* fixture (env 게이트)
    ├── vcr_config.py  # cassette 공통 설정 + 보안 마스킹
    ├── test_llm_client_live.py   # OpenAI 실제 호출
    ├── test_llm_client_vcr.py    # cassette 기반 재생
    ├── test_qdrant_live.py       # Qdrant cluster 호출
    └── test_langsmith_live.py    # LangSmith run 기록
```

## 실행 모드

### Default (CI, 로컬 개발) — Unit만

```bash
pytest -m unit  # 또는 그냥 pytest (default)
# → 1160 passed, 86% cov, ~12초
# → integration test는 모두 skip
```

### Integration LIVE (수동, 비용 발생 가능)

```bash
# 1. 의존성 설치 (최초 1회)
pip install -e ".[test-integration]"

# 2. 환경변수 설정
export CS_ENABLE_LLM_RUNTIME=1     # LIVE 호출 안전 게이트 (필수)
export OPENAI_API_KEY=sk-...        # OpenAI 실제 호출
export QDRANT_URL=http://...        # (선택)
export LANGSMITH_API_KEY=ls-...     # (선택)

# 3. integration만 실행
pytest -m integration -v
```

### Integration VCR (cassette 재생, 비용 0)

```bash
# 최초 녹음 (사용자 명시 동의 시) — 1회만 비용 발생
CS_ENABLE_LLM_RUNTIME=1 OPENAI_API_KEY=sk-... \
  pytest tests/integration/test_llm_client_vcr.py --record-mode=once

# 이후 재생 (key/인터넷 불필요, 비용 0)
pytest tests/integration/test_llm_client_vcr.py
```

## 보안 정책

### API key 마스킹 (cassette)

`vcr_config.py`가 다음 헤더를 **자동 마스킹**:
- `Authorization` → `Bearer [REDACTED]`
- `api-key`, `x-api-key` → `[REDACTED]`
- `openai-organization`, `openai-project` → `[REDACTED]`

**cassette commit 전 의무 확인**:
```bash
grep -i "sk-\|Bearer " tests/integration/cassettes/*.yaml
# → 출력 0줄이어야 안전 (실제 key 포함 안 됨)
```

### LIVE 호출 안전 게이트

`CS_ENABLE_LLM_RUNTIME=1`이 명시되어야만 실제 호출. 실수로 비용 발생 방지:

```python
@pytest.fixture
def require_openai():
    if not _has_openai_key(): pytest.skip()
    if not _llm_runtime_enabled(): pytest.skip()  # 안전 게이트
```

## 비용 추정 (참고)

| Test | 모델 | 1회 비용 (USD) |
|---|---|---|
| `test_classifier_call_via_cassette` | gpt-5.4-nano | ~$0.0005 (최초 녹음만) |
| `test_basic_call_returns_text` | gpt-5.4-nano | ~$0.0005 (매 실행) |
| `test_response_structure_contract` | gpt-5.4-nano | ~$0.0005 |
| `test_record_run_no_raise` | LangSmith | $0 (run 기록만) |

VCR cassette 사용 시 **최초 녹음 1회 외 0원**.

## 회귀 감지 시나리오

Integration test가 잡아내는 것:
1. **SDK 업데이트로 응답 schema 변경** — `LLMCallResult.text` 추출 path 깨짐
2. **모델 ID 변경/제거** — `gpt-5.4-nano` 같은 모델 deprecated 감지
3. **provider 동작 차이** — OpenAI vs OpenRouter 응답 finish_reason 차이
4. **인증/네트워크 정책 변경** — API key 형식, rate limit 응답

Unit test로는 catch 불가능 — production에서야 발견되는 회귀 사전 차단.

## CI 통합 권장

```yaml
# .github/workflows/test.yml 예시
jobs:
  unit:
    steps:
      - run: pytest -m unit --cov  # 매 PR마다

  integration:
    if: github.event_name == 'schedule'  # nightly만
    steps:
      - run: pytest -m integration -v
        env:
          CS_ENABLE_LLM_RUNTIME: "1"
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

PR 검증은 unit만 (빠르고 무료), 비용 발생 가능한 integration은 nightly로 분리.
