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

// The whole text as a RegExp: the placeholders given in params filled in, each
// other one matching any value (a group), as in "Sending again in {seconds} s".
// Whitespace around it is allowed (toHaveText does not trim for a RegExp).
export function pattern(text, params = {}) {
    const escape = (value) => String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    let source = '';
    let last = 0;
    text.replace(/\{(\w+)\}/g, (match, name, offset) => {
        source += escape(text.slice(last, offset)) + (name in params ? escape(params[name]) : '(.+?)');
        last = offset + match.length;
        return match;
    });
    return new RegExp(`^\\s*${source}${escape(text.slice(last))}\\s*$`);
}
