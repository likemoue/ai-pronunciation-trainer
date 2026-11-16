// The recording sheet (wireframes page 2, B1-B6, B19-B21; H3 on a computer): a
// take from the tap to Whisper's score, the limits of a take, its keys, and
// what must never happen while it records. The fake microphone plays the app's
// own voice reading SENTENCE (e2e/global-setup.mjs).
import { readFileSync } from 'node:fs';
import path from 'node:path';

import { test, expect } from '@playwright/test';

import { microphone } from './fixtures.mjs';
import { collectErrors, fixedSentence, openPage } from './helpers.mjs';
import {
    dialog, expectState, gate, inVietnamese, instrument, micReleased, pauseClock, recordAndStop, recordFor, routeScore,
    said, scoreAborted, scoreSentAt, sheet, soundsInSheet, startTake, takeStartedAt, tap,
} from './instrument.mjs';
import { AUDIO_DIR, SENTENCE } from './paths.mjs';
import { en, fill, pattern, vi } from './strings.mjs';

test.use(microphone('sentence.wav'));

const LONG_TEXT = 'Every morning before school, I help my mother make breakfast for the whole family. We usually have '
    + 'rice, eggs and some fresh fruit. After that, I walk to the bus stop with my little brother Nam, and we talk '
    + 'about our favourite games. On the bus I like to read a short funny story until we arrive.';

// The sheet's entrance (200 ms) is over: its boxes are where they stay.
const settled = (page) => dialog(page)
    .evaluate((node) => Promise.all(node.getAnimations().map((animation) => animation.finished)));

test.describe('on a phone', () => {
    test.skip(({ isMobile }) => !isMobile, 'a take is the same on a computer; its keys and dialog are tested there');

    test('a take: recording, checking, then a real score, with focus on the result', async ({ page }) => {
        const errors = collectErrors(page);
        await instrument(page);
        const release = gate();
        const bodies = await routeScore(page, async (route) => {
            await release.opened; // held while checking is looked at
            await route.continue();
        });
        await fixedSentence(page, SENTENCE);
        await openPage(page);

        await startTake(page);
        await expect(page.locator('#recTitle')).toHaveText(en['rec.recording']);
        await expect(page.locator('#recStop')).toBeFocused();
        await expect(page.locator('#recSentence')).toHaveText(SENTENCE);
        await expect(page.locator('#recHint')).toHaveText(fill(en['rec.hint'], { stop: en['controls.stop'] }));
        // The timer counts towards the 30 s limit; by 3 s the whole sentence is in the take.
        await recordFor(page, 3);
        await expect(page.locator('#recTimer')).toHaveText(/^0:0[3-9] \/ 0:30$/);
        await page.locator('#recStop').click();

        await expectState(page, 'checking');
        await expect(page.locator('#recTitle')).toHaveText(en['rec.checking']);
        await expect(page.locator('#recTitle')).toBeFocused();
        await expect(page.locator('#recStop')).toBeHidden();
        await expect(page.locator('#recHint')).toHaveText(en['rec.checkingHint']);
        // Each phase said once in the sheet's polite region.
        await expect.poll(() => said(page)).toEqual([en['rec.recording'], en['rec.checkingAnnounce']]);
        release.open();

        // Whisper's score: the sheet closes and the result takes focus.
        await expect(dialog(page)).toBeHidden({ timeout: 30_000 });
        await expectState(page, 'idle');
        await expect(page.locator('#resultTitle')).not.toBeEmpty();
        await expect(page.locator('#resultTitle')).toBeFocused();
        expect(bodies).toHaveLength(1);
        expect(JSON.parse(bodies[0])).toMatchObject({
            title: SENTENCE, language: 'en', base64Audio: expect.stringMatching(/^data:audio\//),
        });
        expect(await soundsInSheet(page)).toEqual([]);
        expect(await micReleased(page)).toBe(true);
        expect(errors).toEqual([]);
    });

    test('in Vietnamese: the take, and three actions with the primary on its own row', async ({ page, context, baseURL }) => {
        await inVietnamese(context, baseURL);
        await instrument(page);
        await routeScore(page, (route) => route.fulfill({ status: 502, body: 'Bad gateway' }));
        await fixedSentence(page, SENTENCE);
        await openPage(page);

        await startTake(page);
        await expect(page.locator('#recTitle')).toHaveText(vi['rec.recording']);
        await expect(page.locator('#recHint')).toHaveText(fill(vi['rec.hint'], { stop: vi['controls.stop'] }));
        await expect(page.locator('#recStop')).toHaveText(vi['rec.stopCheck']);
        await expect(page.locator('#recCancel')).toHaveText(vi['common.cancel']);
        // The practice text stays English.
        await expect(page.locator('#recSentence')).toHaveAttribute('lang', 'en');

        await recordFor(page, 1);
        await page.locator('#recStop').click();
        await expectState(page, 'failed', 'network');
        await expect(page.locator('#recTitle')).toHaveText(vi['rec.failed.title']);
        await expect(page.locator('#recSend')).toHaveText(vi['rec.sendAgain']);
        await expect(page.locator('#recRecordAgain')).toHaveText(vi['rec.recordAgain']);
        await expect(page.locator('#recCancel')).toHaveText(vi['common.close']);
        // Wireframes B21: Send again on a row of its own, then Record again (the
        // larger part) and Close; no label cut.
        const rows = await page.evaluate(() => ['recSend', 'recRecordAgain', 'recCancel'].map((id) => {
            const node = document.getElementById(id);
            const box = node.getBoundingClientRect();
            return { top: Math.round(box.top), width: Math.round(box.width), fits: node.scrollWidth <= node.clientWidth };
        }));
        expect(rows[0].top).toBeLessThan(rows[1].top);
        expect(rows[1].top).toBe(rows[2].top);
        expect(rows[1].width).toBeGreaterThan(rows[2].width);
        expect(rows.map((row) => row.fits)).toEqual([true, true, true]);
    });

    test('Cancel while the browser still asks: the mic still works, and the late answer is let go', async ({ page }) => {
        await instrument(page, { gum: 'pending' });
        await fixedSentence(page, SENTENCE);
        await openPage(page);

        await page.locator('#btnRecord').click();
        await expectState(page, 'preparing');
        await expect(page.locator('#recTitle')).toHaveText(en['rec.preparing']);
        await expect(page.locator('#recTitle')).toBeFocused();
        await expect(page.locator('#waveOverlayText')).toHaveText(en['rec.allow']);
        await expect(page.locator('#recStop')).toHaveAttribute('aria-disabled', 'true');
        await tap(page.locator('#recCancel'));
        await expectState(page, 'idle');
        await expect(dialog(page)).toBeHidden();
        await expect(page.locator('#btnRecord')).toBeFocused();

        // A new take while the first prompt is still open.
        await page.locator('#btnRecord').click();
        await expectState(page, 'preparing');
        // The first prompt is answered now: its stream belongs to no take and is stopped.
        await page.evaluate(() => window.__e2e.prompts[0].allow());
        await expect.poll(() => page.evaluate(() => window.__e2e.streams.map((stream) => stream.getAudioTracks()[0].readyState)))
            .toEqual(['ended']);
        await expectState(page, 'preparing');
        await page.evaluate(() => window.__e2e.prompts[1].allow());
        await expectState(page, 'recording');
        await expect(page.locator('#recStop')).toBeFocused();
        await tap(page.locator('#recCancel'));
        await expectState(page, 'idle');
        expect(await micReleased(page)).toBe(true);
    });

    test('a double tap on Stop does not land on Cancel', async ({ page }) => {
        await instrument(page);
        const bodies = await routeScore(page, () => {}); // unanswered: the sheet stays on checking
        await fixedSentence(page, SENTENCE);
        await openPage(page);
        await startTake(page);
        await recordFor(page, 1);
        const stop = await page.locator('#recStop').boundingBox();
        const point = [stop.x + stop.width / 2, stop.y + stop.height / 2];
        await page.mouse.dblclick(...point);
        await expectState(page, 'checking');
        // Cancel took Stop's place: the second tap reached it, and was ignored.
        expect(await page.evaluate(([x, y]) => document.elementFromPoint(x, y).closest('button').id, point)).toBe('recCancel');
        await expect.poll(() => bodies.length).toBe(1);
    });

    test('a tap on the backdrop does nothing', async ({ page }) => {
        await instrument(page);
        await fixedSentence(page, SENTENCE);
        await openPage(page);
        await startTake(page);
        await settled(page);
        const box = await dialog(page).boundingBox();
        const point = [box.x + box.width / 2, box.y / 2];
        expect(await page.evaluate(([x, y]) => document.elementFromPoint(x, y).className, point)).toBe('backdrop');
        await page.mouse.click(...point);
        await expectState(page, 'recording');
        await expect(page.locator('#recStop')).toBeFocused();
    });

    test('the reference voice still loading never plays into the take', async ({ page }) => {
        await instrument(page);
        const voice = gate();
        await page.route('**/getAudioFromText', async (route) => {
            await voice.opened;
            // The app's own voice, answered late (the page may have given up on it).
            const wavBase64 = readFileSync(path.join(AUDIO_DIR, 'sentence.wav')).toString('base64');
            await route.fulfill({ json: { wavBase64 } }).catch(() => {});
        });
        await fixedSentence(page, SENTENCE);
        await openPage(page);
        const listen = page.locator('#btnListen');
        await listen.click();
        await expect(listen).toHaveAttribute('data-state', 'loading');

        await startTake(page);
        // The voice is dropped when the sheet opens, and every sound is held while it is open.
        await expect(listen).toHaveAttribute('data-state', 'idle');
        voice.open();
        await recordFor(page, 1); // the late answer has come by now
        expect(await page.evaluate(() => ({ owner: window.AIPT.audio.owner, held: window.AIPT.audio.held })))
            .toEqual({ owner: '', held: true });
        await tap(page.locator('#recCancel'));
        await expectState(page, 'idle');
        expect(await page.evaluate(() => window.AIPT.audio.held)).toBe(false);
        // Nothing played, in the take or after it.
        expect(await page.evaluate(() => window.__e2e.sounds)).toEqual([]);
    });

    test('the 30 s limit: counted down from 25 s and said once, then the take stops and is sent by itself', async ({ page }) => {
        await page.clock.install();
        await instrument(page);
        const bodies = await routeScore(page, () => {}); // unanswered: the sheet stays on checking
        await fixedSentence(page, SENTENCE);
        await openPage(page);
        await startTake(page);
        await recordFor(page, 1); // speech in the take, for the page's own silence check

        // On to just before 25 s into the take, the clock held there; then past it.
        await pauseClock(page, (await takeStartedAt(page)) + 24_900);
        await expect(page.locator('#recTimer')).toHaveText('0:24 / 0:30');
        await expect(sheet(page)).not.toHaveAttribute('data-hint', 'ending');
        await page.clock.runFor(300); // the timer's next tick (4 a second)
        await expect(sheet(page)).toHaveAttribute('data-hint', 'ending');
        await expect(page.locator('#recTimer')).toHaveText('0:25 / 0:30');
        await expect(page.locator('#recHint')).toHaveText(fill(en['rec.stoppingIn'], { seconds: 5 }));
        await expect(page.locator('#recHint')).toHaveClass(/is-warning/);
        await page.clock.runFor(1_000);
        await expect(page.locator('#recHint')).toHaveText(fill(en['rec.stoppingIn'], { seconds: 4 }));

        await page.clock.runFor(4_000);
        await expectState(page, 'checking');
        await expect.poll(() => bodies.length).toBe(1);
        const countdown = pattern(en['rec.stoppingIn']);
        expect((await said(page)).filter((text) => countdown.test(text)))
            .toEqual([fill(en['rec.stoppingIn'], { seconds: 5 })]);
    });

    test('checking: "still checking" in neutral words after 8 s; Cancel gives up the request', async ({ page }) => {
        await page.clock.install();
        await instrument(page);
        const bodies = await routeScore(page, () => {}); // unanswered
        await fixedSentence(page, SENTENCE);
        await openPage(page);
        await recordAndStop(page);
        await expectState(page, 'checking');
        await expect.poll(() => bodies.length).toBe(1);
        await expect(page.locator('#recHint')).toHaveText(en['rec.checkingHint']);
        // The 8 s count from the request.
        await pauseClock(page, (await scoreSentAt(page)) + 7_900);
        await expect(page.locator('#recHint')).toHaveText(en['rec.checkingHint']);
        await page.clock.runFor(200);
        await expect(page.locator('#recHint')).toHaveText(en['rec.stillChecking']);
        await expect(page.locator('#recHint')).not.toHaveClass(/is-warning/);
        await expect.poll(() => said(page)).toContain(en['rec.stillChecking']);

        const aborted = scoreAborted(page);
        await tap(page.locator('#recCancel'));
        await expectState(page, 'idle');
        await aborted;
        await expect(page.locator('#btnRecord')).toBeFocused();
    });

    test.describe('320 x 568', () => {
        test.use({ viewport: { width: 320, height: 568 } });

        test('a long text scrolls in its own area, header and actions in view; Space there scrolls it', async ({ page }) => {
            await instrument(page);
            await fixedSentence(page, LONG_TEXT);
            await openPage(page);
            await startTake(page);
            await settled(page);
            const area = page.locator('#recSentence');
            // It scrolls, so it takes focus (keys scroll it too).
            await expect(area).toHaveAttribute('tabindex', '0');
            const box = await page.evaluate(() => {
                const sentence = document.getElementById('recSentence');
                const rect = (id) => document.getElementById(id).getBoundingClientRect();
                return {
                    scrolls: sentence.scrollHeight > sentence.clientHeight,
                    height: sentence.clientHeight,
                    titleTop: rect('recTitle').top,
                    actionsBottom: Math.max(rect('recStop').bottom, rect('recCancel').bottom),
                };
            });
            expect(box.scrolls).toBe(true);
            expect(box.height).toBeLessThanOrEqual(Math.ceil(568 * 0.35) + 1);
            expect(box.titleTop).toBeGreaterThanOrEqual(0);
            expect(box.actionsBottom).toBeLessThanOrEqual(568);

            // Space on the sentence is the sentence's: it scrolls, the take goes on.
            await area.focus();
            await page.keyboard.press(' ');
            await expect.poll(() => area.evaluate((node) => node.scrollTop)).toBeGreaterThan(0);
            await expectState(page, 'recording');
        });
    });
});

test.describe('on a computer', () => {
    test.skip(({ isMobile }) => isMobile, 'the dialog and the keys of a computer');

    test('the dialog: centred, its hint names Space; Space on the dialog stops, Escape gives up the check', async ({ page }) => {
        await instrument(page);
        const bodies = await routeScore(page, () => {}); // unanswered
        await fixedSentence(page, SENTENCE);
        await openPage(page);
        await startTake(page);
        await settled(page);
        await expect(page.locator('#recHint')).toHaveText(
            fill(en['rec.hintWide'], { stop: en['controls.stop'], space: en['controls.space'] }));
        const viewport = page.viewportSize();
        const box = await dialog(page).boundingBox();
        expect(Math.abs(box.x + box.width / 2 - viewport.width / 2)).toBeLessThanOrEqual(1);
        expect(box.y + box.height).toBeLessThan(viewport.height - 16);

        await recordFor(page, 1);
        // A click on the dialog's text puts focus on the dialog; Space there is Stop.
        await page.locator('#recordSheet .eyebrow').click();
        await page.keyboard.press(' ');
        await expectState(page, 'checking');
        await expect(page.locator('#recTitle')).toBeFocused();
        await expect.poll(() => bodies.length).toBe(1);

        const aborted = scoreAborted(page);
        await page.keyboard.press('Escape');
        await expectState(page, 'idle');
        await aborted;
        await expect(page.locator('#btnRecord')).toBeFocused();
    });

    test('Enter and Space on Cancel cancel the take, never stop it', async ({ page }) => {
        await instrument(page);
        const bodies = await routeScore(page, () => {}); // a take sent by mistake would stay on checking
        await fixedSentence(page, SENTENCE);
        await openPage(page);

        for (const key of ['Enter', ' ']) {
            // The mic by the keyboard too, then the key on Cancel.
            await page.locator('#btnRecord').focus();
            await page.keyboard.press(key);
            await expectState(page, 'recording');
            await recordFor(page, 1); // a take that Stop would send
            await page.locator('#recCancel').focus();
            await page.keyboard.press(key);
            await expectState(page, 'idle');
            await expect(page.locator('#btnRecord')).toBeFocused();
        }
        expect(bodies).toEqual([]);
    });

    test('holding Space: the sheet opens and records, the key\'s repeats do not stop it; Escape cancels', async ({ page }) => {
        await instrument(page);
        const bodies = await routeScore(page, () => {}); // a take sent by mistake would stay on checking
        await fixedSentence(page, SENTENCE);
        await openPage(page);
        await page.evaluate(() => {
            window.__repeats = 0;
            document.addEventListener('keydown', (event) => {
                if (event.repeat) window.__repeats += 1;
            }, true);
            document.activeElement.blur();
        });

        // Space on the page opens the sheet; held down, the key repeats about
        // every 50 ms while the browser asks for the microphone and the take begins.
        await page.keyboard.down(' ');
        await expect(dialog(page)).toBeVisible();
        for (let i = 0; i < 100 && (await sheet(page).getAttribute('data-state')) !== 'recording'; i += 1) {
            await page.keyboard.down(' ');
            await page.waitForTimeout(50);
        }
        for (let i = 0; i < 10; i += 1) {
            await page.keyboard.down(' ');
            await page.waitForTimeout(50);
        }
        await page.keyboard.up(' ');
        await expectState(page, 'recording');
        await expect(page.locator('#recStop')).toBeFocused();
        expect(await page.evaluate(() => window.__repeats)).toBeGreaterThanOrEqual(10);

        // Escape gives up the take: nothing sent, the mic let go, focus back on the mic button.
        await page.keyboard.press('Escape');
        await expectState(page, 'idle');
        await expect(page.locator('#btnRecord')).toBeFocused();
        expect(await micReleased(page)).toBe(true);
        expect(bodies).toEqual([]);
    });
});
