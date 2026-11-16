// English | Vietnamese (design-system §5): switched in place, remembered, and
// the next visit is rendered in Vietnamese by the server.
import { test, expect } from '@playwright/test';

import { fixedSentence, openPage } from './helpers.mjs';
import { en, vi } from './strings.mjs';

test('EN | VI switches the page in place and the next visit opens in Vietnamese', async ({ page, context }) => {
    await fixedSentence(page, 'My bike is red.');
    await openPage(page);
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');

    await page.getByRole('button', { name: en['lang.vi'] }).click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'vi');
    await expect(page.getByRole('button', { name: vi['lang.vi'] })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByRole('radio', { name: vi['level.easy'] })).toBeVisible();
    await expect(page.locator('#micLabel')).toHaveText(vi['controls.speak']);
    // The practice text stays English.
    await expect(page.locator('#sentence')).toHaveAttribute('lang', 'en');
    expect((await context.cookies()).find((cookie) => cookie.name === 'lang')?.value).toBe('vi');

    // The server renders the next page in Vietnamese, before any script runs.
    const html = await (await page.request.get('/')).text();
    expect(html).toContain('<html lang="vi">');
    expect(html).toContain(`>${vi['level.easy']}<`);

    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('lang', 'vi');
    await page.getByRole('button', { name: vi['lang.en'] }).click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'en');
    await expect(page.locator('#micLabel')).toHaveText(en['controls.speak']);
    expect((await context.cookies()).find((cookie) => cookie.name === 'lang')?.value).toBe('en');
});
