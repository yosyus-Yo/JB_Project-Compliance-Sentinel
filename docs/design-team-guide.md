# 디자인 팀 사용 가이드 (비개발자용)

> Compliance Sentinel의 UI/UX를 책임지는 **재사용 가능한 AI 디자인 팀**입니다.
> 한 번 만들어 뒀으니, 디자인 작업이 필요할 때마다 이 팀을 부르면 됩니다.

---

## 1. 이 팀은 무엇인가요?

6명의 **디자인 전문 AI 에이전트**로 구성된 가상 팀입니다. 컴플라이언스 6인 보드(법률·소비자보호
전문가 등)가 콘텐츠를 심의하듯이, 이 팀은 **화면(UI/UX)을 다관점으로 검토하고 개선안을 제안**합니다.

핵심 원칙 2가지:

1. **제안·시안까지만 합니다.** 실제 코드는 당신이 검토하고 승인한 뒤에만 바꿉니다. AI가 멋대로
   화면을 바꿔버리는 일은 없습니다.
2. **시스템 로직은 절대 건드리지 않습니다.** 디자인(보이는 것)만 다루고, 판단 엔진·데이터는 보호합니다.

---

## 2. 팀 멤버 6명 (각자 보는 관점이 다릅니다)

| 멤버 | 한 줄 소개 | 이런 걸 봐줍니다 |
|---|---|---|
| 🎯 **Design Lead** | 팀장 | 6명 의견을 모아 "우선순위 정리된 제안서"로 만듦 |
| 🔍 **UX Researcher** | 흐름 설계자 | "준법 담당자가 더 빨리 판단하는 화면 순서/배치" |
| 🎨 **UI Visual Designer** | 비주얼 | 색·글꼴·여백·위험도 색 신호의 완성도 |
| 🧩 **Design System** | 일관성 지킴이 | 화면마다 색·버튼이 따로 놀지 않게 규칙화 |
| ♿ **Accessibility** | 접근성 | 색약·키보드·저시력 사용자도 쓸 수 있는지 (금융=중요) |
| 🛠️ **Implementation Advisor** | 통역사 | "이 시안이 실제 코드로 만들 수 있는지 + 안전한지" |
| 🤔 **Contrarian Critic** | 반대자 | "이거 정말 필요해?" 과잉 디자인 막기 |

> Contrarian이 7번째처럼 보이지만, 컴플라이언스 보드처럼 **"반대 의견 전문가"를 일부러 둬서**
> 팀이 한쪽으로 쏠리는 걸 막습니다.

---

## 3. 어떻게 부르나요? (실전)

### 방법 A — 가장 쉬움: 그냥 말로 요청

Claude(또는 Codex)에게 이렇게 말하면 됩니다:

```
agents/design-team.yaml 의 디자인 팀으로 Compliance Sentinel 리포트 화면을 검토해줘.
제안·시안까지만.
```

그러면 AI가 6명의 페르소나(`agents/skills/design_team_personas/`)를 불러와 각 관점에서 제안하고,
Design Lead가 우선순위 정리된 제안서로 통합해 줍니다.

### 방법 B — SEAS의 `/team` 으로 즉시 가동 (선택)

SEAS 환경에서 작업한다면:

```
/team Compliance Sentinel 리포트 화면 UI/UX 개선 --agents "design-lead,ux-researcher,ui-visual-designer,accessibility-specialist,contrarian-design-critic"
```

### 방법 C — 특정 한 명만 부르기

```
agents/skills/design_team_personas/accessibility_specialist.md 관점으로
현재 위험도 색상이 색약 사용자에게 괜찮은지만 봐줘.
```

---

## 4. 작업 결과는 이렇게 나옵니다

```
## 디자인 제안서 — 리포트 화면

### 우선순위별 제안
| # | 제안 | 파일 | zone | 난이도 | 근거 |
|---|------|------|------|--------|------|
| 1 | 위험도 CRITICAL을 색+아이콘+라벨 3중 표시 | components/ReportView.tsx | 🟢 | 쉬움 | 색약 사용자 오인 방지 |
| 2 | forest-700을 헤더 주조색으로 통일 | src/index.css | 🟢 | 쉬움 | 일관성 |

### 의견이 갈린 부분
- A안(카드형) vs B안(테이블형) → 당신이 결정

### 다음 단계
승인하면 1번부터 시안 작업
```

당신은 이 제안서를 보고 **"1번 좋아, 진행해" / "2번은 보류" / "A안으로"** 처럼 결정만 하면 됩니다.

---

## 5. 안전 경계 (팀이 자동으로 지킵니다)

팀의 모든 멤버는 아래 규칙을 강제로 따릅니다 (`agents/design-team.yaml`의 `safety_boundary`):

| 구역 | 파일 | 팀의 행동 |
|---|---|---|
| 🟢 초록 | `compliance-sentinel/src/index.css`, `components/*.tsx`, `public/assets/` | 자유롭게 제안 |
| 🟡 노랑 | `App.tsx` 상단 로직, 데이터 바인딩 자리 | 모양만, 로직 줄 보존 |
| 🔴 빨강 | `types.ts`, `server.ts`, `src/compliance_sentinel/` (Python) | **제안조차 차단** |

→ 즉, 디자인 팀이 실수로 판단 엔진이나 데이터 구조를 바꾸자고 하는 일이 구조적으로 막혀 있습니다.

---

## 6. 작업 후 확인 (코드 변경을 승인했다면)

당신이 승인해서 실제 코드를 바꾼 경우:

```bash
cd compliance-sentinel
npm run dev      # 화면 켜서 눈으로 확인 (localhost:3000)
npm run lint     # 문법 안 깨졌는지 자동 검사
```

`lint`가 통과하고 화면이 정상이면 OK. 이상하면 git으로 되돌리면 됩니다.

---

## 7. 팀 구성 파일 위치

```
agents/
  design-team.yaml                          # 팀 헌장 (구성 + 안전 경계)
  skills/design_team_personas/
    design_lead.md                          # 팀장
    ux_researcher.md                        # 흐름/정보구조
    ui_visual_designer.md                   # 비주얼
    design_system_engineer.md               # 토큰/일관성
    accessibility_specialist.md             # 접근성
    frontend_implementation_advisor.md      # 구현 가능성
    contrarian_design_critic.md             # 반대 의견
docs/
  design-team-guide.md                      # 이 문서
```

이 팀은 한 번 만들어 두면 계속 재사용합니다. 멤버를 추가하거나 역할을 바꾸고 싶으면
해당 `.md` 파일을 수정하면 됩니다.
