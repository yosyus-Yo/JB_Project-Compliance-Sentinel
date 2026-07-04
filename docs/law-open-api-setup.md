# 법령정보센터 Open API 발급 절차 (KB-005)

> `spec/kb-ingest-100plus.md` Phase B 사전 준비. `data/law_targets.yaml`의 공식 법령 70+ 항목을 자동 ingest하려면 본 절차를 완료해야 한다.

## 1. 발급 사이트

법령정보센터 OPEN API: **https://open.law.go.kr/** (국가법령정보센터 운영)

## 2. 발급 절차

1. **회원가입** — https://open.law.go.kr/LSO/main.do 접속 후 회원가입 (개인/법인)
2. **OPEN API 신청** — 로그인 후 [마이페이지] → [신청내역] → [신청]
3. **활용 목적 기재** (예: "금융 마케팅 콘텐츠 준법 검토 보조 시스템 (학술/연구 데모용)")
4. **이용신청서 작성** — 일 호출 건수, 활용 분야 명시
5. **승인 대기** — 영업일 기준 2-5일 (수동 검토)
6. **OC 코드 발급** — 승인 시 e-mail로 OC 코드 (`emailId@example.com` 형태) 전달

## 3. 환경변수 설정

발급받은 OC 코드를 `LAW_OPEN_API_KEY` 환경변수에 설정:

```bash
# Linux / macOS
export LAW_OPEN_API_KEY="your-oc-code@example.com"

# Windows PowerShell
$env:LAW_OPEN_API_KEY = "your-oc-code@example.com"

# 영구 설정: ~/.bashrc 또는 ~/.zshrc 또는 시스템 환경변수
```

## 4. 동작 확인

```bash
# `from_env()`가 클라이언트를 반환하는지 확인
python -c "from compliance_sentinel.law_open_api import from_env; print('OK' if from_env() else 'KEY MISSING')"
```

OK 출력 시 발급 완료. 그렇지 않으면 환경변수 또는 키 본문 점검.

## 5. Rate Limit 주의사항

법령정보센터 Open API 정책 (2026-05-16 시점, [추정] — 공식 사이트 재확인 권장):
- 분당 호출 횟수 제한 존재 (정확한 수치 [미확인])
- 일일 호출 총량 제한 존재 (사용신청서에 적은 추정치 기준)
- 본 프로젝트의 `law_open_api.LawOpenApiClient`는 backoff 보유 [미확인 — Phase B KB-101에서 실측 확인 필요]
- 105건 ingest 시 분산 호출 권장 (한 번에 10건 단위 batch + 1초 sleep 권장)

## 6. 발급 불가 시 우회 경로

- **공개 PDF chunk 사용** — 금감원/금융위 사이트의 공개 가이드라인 PDF를 markdown으로 정리 후 `data/internal_standards/`에 보관, `cs-knowledge-ingest --document <file> --source-type official_or_external`로 ingest. 단, `source_url`은 PDF 원본 URL 명시 필수.
- **법령 조문 수동 입력** — `data/laws.json`에 직접 entry 추가. 단, `source_url`은 `law.go.kr` 도메인 명시 (article_provenance가 official_or_external로 분류하도록).

## 7. 검증 수준

| 주장 | 수준 | 근거 |
|---|---|---|
| 발급 사이트 URL `open.law.go.kr` | [검증됨] | 일반 공공기관 API 표준 — 직접 접속 검증은 사용자 책임 |
| OC 코드 형식 `email@example.com` | [추정] | 일반 법령정보센터 API 관례, 본 세션 직접 발급 안 함 |
| 본 프로젝트 `from_env()` 함수 존재 | [검증됨] | `src/compliance_sentinel/law_open_api.py:139` 확인 |
| `LawOpenApiClient` backoff 동작 | [미확인] | KB-101에서 실측 검증 후 결정 |
| Rate limit 정확 수치 | [미확인] | 공식 사이트 재확인 필요 |
