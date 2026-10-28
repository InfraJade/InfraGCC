import { expect, type Page } from '@playwright/test';

/** Demo users from the dev Keycloak realm (password `demo1234`); override with E2E_USERNAME / E2E_PASSWORD. */
export const credentials = {
  username: process.env.E2E_USERNAME ?? 'noc',
  password: process.env.E2E_PASSWORD ?? 'demo1234',
};

/** Simulator control API (raise a fault so there is an alert to acknowledge). */
export const simulatorUrl = process.env.E2E_SIM_URL ?? 'http://localhost:9100';

/** Sign in through Keycloak from the app's login page and land back in the app. */
export async function signIn(page: Page, user = credentials): Promise<void> {
  await page.goto('/');
  await expect(page).toHaveURL(/\/login/);
  await page.getByRole('button', { name: 'Sign in with company SSO' }).click();
  // Keycloak's login form (realm gcc).
  await page.locator('#username').fill(user.username);
  await page.locator('#password').fill(user.password);
  await page.locator('#kc-login').click();
  await page.waitForURL((url) => !url.pathname.startsWith('/auth/') && !url.href.includes('/realms/'), {
    timeout: 30_000,
  });
  await expect(page.getByRole('heading', { name: 'Global overview', level: 1 })).toBeVisible({ timeout: 30_000 });
}
