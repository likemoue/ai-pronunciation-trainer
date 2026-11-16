// The recording sheet's tests (recording*.spec.mjs, microphone.spec.mjs): the
// page's microphone, recorder, sounds and polite region, wrapped so that a test
// can steer and watch them, and the steps those tests share.
import { expect } from '@playwright/test';

// The scoring request (AIPT.API.score).
const SCORE_PATH = '/GetAccuracyFromRecordedAudio';

// Browsers whose steps or words differ (AIPT.detectEnv reads the user agent).
export const UA = {
    chromeAndroid: 'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) '
        + 'Chrome/131.0.0.0 Mobile Safari/537.36',
    safariIos: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) '
        + 'Version/17.1 Mobile/15E148 Safari/604.1',
    chromeWindows: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
        + 'Chrome/131.0.0.0 Safari/537.36',
    edgeWindows: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
        + 'Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0',
    firefoxWindows: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0',
    zaloAndroid: 'Mozilla/5.0 (Linux; Android 13; SM-A536E Build/TP1A.220624.014; wv) AppleWebKit/537.36 '
        + '(KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.230 Mobile Safari/537.36 Zalo android/12050413 '
        + 'ZaloTheme/light ZaloLanguage/vi',
    facebookAndroid: 'Mozilla/5.0 (Linux; Android 13; SM-A536E Build/TP1A.220624.014; wv) AppleWebKit/537.36 '
        + '(KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.230 Mobile Safari/537.36 [FB_IAB/FB4A;FBAV/440.0.0.31.105;]',
    webviewAndroid: 'Mozilla/5.0 (Linux; Android 13; SM-A536E Build/TP1A.220624.014; wv) AppleWebKit/537.36 '
        + '(KHTML, like Gecko) Version/4.0 Chrome/120.0.6099.230 Mobile Safari/537.36',
    messengerIos: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) '
        + 'Mobile/15E148 LightSpeed [FBAN/MessengerLiteForiOS;FBAV/442.0.0.38.112;FBBV/556574003;FBDV/iPhone14,7;'
        + 'FBMD/iPhone;FBSN/iOS;FBSV/17.1;FBSS/3;FBCR/;FBID/phone;FBLC/vi_VN;FBOP/0]',
};

// Before the page loads, in window.__e2e:
// - getUserMedia answers as `gum` says: 'real' (the fake microphone), 'pending'
//   (a prompt left open until prompts[i].allow()), or the name of the error to
//   fail with. setMicrophone() changes it later. It counts its `calls` and
//   keeps the `streams` it handed over.
// - `permission` is what the browser says of the microphone before any tap.
// - `clipboard`: 'ok' takes the text (into `copied`, at page time `copiedAt`),
//   'refuse' refuses it.
// - `recorders`: every MediaRecorder, with the page time of its start
//   (`startedAt`); `requests`: the URL and page time of every fetch. Page
//   times are performance.now(), which page.clock moves (pauseClock).
// - `sounds`: every sound started (audio element, speech, Web Audio node),
//   and whether the recording sheet was open then.
// - `said`: each text of the sheet's polite region (#recStatus).
export async function instrument(page, { gum = 'real', permission = '', clipboard = '' } = {}) {
    await page.addInitScript((given) => {
        const e2e = {
            gum: given.gum, calls: 0, prompts: [], streams: [], recorders: [], requests: [], sounds: [], said: [],
            copied: null, copiedAt: 0,
        };
        window.__e2e = e2e;
        const sheetOpen = () => {
            const sheet = document.getElementById('recordSheet');
            return Boolean(sheet && !sheet.hidden);
        };
        const sound = (kind) => e2e.sounds.push({ kind, sheetOpen: sheetOpen() });

        const devices = navigator.mediaDevices;
        if (devices && devices.getUserMedia) {
            const real = devices.getUserMedia.bind(devices);
            const keep = (stream) => {
                e2e.streams.push(stream);
                return stream;
            };
            devices.getUserMedia = (constraints) => {
                e2e.calls += 1;
                if (e2e.gum === 'real') return real(constraints).then(keep);
                if (e2e.gum === 'pending') {
                    return new Promise((resolve, reject) => e2e.prompts.push({
                        allow: () => real(constraints).then(keep).then(resolve, reject),
                    }));
                }
                return Promise.reject(new DOMException('Made to fail', e2e.gum));
            };
        }
        if (window.MediaRecorder) {
            window.MediaRecorder = class extends window.MediaRecorder {
                constructor(...args) {
                    super(...args);
                    e2e.recorders.push(this);
                }

                start(...args) {
                    this.startedAt = performance.now();
                    return super.start(...args);
                }
            };
        }
        const fetch = window.fetch;
        window.fetch = function (input, init) {
            e2e.requests.push({ url: String(input && input.url ? input.url : input), at: performance.now() });
            return fetch.call(this, input, init);
        };

        const play = HTMLMediaElement.prototype.play;
        HTMLMediaElement.prototype.play = function (...args) {
            sound('media');
            return play.apply(this, args);
        };
        if (window.AudioScheduledSourceNode) {
            const start = AudioScheduledSourceNode.prototype.start;
            AudioScheduledSourceNode.prototype.start = function (...args) {
                sound('node');
                return start.apply(this, args);
            };
        }
        if (window.speechSynthesis) {
            const speak = window.speechSynthesis.speak.bind(window.speechSynthesis);
            window.speechSynthesis.speak = (utterance) => {
                sound('speech');
                return speak(utterance);
            };
        }

        if (given.permission && navigator.permissions) {
            const query = navigator.permissions.query.bind(navigator.permissions);
            navigator.permissions.query = (descriptor) => (descriptor && descriptor.name === 'microphone'
                ? Promise.resolve({ state: given.permission, addEventListener() {} }) : query(descriptor));
        }
        if (given.clipboard) {
            const writeText = given.clipboard === 'ok'
                ? (text) => {
                    e2e.copied = text;
                    e2e.copiedAt = performance.now();
                    return Promise.resolve();
                }
                : () => Promise.reject(new DOMException('Refused', 'NotAllowedError'));
            Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
        }

        document.addEventListener('DOMContentLoaded', () => {
            const region = document.getElementById('recStatus');
            new MutationObserver(() => {
                if (region.textContent) e2e.said.push(region.textContent);
            }).observe(region, { childList: true, characterData: true, subtree: true });
        });
    }, { gum, permission, clipboard });
}

// What getUserMedia does from now on (see instrument).
export async function setMicrophone(page, gum) {
    await page.evaluate((mode) => {
        window.__e2e.gum = mode;
    }, gum);
}

// What the sheet's polite region has said so far.
export const said = (page) => page.evaluate(() => window.__e2e.said);

// Page times (performance.now()): when the n-th scoring request was sent, and
// when the n-th take began recording.
export const scoreSentAt = (page, n = 1) => page.evaluate(([path, index]) => (
    window.__e2e.requests.filter((request) => request.url.includes(path))[index].at), [SCORE_PATH, n - 1]);
export const takeStartedAt = (page, n = 1) => page.evaluate((index) => window.__e2e.recorders[index].startedAt, n - 1);

// Hold the page's clock (page.clock.install() first) at the page time `at`, or
// just ahead of now: from then on it moves only with page.clock.runFor() or
// fastForward(), so a timer of the page fires exactly when the test says.
// The fake microphone, the recorder and the requests run on real time.
export async function pauseClock(page, at) {
    const { now, offset } = await page.evaluate(() => ({ now: performance.now(), offset: Date.now() - performance.now() }));
    await page.clock.pauseAt(offset + (at === undefined ? now + 100 : at));
}

// The sounds started while the recording sheet was open (there must be none).
export const soundsInSheet = (page) => page.evaluate(() => window.__e2e.sounds.filter((s) => s.sheetOpen));

// True when no microphone track is still live.
export const micReleased = (page) => page.evaluate(
    () => window.__e2e.streams.every((stream) => stream.getTracks().every((track) => track.readyState === 'ended')));

// The sheet's root carries its state (data-state, data-detail, data-hint); the
// dialog in it is what shows (the root has no box of its own).
export const sheet = (page) => page.locator('#recordSheet');
export const dialog = (page) => page.locator('#recordSheet [role="dialog"]');

// The sheet's state (data-state) and, when given, its detail ('' for none).
export async function expectState(page, state, detail, options = {}) {
    await expect(sheet(page)).toHaveAttribute('data-state', state, options);
    if (detail === '') await expect(sheet(page)).not.toHaveAttribute('data-detail');
    else if (detail !== undefined) await expect(sheet(page)).toHaveAttribute('data-detail', detail);
}

// A tap on a sheet action. The sheet ignores taps in the 400 ms after its
// actions change (a double tap must not land on the new ones): wait them out.
export async function tap(locator) {
    await locator.page().waitForTimeout(450);
    await locator.click();
}

// The take's own timer in seconds ("0:04 / 0:30" is 4).
async function takeSeconds(page) {
    const match = /^(\d+):(\d\d)/.exec((await page.locator('#recTimer').textContent()) || '');
    return match ? Number(match[1]) * 60 + Number(match[2]) : 0;
}

// Wait until the take has run `seconds` by its timer. The fake microphone plays
// half a second of silence, then the sentence, which ends before 3 s: from 1 s
// a take has speech in it (the page's own silence check lets it go), from 3 s
// the whole sentence (for a real score).
export async function recordFor(page, seconds) {
    await expect.poll(() => takeSeconds(page), { intervals: [100], timeout: (seconds + 15) * 1000 })
        .toBeGreaterThanOrEqual(seconds);
}

// Tap the mic and wait for the take to record.
export async function startTake(page) {
    await page.locator('#btnRecord').click();
    await expectState(page, 'recording');
}

// A take of `seconds`, stopped with Stop (well after its 400 ms).
export async function recordAndStop(page, seconds = 1) {
    await startTake(page);
    await recordFor(page, seconds);
    await page.locator('#recStop').click();
}

// Route the scoring requests: each body is kept (in the array returned), and
// answer(route, n) answers the n-th (the real server when it is left out; a
// handler that does nothing leaves the request unanswered).
export async function routeScore(page, answer = (route) => route.continue()) {
    const bodies = [];
    await page.route(`**${SCORE_PATH}`, async (route) => {
        bodies.push(route.request().postData());
        await answer(route, bodies.length);
    });
    return bodies;
}

// The scoring request given up by the page (Cancel, Escape): wait for it.
export const scoreAborted = (page) => page.waitForEvent('requestfailed', (request) => request.url().includes(SCORE_PATH));

// An error answer of the server (webApp._error), whose message is never shown.
export const answerWith = (status, code = '', headers = {}) => (route) => route.fulfill({
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify({ error: 'the server words, never shown', code }),
});

// A promise and the function that settles it: a request held until the test lets it go.
export function gate() {
    let open;
    const opened = new Promise((resolve) => {
        open = resolve;
    });
    return { opened, open };
}

// The page hidden (switching tabs or apps) and shown again.
export async function setHidden(page, hidden) {
    await page.evaluate((value) => {
        Object.defineProperty(document, 'hidden', { configurable: true, get: () => value });
        Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => (value ? 'hidden' : 'visible') });
        document.dispatchEvent(new Event('visibilitychange'));
    }, hidden);
}

// The interface in Vietnamese from the first render (the server reads the cookie).
export async function inVietnamese(context, baseURL) {
    await context.addCookies([{ name: 'lang', value: 'vi', url: baseURL }]);
}
