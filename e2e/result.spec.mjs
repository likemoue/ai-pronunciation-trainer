// The result card (wireframes page 3, design-system §2.10-2.13 and §3), on
// answers the server's own code makes (e2e/scores/*.json, make_scores.py): a
// real take with the fake microphone, the scoring request answered with one.
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { test, expect } from '@playwright/test';

import { microphone } from './fixtures.mjs';
import { collectErrors, fixedSentence, openPage } from './helpers.mjs';
import { instrument, recordAndStop, routeScore } from './instrument.mjs';
import { en, fill, vi } from './strings.mjs';

test.use(microphone('sentence.wav'));

const SCORES = path.join(path.dirname(fileURLToPath(import.meta.url)), 'scores');
const score = (name) => JSON.parse(readFileSync(path.join(SCORES, `${name}.json`), 'utf8'));

const card = (page) => page.locator('#resultCard');
const word = (page, text) => page.locator('#sentence button[data-status]').filter({ hasText: text });
const chips = (page) => page.locator('#wordChips .word-chip[data-index]');

// A take answered with the named case: its sentence on the card, its answer to the scoring request.
async function scored(page, name) {
    const { sentence, answer } = score(name);
    await instrument(page);
    await fixedSentence(page, sentence);
    await routeScore(page, (route) => route.fulfill({ json: answer }));
    await openPage(page);
    await recordAndStop(page, 1);
    await expect(card(page)).toBeVisible();
    return answer;
}

test.describe('on a phone', () => {
    test.skip(({ isMobile }) => !isMobile, 'the card is the same on a computer; its buttons are tested there');

    test('a typical result: the tier, the marks, the words to practise, the hints', async ({ page }) => {
        const errors = collectErrors(page);
        await scored(page, 'typical-mistakes');
        await expect(card(page)).toHaveAttribute('data-tier', 'good');
        await expect(page.locator('#resultTitle')).toHaveText(en['result.title.good']);
        await expect(page.locator('#resultTitle')).toBeFocused();
        await expect(page.locator('#resultMeaning')).toHaveText(fill(en['result.meaning'], { percent: 79 }));
        await expect(page.locator('#scoreValue')).toHaveText('79');
        // One sentence said, never the counting number.
        await expect(page.locator('#pageStatus')).toHaveText(
            fill(en['result.announce.other'], { percent: 79, count: 3, words: 'written, three, books' }));

        // Marks only after Almost and Needs-work words (Q2); each word says its status.
        await expect(word(page, 'Mary')).toHaveAttribute('data-status', '0');
        await expect(word(page, 'written')).toHaveAttribute('data-status', '2');
        await expect(word(page, 'three')).toHaveAttribute('data-status', '1');
        await expect(word(page, 'books')).toHaveAttribute('data-status', '1');
        await expect(page.locator('#sentence .mark')).toHaveCount(3);
        await expect(word(page, 'Mary').locator('.mark')).toHaveCount(0);
        await expect(word(page, 'three')).toHaveAttribute('aria-label', /Almost/);

        // Words to practise: Needs work first; the worst one's detail is open.
        await expect(chips(page)).toHaveText(['written', 'three', 'books']);
        await expect(page.locator('#wdWord')).toHaveText('written');
        await expect(page.locator('#wdHint')).toBeHidden();

        // "th" said as "t": the hint and both words to listen to.
        await chips(page).filter({ hasText: 'three' }).click();
        await expect(page.locator('#wdWord')).toHaveText('three');
        await expect(page.locator('#wdHint')).toBeVisible();
        await expect(page.locator('#wdHintLead')).toContainText('“th” was said as “t”');
        await expect(page.locator('#wdHintTip')).toHaveText(en['hint.thTip']);
        await expect(page.locator('#wdHintWordText')).toHaveText('three');
        await expect(page.locator('#wdHintHeardText')).toHaveText('tree');

        // The ending left out: the sound comes from the two IPAs.
        await word(page, 'books').click();
        await expect(page.locator('#wdWord')).toHaveText('books');
        await expect(page.locator('#wdHintLead')).toContainText('/s/');
        await expect(page.locator('#wdHintHeardText')).toHaveText('book');

        // The same hint in Vietnamese, switched in place.
        await page.getByRole('button', { name: en['lang.vi'] }).click();
        await expect(page.locator('#resultTitle')).toHaveText(vi['result.title.good']);
        await expect(page.locator('#wdHintLead')).toContainText('/s/');
        await expect(page.locator('#wdHintLead')).toContainText('âm cuối');
        expect(errors).toEqual([]);
    });

    test('nothing to practise: Excellent, and the done line instead of chips', async ({ page }) => {
        await scored(page, 'all-correct');
        await expect(card(page)).toHaveAttribute('data-tier', 'excellent');
        await expect(page.locator('#resultTitle')).toHaveText(en['result.title.excellent']);
        await expect(page.locator('#resultDone')).toBeVisible();
        await expect(chips(page)).toHaveCount(0);
        await expect(page.locator('#sentence .mark')).toHaveCount(0);
    });

    test('60 to 69: Almost there', async ({ page }) => {
        await scored(page, 'almost-there');
        await expect(card(page)).toHaveAttribute('data-tier', 'almost');
        await expect(page.locator('#resultTitle')).toHaveText(en['result.title.almost']);
    });

    test('under 60 with many words: Keep practising, four chips and "+N more"', async ({ page }) => {
        await scored(page, 'many-words');
        await expect(card(page)).toHaveAttribute('data-tier', 'keep');
        await expect(page.locator('#resultTitle')).toHaveText(en['result.title.keep']);
        await expect(chips(page)).toHaveCount(4);
        const more = page.locator('#wordChips .word-chip-more');
        await expect(more).toBeVisible();
        const total = await page.locator('#sentence button[data-status="1"], #sentence button[data-status="2"]')
            .evaluateAll((buttons) => new Set(buttons.map((button) => button.textContent.trim().toLowerCase())).size);
        await more.click();
        await expect(chips(page)).toHaveCount(total);
        await expect(more).toHaveCount(0);
    });

    test('most words not heard: a different sentence, no chips, a word not heard cannot be replayed', async ({ page }) => {
        await scored(page, 'different-sentence');
        await expect(card(page)).toHaveAttribute('data-tier', 'different');
        await expect(page.locator('#resultTitle')).toHaveText(en['result.title.different']);
        await expect(chips(page)).toHaveCount(0);
        await word(page, 'history').click();
        await expect(page.locator('#wdHeardIpa')).toHaveText(en['detail.notHeard']);
        await expect(page.locator('#wdPlayHeard')).toBeDisabled();
    });

    test('Try again and Next stay in the bar, not on the card', async ({ page }) => {
        await scored(page, 'typical-mistakes');
        await expect(page.locator('#btnResultRetry')).toBeHidden();
        await expect(page.locator('#btnResultNext')).toBeHidden();
        await expect(page.locator('#micLabel')).toHaveText(en['controls.tryAgain']);
    });
});

test.describe('on a computer', () => {
    test.skip(({ isMobile }) => isMobile, 'desktop card');

    test('the card ends with Try again and Next sentence, beside the sentence', async ({ page }) => {
        await scored(page, 'typical-mistakes');
        await expect(page.locator('#btnResultRetry')).toBeVisible();
        await expect(page.locator('#btnResultNext')).toBeVisible();
        const sentenceCard = await page.locator('#sentenceCard').boundingBox();
        const result = await card(page).boundingBox();
        expect(result.x).toBeGreaterThanOrEqual(sentenceCard.x + sentenceCard.width);
    });
});
