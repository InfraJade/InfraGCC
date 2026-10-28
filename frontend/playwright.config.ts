import { defineConfig, devices } from '@playwright/test';

/**
 * End-to-end tests (Phase 7): run against a running stack, default the compose `web` service.
 * Browsers are not installed by `npm ci`; run `npx playwright install chromium` once.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:3000',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
