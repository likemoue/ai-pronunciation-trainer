// The page's own words (i18n/*.json), so the tests follow the dictionaries
// instead of repeating them.
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (language) => JSON.parse(readFileSync(path.join(root, 'i18n', `${language}.json`), 'utf8'));

export const en = read('en');
export const vi = read('vi');

// A text with its {placeholders} filled in.
export function fill(text, params = {}) {
    return text.replace(/\{(\w+)\}/g, (match, name) => (name in params ? String(params[name]) : match));
}
