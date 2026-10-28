import { expect, test } from '@playwright/test';

// Smoke test; the full flow (Keycloak sign-in → server → acknowledge an alert) comes in Phase 7.
test('the login page offers company SSO', async ({ page }) => {
  await page.goto('/login');
  await expect(page.getByRole('button', { name: 'Sign in with company SSO' })).toBeVisible();
});
