// A microphone that hears nothing (silence.wav): "We can't hear you" while
// recording (wireframes page 2, B3), and the page's own silence check, which
// sends nothing (B10). Its own file: the fake microphone is set at launch.
import { test, expect } from '@playwright/test';

import { microphone } from './fixtures.mjs';
import { fixedSentence, openPage } from './helpers.mjs';
import { expectState, instrument, recordFor, routeScore, said, sheet, startTake } from './instrument.mjs';
import { SENTENCE } from './paths.mjs';
import { en } from './strings.mjs';

test.use(microphone('silence.wav'));

test.skip(({ isMobile }) => !isMobile, 'the same on a computer');

test('"We can\'t hear you" after 3.5 s of silence, said once; the silent take is not sent', async ({ page }) => {
    await instrument(page);
    const bodies = await routeScore(page);
    await fixedSentence(page, SENTENCE);
    await openPage(page);
    await startTake(page);

    await recordFor(page, 2);
    await expect(sheet(page)).not.toHaveAttribute('data-hint');
    // The warning and the timer read together: it comes in the take's fourth second.
    let timer = '';
    await expect.poll(async () => {
        const now = await page.evaluate(() => ({
            hint: document.getElementById('recordSheet').dataset.hint || '',
            timer: document.getElementById('recTimer').textContent,
        }));
        timer = now.timer;
        return now.hint;
    }, { intervals: [100] }).toBe('quiet');
    expect(timer).toMatch(/^0:0[3-9] /);
    await expect(page.locator('#recHint')).toHaveText(en['rec.cantHear']);
    await expect(page.locator('#recHint')).toHaveClass(/is-warning/);

    // Said once, however long the silence lasts. The take runs to 5 s: Chrome
    // encodes digital silence in about 250 bytes a second (and a 300-byte
    // header), so a shorter one is under the page's 1 KB floor (too short).
    await recordFor(page, 5);
    expect((await said(page)).filter((text) => text === en['rec.cantHear'])).toHaveLength(1);

    await page.locator('#recStop').click();
    await expectState(page, 'no-speech', 'silent');
    await expect(page.locator('#recTitle')).toHaveText(en['rec.noSpeech.title']);
    await expect(page.locator('#recRecordAgain')).toBeFocused();
    expect(bodies).toEqual([]);
});
