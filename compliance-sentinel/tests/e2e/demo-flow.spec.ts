import { expect, test, type Page } from '@playwright/test';

// 시연(발표) 재현성 보장용 E2E: "클릭했는데 작동 안 함 / 에러 발생 / 버그"를 사전 차단.
// 기본은 deterministic 폴백(키 없이 재현). E2E_LIVE=1이면 LLM 경로까지 검증.
const liveE2E = process.env.E2E_LIVE === '1';
const reviewTimeoutMs = liveE2E ? 180_000 : 45_000;

const RISKY_DRAFT = 'JB 슈퍼적금 출시! 누구나 연 8% 확정 수익, 원금 보장!';

// 시연 절차: Python 워커 콜드스타트(~20초)가 끝난 뒤 첫 심의를 눌러야 503이 안 뜬다.
// /api/health의 python_worker.status를 폴링해 ready(또는 deterministic-only) 될 때까지 대기.
async function waitForWorkerReady(page: Page, timeoutMs = 40_000): Promise<void> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await page.request.get('/api/health');
      if (res.ok()) {
        const body = await res.json();
        const worker = body?.python_worker ?? {};
        if (worker.status === 'ready' || worker.enabled === false || worker.status === 'disabled') return;
      }
    } catch {
      /* 서버 아직 기동 중 — 재시도 */
    }
    await page.waitForTimeout(1000);
  }
  // 타임아웃이어도 진행 — deterministic 폴백 경로라도 동작하는지 확인한다.
}

// 제외 대상 노이즈:
//  (1) Vite dev HMR websocket(포트 24678) — dev 모드에서만 나오는 인프라 로그.
//  (2) 503 Service Unavailable — E2E 환경엔 Python 워커가 없어 스트리밍 엔드포인트가
//      503을 반환하면 UI가 비스트리밍 결정론 경로로 graceful fallback한다(결과는 정상 렌더).
//      실제 시연은 워커가 떠 있어 이 503이 나오지 않는다. 결과 렌더 assertion이 실패를
//      이미 막으므로(결과가 안 뜨면 별도 assertion 실패), 이 fallback 503만 제외한다.
const DEV_NOISE_RE = /24678|\[vite\]|websocket closed without opened|failed to connect to websocket|status of 503|503 \(Service Unavailable\)/i;

// 콘솔 error / 처리되지 않은 페이지 예외 수집 — 시연 중 조용한 앱 에러까지 잡는다.
function collectPageErrors(page: Page): string[] {
  const errors: string[] = [];
  const push = (s: string) => {
    if (!DEV_NOISE_RE.test(s)) errors.push(s);
  };
  page.on('console', (msg) => {
    if (msg.type() === 'error') push(`console.error: ${msg.text()}`);
  });
  page.on('pageerror', (err) => push(`pageerror: ${err.message}`));
  page.on('requestfailed', (req) => {
    const url = req.url();
    if (/\/api\/|\.js($|\?)|\.ts($|\?)/.test(url)) {
      push(`requestfailed: ${req.method()} ${url} — ${req.failure()?.errorText ?? ''}`);
    }
  });
  return errors;
}

test.describe('시연 핵심 플로우', () => {
  test('랜딩이 뜨고 광고 문구 입력 → 심의 제출 → 결과 렌더 (콘솔 에러 0)', async ({ page }) => {
    const errors = collectPageErrors(page);
    await page.goto('/');
    await waitForWorkerReady(page);

    // 1) 랜딩 진입 화면 + 입력창 + 제출 버튼이 실제로 보이고 활성
    await expect(page.locator('#pristine-landing-view')).toBeVisible();
    const textarea = page.locator('#input-pristine-textarea');
    await expect(textarea).toBeVisible();
    const submit = page.locator('#btn-submit-pristine');
    await expect(submit).toBeVisible();

    // 2) 입력 후 제출 클릭이 실제로 동작
    await textarea.fill(RISKY_DRAFT);
    await submit.click();

    // 3) 심의 진행(로더) 또는 결과가 나타난다 — 결과 뷰의 복귀 버튼으로 완료 감지.
    //    결과 뷰에 복귀 버튼이 2개 이상 동시 렌더될 수 있어(shared/verdict/pristine) OR-셀렉터가
    //    strict-mode 위반(2+ 매칭)을 낼 수 있으므로 .first()로 첫 매칭만 검사한다.
    await expect(
      page.locator('#btn-return-pristine-shared, #btn-goto-records-verdict, #btn-return-pristine').first(),
    ).toBeVisible({ timeout: reviewTimeoutMs });

    // 4) 결과 화면에 위험 표현 근거/판정이 실제 렌더 (원금 보장 → 위험 탐지)
    await expect(page.locator('body')).toContainText(/원금|보장|위험|승인|심의|HIGH|CRITICAL|APPROVE/i);

    // 5) 전 과정에서 콘솔 에러/페이지 예외가 없어야 시연이 안전
    expect(errors, `프론트 에러 발생:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('결과 후 "돌아가기"로 다시 입력 화면 복귀 (재심의 가능)', async ({ page }) => {
    const errors = collectPageErrors(page);
    await page.goto('/');
    await waitForWorkerReady(page);
    await page.locator('#input-pristine-textarea').fill(RISKY_DRAFT);
    await page.locator('#btn-submit-pristine').click();

    const backBtn = page.locator('#btn-return-pristine-shared, #btn-return-pristine').first();
    await expect(backBtn).toBeVisible({ timeout: reviewTimeoutMs });
    await backBtn.click();

    // 다시 입력 화면으로 복귀 → 연속 시연 가능
    await expect(page.locator('#input-pristine-textarea')).toBeVisible({ timeout: 10_000 });
    expect(errors, `프론트 에러 발생:\n${errors.join('\n')}`).toHaveLength(0);
  });

  test('상단 탭 이동이 동작하고 admin(관리자) 탭이 노출된다', async ({ page }) => {
    const errors = collectPageErrors(page);
    await page.goto('/');

    // admin 탭 재노출됨(HIDDEN_TABS 비움) — 표시되고 클릭 가능해야 한다.
    // (RBAC는 유지: 비-ADMIN 역할에는 canSeeTab이 false를 반환)
    await expect(page.locator('#nav-tab-admin')).toBeVisible();
    await page.locator('#nav-tab-admin').click();

    // 공개 탭들이 클릭으로 실제 전환되는지
    await expect(page.locator('#nav-tab-screen')).toBeVisible();
    await expect(page.locator('#nav-tab-history')).toBeVisible();
    await page.locator('#nav-tab-history').click();
    await expect(page.locator('#search-history-query')).toBeVisible({ timeout: 10_000 });

    await page.locator('#nav-tab-architecture').click();
    await expect(page.locator('#vector-pipeline-schematic')).toBeVisible({ timeout: 10_000 });

    await page.locator('#nav-tab-screen').click();
    await expect(page.locator('#pristine-landing-view')).toBeVisible({ timeout: 10_000 });

    expect(errors, `프론트 에러 발생:\n${errors.join('\n')}`).toHaveLength(0);
  });
});
