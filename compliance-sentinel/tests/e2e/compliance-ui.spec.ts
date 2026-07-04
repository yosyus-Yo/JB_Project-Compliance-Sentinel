import { expect, test } from '@playwright/test';

const riskyDraft = [
  '고객명 홍길동 900101-1234567 010-1234-5678',
  '<script>window.__csXss = true</script><div onclick="window.__csXss = true">JB 대출 누구나 100% 승인, 한도 문제 없음</div>',
  '무심사 확정 수익과 원금 보장을 즉시 안내해주세요.',
].join('\n');
const liveE2E = process.env.E2E_LIVE === '1';
const reviewTimeoutMs = liveE2E ? 180_000 : 30_000;

test('health exposes review concurrency policy', async ({ request }) => {
  const response = await request.get('/api/health');
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  expect(body.review_concurrency).toMatchObject({
    policy: 'bounded-fifo',
    max_in_flight: 1,
    queue_timeout_ms: 0,
  });
  expect(body.runtime.live_profile).toBe('balanced');
  expect(body.runtime.live_effort).toBe('medium');
  expect(body.provider_credentials.openrouter.provider).toBe('openrouter');
  expect(typeof body.provider_credentials.openrouter.present).toBe('boolean');
});

test('review API returns sanitized local fallback with six board personas', async ({ request }) => {
  const response = await request.post('/api/review', {
    data: {
      content: riskyDraft,
      metadata: { language: 'ko', channel: 'SNS', product_type: 'loan', target_audience: 'all' },
    },
  });
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  const report = body.data;
  expect(report.redacted_content).toContain('[HTML_TAG_REDACTED]');
  expect(report.redacted_content.toLowerCase()).not.toContain('<script');
  expect(report.redacted_content).not.toContain('010-1234-5678');
  expect(report.board_diagnostics).toHaveLength(6);
  expect(report.llm_degraded).toBe(liveE2E ? false : true);
  if (liveE2E) {
    const calls = report.raw_report?.llm_calls ?? [];
    expect(calls.filter((call: { called?: boolean }) => call.called).length).toBeGreaterThan(0);
    expect(report.raw_report?.cross_model_result?.model).toBe('openrouter/anthropic/claude-opus-4.8');
  }
});

test('UI renders six-person board without exposing active HTML or PII', async ({ page }) => {
  await page.goto('/');
  await page.evaluate(() => {
    (window as unknown as { __csXss: boolean | null }).__csXss = null;
  });
  await page.locator('#input-pristine-textarea').fill(riskyDraft);
  await page.locator('#btn-submit-pristine').click();

  await expect(page.locator('#card-screening-visualizer')).toBeVisible({ timeout: reviewTimeoutMs });
  await expect(page.getByText(/종합 AI 6인 준법 자문 위원회/)).toBeVisible();
  await expect(page.getByText('[HTML_TAG_REDACTED]').first()).toBeVisible();

  const bodyText = await page.locator('body').innerText();
  expect(bodyText).not.toContain('010-1234-5678');
  expect(bodyText).not.toContain('900101-1234567');
  expect(bodyText).not.toContain('<script>');
  for (const label of ['법률검토', '개인정보', '소비자보호', '운영리스크', '실무적용', '반대의견']) {
    await expect(page.getByText(label).first()).toBeVisible();
  }
  await expect.poll(() => page.evaluate(() => (window as unknown as { __csXss: boolean | null }).__csXss)).toBeNull();
});
