// Makes the WAV files that Chromium's fake microphone plays (e2e/fixtures.mjs):
// the warm-up sentence in the app's own voice, framed by silence, and plain
// silence. The app must be running (playwright.config.mjs).
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';

import { AUDIO_DIR, SENTENCE } from './paths.mjs';

const SAMPLE_RATE = 22050;

function wav(samples, rate = SAMPLE_RATE) {
    const data = Buffer.alloc(samples.length * 2);
    samples.forEach((value, index) => {
        data.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(value))), index * 2);
    });
    const header = Buffer.alloc(44);
    header.write('RIFF', 0);
    header.writeUInt32LE(36 + data.length, 4);
    header.write('WAVE', 8);
    header.write('fmt ', 12);
    header.writeUInt32LE(16, 16);
    header.writeUInt16LE(1, 20); // PCM
    header.writeUInt16LE(1, 22); // mono
    header.writeUInt32LE(rate, 24);
    header.writeUInt32LE(rate * 2, 28);
    header.writeUInt16LE(2, 32);
    header.writeUInt16LE(16, 34);
    header.write('data', 36);
    header.writeUInt32LE(data.length, 40);
    return Buffer.concat([header, data]);
}

// The 16-bit mono PCM samples of a WAV file (Piper's output).
function pcmSamples(buffer) {
    let offset = 12;
    let format = null;
    while (offset + 8 <= buffer.length) {
        const id = buffer.toString('ascii', offset, offset + 4);
        const size = buffer.readUInt32LE(offset + 4);
        if (id === 'fmt ') {
            format = {
                channels: buffer.readUInt16LE(offset + 10),
                rate: buffer.readUInt32LE(offset + 12),
                bits: buffer.readUInt16LE(offset + 22),
            };
        } else if (id === 'data') {
            if (!format || format.channels !== 1 || format.bits !== 16) {
                throw new Error(`Unexpected voice format: ${JSON.stringify(format)}`);
            }
            const samples = [];
            for (let i = offset + 8; i + 1 < offset + 8 + size && i + 1 < buffer.length; i += 2) {
                samples.push(buffer.readInt16LE(i));
            }
            return { rate: format.rate, samples };
        }
        offset += 8 + size + (size % 2);
    }
    throw new Error('No data chunk in the voice WAV');
}

export default async function globalSetup(config) {
    const baseURL = config.projects[0].use.baseURL;
    mkdirSync(AUDIO_DIR, { recursive: true });

    const response = await fetch(new URL('/getAudioFromText', baseURL), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value: SENTENCE, language: 'en' }),
    });
    if (!response.ok) {
        throw new Error(`The app at ${baseURL} did not read the test sentence: ${response.status}`);
    }
    const { wavBase64 } = await response.json();
    const voice = pcmSamples(Buffer.from(wavBase64, 'base64'));
    const silence = (seconds) => new Array(Math.round(seconds * voice.rate)).fill(0);
    // Half a second before the speech (the recorder starts) and plenty after it
    // (the test taps Stop), so the whole sentence is in every take.
    writeFileSync(path.join(AUDIO_DIR, 'sentence.wav'),
        wav([...silence(0.5), ...voice.samples, ...silence(4)], voice.rate));
    writeFileSync(path.join(AUDIO_DIR, 'silence.wav'), wav(silence(6)));
}
