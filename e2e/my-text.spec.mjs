// The My text sheet (wireframes page 7).
import { test, expect } from '@playwright/test';

import { fixedSentence, openPage } from './helpers.mjs';
import { en, fill } from './strings.mjs';

const sheet = (page) => page.getByRole('dialog', { name: en['mytext.title'] });

async function openSheet(page) {
    await page.locator('#btnMyText').click();
    await expect(sheet(page)).toBeVisible();
    await expect(page.locator('#myTextTitle')).toBeFocused();
}

test('counts the text as the server will, then practises it', async ({ page }) => {
    await fixedSentence(page, 'A bank sentence.');
    await openPage(page);
    await openSheet(page);
    // Curly quote, zero-width space and ellipsis, as pasted from Word: read as
    // "It's a nice day..." (18 characters, 4 words).
    await page.locator('#customText').fill('It\u{2019}s a \u{200B}nice day\u{2026}');
    await expect(page.locator('#countChars')).toHaveText(fill(en['mytext.chars'], { count: 18, max: 300 }));
    await expect(page.locator('#countWords')).toHaveText(fill(en['mytext.words'], { count: 4, max: 60 }));
    await page.locator('#btnUseCustom').click();
    await expect(sheet(page)).toBeHidden();
    await expect(page.locator('#sentence')).toHaveText("It's a nice day...");
    await expect(page.locator('#cardLabelText')).toHaveText(en['card.myText']);
    await expect(page.locator('[role="radio"][aria-checked="true"]')).toHaveCount(0);

    // A level goes back to the bank.
    await page.getByRole('radio', { name: en['level.easy'] }).click();
    await expect(page.locator('#sentence')).toHaveText('A bank sentence.');
    await expect(page.locator('#cardLabelText')).toHaveText(en['card.eyebrow']);
});

test('a text too long or not English is stopped before sending', async ({ page }) => {
    await fixedSentence(page, 'A bank sentence.');
    let sent = 0;
    await page.route('**/getCustomSample', (route) => {
        sent += 1;
        return route.continue();
    });
    await openPage(page);
    await openSheet(page);
    // The error shows while typing, and the submit says why instead of sending
    // (aria-disabled: still focusable and tappable).
    const submit = page.locator('#btnUseCustom');
    await page.locator('#customText').fill(`${'My school is big and green. '.repeat(11)}Yes.`);
    await expect(page.locator('#customMessage')).toBeVisible();
    await expect(submit).toHaveAttribute('aria-disabled', 'true');
    await submit.click({ force: true });
    await expect(sheet(page)).toBeVisible();

    await page.locator('#customText').fill('Hôm nay em đi học bằng xe đạp cùng các bạn.');
    await submit.click({ force: true });
    await expect(page.locator('#customMessage')).toContainText(en['error.text_not_english']);
    await expect(sheet(page)).toBeVisible();
    expect(sent).toBe(0);
});

test('the draft is kept when the sheet closes and after a reload', async ({ page }) => {
    await fixedSentence(page, 'A bank sentence.');
    await openPage(page);
    await openSheet(page);
    await page.locator('#customText').fill('My cat sleeps on the sofa.');
    await page.keyboard.press('Escape');
    await expect(sheet(page)).toBeHidden();
    await expect(page.locator('#btnMyText')).toBeFocused();
    await page.reload();
    await openSheet(page);
    await expect(page.locator('#customText')).toHaveValue('My cat sleeps on the sofa.');
});
