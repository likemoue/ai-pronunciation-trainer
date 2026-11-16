// The page shell (wireframes pages 1 and 8): a sentence by level, the controls,
// the notices docked above them.
import { test, expect } from '@playwright/test';

import { collectErrors, dockedNotice, fixedSentence, openPage } from './helpers.mjs';
import { en } from './strings.mjs';

test('a bank sentence loads, with no error', async ({ page }) => {
    const errors = collectErrors(page);
    await openPage(page);
    await expect(page.locator('#sentence')).toBeVisible();
    await expect(page.locator('#sentence')).not.toBeEmpty();
    await expect(page.getByRole('radio', { name: en['level.easy'] })).toHaveAttribute('aria-checked', 'true');
    for (const id of ['#btnListen', '#btnRecord', '#btnNext']) {
        await expect(page.locator(id)).not.toHaveAttribute('aria-disabled', 'true');
    }
    expect(errors).toEqual([]);
});

test('the level chips keep only the latest choice', async ({ page }) => {
    await page.route('**/getSample', async (route) => {
        const { category } = JSON.parse(route.request().postData() || '{}');
        if (String(category) === '3') await new Promise((resolve) => setTimeout(resolve, 1500));
        const sentence = `Sentence for level ${category}.`;
        await route.fulfill({ json: { real_transcript: [sentence], ipa_transcript: '', transcript_translation: '', tts_url: '' } })
            .catch(() => {}); // the page gave up on it
    });
    await openPage(page);
    await page.getByRole('radio', { name: en['level.hard'] }).click();
    await page.getByRole('radio', { name: en['level.medium'] }).click();
    await expect(page.locator('#sentence')).toHaveText('Sentence for level 2.');
    await page.waitForTimeout(2000); // Hard's late answer must not replace it
    await expect(page.locator('#sentence')).toHaveText('Sentence for level 2.');
    await expect(page.getByRole('radio', { name: en['level.medium'] })).toHaveAttribute('aria-checked', 'true');
    await expect(page.getByRole('radio', { name: en['level.hard'] })).toHaveAttribute('aria-checked', 'false');
});

test('arrow keys move between levels and choose', async ({ page }) => {
    await fixedSentence(page, '', { perLevel: true });
    await openPage(page);
    await page.getByRole('radio', { name: en['level.easy'] }).focus();
    await page.keyboard.press('ArrowRight');
    const medium = page.getByRole('radio', { name: en['level.medium'] });
    await expect(medium).toBeFocused();
    await expect(medium).toHaveAttribute('aria-checked', 'true');
    await expect(page.locator('#sentence')).toHaveText('Sentence for level 2.');
});

test('a failed load says so in the card, and Try again loads', async ({ page }) => {
    let calls = 0;
    await page.route('**/getSample', async (route) => {
        calls += 1;
        if (calls === 1) {
            await route.fulfill({ status: 500, json: { error: 'boom', code: 'server_error' } });
        } else {
            await route.fulfill({ json: { real_transcript: ['The second try works.'], ipa_transcript: '', transcript_translation: '', tts_url: '' } });
        }
    });
    await page.goto('/');
    await expect(page.locator('#loadError')).toBeVisible();
    await expect(page.locator('#loadError')).toContainText(en['card.loadFailed']);
    await page.locator('#btnRetryLoad').click();
    await expect(page.locator('#sentence')).toHaveText('The second try works.');
    await expect(page.locator('#loadError')).toBeHidden();
});

test('a failed Next keeps the sentence and says why above the controls', async ({ page }) => {
    await fixedSentence(page, 'The first sentence stays.');
    await openPage(page);
    await page.unrouteAll();
    await page.route('**/getSample', (route) => route.fulfill({ status: 502, body: 'Bad gateway' }));
    await page.locator('#btnNext').click();
    await expect(dockedNotice(page)).toContainText(en['notice.loadFailed.title']);
    await expect(page.locator('#sentence')).toHaveText('The first sentence stays.');
});

test('offline: a notice, Next disabled, the mic still usable', async ({ page, context }) => {
    await fixedSentence(page, 'We stay on this sentence.');
    await openPage(page);
    await context.setOffline(true);
    await expect(dockedNotice(page)).toContainText(en['notice.offline.title']);
    await expect(page.locator('#btnNext')).toHaveAttribute('aria-disabled', 'true');
    await expect(page.locator('#btnRecord')).not.toHaveAttribute('aria-disabled', 'true');
    await context.setOffline(false);
    await expect(dockedNotice(page)).toHaveCount(0);
    await expect(page.locator('#btnNext')).not.toHaveAttribute('aria-disabled', 'true');
});

test('a browser that cannot record says so before the first tap', async ({ page }) => {
    await page.addInitScript(() => { delete window.MediaRecorder; });
    await fixedSentence(page, 'Nothing can be recorded here.');
    await openPage(page);
    await expect(dockedNotice(page)).toContainText(en['notice.cantRecord.title']);
    await expect(page.locator('#micLabel')).toHaveText(en['controls.cantRecord']);
    await expect(page.locator('#btnRecord')).toHaveAttribute('aria-disabled', 'true');
    // aria-disabled, not disabled: a tap still reaches it, and points to the notice.
    await page.locator('#btnRecord').click({ force: true });
    await expect(dockedNotice(page)).toBeFocused();
    await expect(page.getByRole('dialog')).toHaveCount(0);
});
