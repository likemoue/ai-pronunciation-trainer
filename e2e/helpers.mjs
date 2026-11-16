// Shared steps of the browser tests.
import { expect } from '@playwright/test';

// Every sentence the page asks for is `text` (a bank sentence's answer, without
// its MP3, so Listen reads it through the TTS route). With `level`, the answer
// names the level asked for: "Sentence for level 2."
export async function fixedSentence(page, text, { ipa = '', perLevel = false } = {}) {
    await page.route('**/getSample', async (route) => {
        const asked = JSON.parse(route.request().postData() || '{}');
        const sentence = perLevel ? `Sentence for level ${asked.category}.` : text;
        await route.fulfill({
            json: { real_transcript: [sentence], ipa_transcript: ipa, transcript_translation: '', tts_url: '' },
        });
    });
}

// The sentence the app itself gives for `text` (its IPA from the server).
export async function serverSentence(page, text) {
    await page.route('**/getSample', async (route) => {
        const response = await route.fetch({
            url: new URL('/getCustomSample', route.request().url()).href,
            postData: JSON.stringify({ text, language: 'en' }),
        });
        await route.fulfill({ response });
    });
}

// Errors the page logs or throws; checked at the end of a test.
export function collectErrors(page) {
    const errors = [];
    page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`));
    page.on('console', (message) => {
        if (message.type() === 'error') errors.push(`console: ${message.text()}`);
    });
    return errors;
}

export async function openPage(page, path = '/') {
    await page.goto(path);
    await expect(page.locator('#sentenceCard')).toHaveAttribute('aria-busy', 'false');
}

// The notice docked above the controls (one at a time).
export const dockedNotice = (page) => page.locator('#dock .notice');
