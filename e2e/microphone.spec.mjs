// A microphone that does not start (wireframes page 2, B13-B18; page 4, D9 and
// D10): blocked, with the steps of the browser in hand; none, busy or failing;
// and inside an app's own browser, the way out of it. getUserMedia fails as each
// test says (e2e/instrument.mjs); the user agent says which browser this is.
import { test, expect } from '@playwright/test';

import { microphone } from './fixtures.mjs';
import { dockedNotice, fixedSentence, openPage } from './helpers.mjs';
import { UA, expectState, inVietnamese, instrument, pauseClock, said, setMicrophone, tap } from './instrument.mjs';
import { SENTENCE } from './paths.mjs';
import { en, fill, pattern, vi } from './strings.mjs';

test.use(microphone('sentence.wav'));

// The page, then a tap on the mic, getUserMedia answering as `gum` says (the
// name of its error, or 'real').
async function tapWithMic(page, gum, options = {}) {
    await instrument(page, { gum, ...options });
    await fixedSentence(page, SENTENCE);
    await openPage(page);
    await page.locator('#btnRecord').click();
}

const steps = (page) => page.locator('#recSteps li');
const calls = (page) => page.evaluate(() => window.__e2e.calls);
const pageAddress = (baseURL) => new URL('/', baseURL).href;

test.describe('on a phone', () => {
    test.skip(({ isMobile }) => !isMobile, 'the browsers of a phone');

    test.describe('Chrome on Android', () => {
        test.use({ userAgent: UA.chromeAndroid });

        test('blocked: the steps for Chrome; Try again asks again', async ({ page }) => {
            await tapWithMic(page, 'NotAllowedError');
            await expectState(page, 'mic-blocked', 'android');
            await expect(page.locator('#recTitle')).toHaveText(en['rec.blocked.title']);
            await expect(page.locator('#recLead')).toHaveText(en['rec.blocked.lead']);
            await expect(page.locator('#recText')).toHaveText(en['rec.blocked.howChrome']);
            await expect(steps(page)).toHaveText([
                fill(en['rec.blocked.android1'], { lock: en['rec.ui.lock'], tune: en['rec.ui.tune'] }),
                fill(en['rec.blocked.android2'], {
                    permissions: en['rec.ui.permissions'], microphone: en['rec.ui.microphone'], allow: en['rec.ui.allow'],
                }),
                fill(en['rec.blocked.androidLast'], { tryAgain: en['common.tryAgain'] }),
            ]);
            await expect(page.locator('#recAlert')).toContainText(en['rec.blocked.title']);
            await expect(page.locator('#recTryAgain')).toBeFocused();
            await expect(page.locator('#recCancel')).toHaveText(en['common.close']);

            // Allowed in the settings meanwhile: Try again asks, and records.
            await setMicrophone(page, 'real');
            await tap(page.locator('#recTryAgain'));
            await expectState(page, 'recording');
            expect(await calls(page)).toBe(2);
        });

        test('blocked before the tap: the steps at once, without asking', async ({ page }) => {
            await tapWithMic(page, 'real', { permission: 'denied' });
            await expectState(page, 'mic-blocked', 'android');
            await expect(page.locator('#recTryAgain')).toBeFocused();
            expect(await calls(page)).toBe(0);
            await tap(page.locator('#recTryAgain'));
            await expectState(page, 'recording');
            expect(await calls(page)).toBe(1);
        });

        for (const [error, state, detail, keys] of [
            ['NotFoundError', 'mic-none', '', 'rec.none'],
            ['NotReadableError', 'mic-busy', '', 'rec.micBusy'],
            ['AbortError', 'mic-error', 'AbortError', 'rec.micError'], // any other error
        ]) {
            test(`${error}: ${state}, and Try again`, async ({ page }) => {
                await tapWithMic(page, error);
                await expectState(page, state, detail);
                await expect(page.locator('#recTitle')).toHaveText(en[`${keys}.title`]);
                await expect(page.locator('#recLead')).toHaveText(en[`${keys}.lead`]);
                if (en[`${keys}.text`]) await expect(page.locator('#recText')).toHaveText(en[`${keys}.text`]);
                else await expect(page.locator('#recText')).toBeHidden();
                await expect(steps(page)).toHaveCount(0);
                await expect(page.locator('#recTryAgain')).toBeFocused();
                await expect(page.locator('#recCancel')).toHaveText(en['common.close']);
            });
        }
    });

    test.describe('Safari on iPhone', () => {
        test.use({ userAgent: UA.safariIos });

        test('blocked: the steps for Safari', async ({ page }) => {
            await tapWithMic(page, 'NotAllowedError');
            await expectState(page, 'mic-blocked', 'ios');
            await expect(page.locator('#recLead')).toHaveText(en['rec.blocked.leadSafari']);
            await expect(page.locator('#recText')).toHaveText(en['rec.blocked.how']);
            await expect(steps(page)).toHaveText([
                pattern(en['rec.blocked.ios1']), // {aa}: Safari's own button
                fill(en['rec.blocked.ios2'], { websiteSettings: en['rec.ui.websiteSettings'] }),
                fill(en['rec.blocked.ios3'], { microphone: en['rec.ui.microphone'], allow: en['rec.ui.allow'] }),
                fill(en['rec.blocked.iosLast'], { tryAgain: en['common.tryAgain'] }),
            ]);
        });
    });

    test.describe('Zalo on Android', () => {
        test.use({ userAgent: UA.zaloAndroid });

        test('any microphone failure: Open in Chrome is an intent link to this page; Copy link says so for 4 s', async ({ page, baseURL }) => {
            await page.clock.install();
            await tapWithMic(page, 'NotReadableError', { clipboard: 'ok' });
            await expectState(page, 'in-app', 'android');
            await expect(page.locator('#recTitle')).toHaveText(fill(en['inapp.title'], { app: 'Zalo' }));
            await expect(page.locator('#recLead')).toHaveText(fill(en['inapp.lead'], { app: 'Zalo' }));
            await expect(page.locator('#recText')).toHaveText(en['inapp.chrome']);
            const address = new URL(pageAddress(baseURL));
            await expect(page.locator('#recOpenChrome')).toHaveAttribute('href',
                `intent://${address.host}${address.pathname}#Intent;scheme=${address.protocol.replace(':', '')};`
                + `package=com.android.chrome;S.browser_fallback_url=${encodeURIComponent(address.href)};end`);
            await expect(page.locator('#recOpenChrome')).toHaveText(en['inapp.openChrome']);
            await expect(page.locator('#recOpenChrome')).toBeFocused();

            await tap(page.locator('#recCopyLink'));
            await expect(page.locator('#recCopyLabel')).toHaveText(en['notice.linkCopied.title']);
            await expect.poll(() => said(page)).toContain(en['notice.linkCopied.title']);
            expect(await page.evaluate(() => window.__e2e.copied)).toBe(address.href);
            await pauseClock(page, (await page.evaluate(() => window.__e2e.copiedAt)) + 3_900);
            await expect(page.locator('#recCopyLabel')).toHaveText(en['notice.linkCopied.title']);
            await page.clock.runFor(200);
            await expect(page.locator('#recCopyLabel')).toHaveText(en['notice.copyLink']);
        });

        test('in Vietnamese', async ({ page, context, baseURL }) => {
            await inVietnamese(context, baseURL);
            await tapWithMic(page, 'NotAllowedError');
            await expectState(page, 'in-app', 'android');
            await expect(page.locator('#recTitle')).toHaveText(fill(vi['inapp.title'], { app: 'Zalo' }));
            await expect(page.locator('#recLead')).toHaveText(fill(vi['inapp.lead'], { app: 'Zalo' }));
            await expect(page.locator('#recOpenChrome')).toHaveText(vi['inapp.openChrome']);
            await expect(page.locator('#recCopyLabel')).toHaveText(vi['notice.copyLink']);
            await expect(page.locator('#recCancel')).toHaveText(vi['common.close']);
        });

        test('Copy link refused: the address, selected, to copy by hand', async ({ page, baseURL }) => {
            await tapWithMic(page, 'NotAllowedError', { clipboard: 'refuse' });
            await expectState(page, 'in-app', 'android');
            await tap(page.locator('#recCopyLink'));
            await expect(page.locator('#recCopyHelp')).toContainText(en['notice.copyBlocked.text']);
            const field = page.locator('#recCopyHelp input');
            await expect(field).toBeFocused();
            await expect(field).toHaveValue(pageAddress(baseURL));
            expect(await field.evaluate((input) => [input.selectionStart, input.selectionEnd]))
                .toEqual([0, pageAddress(baseURL).length]);
        });
    });

    test.describe('Facebook on Android', () => {
        test.use({ userAgent: UA.facebookAndroid });

        test('Open in Chrome, or the app\'s own menu', async ({ page }) => {
            await tapWithMic(page, 'NotAllowedError');
            await expectState(page, 'in-app', 'android');
            await expect(page.locator('#recTitle')).toHaveText(fill(en['inapp.title'], { app: 'Facebook' }));
            await expect(page.locator('#recText')).toHaveText(
                fill(en['inapp.chromeOrMenu'], { menu: en['inapp.menu'], openInBrowser: en['inapp.openInBrowser'] }));
            await expect(page.locator('#recOpenChrome')).toBeVisible();
        });
    });

    test.describe('an Android app not known by name', () => {
        test.use({ userAgent: UA.webviewAndroid });

        test('its own words, and Open in Chrome', async ({ page }) => {
            await tapWithMic(page, 'NotFoundError');
            await expectState(page, 'in-app', 'android');
            await expect(page.locator('#recTitle')).toHaveText(en['inapp.titleUnnamed']);
            await expect(page.locator('#recLead')).toHaveText(en['inapp.leadUnnamed']);
            await expect(page.locator('#recOpenChrome')).toBeVisible();
        });
    });

    test.describe('Messenger on iPhone', () => {
        test.use({ userAgent: UA.messengerIos });

        test('the steps through the app\'s ••• menu, Copy link first, and the pointer to the menu', async ({ page }) => {
            await tapWithMic(page, 'NotAllowedError');
            await expectState(page, 'in-app', 'ios');
            await expect(page.locator('#recTitle')).toHaveText(en['inapp.iosTitle']);
            await expect(page.locator('#recLead')).toHaveText(en['inapp.iosLead']);
            await expect(page.locator('#recText')).toHaveText(en['inapp.iosHow']);
            await expect(steps(page)).toHaveText([
                pattern(en['inapp.ios1']), // {dots}: the app's ••• button
                fill(en['inapp.ios2'], { openInSafari: en['inapp.openInSafari'], openInBrowser: en['inapp.openInBrowser'] }),
            ]);
            await expect(page.locator('#recCopyLink')).toBeFocused();
            await expect(page.locator('#recCopyLink')).toHaveClass(/btn-primary/);
            await expect(page.locator('#recOpenChrome')).toBeHidden();
            await expect(page.locator('.inapp-pointer')).toBeVisible();
            await expect(page.locator('.inapp-pointer')).toHaveText(en['inapp.pointer']);
            await tap(page.locator('#recCancel'));
            await expectState(page, 'idle');
            await expect(page.locator('.inapp-pointer')).toBeHidden();
        });
    });

    test.describe('a browser that cannot record', () => {
        test.beforeEach(async ({ page }) => {
            await page.addInitScript(() => {
                delete window.MediaRecorder;
            });
        });

        test('the notice\'s Copy link: "Link copied" for 4 s', async ({ page }) => {
            await page.clock.install();
            await instrument(page, { clipboard: 'ok' });
            await fixedSentence(page, SENTENCE);
            await openPage(page);
            const notice = dockedNotice(page);
            await expect(notice).toContainText(en['notice.cantRecord.title']);
            await notice.getByRole('button', { name: en['notice.copyLink'] }).click();
            await expect(notice).toContainText(en['notice.linkCopied.title']);
            await expect(notice.getByRole('button', { name: en['notice.copied'] })).toBeVisible();
            await page.clock.fastForward(4_100);
            await expect(notice).toContainText(en['notice.cantRecord.title']);
            await expect(notice.getByRole('button', { name: en['notice.copyLink'] })).toBeVisible();
        });

        test('the notice\'s Copy link refused: the address to copy by hand', async ({ page, baseURL }) => {
            await instrument(page, { clipboard: 'refuse' });
            await fixedSentence(page, SENTENCE);
            await openPage(page);
            const notice = dockedNotice(page);
            await notice.getByRole('button', { name: en['notice.copyLink'] }).click();
            await expect(notice).toContainText(en['notice.copyBlocked.title']);
            const field = notice.getByRole('textbox', { name: en['notice.address'] });
            await expect(field).toBeFocused();
            await expect(field).toHaveValue(pageAddress(baseURL));
        });
    });
});

test.describe('on a computer', () => {
    test.skip(({ isMobile }) => isMobile, 'the browsers of a computer');

    for (const [browser, userAgent] of [['Chrome', UA.chromeWindows], ['Edge', UA.edgeWindows]]) {
        test.describe(browser, () => {
            test.use({ userAgent });

            test('blocked: the steps of the address bar', async ({ page }) => {
                await tapWithMic(page, 'NotAllowedError');
                await expectState(page, 'mic-blocked', 'desktop');
                await expect(page.locator('#recText')).toHaveText(en['rec.blocked.how']);
                await expect(steps(page)).toHaveText([
                    fill(en['rec.blocked.desktop1'], { lock: en['rec.ui.lock'], tune: en['rec.ui.tune'] }),
                    fill(en['rec.blocked.desktop2'], { microphone: en['rec.ui.microphone'], allow: en['rec.ui.allow'] }),
                    fill(en['rec.blocked.desktopLast'], { tryAgain: en['common.tryAgain'] }),
                ]);
                await expect(page.locator('#recTryAgain')).toBeFocused();
            });
        });
    }

    test.describe('Firefox', () => {
        test.use({ userAgent: UA.firefoxWindows });

        test('blocked: the browser\'s settings, no steps', async ({ page }) => {
            await tapWithMic(page, 'NotAllowedError');
            await expectState(page, 'mic-blocked', 'other');
            await expect(page.locator('#recText')).toHaveText(en['rec.blocked.inSettings']);
            await expect(steps(page)).toHaveCount(0);
            await expect(page.locator('#recSteps')).toBeHidden();
        });
    });
});
