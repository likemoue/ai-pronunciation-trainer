// The fake microphone: `test.use(microphone('sentence.wav'))` in a test file
// launches Chromium with that WAV file as the only microphone (played once,
// then silence), and the permission already granted.
import path from 'node:path';

import { AUDIO_DIR } from './paths.mjs';

export function microphone(file) {
    return {
        permissions: ['microphone'],
        launchOptions: {
            args: [
                '--use-fake-ui-for-media-stream',
                '--use-fake-device-for-media-stream',
                `--use-file-for-fake-audio-capture=${path.join(AUDIO_DIR, file)}%noloop`,
                '--autoplay-policy=no-user-gesture-required',
            ],
        },
    };
}
