// A take that cannot be scored (wireframes page 2, B7-B12): a busy server,
// failures that sending again can fix (the recording is kept), offline, no
// speech, too short, interrupted, and a recording the server refuses.
import { test, expect } from '@playwright/test';

import { microphone } from './fixtures.mjs';
import { dockedNotice, fixedSentence, openPage } from './helpers.mjs';
import {
    answerWith, dialog, expectState, instrument, micReleased, pauseClock, recordAndStop, recordFor, routeScore, said,
    scoreSentAt, setHidden, startTake, tap,
} from './instrument.mjs';
import { SENTENCE } from './paths.mjs';
import { en, pattern } from './strings.mjs';

test.use(microphone('sentence.wav'));

test.skip(({ isMobile }) => !isMobile, 'the states are the same on a computer');

test.beforeEach(async ({ page }) => {
    await fixedSentence(page, SENTENCE);
});

const BUSY_TRIES = 3;
const overlayLine = (page, index) => page.locator('#waveOverlayText .wave-line').nth(index);
const countdown = (attempt) => pattern(en['rec.busyCountdown'], { attempt, total: BUSY_TRIES });
const busyAnswer = (retryAfter) => answerWith(503, 'busy', { 'Retry-After': String(retryAfter) });

test('a busy server: counted down, the same recording sent again by itself, then scored', async ({ page }) => {
    await page.clock.install();
    await instrument(page);
    const bodies = await routeScore(page, (route, n) => (n <= 2 ? busyAnswer(3)(route) : route.continue()));
    await openPage(page);
    await startTake(page);
    await recordFor(page, 3); // the whole sentence, for a real score
    // The clock held from here: the waits move only when the test says.
    await pauseClock(page);
    await page.locator('#recStop').click();

    await expectState(page, 'busy');
    await expect(overlayLine(page, 0)).toHaveText(en['rec.busyLine']);
    await expect(overlayLine(page, 1)).toHaveText(countdown(1));
    await expect(page.locator('#recHint')).toHaveText(en['rec.busyHint']);
    await expect(page.locator('#recSend')).toBeHidden();
    await expect(page.locator('#recCancel')).toHaveText(en['common.cancel']);
    // The wait is Retry-After and up to 2 s more, counted down on screen.
    const seconds = async () => Number(countdown(1).exec(await overlayLine(page, 1).textContent())[1]);
    const first = await seconds();
    expect(first).toBeGreaterThanOrEqual(3);
    expect(first).toBeLessThanOrEqual(5);
    await page.clock.runFor(1_000);
    await expect.poll(seconds).toBe(first - 1);

    // Sent again when the wait is over: busy once more, then scored.
    await page.clock.runFor((first - 1) * 1_000);
    await expect(overlayLine(page, 1)).toHaveText(countdown(2));
    expect(bodies).toHaveLength(2);
    await page.clock.runFor(5_000);
    await expect(dialog(page)).toBeHidden({ timeout: 30_000 });
    await expectState(page, 'idle');
    await expect(page.locator('#resultTitle')).not.toBeEmpty();
    expect(bodies).toHaveLength(3);
    expect(new Set(bodies).size).toBe(1); // the same recording each time
    // Said when the first wait starts, not at each one.
    expect((await said(page)).filter((text) => text === en['rec.busyAnnounce'])).toHaveLength(1);
});

test('still busy after three more tries: failed, the recording kept', async ({ page }) => {
    await page.clock.install();
    await instrument(page);
    const bodies = await routeScore(page, busyAnswer(1));
    await openPage(page);
    await startTake(page);
    await recordFor(page, 1);
    await pauseClock(page);
    await page.locator('#recStop').click();
    for (let attempt = 1; attempt <= BUSY_TRIES; attempt += 1) {
        await expect(overlayLine(page, 1)).toHaveText(countdown(attempt));
        await page.clock.runFor(3_000); // Retry-After (1 s) and up to 2 s more
    }
    await expectState(page, 'failed', 'busy');
    expect(bodies).toHaveLength(1 + BUSY_TRIES);
    await expect(page.locator('#recLead')).toHaveText(en['rec.failed.busy']);
    await expect(page.locator('#recKept')).toHaveText(pattern(en['rec.kept']));
    await expect(page.locator('#recSend')).toBeFocused();
});

test('a failure that sending again can fix keeps the recording; Send again sends the same one', async ({ page }) => {
    await instrument(page);
    // Each answer, and what the sheet calls it (data-detail, and the lead rec.failed.<detail>).
    const failures = [
        [(route) => route.fulfill({ status: 502, contentType: 'text/html', body: '<h1>502 Bad Gateway</h1>' }), 'network'],
        [answerWith(504), 'slow'],
        [answerWith(524), 'slow'], // Cloudflare's timeout
        [answerWith(500, 'scoring_failed'), 'server'],
        [(route) => route.abort('connectionreset'), 'network'], // no answer at all, while online
    ];
    const bodies = await routeScore(page, (route, n) => (n <= failures.length ? failures[n - 1][0](route) : route.continue()));
    await openPage(page);
    await recordAndStop(page, 3); // the whole sentence, for a real score at the end

    for (const [index, [, detail]] of failures.entries()) {
        await expectState(page, 'failed', detail);
        await expect(page.locator('#recTitle')).toHaveText(en['rec.failed.title']);
        await expect(page.locator('#recLead')).toHaveText(en[`rec.failed.${detail}`]);
        await expect(page.locator('#recText')).toHaveText(en['rec.failed.text']);
        await expect(page.locator('#recKept')).toHaveText(pattern(en['rec.kept']));
        await expect(page.locator('#recAlert')).toContainText(en[`rec.failed.${detail}`]);
        await expect(page.locator('#recSend')).toBeFocused();
        // Send again, Record again, Close: in this order, which is also focus order.
        expect(await page.locator('#recActions > :not([hidden])').evaluateAll((nodes) => nodes.map((node) => node.id)))
            .toEqual(['recSend', 'recRecordAgain', 'recCancel']);
        await expect(page.locator('#recCancel')).toHaveText(en['common.close']);
        await tap(page.locator('#recSend'));
        await expect.poll(() => bodies.length).toBe(index + 2);
    }
    await expect(dialog(page)).toBeHidden({ timeout: 30_000 });
    await expect(page.locator('#resultTitle')).not.toBeEmpty();
    expect(new Set(bodies).size).toBe(1); // the same recording each time
});

test('failed: Record again starts a new take; Close closes the sheet', async ({ page }) => {
    await instrument(page);
    const bodies = await routeScore(page, answerWith(502));
    await openPage(page);
    await recordAndStop(page);
    await expectState(page, 'failed', 'network');

    await tap(page.locator('#recRecordAgain'));
    await expectState(page, 'recording');
    await expect(page.locator('#recStop')).toBeFocused();
    await expect(page.locator('#recTimer')).toHaveText(/^0:0[01] \/ 0:30$/); // from the start
    await recordFor(page, 1);
    await page.locator('#recStop').click();
    await expectState(page, 'failed', 'network');
    expect(bodies).toHaveLength(2);
    expect(bodies[1]).not.toBe(bodies[0]); // a new recording

    await tap(page.locator('#recCancel'));
    await expectState(page, 'idle');
    await expect(dialog(page)).toBeHidden();
    await expect(page.locator('#btnRecord')).toBeFocused();
});

test('no answer within 100 s: the server took too long, the recording kept', async ({ page }) => {
    await page.clock.install();
    await instrument(page);
    const bodies = await routeScore(page, () => {}); // never answered
    await openPage(page);
    await recordAndStop(page);
    await expect.poll(() => bodies.length).toBe(1);
    // The 100 s count from the request.
    await pauseClock(page, (await scoreSentAt(page)) + 99_900);
    await expectState(page, 'checking');
    await page.clock.runFor(200);
    await expectState(page, 'failed', 'slow');
    await expect(page.locator('#recLead')).toHaveText(en['rec.failed.slow']);
    await expect(page.locator('#recKept')).toHaveText(pattern(en['rec.kept']));
});

test('offline while sending: the recording kept, back online said, Send again scores it', async ({ page, context }) => {
    await instrument(page);
    await openPage(page);
    await startTake(page);
    await context.setOffline(true);
    // The page's notice, behind the sheet, says that a recording made offline is kept.
    await expect(dockedNotice(page)).toContainText(en['notice.offline.text']);
    await recordFor(page, 3); // the whole sentence, for a real score
    await page.locator('#recStop').click();

    await expectState(page, 'offline', '');
    await expect(page.locator('#recTitle')).toHaveText(en['rec.offline.title']);
    await expect(page.locator('#recLead')).toHaveText(en['rec.offline.lead']);
    await expect(page.locator('#recText')).toHaveText(en['rec.offline.text']);
    await expect(page.locator('#recKept')).toHaveText(pattern(en['rec.kept']));
    await expect(page.locator('#recNote')).toBeHidden();
    await expect(page.locator('#recSend')).toBeFocused();

    await context.setOffline(false);
    await expectState(page, 'offline', 'online');
    await expect(page.locator('#recNote')).toHaveText(en['rec.backOnline']);
    await expect.poll(() => said(page)).toContain(en['rec.backOnline']);
    // Sending stays the learner's choice.
    await expect(page.locator('#recSend')).toBeFocused();
    await tap(page.locator('#recSend'));
    await expect(dialog(page)).toBeHidden({ timeout: 30_000 });
    await expect(page.locator('#resultTitle')).not.toBeEmpty();
});

test('the server heard no speech: Record again, nothing kept', async ({ page }) => {
    await instrument(page);
    await routeScore(page, answerWith(422, 'no_speech'));
    await openPage(page);
    await recordAndStop(page);
    await expectState(page, 'no-speech', 'server');
    await expect(page.locator('#recTitle')).toHaveText(en['rec.noSpeech.title']);
    await expect(page.locator('#recLead')).toHaveText(en['rec.noSpeech.lead']);
    await expect(page.locator('#recText')).toHaveText(en['rec.noSpeech.text']);
    await expect(page.locator('#recRecordAgain')).toBeFocused();
    await expect(page.locator('#recRecordAgain')).toHaveClass(/btn-primary/);
    await expect(page.locator('#recSend')).toBeHidden();
    await expect(page.locator('#recKept')).toBeHidden();
});

test('too short: nothing sent, Record again', async ({ page }) => {
    await instrument(page);
    const bodies = await routeScore(page);
    await openPage(page);
    await startTake(page);
    // Enter on Stop, which has focus: a key acts at once (a tap waits out the sheet's 400 ms).
    await expect(page.locator('#recStop')).toBeFocused();
    await page.keyboard.press('Enter');
    await expectState(page, 'too-short');
    await expect(page.locator('#recTitle')).toHaveText(en['rec.tooShort.title']);
    await expect(page.locator('#recLead')).toHaveText(en['rec.tooShort.lead']);
    await expect(page.locator('#recText')).toHaveText(en['rec.tooShort.text']);
    await expect(page.locator('#recRecordAgain')).toBeFocused();
    expect(bodies).toEqual([]);
});

test('interrupted (the page hidden, the track ended, the recorder failed): nothing sent, Record again', async ({ page }) => {
    await instrument(page);
    const bodies = await routeScore(page);
    await openPage(page);
    const interruptions = [
        ['hidden', () => setHidden(page, true)],
        ['ended', () => page.evaluate(() => window.__e2e.streams.at(-1).getAudioTracks()[0].dispatchEvent(new Event('ended')))],
        ['error', () => page.evaluate(() => window.__e2e.recorders.at(-1).dispatchEvent(new Event('error')))],
    ];
    await startTake(page);
    await recordFor(page, 1); // speech in the first take: only the interruption keeps it from being sent
    for (const [detail, interrupt] of interruptions) {
        await interrupt();
        await expectState(page, 'interrupted', detail);
        await expect(page.locator('#recTitle')).toHaveText(en['rec.interrupted.title']);
        await expect(page.locator('#recLead')).toHaveText(en['rec.interrupted.lead']);
        await expect(page.locator('#recText')).toHaveText(en['rec.interrupted.text']);
        await expect(page.locator('#recRecordAgain')).toBeFocused();
        expect(await micReleased(page)).toBe(true);
        if (detail === 'hidden') await setHidden(page, false);
        await tap(page.locator('#recRecordAgain'));
        await expectState(page, 'recording');
    }
    await tap(page.locator('#recCancel'));
    await expectState(page, 'idle');
    expect(bodies).toEqual([]);
});

test('a recording the server refuses: its reason, and Record again', async ({ page }) => {
    await instrument(page);
    await routeScore(page, answerWith(400, 'bad_audio'));
    await openPage(page);
    await recordAndStop(page);
    await expectState(page, 'rejected', 'bad_audio');
    await expect(page.locator('#recTitle')).toHaveText(en['rec.failed.title']);
    await expect(page.locator('#recLead')).toHaveText(en['error.bad_audio']);
    await expect(page.locator('#recRecordAgain')).toBeFocused();
    await expect(page.locator('#recSend')).toBeHidden();
    await expect(page.locator('#recKept')).toBeHidden();
});
