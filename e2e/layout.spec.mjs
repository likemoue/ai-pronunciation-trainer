// The layout at the sizes the wireframes were drawn for (design-system §1.10).
import { test, expect } from '@playwright/test';

import { fixedSentence, openPage } from './helpers.mjs';

const SENTENCE = 'Mary has written three books.';

async function noHorizontalScroll(page) {
    const { scroll, width } = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth, width: window.innerWidth,
    }));
    expect(scroll).toBeLessThanOrEqual(width);
}

test.describe('phones', () => {
    test.skip(({ isMobile }) => !isMobile, 'phone layout');

    test('320 x 568: nothing overflows', async ({ page }) => {
        await page.setViewportSize({ width: 320, height: 568 });
        await fixedSentence(page, SENTENCE);
        await openPage(page);
        await noHorizontalScroll(page);
    });

    test('360 x 640: the sentence and the mic share the first screen, the bar is fixed', async ({ page }) => {
        await page.setViewportSize({ width: 360, height: 640 });
        await fixedSentence(page, SENTENCE);
        await openPage(page);
        await noHorizontalScroll(page);
        expect(await page.locator('#controlZone').evaluate((node) => getComputedStyle(node).position)).toBe('fixed');
        const mic = await page.locator('#btnRecord').boundingBox();
        const sentence = await page.locator('#sentence').boundingBox();
        expect(mic.y + mic.height).toBeLessThanOrEqual(640);
        expect(sentence.y + sentence.height).toBeLessThanOrEqual(mic.y);
        for (const id of ['#btnListen', '#btnRecord', '#btnNext']) {
            const box = await page.locator(id).boundingBox();
            expect(Math.min(box.width, box.height)).toBeGreaterThanOrEqual(44);
        }
    });

    test('a phone held sideways (under 480 px tall): the bar is not fixed', async ({ page }) => {
        await page.setViewportSize({ width: 640, height: 360 });
        await fixedSentence(page, SENTENCE);
        await openPage(page);
        expect(await page.locator('#controlZone').evaluate((node) => getComputedStyle(node).position)).not.toBe('fixed');
    });
});

test.describe('desktop', () => {
    test.skip(({ isMobile }) => isMobile, 'desktop layout');

    test('1280 x 800: two columns, the result column beside the sentence', async ({ page }) => {
        await fixedSentence(page, SENTENCE);
        await openPage(page);
        await noHorizontalScroll(page);
        const card = await page.locator('#sentenceCard').boundingBox();
        const side = await page.locator('#howItWorks').boundingBox();
        expect(side.x).toBeGreaterThanOrEqual(card.x + card.width);
        expect(await page.locator('#controlZone').evaluate((node) => getComputedStyle(node).position)).not.toBe('fixed');
    });

    test('768 x 1024: one column with the controls inline', async ({ page }) => {
        await page.setViewportSize({ width: 768, height: 1024 });
        await fixedSentence(page, SENTENCE);
        await openPage(page);
        await noHorizontalScroll(page);
        expect(await page.locator('#controlZone').evaluate((node) => getComputedStyle(node).position)).not.toBe('fixed');
        const card = await page.locator('#sentenceCard').boundingBox();
        const tips = await page.locator('#howItWorks').boundingBox();
        expect(tips.y).toBeGreaterThanOrEqual(card.y + card.height);
    });
});
