// Progress kept on the device (wireframes page 6, F1-F7; progress.js): the points of each score, the ★ chip,
// the progress sheet (today, the streak and the last 7 days in Vietnam time, the words to review), a word
// practised on its own, New learner, and a record the page does not recognise. Takes are real (the fake
// microphone); the scoring request is answered with a case the server's own code made (e2e/scores/*.json).
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { test, expect } from '@playwright/test';

import { microphone } from './fixtures.mjs';
import { collectErrors, dockedNotice, fixedSentence, openPage } from './helpers.mjs';
import { dialog, inVietnamese, instrument, recordAndStop, routeScore } from './instrument.mjs';
import { en, fill, vi } from './strings.mjs';

test.use(microphone('sentence.wav'));

const SCORES = path.join(path.dirname(fileURLToPath(import.meta.url)), 'scores');
const score = (name) => JSON.parse(readFileSync(path.join(SCORES, `${name}.json`), 'utf8'));
// The same answer with another score (a better or a worse attempt at the same sentence).
const scoredAt = (answer, accuracy) => ({ ...answer, pronunciation_accuracy: String(accuracy) });

// The record (the comment at the top of progress.js).
const KEY = 'aipt.progress.v1';
const record = ({ days = {}, today = { day: '', texts: {} }, streak = { count: 0, last: '' }, words = [] } = {}) => ({
    v: 1, days, today, streak, words,
});

// Days in Vietnam ('2026-11-16' is a Monday), moved on the calendar alone, and a time on one of them.
const MONDAY = '2026-11-16';
const shift = (day, n) => {
    const [year, month, date] = day.split('-').map(Number);
    return new Date(Date.UTC(year, month - 1, date + n)).toISOString().slice(0, 10);
};
const at = (day, time) => new Date(`${day}T${time}:00+07:00`);

// This browser's storage as a returning learner left it: written before the first load of the page, not
// again on a reload (the page's own changes stay).
async function inStorage(page, entries) {
    const values = Object.fromEntries(Object.entries(entries)
        .map(([key, value]) => [key, typeof value === 'string' ? value : JSON.stringify(value)]));
    await page.addInitScript((given) => {
        if (sessionStorage.getItem('e2e.stored')) return;
        sessionStorage.setItem('e2e.stored', '1');
        Object.entries(given).forEach(([key, value]) => localStorage.setItem(key, value));
    }, values);
}
const stored = (page, keys) => page.evaluate((names) => names.map((name) => localStorage.getItem(name)), keys);

// The form of a text for a count, as the page picks it ("1-day streak", "3 days").
const plural = (dict, key, count) => dict[`${key}.${new Intl.PluralRules(dict === vi ? 'vi' : 'en').select(count)}`];

// The last 7 days, today last, as each is read out: its name, practised or not, today.
function week(dict, today, practised) {
    return [6, 5, 4, 3, 2, 1, 0].map((back) => {
        const day = shift(today, -back);
        const said = [
            dict[`progress.day.${new Date(`${day}T00:00:00Z`).getUTCDay()}`],
            dict[practised.includes(day) ? 'progress.dayDone' : 'progress.dayMissed'],
        ];
        if (!back) said.push(dict['progress.dayToday']);
        return said.join(', ');
    });
}

// "Today · Mon 16 Nov": the names are Intl's, the order the dictionary's.
const todayIs = (dict, weekday, day, month) => fill(dict['progress.today'], {
    date: fill(dict['progress.date'], { weekday, day, month }),
});

const chip = (page) => page.locator('#btnProgress');
const chipPoints = (page) => page.locator('#btnProgress .progress-chip-short');
const progress = (page) => page.locator('#progressSheet [role="dialog"]');
const streak = (page) => page.locator('#progressStreak');
const streakHint = (page) => page.locator('#progressStreakHint');
const weekDays = (page) => page.locator('#progressWeek li');
const reviewChips = (page) => page.locator('#reviewChips .word-chip[data-word]');

async function openProgress(page) {
    await chip(page).click();
    await expect(progress(page)).toBeVisible();
    await expect(page.locator('#progressTitle')).toBeFocused();
}

async function closeProgress(page) {
    await page.keyboard.press('Escape');
    await expect(progress(page)).toBeHidden();
    await expect(chip(page)).toBeFocused();
}

// Today's three numbers in the sheet (English); no average before the first score.
async function expectToday(page, points, sentences, average) {
    await expect(page.locator('#statPoints')).toHaveText(points.toLocaleString('en'));
    await expect(page.locator('#statPointsLabel')).toHaveText(plural(en, 'progress.points', points));
    await expect(page.locator('#statSentences')).toHaveText(String(sentences));
    await expect(page.locator('#statSentencesLabel')).toHaveText(plural(en, 'progress.sentences', sentences));
    if (average === null) await expect(page.locator('#statAverage .visually-hidden')).toHaveText(en['progress.noAverage']);
    else await expect(page.locator('#statAverage')).toHaveText(`${average}%`);
}

// A take of the text on the card, answered as the test routed the scoring request: done when the result
// has replaced the recording sheet (the points are counted as it renders).
async function take(page) {
    await recordAndStop(page, 1);
    await expect(dialog(page)).toBeHidden();
}

test.describe('on a phone', () => {
    test.skip(({ isMobile }) => !isMobile, 'the rules are the same on a computer; its chip and dialog are tested there');

    test('a score earns its points; a better attempt only the difference; a worse one, or the same again, nothing', async ({ page }) => {
        const errors = collectErrors(page);
        const { sentence, answer } = score('typical-mistakes'); // 79
        const answers = [answer, scoredAt(answer, 90), scoredAt(answer, 70), scoredAt(answer, 90)];
        await instrument(page);
        const bodies = await routeScore(page, (route, n) => route.fulfill({ json: answers[n - 1] }));
        await fixedSentence(page, sentence); // an Easy sentence: x1
        await openPage(page);
        await expect(chipPoints(page)).toHaveText('0');
        await expect(chip(page)).toHaveAccessibleName(fill(en['progress.chipLabel'], { points: 0 }));

        await take(page);
        await expect(chipPoints(page)).toHaveText('79');
        await expect(chip(page)).toHaveAccessibleName(
            fill(plural(en, 'progress.chipLabelStreak', 1), { points: 79, count: 1 }));
        // 90: 11 more. 70, then 90 again: nothing more.
        for (const shown of ['90', '90', '90']) {
            await take(page);
            await expect(chipPoints(page)).toHaveText(shown);
        }
        expect(bodies).toHaveLength(4);

        // One sentence today, at its best attempt; a streak begun, so no hint.
        await openProgress(page);
        await expectToday(page, 90, 1, 90);
        await expect(streak(page)).toHaveText(fill(plural(en, 'progress.streak', 1), { count: 1 }));
        await expect(streakHint(page)).toBeHidden();
        expect(errors).toEqual([]);
    });

    for (const [level, points] of [[2, 103], [3, 126]]) {
        test(`Random: a sentence pays at its own level, as getSample names it (${level}: 79 makes ${points})`, async ({ page }) => {
            const { sentence, answer } = score('typical-mistakes');
            const asked = [];
            await page.route('**/getSample', (route) => {
                const { category } = route.request().postDataJSON();
                asked.push(String(category));
                const random = String(category) === '0';
                return route.fulfill({
                    json: {
                        real_transcript: [random ? sentence : 'A first sentence to read.'],
                        ipa_transcript: '',
                        transcript_translation: '',
                        tts_url: '',
                        category: random ? level : 1,
                    },
                });
            });
            await instrument(page);
            await routeScore(page, (route) => route.fulfill({ json: answer }));
            await openPage(page);
            await page.getByRole('radio', { name: en['level.random'] }).click();
            await expect(page.locator('#sentence')).toHaveText(sentence);
            await take(page);
            // Random itself has no level, and five words would be Easy by the bank's own rule (79).
            await expect(chipPoints(page)).toHaveText(String(points));
            expect(asked).toEqual(['1', '0']);
        });
    }

    test('"a different sentence" counts for nothing: no points, no streak, no words', async ({ page }) => {
        const { sentence, answer } = score('different-sentence');
        await instrument(page);
        await routeScore(page, (route) => route.fulfill({ json: answer }));
        await fixedSentence(page, sentence);
        await openPage(page);
        await take(page);
        await expect(page.locator('#resultCard')).toHaveAttribute('data-tier', 'different');
        await expect(chipPoints(page)).toHaveText('0');
        await expect(chip(page)).toHaveAccessibleName(fill(en['progress.chipLabel'], { points: 0 }));

        await openProgress(page);
        await expectToday(page, 0, 0, null);
        await expect(streak(page)).toHaveText(en['progress.noStreak']);
        await expect(streakHint(page)).toHaveText(en['progress.startStreak']);
        await expect(reviewChips(page)).toHaveCount(0);
        await expect(page.locator('#reviewHint')).toHaveText(en['progress.reviewEmpty']);
    });

    test.describe('a phone set to New York time', () => {
        test.use({ timezoneId: 'America/New_York' });

        test('today, the streak and the last 7 days follow Vietnam time', async ({ page }) => {
            const { sentence, answer } = score('typical-mistakes');
            const sunday = shift(MONDAY, -1);
            const tuesday = shift(MONDAY, 1);
            const thursday = shift(MONDAY, 3);
            // 23:30 on Monday in Vietnam, 11:30 in New York; Sunday was practised.
            await page.clock.install({ time: at(MONDAY, '23:30') });
            await inStorage(page, {
                [KEY]: record({ days: { [sunday]: [60, 1, 60] }, streak: { count: 1, last: sunday } }),
            });
            await instrument(page);
            await routeScore(page, (route) => route.fulfill({ json: answer }));
            await fixedSentence(page, sentence);
            await openPage(page);

            await openProgress(page);
            await expect(page.locator('#progressToday')).toHaveText(todayIs(en, 'Mon', 16, 'Nov'));
            await expectToday(page, 0, 0, null);
            await expect(streak(page)).toHaveText(fill(plural(en, 'progress.streak', 1), { count: 1 }));
            await expect(streakHint(page)).toHaveText(en['progress.keepStreak']);
            await expect(weekDays(page)).toHaveText(week(en, MONDAY, [sunday]));
            await expect(weekDays(page).last()).toHaveClass(/is-today/);
            await closeProgress(page);

            // A score on Monday: two days in a row.
            await take(page);
            await openProgress(page);
            await expectToday(page, 79, 1, 79);
            await expect(streak(page)).toHaveText(fill(plural(en, 'progress.streak', 2), { count: 2 }));
            await expect(streakHint(page)).toBeHidden();
            await expect(weekDays(page)).toHaveText(week(en, MONDAY, [sunday, MONDAY]));

            // 00:30 on Tuesday in Vietnam, still Monday in New York: a new day, in the open sheet; the
            // streak lives on until the end of Tuesday.
            await page.clock.fastForward('01:00:00');
            await expect(page.locator('#progressToday')).toHaveText(todayIs(en, 'Tue', 17, 'Nov'));
            await expectToday(page, 0, 0, null);
            await expect(streak(page)).toHaveText(fill(plural(en, 'progress.streak', 2), { count: 2 }));
            await expect(streakHint(page)).toHaveText(en['progress.keepStreak']);
            await expect(weekDays(page)).toHaveText(week(en, tuesday, [sunday, MONDAY]));
            await closeProgress(page);
            await expect(chipPoints(page)).toHaveText('0');

            // Thursday: Wednesday went by without practice, so the streak is over; a score starts another,
            // and the same sentence counts again on another day.
            await page.clock.fastForward(at(thursday, '10:00') - at(tuesday, '00:30'));
            await openProgress(page);
            await expect(page.locator('#progressToday')).toHaveText(todayIs(en, 'Thu', 19, 'Nov'));
            await expect(streak(page)).toHaveText(en['progress.noStreak']);
            await expect(streakHint(page)).toHaveText(en['progress.startStreak']);
            await closeProgress(page);
            await take(page);
            await expect(chipPoints(page)).toHaveText('79');
            await openProgress(page);
            await expect(streak(page)).toHaveText(fill(plural(en, 'progress.streak', 1), { count: 1 }));
            await expect(weekDays(page)).toHaveText(week(en, thursday, [sunday, MONDAY, thursday]));
        });
    });

    test('words to review, ✗ first; one practised on its own leaves after two Correct readings; Back to sentences', async ({ page }) => {
        const typical = score('typical-mistakes'); // written ✗, three ~, books ~
        const word = score('one-word'); // books, said right
        await instrument(page);
        const bodies = await routeScore(page, (route, n) => route.fulfill({ json: (n === 1 ? typical : word).answer }));
        await fixedSentence(page, typical.sentence);
        await openPage(page);
        // A Hard sentence (x1.6: 79 makes 126), so that the word's own x1 shows.
        const hard = page.getByRole('radio', { name: en['level.hard'] });
        await hard.click();
        await expect(page.locator('#sentenceCard')).toHaveAttribute('aria-busy', 'false');
        await take(page);
        await expect(chipPoints(page)).toHaveText('126');

        await openProgress(page);
        await expect(reviewChips(page)).toHaveText(['written', 'three', 'books']);
        expect(await reviewChips(page).evaluateAll((chips) => chips.map((node) => node.dataset.status))).toEqual(['2', '1', '1']);
        await expect(reviewChips(page).first()).toHaveAccessibleName(
            fill(en['progress.wordLabel'], { word: 'written', status: en['status.needsWork'] }));
        await expect(page.locator('#reviewHint')).toHaveText(en['progress.reviewHint']);

        // F6: the word becomes the text to read; its IPA comes from the server.
        await reviewChips(page).filter({ hasText: word.sentence }).click();
        await expect(progress(page)).toBeHidden();
        await expect(page.locator('#sentence')).toHaveText(word.sentence);
        await expect(page.locator('#sentence')).toBeFocused();
        await expect(page.locator('#cardLabelText')).toHaveText(en['card.wordToReview']);
        await expect(page.locator('#myTextLabel')).toHaveText(en['card.backToSentences']);
        await expect(page.getByRole('radio', { checked: true })).toHaveCount(0);
        await expect(page.locator('#pageStatus')).toHaveText(fill(en['card.wordReady'], { word: word.sentence }));
        await expect(page.locator('#ipa')).toHaveText(`/ ${word.answer.real_transcripts_ipa} /`);

        // Correct once: still to review, and the word's score counts at x1 (100). Correct twice: off the list,
        // and nothing more to earn.
        await take(page);
        expect(JSON.parse(bodies[1]).title).toBe(word.sentence);
        await expect(chipPoints(page)).toHaveText('226');
        await openProgress(page);
        await expect(reviewChips(page)).toHaveText(['written', 'three', 'books']);
        await closeProgress(page);
        await take(page);
        await expect(chipPoints(page)).toHaveText('226');
        await openProgress(page);
        await expect(reviewChips(page)).toHaveText(['written', 'three']);
        await closeProgress(page);

        // Back to sentences: the bank again, at the level last chosen.
        await page.locator('#btnMyText').click();
        await expect(page.locator('#sentence')).toHaveText(typical.sentence);
        await expect(page.locator('#cardLabelText')).toHaveText(en['card.eyebrow']);
        await expect(page.locator('#myTextLabel')).toHaveText(en['card.myText']);
        await expect(hard).toHaveAttribute('aria-checked', 'true');
    });

    test('"Show all": 12 words at first, ✗ before ~ and the latest first, then all of them; 12.5K on the chip', async ({ page }) => {
        // Fourteen words, kept in no particular order, each missed at its own minute.
        const missed = (minute) => at(MONDAY, '09:00').getTime() + minute * 60_000;
        const words = [
            ['library', 1, 3], ['written', 2, 1], ['months', 1, 9], ['thinks', 1, 12], ['they', 2, 7],
            ['clothes', 1, 5], ['unbelievably', 2, 11], ['three', 1, 2], ['sixth', 1, 13], ['books', 1, 8],
            ['thoroughly', 2, 4], ['bad', 1, 6], ['world', 1, 10], ['rhythm', 1, 14],
        ].map(([w, s, minute]) => ({ w, s, ok: 0, at: missed(minute) }));
        const order = ['unbelievably', 'they', 'thoroughly', 'written', 'rhythm', 'sixth', 'thinks', 'world', 'months',
            'books', 'bad', 'clothes', 'library', 'three'];
        await page.clock.setFixedTime(at(MONDAY, '10:00'));
        await inStorage(page, {
            [KEY]: record({ days: { [MONDAY]: [12480, 38, 2888] }, streak: { count: 12, last: MONDAY }, words }),
        });
        await fixedSentence(page, 'A bank sentence.');
        await openPage(page);
        // From 10,000 the chip has the short form; the sheet the whole number.
        await expect(chipPoints(page)).toHaveText('12.5K');

        await openProgress(page);
        await expectToday(page, 12480, 38, 76);
        await expect(reviewChips(page)).toHaveText(order.slice(0, 12));
        const more = page.locator('#reviewChips .word-chip-more');
        await expect(more).toHaveText(fill(en['progress.showAll'], { count: 14 }));
        await more.click();
        await expect(reviewChips(page)).toHaveText(order);
        await expect(more).toHaveCount(0);
        await expect(reviewChips(page).nth(12)).toBeFocused();
    });

    test('New learner: asked first, focus on Cancel; clears progress, draft and tour, keeps the language; "Progress deleted" offers the tour', async ({ page, context }) => {
        const errors = collectErrors(page);
        await page.clock.setFixedTime(at(MONDAY, '10:00'));
        await inStorage(page, {
            [KEY]: record({
                days: { [MONDAY]: [245, 7, 574] },
                today: { day: MONDAY, texts: {} },
                streak: { count: 3, last: MONDAY },
                words: [{ w: 'thinks', s: 1, ok: 0, at: at(MONDAY, '09:00').getTime() }],
            }),
            'aipt.draft': 'My cat sleeps on the sofa.',
        });
        await fixedSentence(page, 'A bank sentence.');
        await openPage(page);
        // This learner reads the page in Vietnamese (remembered on the device).
        await page.getByRole('button', { name: en['lang.vi'] }).click();
        await expect(page.locator('html')).toHaveAttribute('lang', 'vi');

        await openProgress(page);
        await expect(page.locator('#statPoints')).toHaveText('245');
        const newLearner = page.getByRole('button', { name: vi['progress.newLearner'] });
        await newLearner.click();
        // F4: an alertdialog over the sheet, the safe choice focused.
        const confirm = page.getByRole('alertdialog', { name: vi['progress.confirmTitle'] });
        await expect(confirm).toBeVisible();
        await expect(confirm).toHaveAccessibleDescription(vi['progress.confirmText']);
        const cancel = confirm.getByRole('button', { name: vi['common.cancel'] });
        const remove = confirm.getByRole('button', { name: vi['progress.confirmDelete'] });
        await expect(cancel).toBeFocused();
        await expect(page.locator('#progressSheet')).toHaveJSProperty('inert', true);
        await page.keyboard.press('Tab');
        await expect(remove).toBeFocused();
        await page.keyboard.press('Tab');
        await expect(cancel).toBeFocused();
        // Escape closes the question only, and nothing goes.
        await page.keyboard.press('Escape');
        await expect(confirm).toBeHidden();
        await expect(progress(page)).toBeVisible();
        await expect(newLearner).toBeFocused();
        await expect(page.locator('#statPoints')).toHaveText('245');

        await newLearner.click();
        await remove.click();
        await expect(confirm).toBeHidden();
        await expect(progress(page)).toBeHidden();
        // Gone: points, streak, words, the My text draft and the tour's flag. Kept: the language.
        expect(await stored(page, [KEY, 'aipt.draft', 'aipt.tour', 'aipt.lang'])).toEqual([null, null, null, 'vi']);
        expect((await context.cookies()).find((cookie) => cookie.name === 'lang')?.value).toBe('vi');
        await expect(page.locator('html')).toHaveAttribute('lang', 'vi');
        await expect(chipPoints(page)).toHaveText('0');
        await expect(chip(page)).toHaveAccessibleName(fill(vi['progress.chipLabel'], { points: 0 }));

        // F5: a notice above the controls, with the tour one tap away.
        const notice = dockedNotice(page);
        await expect(notice).toHaveAttribute('data-notice', 'welcome');
        await expect(notice).toBeFocused();
        await expect(notice.locator('.notice-title')).toHaveText(vi['notice.welcome.title']);
        await expect(notice.locator('.notice-text')).toHaveText(vi['notice.welcome.text']);
        await notice.getByRole('button', { name: vi['notice.welcome.tour'] }).click();
        await expect(page.locator('#tour')).toHaveAttribute('data-step', '1');
        await expect(page.locator('#tourTitle')).toHaveText(vi['tour.listenTitle']);
        await expect(dockedNotice(page)).toHaveCount(0);
        await page.keyboard.press('Escape');
        await expect(page.locator('#tour')).toBeHidden();

        // My text starts empty; the next visit is still in Vietnamese.
        await page.locator('#btnMyText').click();
        await expect(page.locator('#customText')).toHaveValue('');
        await page.keyboard.press('Escape');
        await page.reload();
        await expect(page.locator('html')).toHaveAttribute('lang', 'vi');
        await expect(page.getByRole('radio', { name: vi['level.easy'] })).toBeVisible();
        expect(errors).toEqual([]);
    });

    test('a record the page does not recognise starts again quietly', async ({ page }) => {
        const errors = collectErrors(page);
        const { sentence, answer } = score('typical-mistakes');
        await page.clock.install({ time: at(MONDAY, '10:00') });
        await instrument(page);
        await routeScore(page, (route) => route.fulfill({ json: answer }));
        await fixedSentence(page, sentence);
        await openPage(page);
        const damaged = [
            ['cut short', '{"v": 1, "days": {"2026-11-16": [245,', []],
            ['another version', JSON.stringify({ v: 2, days: { [MONDAY]: [999, 9, 900] } }), []],
            ['not a record', '[245, 7, 574]', []],
            // Of these, only one word is what the page keeps; "2:30" cannot be practised alone.
            ['wrong shapes', JSON.stringify({
                v: 1,
                days: { [MONDAY]: [245, 'seven', 574], yesterday: [1, 1, 1] },
                today: 'today',
                streak: { count: -3, last: MONDAY },
                words: [{ w: 3 }, { w: 'they', s: 9, ok: 0, at: 1 }, { w: 'books', s: 1, ok: 0, at: 1 }, null,
                    { w: '2:30', s: 2, ok: 0, at: 2 }],
            }), ['books']],
        ];
        for (const [name, value, words] of damaged) {
            await page.evaluate(([key, given]) => localStorage.setItem(key, given), [KEY, value]);
            await page.reload();
            await expect(page.locator('#sentence'), name).toBeVisible();
            await expect(chipPoints(page), name).toHaveText('0');
            await openProgress(page);
            await expect(page.locator('#statPoints'), name).toHaveText('0');
            await expect(streak(page), name).toHaveText(en['progress.noStreak']);
            if (words.length) await expect(reviewChips(page), name).toHaveText(words);
            else await expect(reviewChips(page), name).toHaveCount(0);
            await closeProgress(page);
        }
        // The next score writes a whole record of this version again.
        await take(page);
        await expect(chipPoints(page)).toHaveText('79');
        const [kept] = await stored(page, [KEY]);
        expect(JSON.parse(kept)).toMatchObject({ v: 1, days: { [MONDAY]: [79, 1, 79] }, streak: { count: 1, last: MONDAY } });
        expect(errors).toEqual([]);
    });

    test('in Vietnamese: "Hôm nay · Thứ Hai 16/11", T2…CN, numbers as Vietnamese writes them', async ({ page, context, baseURL }) => {
        await inVietnamese(context, baseURL);
        await page.clock.setFixedTime(at(MONDAY, '10:00'));
        await inStorage(page, {
            [KEY]: record({
                days: { [shift(MONDAY, -2)]: [50, 1, 50], [shift(MONDAY, -1)]: [60, 1, 60], [MONDAY]: [1240, 15, 1200] },
                streak: { count: 3, last: MONDAY },
                words: [{ w: 'thinks', s: 1, ok: 0, at: at(MONDAY, '09:00').getTime() }],
            }),
        });
        await fixedSentence(page, 'A bank sentence.');
        await openPage(page);
        await expect(chipPoints(page)).toHaveText('1.240');
        await expect(chip(page)).toHaveAccessibleName(
            fill(plural(vi, 'progress.chipLabelStreak', 3), { points: '1.240', count: 3 }));

        await openProgress(page);
        await expect(progress(page)).toHaveAccessibleName(vi['progress.title']);
        await expect(page.locator('#progressToday')).toHaveText(todayIs(vi, 'Thứ Hai', 16, 11));
        await expect(page.locator('#statPoints')).toHaveText('1.240');
        await expect(page.locator('#statPointsLabel')).toHaveText(plural(vi, 'progress.points', 1240));
        await expect(page.locator('#statSentencesLabel')).toHaveText(plural(vi, 'progress.sentences', 15));
        await expect(page.locator('#statAverage')).toHaveText('80%');
        await expect(streak(page)).toHaveText(fill(plural(vi, 'progress.streak', 3), { count: 3 }));
        await expect(weekDays(page)).toHaveText(week(vi, MONDAY, [shift(MONDAY, -2), shift(MONDAY, -1), MONDAY]));
        await expect(reviewChips(page).first()).toHaveAccessibleName(
            fill(vi['progress.wordLabel'], { word: 'thinks', status: vi['status.almost'] }));
        await expect(page.locator('#reviewHint')).toHaveText(vi['progress.reviewHint']);
    });
});

test.describe('on a computer', () => {
    test.skip(({ isMobile }) => isMobile, 'the chip\'s long form and the dialog are from 768 px');

    test('the chip reads "245 today · 3 days"; the sheet is a dialog in the middle; Escape gives focus back', async ({ page }) => {
        await page.clock.setFixedTime(at(MONDAY, '10:00'));
        await inStorage(page, {
            [KEY]: record({
                days: { [MONDAY]: [245, 7, 574] },
                streak: { count: 3, last: MONDAY },
                words: [{ w: 'thinks', s: 1, ok: 0, at: at(MONDAY, '09:00').getTime() }],
            }),
        });
        await fixedSentence(page, 'A bank sentence.');
        await openPage(page);
        await expect(chipPoints(page)).toBeHidden();
        const long = page.locator('#btnProgress .progress-chip-long');
        await expect(long).toBeVisible();
        await expect(long).toContainText(fill(en['progress.chipToday'], { points: 245 }));
        await expect(long).toContainText(fill(plural(en, 'progress.chipDays', 3), { count: 3 }));

        await openProgress(page);
        await expectToday(page, 245, 7, 82);
        // Its entrance (200 ms) over, the dialog is where it stays.
        await progress(page).evaluate((node) => Promise.all(node.getAnimations().map((animation) => animation.finished)));
        const box = await progress(page).boundingBox();
        const { width, height } = page.viewportSize();
        expect(Math.abs(box.x + box.width / 2 - width / 2)).toBeLessThanOrEqual(1);
        expect(Math.abs(box.y + box.height / 2 - height / 2)).toBeLessThanOrEqual(1);
        await expect(page.locator('#reviewHint')).toHaveText(en['progress.reviewHintWide']);
        await closeProgress(page);
    });
});
