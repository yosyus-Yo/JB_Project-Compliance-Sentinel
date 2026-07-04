# R2·R11 — 분석 대시보드 지표 정직화 구현 스펙

> **대상**: `compliance-sentinel/` 분석 대시보드(dashboard 탭) · **상태**: 인벤토리 R2(🔴)·R11(🔴)
> **한 줄**: 대시보드 KPI 중 일부가 **미측정(0)** 이거나 **가짜 그래프(하드코딩 더미)** 로 표시된다. 실측으로 바꾸거나 빈 상태로 정직하게 표기한다.
> **검증으로 정정됨**: 원래 R2+R11+R12 묶음이었으나 확인 결과 R12(엔진 배지)는 라이브 코드에서 **이미 동적**(App.tsx:760)이라 비이슈 → R10(死컴포넌트)으로 흡수. 본 스펙은 R2·R11만 다룬다.

---

## 0. 검증된 현황 (중요 — 무엇이 진짜 문제인가)
| 지표 | 실제 상태 | 판정 |
|------|----------|------|
| TPS **숫자** (실시간 처리율) | server.ts:2660 `last60/60` **실측 계산** | ✅ 정상 (가짜 아님) |
| TPS **그래프** (AreaChart 타임라인) | App.tsx:2046-2048: 실데이터 없으면 **하드코딩 더미** `[{18:50,4},{18:51,6}...]` 렌더 | 🔴 **R11 — 가짜 그래프** |
| 평균 심의 속도 (avgDurationMs) | server.ts:2663 `avgDurationMs: 0` 하드코딩, App.tsx:2017이 `"—  (측정 미지원)"` 표기 | 🟡 **R2 — 미구현(단 UI는 정직)** |
| 엔진 상태 배지 | 라이브 App.tsx:760 `엔진 {workerStatus}` **동적** | ✅ 정상 (하드코딩본은 死컴포넌트 DemoPanel:65 → 안 뜸) |

> 즉 **사용자를 오해시키는 진짜 결함은 R11(가짜 그래프) 하나**, R2는 "정직하게 미지원 표기 중인 미구현 기능"이다.

---

## R11 🔴 — TPS 타임라인 가짜 그래프 제거 (우선)

### 문제
- `metrics.timelineGraph`가 비었을 때(Python worker 미실행/데이터 없음) AreaChart가 **하드코딩 더미 데이터**(18:50~18:55, 값 4~6)를 그린다 → 사용자는 "실시간 활동이 있다"고 오인.
- 근거: App.tsx:2046-2053 `data={timelineGraph.length>0 ? timelineGraph : [{time:"18:50",value:4},...]}`

### 개발자 작업
1. **하드코딩 더미 fallback 제거.**
2. 데이터 없을 때 → **빈 상태 UI**: "아직 처리 데이터 없음" placeholder(빈 차트 + 안내문) 표시.
3. (선택) `timelineGraph`를 server `buildRealtimeMetrics()`가 실제 최근 N분 버킷으로 채우도록 보강 — historyDB 타임스탬프 기반 분당 집계.

### 변경 위치
- App.tsx:2046-2053 (더미 배열 삭제 + 빈상태 분기)
- (선택) server.ts:2617 `buildRealtimeMetrics()` — `timelineGraph` 실집계 추가

---

## R2 🟡 — 평균 심의 속도(avgDurationMs) 실측 구현

### 문제
- `avgDurationMs`가 항상 0 → UI가 정직하게 "—  (측정 미지원)" 표기(App.tsx:2017). **오해는 없으나 기능 미완**.
- 근거: server.ts:2663 `avgDurationMs: 0`, adapter.ts:421-424 client fallback도 0.

### 개발자 작업
1. **리뷰 처리 시간 측정**: `/api/review` 처리 시작~완료(또는 Python worker 응답 소요) ms를 기록.
   - 각 리뷰 결과에 `processing_ms` 저장(historyDB item 또는 별도 ring buffer).
2. `buildRealtimeMetrics()`에서 최근 N건의 `processing_ms` 평균 → `avgDurationMs` 반환.
3. UI는 이미 `>0`이면 "ms" 표기하므로(App.tsx:2017) **프론트 변경 불필요** — 서버가 실값만 주면 자동 표시.

### 변경 위치
- server.ts: 리뷰 처리 경로에 소요시간 측정 + 저장 / `buildRealtimeMetrics():2617` 평균 계산
- (프론트 무변경)

---

## 수용 기준 (AC)
- [ ] R11: Python worker 끄고 대시보드 진입 시 **18:50~ 가짜 그래프가 안 나오고** "데이터 없음" 빈상태 표시
- [ ] R11: 실제 심의 N건 발생 후 그래프가 **실 타임라인**으로 채워짐
- [ ] R2: 심의 수 건 후 "평균 심의 속도" 카드가 **실 ms 값** 표시(더 이상 "측정 미지원" 고정 아님)
- [ ] TPS 숫자/엔진 배지는 회귀 없음(이미 정상)

## 범위 / 비범위
- **범위**: R11 더미 제거+빈상태, R2 소요시간 측정·평균.
- **비범위**: 과거 데이터 소급 집계, 장기 시계열 저장(DB), 차트 라이브러리 교체.
- **R12 제외**: 라이브 엔진 배지는 이미 동적 → 손댈 것 없음. 死컴포넌트(DemoPanel) 정리는 R10에서.

---

### 검증 수준
| 주장 | 수준 | 근거 |
|------|------|------|
| TPS 숫자는 실측(가짜 아님) | [검증됨] | server.ts:2660 `last60/60` 계산 직독 |
| TPS 그래프는 하드코딩 더미 fallback | [검증됨] | App.tsx:2046-2048 더미 배열 직독 |
| avgDurationMs=0 + UI 정직 표기 | [검증됨] | server.ts:2663 + App.tsx:2017 직독 |
| R12 엔진 배지 라이브는 동적(비이슈) | [검증됨] | App.tsx:760 `엔진 {workerStatus}` vs DemoPanel:65(死) 대조 |
| 소요시간 측정 미구현 | [검증됨] | server.ts에 processing time 기록 없음 |
