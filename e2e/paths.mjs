// Shared by the global setup and the tests.
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));

// Where the fake microphone's WAV files go (git-ignored with test-results/).
export const AUDIO_DIR = path.join(here, '..', 'test-results', 'fake-mic');

// The app's warm-up and smoke-test sentence: its voice reads it in a way
// Whisper hears word for word (CLAUDE.md, deploy/smoke_test.py).
export const SENTENCE = 'I have a cat and a dog at home.';
