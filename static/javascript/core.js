'use strict';

// The page's scripts share one global, AIPT, and run in this order (defer):
// core.js, i18n.js, ui.js, inapp.js, audio.js, recorder.js, result.js,
// progress.js, miccheck.js, tour.js, banner.js, app.js. They are
// classic scripts with no build step, for the browsers of
// context/design-system.md §6 (Chrome 109, iOS 15 Safari, Android WebView,
// Firefox ESR 115): ES2021, and none of Array.prototype.at, findLast,
// structuredClone, Object.hasOwn, AbortSignal.timeout or crypto.randomUUID.
//
// This one holds what the others need: the API, the limits, DOM helpers,
// requests with a time limit, storage that never throws, the text rules of
// validation.py, and what kind of browser this is.
(() => {
    window.AIPT = {};

    AIPT.API = Object.freeze({
        sample: '/getSample',
        custom: '/getCustomSample',
        score: '/GetAccuracyFromRecordedAudio',
        tts: '/getAudioFromText',
    });

    // The language practised; the interface's is AIPT.i18n.lang.
    AIPT.PRACTICE_LANGUAGE = 'en';

    // validation.py (MAX_TEXT_CHARS, MAX_TEXT_WORDS, MIN_LATIN_LETTER_RATIO),
    // and the longest recording: one Whisper window.
    AIPT.LIMITS = Object.freeze({ chars: 300, words: 60, latinRatio: 0.9, recordingSeconds: 30 });

    // ---------------------------------------------------------------- DOM
    AIPT.$ = (id) => document.getElementById(id);

    // A new element: el('p', { className: 'x', text: 'Hello', attrs: { role: 'status' } }, [child, ...]).
    // Text always goes in as text, never as markup.
    AIPT.el = (tag, { className = '', text = '', attrs = {} } = {}, children = []) => {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text) node.textContent = text;
        Object.keys(attrs).forEach((name) => {
            if (attrs[name] !== null && attrs[name] !== undefined) node.setAttribute(name, attrs[name]);
        });
        children.forEach((child) => {
            if (child) node.appendChild(child);
        });
        return node;
    };

    const SVG = 'http://www.w3.org/2000/svg';

    // An icon of the sprite in templates/main.html (#i-<name>), hidden from
    // assistive technology: the control or text next to it names it.
    AIPT.icon = (name, className = '') => {
        const svg = document.createElementNS(SVG, 'svg');
        svg.setAttribute('class', className ? `icon ${className}` : 'icon');
        svg.setAttribute('aria-hidden', 'true');
        svg.setAttribute('focusable', 'false');
        const use = document.createElementNS(SVG, 'use');
        use.setAttribute('href', `#i-${name}`);
        svg.appendChild(use);
        return svg;
    };

    // A control the keyboard already acts on: the page's own shortcut (Space
    // to record) leaves it alone.
    const CONTROL = [
        'button', 'a[href]', 'input', 'textarea', 'select', 'summary', '[contenteditable=""]',
        '[contenteditable="true"]', '[role="button"]', '[role="radio"]', '[role="checkbox"]',
        '[role="switch"]', '[role="tab"]', '[role="link"]', '[role="menuitem"]',
    ].join(', ');
    AIPT.isControl = (node) => Boolean(node && node.closest && node.closest(CONTROL));

    // aria-disabled (design-system §2.2) keeps a control focusable, so that
    // it can say why it does nothing.
    AIPT.isDisabled = (node) => Boolean(node) && (node.disabled === true || node.getAttribute('aria-disabled') === 'true');

    AIPT.setDisabled = (node, disabled) => {
        if (disabled) node.setAttribute('aria-disabled', 'true');
        else node.removeAttribute('aria-disabled');
    };

    // ---------------------------------------------------------------- text
    // validation.normalize_text on the server, rule for rule: keep the two in
    // step. The invisible characters go (soft hyphen, zero-width space,
    // non-joiner and joiner, word joiner, byte order mark), and \x85,
    // \x91-\x94, \x96 and \x97 are Windows-1252's ellipsis, quotes and dashes
    // read as Latin-1.
    const normalizeText = (text) => text
        .replace(/[\xad\u{200B}-\u{200D}\u{2060}\u{FEFF}]/gu, '')
        .replace(/[‘’‛′\x91\x92]/g, "'")
        .replace(/[“”‟″\x93\x94]/g, '"')
        .replace(/[–—−\x96\x97]/g, ' - ')
        .replace(/[…\x85]/g, '...')
        // Python's str.split() also splits at U+001C-001F, which \s does not match.
        // eslint-disable-next-line no-control-regex -- those separators are what it looks for
        .replace(/[\s\x1c-\x1f]+/g, ' ')
        .trim()
        .split(' ')
        .filter((token) => /[\p{L}\p{N}]/u.test(token))
        .join(' ');

    const stripPunctuation = (word) => word.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, '');

    AIPT.normalizeText = normalizeText;
    AIPT.stripPunctuation = stripPunctuation;

    // validation._UNREADABLE: control characters and lone UTF-16 surrogates
    // (with the u flag, a range of surrogates matches only unpaired ones).
    // eslint-disable-next-line no-control-regex -- control characters are what it looks for
    const UNREADABLE = /[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\u{D800}-\u{DFFF}]/u;

    // validation.latin_letter_ratio: the share of letters (str.isalpha) that
    // are A-Z once lowercased, compared as strings as Python does.
    function latinLetterRatio(text) {
        let letters = 0;
        let latin = 0;
        for (const ch of text) {
            if (!/\p{L}/u.test(ch)) continue;
            letters += 1;
            const lower = ch.toLowerCase();
            if (lower >= 'a' && lower <= 'z') latin += 1;
        }
        return letters ? latin / letters : 0;
    }

    // validation.practice_text, rule for rule and in its order, so the page
    // stops before sending what the server would refuse: the normalised text,
    // its length in characters (code points, as Python counts) and words, and
    // the first problem: 'empty', 'text_too_long', 'text_bad_characters' or
    // 'text_not_english' (the server's error codes), or '' when it would pass.
    AIPT.checkText = (value) => {
        const text = normalizeText(String(value || ''));
        const chars = Array.from(text).length;
        const words = text ? text.split(' ').length : 0;
        const tooManyChars = chars > AIPT.LIMITS.chars;
        const tooManyWords = words > AIPT.LIMITS.words;
        let problem = '';
        if (!text) problem = 'empty';
        else if (tooManyChars || tooManyWords) problem = 'text_too_long';
        else if (UNREADABLE.test(text)) problem = 'text_bad_characters';
        else if (latinLetterRatio(text) < AIPT.LIMITS.latinRatio) problem = 'text_not_english';
        return { text, chars, words, tooManyChars, tooManyWords, problem };
    };
    AIPT.latinLetterRatio = latinLetterRatio;

    // "0:04" for 4.7 seconds.
    AIPT.formatClock = (seconds) => {
        const whole = Math.max(0, Math.floor(seconds));
        return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
    };

    // ---------------------------------------------------------------- requests
    const abortError = () => new DOMException('Aborted', 'AbortError');

    // fetch, given up after `timeout` ms (then an Error with code 'timeout')
    // or when the outer `signal` aborts (the AbortError, as fetch gives it).
    // No answer at all is an Error with code 'network'. `read` turns the
    // response into the result within the same time limit.
    async function fetchWithin(url, init, { signal, timeout = 0, read = (response) => response } = {}) {
        if (signal && signal.aborted) throw abortError();
        const controller = new AbortController();
        let timedOut = false;
        const abort = () => controller.abort();
        if (signal) signal.addEventListener('abort', abort, { once: true });
        const timer = timeout ? setTimeout(() => {
            timedOut = true;
            controller.abort();
        }, timeout) : 0;
        try {
            const response = await fetch(url, { ...init, signal: controller.signal });
            return await read(response);
        } catch (err) {
            if (timedOut) throw Object.assign(new Error('timeout'), { code: 'timeout', status: 0 });
            if (err && err.name === 'AbortError') throw err;
            if (err instanceof TypeError) throw Object.assign(new Error('network'), { code: 'network', status: 0 });
            throw err;
        } finally {
            clearTimeout(timer);
            if (signal) signal.removeEventListener('abort', abort);
        }
    }

    // The answer's JSON; an answer that is not OK is an Error with the
    // server's `code` (webApp._error), its `status`, and `retryAfter` in
    // seconds (at most 60) for a busy server. The server's message is never
    // shown: the page maps each code to its own text (i18n, error.<code>).
    async function readJSON(response) {
        const raw = await response.text();
        let data;
        try {
            data = raw ? JSON.parse(raw) : null;
        } catch (_) {
            data = null;
        }
        if (!response.ok) {
            const code = data && typeof data.code === 'string' ? data.code : '';
            const err = new Error(code || `HTTP ${response.status}`);
            err.status = response.status;
            err.code = code;
            const retryAfter = Number(response.headers.get('Retry-After') || (data && data.retry_after));
            err.retryAfter = Number.isFinite(retryAfter) && retryAfter > 0 ? Math.min(retryAfter, 60) : 0;
            throw err;
        }
        return data;
    }

    // POST a JSON body and read the JSON answer: postJSON(url, body, { signal, timeout }).
    AIPT.postJSON = (url, body, options = {}) => fetchWithin(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    }, { ...options, read: readJSON });

    // GET a file as a Blob (the bank sentence's MP3), with the same errors.
    AIPT.fetchBlob = (url, options = {}) => fetchWithin(url, {}, {
        ...options,
        read: async (response) => {
            if (!response.ok) await readJSON(response);
            return response.blob();
        },
    });

    AIPT.sleep = (ms, signal) => new Promise((resolve, reject) => {
        if (signal && signal.aborted) {
            reject(abortError());
            return;
        }
        const timer = setTimeout(resolve, ms);
        if (signal) {
            signal.addEventListener('abort', () => {
                clearTimeout(timer);
                reject(abortError());
            }, { once: true });
        }
    });

    // ---------------------------------------------------------------- storage
    // localStorage and sessionStorage, which some WebViews and private modes
    // refuse, even to read: every access is in try/catch, and the page works
    // on without them (nothing is remembered).
    function storageArea(name) {
        const area = () => {
            try {
                return window[name] || null;
            } catch (_) {
                return null;
            }
        };
        return {
            get(key, fallback = null) {
                try {
                    const store = area();
                    const value = store ? store.getItem(key) : null;
                    return value === null ? fallback : value;
                } catch (_) {
                    return fallback;
                }
            },
            set(key, value) {
                try {
                    const store = area();
                    if (!store) return false;
                    store.setItem(key, String(value));
                    return true;
                } catch (_) {
                    return false;
                }
            },
            remove(key) {
                try {
                    const store = area();
                    if (store) store.removeItem(key);
                } catch (_) {
                    // Nothing to remove from a store the browser refuses.
                }
            },
        };
    }

    AIPT.storage = storageArea('localStorage');
    AIPT.storage.session = storageArea('sessionStorage');

    // ---------------------------------------------------------------- environment
    // What the browser is, from its user agent (design/wireframes/04-in-app-banner.html):
    // inApp names the app whose own browser shows the page ('zalo', 'messenger',
    // 'instagram', 'line', 'facebook', 'webview' for any other Android WebView,
    // '' for none); platform is 'android', 'ios' or 'other'; browser is
    // 'chrome', 'edge', 'safari', 'firefox' or 'other'.
    function detectEnv(userAgent, maxTouchPoints = 0) {
        const ua = String(userAgent || '');
        let inApp = '';
        if (/Zalo/i.test(ua)) inApp = 'zalo';
        else if (/Messenger/i.test(ua)) inApp = 'messenger'; // Messenger, FB_IAB/MESSENGER, MessengerForiOS
        else if (/Instagram/.test(ua)) inApp = 'instagram';
        else if (/\bLine\//.test(ua)) inApp = 'line';
        else if (/FBAN|FBAV|FB_IAB/.test(ua)) inApp = 'facebook';
        else if (/Android/.test(ua) && /; wv\)/.test(ua)) inApp = 'webview';

        const ios = /iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && maxTouchPoints > 1);
        const platform = /Android/.test(ua) ? 'android' : ios ? 'ios' : 'other';

        let browser = 'other';
        if (/\bEdg(?:e|A|iOS)?\//.test(ua)) browser = 'edge';
        else if (/Firefox\/|FxiOS\//.test(ua)) browser = 'firefox';
        else if (/OPR\/|SamsungBrowser\/|YaBrowser\//.test(ua)) browser = 'other';
        else if (/Chrome\/|CriOS\//.test(ua)) browser = 'chrome';
        else if (/Safari\//.test(ua) && !/Android/.test(ua)) browser = 'safari';

        return { inApp, platform, browser };
    }

    const secure = window.isSecureContext !== false;
    const canCapture = Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    AIPT.detectEnv = detectEnv;
    AIPT.env = Object.freeze({
        ...detectEnv(navigator.userAgent, navigator.maxTouchPoints),
        // Recording needs all three; checked before any tap (wireframes A10).
        secure,
        canRecord: secure && canCapture && typeof window.MediaRecorder === 'function',
    });

    const motion = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
    AIPT.reducedMotion = () => Boolean(motion && motion.matches);
})();
