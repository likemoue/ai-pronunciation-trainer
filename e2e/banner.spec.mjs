// The banner shown inside an app's own browser (wireframes page 4, D1-D8; banner.js): which app, read from
// the user agent alone, the way out of it on Android and on iPhone, Copy link, and dismissed for the visit.
// The microphone failing inside an app (D9, D10) is in e2e/microphone.spec.mjs.
import { test, expect } from '@playwright/test';

import { fixedSentence, openPage } from './helpers.mjs';
import { UA, inVietnamese, instrument, pauseClock } from './instrument.mjs';
import { en, fill, pattern, vi } from './strings.mjs';

const SENTENCE = 'Mary has written three books.';

const banner = (page) => page.locator('#bannerSlot .banner');
const title = (page) => page.locator('#bannerSlot .banner-title');
const text = (page) => page.locator('#bannerSlot .banner-text');
const actions = (page) => page.locator('#bannerSlot .banner-actions > *');

// The link that opens this page in Chrome on Android (D1).
function intentUrl(baseURL) {
    const address = new URL('/', baseURL);
    return `intent://${address.host}${address.pathname}#Intent;scheme=${address.protocol.replace(':', '')};`
        + `package=com.android.chrome;S.browser_fallback_url=${encodeURIComponent(address.href)};end`;
}

// The ⋮ menu's line of the Facebook family on Android (D5); the menu is an icon named for screen readers.
const chromeOrMenu = (dict) => fill(dict['banner.chromeOrMenu'], { menu: dict['inapp.menu'], openInBrowser: dict['inapp.openInBrowser'] });

// What each app's browser shows. dismiss: ✕ in the corner, or Not now where the corner is kept for the
// arrow to the app's own menu (pointer: its words).
const APPS = [
    {
        name: 'Zalo on Android', userAgent: UA.zaloAndroid, app: 'zalo', platform: 'android',
        title: fill(en['banner.title'], { app: 'Zalo' }), text: en['banner.chrome'], openChrome: true,
    },
    {
        name: 'Facebook on Android', userAgent: UA.facebookAndroid, app: 'facebook', platform: 'android',
        title: fill(en['banner.title'], { app: 'Facebook' }), text: chromeOrMenu(en), openChrome: true,
        pointer: fill(en['inapp.pointerMenu'], { menu: '' }).trim(), // "Or tap" and the ⋮ icon
    },
    {
        name: 'Instagram on Android', userAgent: UA.instagramAndroid, app: 'instagram', platform: 'android',
        title: fill(en['banner.title'], { app: 'Instagram' }), text: chromeOrMenu(en), openChrome: true,
        pointer: fill(en['inapp.pointerMenu'], { menu: '' }).trim(),
    },
    {
        name: 'LINE on Android', userAgent: UA.lineAndroid, app: 'line', platform: 'android',
        title: fill(en['banner.title'], { app: 'LINE' }), text: chromeOrMenu(en), openChrome: true,
        pointer: fill(en['inapp.pointerMenu'], { menu: '' }).trim(),
    },
    {
        name: 'an Android app not known by name', userAgent: UA.webviewAndroid, app: 'webview', platform: 'android',
        title: en['banner.titleUnnamed'], text: en['banner.chrome'], openChrome: true,
    },
    {
        name: 'Messenger on iPhone', userAgent: UA.messengerIos, app: 'messenger', platform: 'ios',
        title: fill(en['banner.titleIos'], { app: 'Messenger' }),
        text: pattern(en['banner.ios'], { item: en['inapp.openInSafari'] }), // {dots}: the app's ••• button
        openChrome: false, pointer: en['inapp.pointer'],
    },
    {
        name: 'Zalo on iPhone', userAgent: UA.zaloIos, app: 'zalo', platform: 'ios',
        title: fill(en['banner.titleIos'], { app: 'Zalo' }),
        text: pattern(en['banner.ios'], { item: en['inapp.openInBrowser'] }), // Zalo's menu says "Open in browser"
        openChrome: false, pointer: en['inapp.pointer'],
    },
];

test.describe('inside an app', () => {
    test.skip(({ isMobile }) => !isMobile, 'the apps are on phones');

    for (const app of APPS) {
        test.describe(app.name, () => {
            test.use({ userAgent: app.userAgent });

            test('the banner, first on the page: the app, the way out, Copy link', async ({ page, baseURL }) => {
                await fixedSentence(page, SENTENCE);
                await openPage(page);
                const aside = page.getByRole('complementary', { name: app.title });
                await expect(aside).toBeVisible();
                await expect(banner(page)).toHaveAttribute('data-app', app.app);
                await expect(banner(page)).toHaveAttribute('data-platform', app.platform);
                await expect(banner(page)).toHaveAttribute('data-state', 'ready');
                await expect(banner(page)).toHaveClass(/notice-warning/);
                await expect(text(page)).toHaveText(app.text);
                // Above the header, in the page's flow.
                expect(await page.locator('#app > *').first().getAttribute('id')).toBe('bannerSlot');
                const header = await page.locator('.topbar').boundingBox();
                const box = await banner(page).boundingBox();
                expect(box.y + box.height).toBeLessThanOrEqual(header.y);

                const expected = [
                    ...(app.openChrome ? [en['inapp.openChrome']] : []),
                    en['notice.copyLink'],
                    ...(app.pointer ? [en['banner.notNow']] : []),
                ];
                await expect(actions(page)).toHaveText(expected);
                const openChrome = aside.getByRole('link', { name: en['inapp.openChrome'] });
                if (app.openChrome) await expect(openChrome).toHaveAttribute('href', intentUrl(baseURL));
                const dismiss = aside.getByRole('button', { name: en['banner.dismiss'] });
                const pointer = aside.locator('.inapp-pointer');
                if (app.pointer) {
                    await expect(pointer).toBeVisible();
                    await expect(pointer).toHaveText(app.pointer);
                    await expect(pointer).toHaveAttribute('aria-hidden', 'true');
                    await expect(dismiss).toHaveCount(0);
                } else {
                    await expect(pointer).toHaveCount(0);
                    await expect(dismiss).toBeVisible();
                }
            });
        });
    }

    test.describe('Zalo on Android', () => {
        test.use({ userAgent: UA.zaloAndroid });

        test('Copy link: "Link copied", said; the address without its fragment; back after 4 s', async ({ page, baseURL }) => {
            await page.clock.install();
            await instrument(page, { clipboard: 'ok' });
            await fixedSentence(page, SENTENCE);
            await openPage(page, '/#shared-in-zalo');
            const copy = banner(page).getByRole('button', { name: en['notice.copyLink'] });
            await copy.click();
            await expect(banner(page)).toHaveAttribute('data-state', 'copied');
            await expect(banner(page)).toHaveClass(/notice-success/);
            await expect(title(page)).toHaveText(en['notice.linkCopied.title']);
            await expect(text(page)).toHaveText(en['notice.linkCopied.text']);
            // The same button, relabelled: it keeps its focus.
            const copied = banner(page).getByRole('button', { name: en['notice.copied'] });
            await expect(copied).toBeFocused();
            await expect(page.locator('#pageStatus')).toHaveText(en['notice.linkCopied.title']);
            expect(await page.evaluate(() => window.__e2e.copied)).toBe(new URL('/', baseURL).href);

            await pauseClock(page, (await page.evaluate(() => window.__e2e.copiedAt)) + 3_900);
            await expect(copied).toBeVisible();
            await page.clock.runFor(200);
            await expect(banner(page)).toHaveAttribute('data-state', 'ready');
            await expect(title(page)).toHaveText(fill(en['banner.title'], { app: 'Zalo' }));
            await expect(copy).toBeFocused();
        });

        test('Copy link refused: the address, selected, to copy by hand; ✕ stays', async ({ page, baseURL }) => {
            await instrument(page, { clipboard: 'refuse' });
            await fixedSentence(page, SENTENCE);
            await openPage(page);
            await banner(page).getByRole('button', { name: en['notice.copyLink'] }).click();
            await expect(banner(page)).toHaveAttribute('data-state', 'refused');
            await expect(banner(page)).toHaveClass(/notice-info/);
            await expect(title(page)).toHaveText(en['notice.copyBlocked.title']);
            await expect(text(page)).toHaveText(en['notice.copyBlocked.text']);
            const address = new URL('/', baseURL).href;
            const field = banner(page).getByRole('textbox', { name: en['notice.address'] });
            await expect(field).toBeFocused();
            await expect(field).toHaveValue(address);
            await expect(field).toHaveAttribute('readonly', '');
            expect(await field.evaluate((input) => [input.selectionStart, input.selectionEnd])).toEqual([0, address.length]);
            await expect(actions(page)).toHaveCount(0);
            await expect(banner(page).getByRole('button', { name: en['banner.dismiss'] })).toBeVisible();
        });

        test('✕: gone for this visit, focus on to the header; back on the next visit', async ({ page, context }) => {
            await fixedSentence(page, SENTENCE);
            await openPage(page);
            await banner(page).getByRole('button', { name: en['banner.dismiss'] }).click();
            await expect(banner(page)).toHaveCount(0);
            await expect(page.locator('#bannerSlot')).toBeHidden();
            await expect(page.getByRole('button', { name: en['lang.en'] })).toBeFocused();

            // The same visit: a reload of this tab keeps it away.
            await page.reload();
            await expect(page.locator('#sentence')).toHaveText(SENTENCE);
            await expect(banner(page)).toHaveCount(0);

            // The next visit (another tab, a new session): it is back.
            const next = await context.newPage();
            await fixedSentence(next, SENTENCE);
            await openPage(next);
            await expect(banner(next)).toBeVisible();
        });

        test('in Vietnamese, also when the learner switches language with the banner shown', async ({ page }) => {
            await fixedSentence(page, SENTENCE);
            await openPage(page);
            await page.getByRole('button', { name: en['lang.vi'] }).click();
            const aside = page.getByRole('complementary', { name: fill(vi['banner.title'], { app: 'Zalo' }) });
            await expect(aside).toBeVisible();
            await expect(text(page)).toHaveText(vi['banner.chrome']);
            await expect(actions(page)).toHaveText([vi['inapp.openChrome'], vi['notice.copyLink']]);
            await expect(aside.getByRole('button', { name: vi['banner.dismiss'] })).toBeVisible();
        });

        test('360 x 560 (what Zalo leaves): the banner, the sentence and the mic in the first screen', async ({ page }) => {
            await page.setViewportSize({ width: 360, height: 560 });
            await fixedSentence(page, SENTENCE);
            await openPage(page);
            await expect(banner(page)).toBeVisible();
            const sentence = await page.locator('#sentence').boundingBox();
            const mic = await page.locator('#btnRecord').boundingBox();
            expect(sentence.y + sentence.height).toBeLessThanOrEqual(mic.y);
            expect(mic.y + mic.height).toBeLessThanOrEqual(560);
            const { scroll, width } = await page.evaluate(() => ({
                scroll: document.documentElement.scrollWidth, width: window.innerWidth,
            }));
            expect(scroll).toBeLessThanOrEqual(width);
        });
    });

    test.describe('Messenger on iPhone', () => {
        test.use({ userAgent: UA.messengerIos });

        test('Not now: gone for this visit', async ({ page }) => {
            await fixedSentence(page, SENTENCE);
            await openPage(page);
            await banner(page).getByRole('button', { name: en['banner.notNow'] }).click();
            await expect(banner(page)).toHaveCount(0);
            await page.reload();
            await expect(page.locator('#sentence')).toHaveText(SENTENCE);
            await expect(banner(page)).toHaveCount(0);
        });

        test('in Vietnamese (D4)', async ({ page, context, baseURL }) => {
            await inVietnamese(context, baseURL);
            await fixedSentence(page, SENTENCE);
            await openPage(page);
            const aside = page.getByRole('complementary', { name: fill(vi['banner.titleIos'], { app: 'Messenger' }) });
            await expect(aside).toBeVisible();
            await expect(text(page)).toHaveText(pattern(vi['banner.ios'], { item: vi['inapp.openInSafari'] }));
            await expect(actions(page)).toHaveText([vi['notice.copyLink'], vi['banner.notNow']]);
            await expect(aside.locator('.inapp-pointer')).toHaveText(vi['inapp.pointer']);
        });
    });
});

test.describe('outside an app', () => {
    // Chrome on Android (phone), Chrome on Windows (desktop).
    test('no banner', async ({ page }) => {
        await fixedSentence(page, SENTENCE);
        await openPage(page);
        await expect(page.locator('#bannerSlot')).toBeEmpty();
        await expect(page.locator('#bannerSlot')).toBeHidden();
    });

    test.describe('Safari on iPhone', () => {
        test.skip(({ isMobile }) => !isMobile, 'an iPhone');
        test.use({ userAgent: UA.safariIos });

        test('no banner', async ({ page }) => {
            await fixedSentence(page, SENTENCE);
            await openPage(page);
            await expect(page.locator('#bannerSlot')).toBeEmpty();
        });
    });
});
