// The microphone check with a microphone that hears nothing (silence.wav): "We didn't hear anything"
// (wireframes page 5, E8). Its own file: the fake microphone is set at launch (e2e/tour.spec.mjs has the
// rest of the check).
import { test, expect } from '@playwright/test';

import { microphone } from './fixtures.mjs';
import { fixedSentence, openPage } from './helpers.mjs';
import { instrument, micReleased } from './instrument.mjs';
import { SENTENCE } from './paths.mjs';
import { en } from './strings.mjs';

test.use(microphone('silence.wav'));

test.skip(({ isMobile }) => !isMobile, 'the same on a computer');

test('nothing heard in 3 s: "We didn\'t hear anything", what to check, Try again listens again', async ({ page }) => {
    await instrument(page);
    await fixedSentence(page, SENTENCE);
    await openPage(page);
    await page.getByRole('button', { name: en['how.micCheck'] }).click();
    const check = page.locator('#micCheck');
    await page.locator('#micStart').click();
    await expect(check).toHaveAttribute('data-state', 'listening');

    await expect(check).toHaveAttribute('data-state', 'silent', { timeout: 10_000 });
    await expect(page.locator('#micTitle')).toHaveText(en['mic.silent']);
    await expect(page.locator('#micTips li')).toHaveText([en['mic.silent1'], en['mic.silent2'], en['mic.silent3']]);
    await expect(page.locator('#micMeter')).toBeVisible();
    await expect(page.locator('#micMeter i.is-lit')).toHaveCount(0);
    await expect(page.locator('#micTryAgain')).toBeFocused();
    await expect(page.locator('#micSkip')).toHaveText(en['common.skip']);
    await expect(page.locator('#micAlert')).toHaveText(en['mic.silent']);
    expect(await micReleased(page)).toBe(true);

    await page.locator('#micTryAgain').click();
    await expect(check).toHaveAttribute('data-state', 'listening');
    expect(await page.evaluate(() => window.__e2e.calls)).toBe(2);
});
