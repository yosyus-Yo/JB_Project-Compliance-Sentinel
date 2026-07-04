# legalize-kr Optional Mirror Decision

## 결론

`legalize-kr/legalize-kr`는 Compliance Sentinel의 핵심 runtime 의존성이 아니라 **선택적 offline mirror**로만 둔다.

- 공식 source of truth: `law.go.kr` / 국가법령정보센터 Open API
- 기본 재현 경로: `data/laws.json` + `data/jb_terms.json`
- optional 보강: legalize-kr clone/sparse checkout을 통한 offline grep, 개정 이력 diff, API 장애 시 fallback

## PDF 지정주제 2와의 관계

| PDF 요구 | 법제처 Open API | legalize-kr |
|---|---|---|
| 최신 금융규제 자동 추적 | 공식 본문 fetch에 직접 부합 | Git history/diff 보조에 유용 |
| 규제 문서 검색·근거 제공 | citation source로 적합 | 대량 markdown search corpus로 적합 |
| 준법 workflow | 간접 기여 | 간접 기여 |
| 마케팅 프로세스 연계 | 직접 관련 낮음 | 직접 관련 낮음 |

## 왜 필수 의존성으로 넣지 않는가

1. README가 force-push 가능성을 명시하므로 commit hash를 영구 citation으로 쓰기 어렵다.
2. 전체 법령 clone/ingest는 대회 MVP 범위 대비 과도하다.
3. 공식 근거는 법제처 API URL과 조문 원문이어야 한다.
4. 현재 프로젝트는 deterministic local KB와 API fallback 구조를 이미 갖고 있다.

## 권장 사용 방식

```text
Tier 1: curated local KB
  data/laws.json + data/jb_terms.json

Tier 2: official law.go.kr API
  LAW_OPEN_API_KEY로 핵심 조문 본문 fetch

Tier 3: legalize-kr optional mirror
  shallow/sparse checkout
  금융 관련 법령만 grep/diff
  nightly 또는 수동 refresh
```

## 사용하지 말아야 할 방식

- legalize-kr 전체 저장소를 runtime 필수 dependency로 추가
- 모든 법령을 대회 제출 전 ingest
- legalize-kr commit hash를 공식 법령 근거로 표기
- 법제처 API와 legalize-kr을 동시에 필수 dependency로 요구

## 다음 단계 후보

- `scripts/legalize_mirror_diff.py` 추가: 금융 관련 법령만 sparse checkout 후 changed law list 산출
- `data/legalize_allowlist.json` 추가: 금융소비자보호법, 개인정보보호법, 신용정보법, 전자금융거래법, 자본시장법, 표시광고법 등만 허용
- 변경 감지 결과는 직접 판단에 반영하지 말고 `HUMAN_REVIEW_REQUIRED` 또는 KB refresh task로만 연결
