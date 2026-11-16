// The first-visit tour and the microphone check (wireframes page 5, E1-E10; tour.js, miccheck.js). The tour
// starts by itself on a first visit only: the tests of a first visit start without its flag, which
// playwright.config.mjs sets for every other test. The fake microphone plays the app's own voice, so the
// check hears speech (e2e/mic-check-silence.spec.mjs has the microphone that hears nothing).
import { test, expect } from '@playwright/test';

import { microphone } from './fixtures.mjs';
import { collectErrors, dockedNotice, fixedSentence, openPage } from './helpers.mjs';
import { UA, gate, instrument, micReleased, setMicrophone } from './instrument.mjs';
import { SENTENCE } from './paths.mjs';
import { en, fill, pattern } from './strings.mjs';

test.use(microphone('sentence.wav'));

// No flag in this browser: the tour has never been seen.
const FIRST_VISIT = { storageState: { cookies: [], origins: [] } };

const tour = (page) => page.locator('#tour');
const callout = (page) => page.locator('#tourCallout');
const check = (page) => page.locator('#micCheck');
const checkDialog = (page) => page.locator('#micCheck [role="dialog"]');

// The step's spotlight is around `target`; the callout is on screen and clear of it.
async function expectSpotOn(page, target) {
    const boxes = () => Promise.all([page.locator('#tourSpot'), page.locator(target), callout(page)]
        .map((locator) => locator.boundingBox()));
    await expect.poll(async () => {
        const [spot, box, card] = await boxes();
        const around = spot.x <= box.x && spot.y <= box.y && spot.x + spot.width >= box.x + box.width
            && spot.y + spot.height >= box.y + box.height;
        const clear = card.y >= spot.y + spot.height || card.y + card.height <= spot.y;
        const onScreen = card.y >= 0 && card.y + card.height <= page.viewportSize().height;
        return { around, clear, onScreen };
    }).toEqual({ around: true, clear: true, onScreen: true });
}

test.describe('a first visit', () => {
    test.use(FIRST_VISIT);

    test.describe('on a phone', () => {
        test.skip(({ isMobile }) => !isMobile, 'the tour starts the same way on a computer');

        test('the tour starts once the sentence shows: step 1 over Listen, focus on its title, Tab stays inside', async ({ page }) => {
            const errors = collectErrors(page);
            const sample = gate();
            await page.route('**/getSample', async (route) => {
                await sample.opened;
                await route.fulfill({
                    json: { real_transcript: [SENTENCE], ipa_transcript: '', transcript_translation: '', tts_url: '' },
                });
            });
            await page.goto('/');
            await expect(page.locator('#sentenceCard')).toHaveAttribute('aria-busy', 'true');
            await expect(tour(page)).toBeHidden();
            sample.open();
            await expect(page.locator('#sentence')).toHaveText(SENTENCE);

            await expect(tour(page)).toHaveAttribute('data-step', '1');
            await expect(page.getByRole('dialog', { name: en['tour.listenTitle'] })).toBeVisible();
            await expect(page.locator('#tourStep')).toHaveText(fill(en['tour.step'], { step: 1, total: 3 }));
            await expect(page.locator('#tourTitle')).toBeFocused();
            await expect(page.locator('#tourText')).toHaveText(
                fill(en['tour.listenText'], { listen: en['controls.listen'], slow: en['card.slow'] }));
            await expect(page.locator('#tourSkip')).toHaveText(en['common.skip']);
            await expect(page.locator('#tourNextLabel')).toHaveText(en['tour.next']);
            await expectSpotOn(page, '#btnListen');
            // The page under it rests: inert, and Space records nothing.
            await expect(page.locator('#app')).toHaveJSProperty('inert', true);
            await page.keyboard.press(' ');
            await expect(page.locator('#recordSheet')).toBeHidden();

            // Tab and Shift+Tab go round Skip and Next.
            const skip = page.locator('#tourSkip');
            const next = page.locator('#tourNext');
            for (const [key, focused] of [['Tab', skip], ['Tab', next], ['Tab', skip], ['Shift+Tab', next], ['Shift+Tab', skip]]) {
                await page.keyboard.press(key);
                await expect(focused).toBeFocused();
            }
            expect(errors).toEqual([]);
        });

        test('Next, Next, then Check my mic: the check opens on its explanation; the tour never comes back by itself', async ({ page }) => {
            await fixedSentence(page, SENTENCE);
            await openPage(page);
            await expect(tour(page)).toHaveAttribute('data-step', '1');

            await page.locator('#tourNext').click();
            await expect(tour(page)).toHaveAttribute('data-step', '2');
            await expect(page.getByRole('dialog', { name: en['tour.micTitle'] })).toBeVisible();
            await expect(page.locator('#tourStep')).toHaveText(fill(en['tour.step'], { step: 2, total: 3 }));
            await expect(page.locator('#tourTitle')).toBeFocused();
            await expect(page.locator('#tourText')).toHaveText(fill(en['tour.micText'], { stop: en['controls.stop'] }));
            await expectSpotOn(page, '#btnRecord');

            // The last step: what the marks mean; Done, or the microphone check as the main action.
            await page.locator('#tourNext').click();
            await expect(tour(page)).toHaveAttribute('data-step', '3');
            await expect(page.locator('#tourTitle')).toHaveText(en['tour.resultTitle']);
            await expect(page.locator('#tourTitle')).toBeFocused();
            await expect(page.locator('#tourText')).toHaveText(fill(en['tour.resultText'], {
                almost: en['status.almost'],
                needsWork: en['status.needsWork'],
                letters: en['tour.boldDotted'],
                example: `books${en['status.almost']}`, // "books" with its ~ mark, named
            }));
            await expect(page.locator('#tourSkip')).toHaveText(en['common.done']);
            await expect(page.locator('#tourNextLabel')).toHaveText(en['tour.checkMic']);
            await expectSpotOn(page, '#sentenceCard');

            await page.locator('#tourNext').click();
            await expect(tour(page)).toBeHidden();
            await expect(check(page)).toHaveAttribute('data-state', 'intro');
            await expect(page.getByRole('dialog', { name: en['mic.title'] })).toBeVisible();
            await expect(page.locator('#micTitle')).toBeFocused();
            await page.locator('#micSkip').click();
            await expect(checkDialog(page)).toBeHidden();
            await expect(page.locator('#btnListen')).toBeFocused();

            await page.reload();
            await expect(page.locator('#sentence')).toHaveText(SENTENCE);
            await expect(tour(page)).toBeHidden();
        });

        test('Skip: the tour closes at once, focus on Listen, and it does not come back on the next visit', async ({ page }) => {
            await fixedSentence(page, SENTENCE);
            await openPage(page);
            await expect(tour(page)).toHaveAttribute('data-step', '1');
            await page.locator('#tourSkip').click();
            await expect(tour(page)).toBeHidden();
            await expect(page.locator('#btnListen')).toBeFocused();
            await expect(page.locator('#app')).toHaveJSProperty('inert', false);

            await page.reload();
            await expect(page.locator('#sentence')).toHaveText(SENTENCE);
            await expect(tour(page)).toBeHidden();
        });

        test('not over a sheet the learner opened first; then on the next visit', async ({ page }) => {
            const sample = gate();
            await page.route('**/getSample', async (route) => {
                await sample.opened;
                await route.fulfill({
                    json: { real_transcript: [SENTENCE], ipa_transcript: '', transcript_translation: '', tts_url: '' },
                });
            });
            await page.goto('/');
            await page.locator('#btnMyText').click();
            const myText = page.getByRole('dialog', { name: en['mytext.title'] });
            await expect(myText).toBeVisible();
            sample.open();
            await expect(page.locator('#sentence')).toHaveText(SENTENCE);
            await expect(tour(page)).toBeHidden();
            await expect(myText).toBeVisible();

            await page.keyboard.press('Escape');
            await expect(myText).toBeHidden();
            await page.reload();
            await expect(tour(page)).toHaveAttribute('data-step', '1');
        });

        test.describe('inside an app\'s browser', () => {
            test.use({ userAgent: UA.zaloAndroid });

            test('the banner speaks first: no tour', async ({ page }) => {
                await fixedSentence(page, SENTENCE);
                await openPage(page);
                await expect(page.locator('#bannerSlot .banner')).toBeVisible();
                await expect(tour(page)).toBeHidden();
            });
        });

        test('where the browser keeps nothing: no tour (it would come back on every visit)', async ({ page }) => {
            await page.addInitScript(() => {
                Storage.prototype.setItem = () => {
                    throw new DOMException('Refused', 'SecurityError');
                };
            });
            await fixedSentence(page, SENTENCE);
            await openPage(page);
            await expect(tour(page)).toBeHidden();
        });

        test.describe('a browser that cannot record', () => {
            test.beforeEach(async ({ page }) => {
                await page.addInitScript(() => {
                    delete window.MediaRecorder;
                });
            });

            test('its notice speaks first: no tour; How it works gives one that ends with Done, and no check', async ({ page }) => {
                await fixedSentence(page, SENTENCE);
                await openPage(page);
                await expect(dockedNotice(page)).toHaveAttribute('data-notice', 'cannotRecord');
                await expect(tour(page)).toBeHidden();

                const again = page.getByRole('button', { name: en['how.tourAgain'] });
                await again.click();
                await expect(tour(page)).toHaveAttribute('data-step', '1');
                await page.locator('#tourNext').click();
                await page.locator('#tourNext').click();
                await expect(tour(page)).toHaveAttribute('data-step', '3');
                await expect(page.locator('#tourNextLabel')).toHaveText(en['common.done']);
                await expect(page.locator('#tourSkip')).toBeHidden();
                await page.locator('#tourNext').click();
                await expect(tour(page)).toBeHidden();
                await expect(again).toBeFocused();
                await expect(check(page)).toBeHidden();

                // Check my microphone says why it does nothing: its tap points to the notice.
                const checkButton = page.getByRole('button', { name: en['how.micCheck'] });
                await expect(checkButton).toHaveAttribute('aria-disabled', 'true');
                await checkButton.click({ force: true });
                await expect(dockedNotice(page)).toBeFocused();
                await expect(check(page)).toBeHidden();
            });
        });
    });
});

test.describe('How it works, on a phone', () => {
    test.skip(({ isMobile }) => !isMobile, 'from 1024 px the header has the link');

    test('Show the tour again; Escape closes it, focus back on the button', async ({ page }) => {
        await fixedSentence(page, SENTENCE);
        await openPage(page);
        await expect(tour(page)).toBeHidden(); // a returning learner
        await expect(page.locator('#btnHowHeader')).toBeHidden();
        const again = page.getByRole('button', { name: en['how.tourAgain'] });
        await again.click();
        await expect(tour(page)).toHaveAttribute('data-step', '1');
        await expect(page.locator('#tourTitle')).toBeFocused();
        await page.locator('#tourNext').click();
        await expect(tour(page)).toHaveAttribute('data-step', '2');
        await page.keyboard.press('Escape');
        await expect(tour(page)).toBeHidden();
        await expect(again).toBeFocused();
        await expect(page.locator('#app')).toHaveJSProperty('inert', false);
    });
});

test.describe('How it works, on a computer', () => {
    test.skip(({ isMobile }) => isMobile, 'phones have no header link');

    test('the header\'s link starts the tour, in a computer\'s words, over the inline controls', async ({ page }) => {
        await fixedSentence(page, SENTENCE);
        await openPage(page);
        await expect(page.getByRole('button', { name: en['how.tourAgain'] })).toBeHidden();
        const how = page.locator('#btnHowHeader');
        await expect(how).toHaveText(en['how.title']);
        await how.click();
        await expect(tour(page)).toHaveAttribute('data-step', '1');
        await expect(page.locator('#tourText')).toHaveText(
            fill(en['tour.listenTextWide'], { listen: en['controls.listen'], slow: en['card.slow'] }));
        await expectSpotOn(page, '#btnListen');

        await page.locator('#tourNext').click();
        await expect(page.locator('#tourTitle')).toHaveText(en['tour.micTitleWide']);
        await expect(page.locator('#tourText')).toHaveText(
            fill(en['tour.micTextWide'], { stop: en['controls.stop'], space: en['controls.space'] }));
        await expectSpotOn(page, '#btnRecord');

        await page.locator('#tourNext').click();
        await expect(page.locator('#tourText')).toHaveText(fill(en['tour.resultTextWide'], {
            almost: en['status.almost'], needsWork: en['status.needsWork'], letters: en['tour.boldDotted'],
            example: `books${en['status.almost']}`,
        }));
        await page.keyboard.press('Escape');
        await expect(tour(page)).toBeHidden();
        await expect(how).toBeFocused();
    });
});

test.describe('the microphone check', () => {
    // Opened from How it works (E10).
    async function openCheck(page) {
        await page.getByRole('button', { name: en['how.micCheck'] }).click();
        await expect(check(page)).toHaveAttribute('data-state', 'intro');
        await expect(page.locator('#micTitle')).toBeFocused();
    }

    test.describe('on a phone', () => {
        test.skip(({ isMobile }) => !isMobile, 'the check is the same on a computer; its blocked steps are tested there');

        test('the prompt explained first, 3 s of listening, "works"; Start practising goes to Listen; the microphone let go, nothing recorded or sent', async ({ page }) => {
            const errors = collectErrors(page);
            await instrument(page, { permission: 'prompt' });
            await fixedSentence(page, SENTENCE);
            await openPage(page);
            const sent = [];
            page.on('request', (request) => {
                if (request.method() !== 'GET') sent.push(request.url());
            });

            // E5: what happens, and the browser's question explained before it comes.
            await openCheck(page);
            await expect(page.getByRole('dialog', { name: en['mic.title'] })).toBeVisible();
            await expect(page.locator('#micMsg')).toHaveText(en['mic.intro']);
            await expect(page.locator('#micHint')).toHaveText(fill(en['mic.allow'], { allow: en['rec.ui.allow'] }));
            await expect(page.locator('#micSkip')).toHaveText(en['common.skip']);
            await expect(page.locator('#micStart')).toHaveText(en['mic.start']);
            expect(await page.evaluate(() => window.__e2e.calls)).toBe(0);

            // E6: listening, said; the meter is decoration and moves with the voice.
            await page.locator('#micStart').click();
            await expect(check(page)).toHaveAttribute('data-state', 'listening');
            await expect(page.locator('#micTitle')).toHaveText(en['mic.listening']);
            await expect(page.locator('#micTimer')).toHaveText(pattern(en['mic.timer']));
            await expect(page.locator('#micHint')).toHaveText(pattern(en['mic.keepTalking.other']));
            await expect(page.locator('#micSkip')).toHaveText(en['common.cancel']);
            await expect(page.locator('#micStatus')).toHaveText(en['mic.listeningAnnounce']);
            await expect(page.locator('#micMeter')).toHaveAttribute('aria-hidden', 'true');
            await expect.poll(() => page.locator('#micMeter i.is-lit').count()).toBeGreaterThan(0);

            // E7: heard; focus on Start practising, the outcome said.
            await expect(check(page)).toHaveAttribute('data-state', 'works', { timeout: 10_000 });
            await expect(page.locator('#micTitle')).toHaveText(en['mic.works']);
            await expect(page.locator('#micMsg')).toHaveText(en['mic.worksText']);
            await expect(page.locator('#micHint')).toHaveText(en['mic.tip']);
            const practise = page.getByRole('button', { name: en['mic.startPractising'] });
            await expect(practise).toBeFocused();
            await expect(page.locator('#micStatus')).toHaveText(`${en['mic.works']} ${en['mic.worksText']}`);
            expect(await micReleased(page)).toBe(true);

            await practise.click();
            await expect(checkDialog(page)).toBeHidden();
            await expect(page.locator('#btnListen')).toBeFocused();
            expect(await page.evaluate(() => window.__e2e.calls)).toBe(1);
            expect(await page.evaluate(() => window.__e2e.recorders.length)).toBe(0);
            expect(sent).toEqual([]);
            expect(errors).toEqual([]);
        });

        test('blocked: the steps of Chrome on Android; Try again asks again; Cancel lets the microphone go at once', async ({ page }) => {
            await instrument(page, { gum: 'NotAllowedError' });
            await fixedSentence(page, SENTENCE);
            await openPage(page);
            await openCheck(page);
            await page.locator('#micStart').click();
            await expect(check(page)).toHaveAttribute('data-state', 'mic-blocked');
            await expect(check(page)).toHaveAttribute('data-detail', 'android');
            await expect(page.locator('#micTitle')).toHaveText(en['rec.blocked.title']);
            await expect(page.locator('#micLead')).toHaveText(en['rec.blocked.lead']);
            await expect(page.locator('#micText')).toHaveText(en['rec.blocked.howChrome']);
            await expect(page.locator('#micSteps li')).toHaveText([
                fill(en['rec.blocked.android1'], { lock: en['rec.ui.lock'], tune: en['rec.ui.tune'] }),
                fill(en['rec.blocked.android2'], {
                    permissions: en['rec.ui.permissions'], microphone: en['rec.ui.microphone'], allow: en['rec.ui.allow'],
                }),
                fill(en['rec.blocked.androidLast'], { tryAgain: en['common.tryAgain'] }),
            ]);
            await expect(page.locator('#micAlert')).toContainText(en['rec.blocked.title']);
            await expect(page.locator('#micTryAgain')).toBeFocused();
            await expect(page.locator('#micSkip')).toHaveText(en['common.skip']);

            // Allowed in the settings meanwhile: Try again asks, and listens.
            await setMicrophone(page, 'real');
            await page.locator('#micTryAgain').click();
            await expect(check(page)).toHaveAttribute('data-state', 'listening');
            expect(await page.evaluate(() => window.__e2e.calls)).toBe(2);
            expect(await micReleased(page)).toBe(false);
            await page.locator('#micSkip').click();
            await expect(checkDialog(page)).toBeHidden();
            expect(await micReleased(page)).toBe(true);
            await expect(page.getByRole('button', { name: en['how.micCheck'] })).toBeFocused();
        });

        // The blocked message's words stay in #micLead and #micText inside the hidden #micMessage: "works" must
        // not say them too ("This site is not allowed to use the microphone. To allow it in Chrome:").
        test('allowed after being blocked: "works" says only its own words', async ({ page }) => {
            await instrument(page, { gum: 'NotAllowedError' });
            await fixedSentence(page, SENTENCE);
            await openPage(page);
            await openCheck(page);
            await page.locator('#micStart').click();
            await expect(check(page)).toHaveAttribute('data-state', 'mic-blocked');
            await setMicrophone(page, 'real');
            await page.locator('#micTryAgain').click();
            await expect(check(page)).toHaveAttribute('data-state', 'works', { timeout: 10_000 });
            await expect(page.locator('#micStatus')).toHaveText(`${en['mic.works']} ${en['mic.worksText']}`);
        });

        test.describe('Zalo on Android', () => {
            test.use({ userAgent: UA.zaloAndroid });

            test('inside the app: Open in Chrome and Copy link instead of the steps', async ({ page, baseURL }) => {
                await instrument(page, { gum: 'NotAllowedError', clipboard: 'ok' });
                await fixedSentence(page, SENTENCE);
                await openPage(page);
                await openCheck(page);
                await page.locator('#micStart').click();
                await expect(check(page)).toHaveAttribute('data-state', 'in-app');
                await expect(check(page)).toHaveAttribute('data-detail', 'android');
                await expect(page.locator('#micTitle')).toHaveText(fill(en['inapp.title'], { app: 'Zalo' }));
                await expect(page.locator('#micLead')).toHaveText(fill(en['inapp.lead'], { app: 'Zalo' }));
                await expect(page.locator('#micText')).toHaveText(en['inapp.chrome']);
                await expect(page.locator('#micSteps')).toBeHidden();
                const address = new URL('/', baseURL);
                const openChrome = checkDialog(page).getByRole('link', { name: en['inapp.openChrome'] });
                await expect(openChrome).toHaveAttribute('href',
                    `intent://${address.host}${address.pathname}#Intent;scheme=${address.protocol.replace(':', '')};`
                    + `package=com.android.chrome;S.browser_fallback_url=${encodeURIComponent(address.href)};end`);
                await expect(openChrome).toBeFocused();
                await expect(page.locator('#micSkip')).toHaveText(en['common.close']);

                // Copy link says so in the sheet's polite region; the address is in the clipboard.
                await page.locator('#micCopyLink').click();
                await expect(page.locator('#micCopyLabel')).toHaveText(en['notice.linkCopied.title']);
                await expect(page.locator('#micStatus')).toHaveText(en['notice.linkCopied.title']);
                expect(await page.evaluate(() => window.__e2e.copied)).toBe(address.href);
            });
        });

        test.describe('Messenger on iPhone', () => {
            test.use({ userAgent: UA.messengerIos });

            test('inside the app: the steps through its ••• menu, Copy link first, and the pointer to the menu', async ({ page }) => {
                await instrument(page, { gum: 'NotAllowedError' });
                await fixedSentence(page, SENTENCE);
                await openPage(page);
                await openCheck(page);
                await page.locator('#micStart').click();
                await expect(check(page)).toHaveAttribute('data-state', 'in-app');
                await expect(check(page)).toHaveAttribute('data-detail', 'ios');
                await expect(page.locator('#micTitle')).toHaveText(en['inapp.iosTitle']);
                await expect(page.locator('#micLead')).toHaveText(en['inapp.iosLead']);
                await expect(page.locator('#micText')).toHaveText(en['inapp.iosHow']);
                await expect(page.locator('#micSteps li')).toHaveText([
                    pattern(en['inapp.ios1']), // {dots}: the app's ••• button
                    fill(en['inapp.ios2'], { openInSafari: en['inapp.openInSafari'], openInBrowser: en['inapp.openInBrowser'] }),
                ]);
                await expect(page.locator('#micCopyLink')).toBeFocused();
                await expect(page.locator('#micCopyLink')).toHaveClass(/btn-primary/);
                await expect(page.locator('#micOpenChrome')).toBeHidden();
                const pointer = page.locator('#micCheck .inapp-pointer');
                await expect(pointer).toBeVisible();
                await expect(pointer).toHaveText(en['inapp.pointer']);
                await page.locator('#micSkip').click();
                await expect(checkDialog(page)).toBeHidden();
                await expect(pointer).toBeHidden();
            });
        });
    });

    test.describe('on a computer', () => {
        test.skip(({ isMobile }) => isMobile, 'the steps of a computer\'s browser');

        test('blocked: the steps of the address bar; a dialog in the middle', async ({ page }) => {
            await instrument(page, { gum: 'NotAllowedError' });
            await fixedSentence(page, SENTENCE);
            await openPage(page);
            await openCheck(page);
            await page.locator('#micStart').click();
            await expect(check(page)).toHaveAttribute('data-state', 'mic-blocked');
            await expect(check(page)).toHaveAttribute('data-detail', 'desktop');
            await expect(page.locator('#micText')).toHaveText(en['rec.blocked.how']);
            await expect(page.locator('#micSteps li')).toHaveText([
                fill(en['rec.blocked.desktop1'], { lock: en['rec.ui.lock'], tune: en['rec.ui.tune'] }),
                fill(en['rec.blocked.desktop2'], { microphone: en['rec.ui.microphone'], allow: en['rec.ui.allow'] }),
                fill(en['rec.blocked.desktopLast'], { tryAgain: en['common.tryAgain'] }),
            ]);
            await expect(page.locator('#micTryAgain')).toBeFocused();
            // From 768 px the check is a dialog in the middle of the screen.
            const box = await checkDialog(page).boundingBox();
            expect(Math.abs(box.x + box.width / 2 - page.viewportSize().width / 2)).toBeLessThanOrEqual(1);
        });
    });
});
