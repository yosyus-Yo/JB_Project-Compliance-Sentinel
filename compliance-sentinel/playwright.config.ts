import { defineConfig, devices } from '@playwright/test';

const port = Number(process.env.E2E_PORT || 3217);
const baseURL = `http://127.0.0.1:${port}`;
const liveE2E = process.env.E2E_LIVE === '1';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: liveE2E ? 180_000 : 30_000,
  expect: { timeout: liveE2E ? 30_000 : 10_000 },
  fullyParallel: false,
  reporter: [['list']],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'npx tsx server.ts',
    url: baseURL,
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
    env: {
      ...process.env,
      PORT: String(port),
      ...(liveE2E ? {} : { CS_DISABLE_PYTHON_BRIDGE: '1' }),
      CS_PYTHON_WORKER_PORT: process.env.CS_PYTHON_WORKER_PORT || String(port + 5580),
      CS_DISABLE_REVIEW_CACHE: '1',
      CS_REVIEW_MAX_IN_FLIGHT: '1',
      CS_REVIEW_QUEUE_TIMEOUT_MS: '0',
      CS_LIVE_REVIEW_PROFILE: 'balanced',
      CS_LIVE_REVIEW_EFFORT: 'medium',
    },
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
