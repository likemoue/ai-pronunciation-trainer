// Browser tests of the page (e2e/): `npm run e2e`, against a running app.
//
// The app is not started from here: point E2E_BASE_URL at one (default
// http://127.0.0.1:3000): `OPEN_BROWSER=0 python webApp.py` with the models, or
// the image as CI runs it. Chromium's fake microphone plays a WAV file instead of
// a real device (e2e/global-setup.mjs makes them from the app's own voice), so the
// whole path is real: MediaRecorder, the upload, ffmpeg, Whisper and the scoring.
import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.E2E_BASE_URL || 'http://127.0.0.1:3000';

export default defineConfig({
    testDir: 'e2e',
    globalSetup: './e2e/global-setup.mjs',
    // One scoring at a time keeps the timings of the busy/timeout tests honest
    // and leaves the app's queue to the tests that want it.
    workers: 1,
    fullyParallel: false,
    retries: process.env.CI ? 1 : 0,
    timeout: 90_000,
    expect: { timeout: 15_000 },
    reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
    use: {
        baseURL,
        // A returning learner: the first-visit tour (e2e/tour.spec.mjs clears this) would cover the page.
        storageState: {
            cookies: [],
            origins: [{ origin: new URL(baseURL).origin, localStorage: [{ name: 'aipt.tour', value: 'seen' }] }],
        },
        locale: 'en-US',
        timezoneId: 'Asia/Ho_Chi_Minh',
        trace: 'retain-on-failure',
        screenshot: 'only-on-failure',
    },
    projects: [
        {
            name: 'phone',
            use: { ...devices['Pixel 7'], browserName: 'chromium' },
        },
        {
            name: 'desktop',
            use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 } },
        },
    ],
});
