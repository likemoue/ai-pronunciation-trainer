// The page and the server must read a text the same way (CLAUDE.md): the page's
// normalizeText and checkText (static/javascript/core.js) against
// validation.normalize_text and validation.practice_text, on curated strings and
// 20,000 random ones built from the characters where they could differ.
//
//     node --test tests/js/          (PYTHON names the interpreter; default python3)
//
// validation.py needs only the standard library, so any Python 3.12 will do.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

// core.js in a sandbox that has just enough of a browser for it to load.
function loadPage() {
    const sandbox = {
        console,
        document: { getElementById: () => null, querySelector: () => null, documentElement: { lang: 'en' } },
        navigator: { userAgent: 'Mozilla/5.0', mediaDevices: {} },
        location: { protocol: 'https:', href: 'https://example.test/' },
        matchMedia: () => ({ matches: false, addEventListener() {} }),
        isSecureContext: true,
    };
    sandbox.window = sandbox;
    sandbox.self = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(readFileSync(path.join(ROOT, 'static', 'javascript', 'core.js'), 'utf8'), sandbox);
    return sandbox.AIPT;
}

// What the server makes of each text: [normalize_text, practice_text's error code or ''].
function server(texts) {
    const script = [
        'import json, sys, validation',
        'out = []',
        'for text in json.load(sys.stdin):',
        '    try:',
        '        validation.practice_text(text)',
        "        code = ''",
        '    except validation.ValidationError as e:',
        '        code = e.code',
        '    out.append([validation.normalize_text(text), code])',
        'print(json.dumps(out))',
    ].join('\n');
    const output = execFileSync(process.env.PYTHON || 'python3', ['-c', script], {
        cwd: ROOT,
        input: JSON.stringify(texts),
        env: { ...process.env, PYTHONUTF8: '1' },
        maxBuffer: 64 * 1024 * 1024,
    });
    return JSON.parse(output.toString('utf8'));
}

// The page names an empty text 'empty'; the server refuses it as invalid_request.
const PAGE_CODE = { '': '', empty: 'invalid_request' };

const CURATED = [
    '', '   ', 'Hello world', '  Mary  has\twritten\nthree books. ',
    'It\u{2019}s \u{201C}fine\u{201D} \u{2014} really\u{2026}', 'It\x92s \x93fine\x94 \x97 really\x85',
    'zero\u{200B}width\u{200C} words\u{200D}\u{2060}\u{FEFF}', 'soft\xADhyphen', 'File\x1cseparator\x1d here\x1e\x1f',
    'tab\x0bvertical', 'bell\x07 rings', 'ap\x9bples', 'lone \uD800 surrogate', 'Hôm nay em đi học',
    'Café au lait is nice', 'André reads 2:30', '- - -', '... !!!', 'word '.repeat(61), 'a'.repeat(301),
    `${'abcdefghij '.repeat(27)}abcdefgh`, '\u{3000}ideographic\u{3000}space', 'nbsp\xa0here', 'line\u{2028}sep',
];

const POOL = ['a', 'b', 'Z', 'e', ' ', '\t', '\n', '\x0b', '\x1c', '\x1f', '\x85', '\x91', '\x92', '\x93',
    '\x94', '\x96', '\x97', '\x9b', '\xa0', '\u{2003}', '\u{2028}', '\u{200B}', '\u{200D}', '\u{FEFF}', '\xad', '\u{2019}',
    '\u{201C}', '\u{2014}', '\u{2026}', '-', '.', ',', '1', 'é', 'ạ', '\u{3000}', '!', '?', '\u{301}', 'Δ'];

function randomTexts(count) {
    let seed = 20261116;
    const next = () => {
        seed = (seed * 1103515245 + 12345) % 2147483648;
        return seed / 2147483648;
    };
    const texts = [];
    for (let i = 0; i < count; i += 1) {
        let text = '';
        const length = 1 + Math.floor(next() * 14);
        for (let j = 0; j < length; j += 1) text += POOL[Math.floor(next() * POOL.length)];
        texts.push(text);
    }
    return texts;
}

test('the page reads a text exactly as the server does', () => {
    const page = loadPage();
    const texts = [...CURATED, ...randomTexts(20000)];
    const expected = server(texts);
    const differences = [];
    texts.forEach((text, index) => {
        const [normalized, code] = expected[index];
        const checked = page.checkText(text);
        const pageCode = PAGE_CODE[checked.problem] ?? checked.problem;
        if (page.normalizeText(text) !== normalized || checked.text !== normalized || pageCode !== code) {
            differences.push({ text, page: [page.normalizeText(text), pageCode], server: [normalized, code] });
        }
    });
    assert.deepEqual(differences.slice(0, 5), [], `${differences.length} texts read differently`);
});
