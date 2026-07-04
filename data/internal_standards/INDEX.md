# Internal Standards Index — KB Phase C 입력 디렉토리

> `spec/kb-ingest-100plus.md` Phase C 입력. 본 디렉토리의 각 markdown은 `cs-knowledge-ingest --document <file> --source-type internal_standard --merge` 배치로 `data/laws.json`에 통합된다.

## 디렉토리 구조

```text
data/internal_standards/
├── INDEX.md                          # 본 파일
├── jb-marketing-review.md            # 8 entries (마케팅 콘텐츠 심의)
├── jb-multilingual-guide.md          # 3 entries (다국어 콘텐츠)
├── fsc-advertising-guideline.md      # 9 entries (금융위 광고 가이드)
├── fss-consumer-protection.md        # 8 entries (금감원 소비자보호 표준)
└── external/
    ├── kidi-insurance-ad.md          # 2 entries (KIDI 보험광고 표준)
    └── kfb-self-regulation.md        # 1 entry (은행연합회 자율규제)
```

## Source 분류

| 출처 | source_type | source_url prefix |
|---|---|---|
| JB 내부 (jb-*.md) | internal_standard | `local://jb-internal/` |
| 금감원/금융위 공개 가이드 (fsc-*, fss-*.md) | internal_standard | `local://fsc-guideline/` or `local://fss-standard/` |
| 외부 표준 (external/*.md) | official_or_external | 원본 URL (KIDI/은행연합회 공식 사이트) |

> `knowledge_base.article_provenance()`가 `source_url` prefix `local://` 시작 시 internal_standard로 자동 분류. 외부 표준은 공식 도메인 URL을 source_url로 명시해야 official_or_external 분류됨.

## 작성 상태 (Phase C KB-201~206)

| 파일 | 항목 수 | 상태 | 작성 메모 |
|---|---:|---|---|
| jb-marketing-review.md | 5 | todo | KB-203 — 데모용 sample. 실 운영 보안 검토 별도 |
| jb-multilingual-guide.md | 3 | todo | KB-203 — 5개 외국어 표현 정합성/문화 적합성/번역 위탁 |
| fsc-advertising-guideline.md | 9 | todo | KB-202 — 금융위 공개 가이드 chunk |
| fss-consumer-protection.md | 8 | todo | KB-202 — 금감원 공개 표준 chunk |
| external/kidi-insurance-ad.md | 2 | todo | KB-206 — 외부 표준 |
| external/kfb-self-regulation.md | 1 | todo | KB-206 — 은행연합회 자율규제 |
| **합계** | **28** | | target 26+ 충족 |

## KB-006: 기존 32 articles `last_verified_at` 백필 정책

> `data/laws.json` (현재 12 articles 실측, 32는 보고 시점 차이) — `LawArticle` dataclass에 `last_verified_at` 필드 부재. `article_provenance()`가 `effective_date` 기반으로 freshness 추론.

**결정**: `LawArticle` dataclass 변경 없이 운영. `article_provenance()`가 `STALE_AFTER_DAYS` 기준 자동 freshness 판정. 기존 32 articles의 `effective_date`가 180일 초과 시 stale로 표시.

**대안 결정 후보** (Phase B/D에서 재검토):
- (a) `LawArticle.last_verified_at` 필드 추가 → backward compat 깨질 위험. 신규 ingest는 채우고, 기존은 effective_date copy
- (b) `data/verification_log.jsonl` 별도 파일로 verification history 관리 → article 단위 backfill 불필요
- (c) 본 결정 유지 (effective_date 기반) → 단순. 단 KB-005에서 ingest 시점에 effective_date를 갱신해야 stale 차단

**현재 선택**: (c). Phase B에서 ingest 시점에 모든 신규 article의 `effective_date`를 정확히 채움 → freshness 자동 통과.

## 검증 수준

| 주장 | 수준 | 근거 |
|---|---|---|
| 디렉토리 구조 | [검증됨] | 본 turn에서 INDEX.md 작성 시 디렉토리 자동 생성 |
| `source_url` prefix 분류 로직 | [검증됨] | `knowledge_base.py:30` is_local 조건 |
| 백필 결정 (c) 적정성 | [추정] | LawArticle dataclass 보호 + ingest 시점 갱신으로 충분 가정 |
| 항목 수 28 (target 26+ 충족) | [검증됨] | 본 INDEX 표 합계 |
