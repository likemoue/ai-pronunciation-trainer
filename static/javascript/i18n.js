'use strict';

// The interface's words in English and Vietnamese (context/design-system.md
// §5). The server renders the page in the learner's language (the `lang`
// cookie) and puts both dictionaries in #i18nData (i18n.py): keys are
// "<area>.<name>", {name} is a placeholder, and a plural is a pair of keys,
// "<key>.one" and "<key>.other", chosen with Intl.PluralRules.
//
// Elements carry their key, so a language switch re-renders them in place:
// data-i18n="key" (the text), data-i18n-params='{"count": 3}' (its
// placeholders), data-i18n-attr="aria-label:key; placeholder:key" (attributes)
// and data-i18n-rich="key" (a text with elements in it: each {slot} is the
// child element with data-slot="slot", which keeps its own data-i18n).
(() => {
    const LANGUAGES = ['en', 'vi'];
    const DEFAULT = 'en';
    const STORAGE_KEY = 'aipt.lang';
    const TIME_ZONE = 'Asia/Ho_Chi_Minh';
    const PLACEHOLDER = /\{(\w+)\}/g;
    const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

    let dictionaries = {};
    try {
        dictionaries = JSON.parse(document.getElementById('i18nData').textContent) || {};
    } catch (err) {
        console.error('The page has no dictionaries', err);
    }

    let lang = LANGUAGES.includes(document.documentElement.lang) ? document.documentElement.lang : DEFAULT;
    const listeners = [];
    const numberFormats = {};
    const pluralRules = {};

    function lookup(key) {
        const mine = dictionaries[lang] || {};
        if (own(mine, key)) return mine[key];
        const fallback = dictionaries[DEFAULT] || {};
        return own(fallback, key) ? fallback[key] : undefined;
    }

    const has = (key) => lookup(key) !== undefined || lookup(`${key}.other`) !== undefined;

    // 1,240 in English, 1.240 in Vietnamese.
    function formatNumber(value, options) {
        const id = `${lang} ${JSON.stringify(options || {})}`;
        if (!numberFormats[id]) numberFormats[id] = new Intl.NumberFormat(lang, options);
        return numberFormats[id].format(value);
    }

    function pluralForm(count) {
        if (!pluralRules[lang]) pluralRules[lang] = new Intl.PluralRules(lang);
        return pluralRules[lang].select(count);
    }

    // The raw text of a key, or of its plural form for params.count.
    function template(key, params) {
        let text = lookup(key);
        if (text === undefined && params && typeof params.count === 'number') {
            text = lookup(`${key}.${pluralForm(params.count)}`);
            if (text === undefined) text = lookup(`${key}.other`);
        }
        if (text === undefined) {
            console.warn('No text for', key);
            return key;
        }
        return text;
    }

    const show = (value) => (typeof value === 'number' ? formatNumber(value) : String(value));

    // The text of key in the interface language, its placeholders filled
    // (numbers formatted for the language).
    function t(key, params) {
        return template(key, params).replace(PLACEHOLDER, (whole, name) => (
            params && own(params, name) ? show(params[name]) : whole));
    }

    // A text with elements in it, as a fragment: rich('how.step2', { mic: element })
    // puts the element where "{mic}" is. A slot may be a function that makes
    // its element; a placeholder without a slot is filled from params.
    function rich(key, slots = {}, params) {
        const fragment = document.createDocumentFragment();
        const text = template(key, params);
        let position = 0;
        text.replace(PLACEHOLDER, (whole, name, offset) => {
            if (offset > position) fragment.appendChild(document.createTextNode(text.slice(position, offset)));
            if (own(slots, name)) {
                const slot = typeof slots[name] === 'function' ? slots[name]() : slots[name];
                fragment.appendChild(slot);
            } else {
                fragment.appendChild(document.createTextNode(params && own(params, name) ? show(params[name]) : whole));
            }
            position = offset + whole.length;
            return whole;
        });
        if (position < text.length) fragment.appendChild(document.createTextNode(text.slice(position)));
        return fragment;
    }

    function paramsOf(node) {
        if (!node.dataset.i18nParams) return undefined;
        try {
            return JSON.parse(node.dataset.i18nParams);
        } catch (_) {
            return undefined;
        }
    }

    // "aria-label:a.b; placeholder:c.d" as [['aria-label', 'a.b'], ['placeholder', 'c.d']].
    const attrPairs = (value) => String(value || '').split(';')
        .map((pair) => pair.split(':').map((part) => part.trim()))
        .filter((pair) => pair.length === 2 && pair[0] && pair[1]);

    function applyRich(node) {
        const slots = {};
        Array.from(node.children).forEach((child) => {
            if (child.dataset.slot) slots[child.dataset.slot] = child;
        });
        node.replaceChildren(rich(node.dataset.i18nRich, slots, paramsOf(node)));
    }

    // Re-render every element under root that carries a key.
    function apply(root = document) {
        const each = (selector, fn) => {
            if (root.matches && root.matches(selector)) fn(root);
            root.querySelectorAll(selector).forEach(fn);
        };
        each('[data-i18n-rich]', applyRich);
        each('[data-i18n]', (node) => {
            node.textContent = t(node.dataset.i18n, paramsOf(node));
        });
        each('[data-i18n-attr]', (node) => {
            attrPairs(node.dataset.i18nAttr).forEach(([name, key]) => node.setAttribute(name, t(key)));
        });
    }

    // Set an element's text from a key, and keep the key for a language switch.
    function text(node, key, params) {
        node.removeAttribute('data-i18n-rich');
        node.dataset.i18n = key;
        if (params) node.dataset.i18nParams = JSON.stringify(params);
        else node.removeAttribute('data-i18n-params');
        node.textContent = t(key, params);
        return node;
    }

    // Set an element's content from a key with elements in it, and keep the
    // key for a language switch: slots names the elements ({ stop: element }),
    // which become its children and keep their own data-i18n.
    function richText(node, key, slots = {}, params) {
        node.removeAttribute('data-i18n');
        node.dataset.i18nRich = key;
        if (params) node.dataset.i18nParams = JSON.stringify(params);
        else node.removeAttribute('data-i18n-params');
        Object.keys(slots).forEach((name) => slots[name].setAttribute('data-slot', name));
        node.replaceChildren(rich(key, slots, params));
        return node;
    }

    // Set an attribute from a key (null: remove it), and keep the key.
    function attr(node, name, key) {
        const pairs = attrPairs(node.dataset.i18nAttr).filter(([other]) => other !== name);
        if (key) {
            pairs.push([name, key]);
            node.setAttribute(name, t(key));
        } else {
            node.removeAttribute(name);
        }
        if (pairs.length) node.dataset.i18nAttr = pairs.map((pair) => pair.join(':')).join('; ');
        else node.removeAttribute('data-i18n-attr');
        return node;
    }

    // Remember the language on this device: localStorage, and the cookie the
    // server reads to render the next page in it (webApp.main).
    function remember(value) {
        AIPT.storage.set(STORAGE_KEY, value);
        try {
            const secure = window.location.protocol === 'https:' ? '; Secure' : '';
            document.cookie = `lang=${value}; Path=/; Max-Age=31536000; SameSite=Lax${secure}`;
        } catch (_) {
            // Cookies refused: the choice still holds for this page.
        }
    }

    function setLanguage(next) {
        if (!LANGUAGES.includes(next)) return;
        remember(next);
        if (next === lang) return;
        lang = next;
        document.documentElement.lang = next;
        apply(document);
        listeners.forEach((fn) => {
            try {
                fn(lang);
            } catch (err) {
                console.error(err);
            }
        });
    }

    // The date (and time) in Vietnam, in the interface language.
    function formatDate(date, options = { dateStyle: 'medium' }) {
        return new Intl.DateTimeFormat(lang, { ...options, timeZone: TIME_ZONE }).format(date);
    }

    // The parts of a date in Vietnam ({ weekday, day, month, year }) as
    // `locale` writes them (the interface language by default).
    function dateParts(date, options, locale = lang) {
        const parts = {};
        new Intl.DateTimeFormat(locale, { ...options, timeZone: TIME_ZONE }).formatToParts(date).forEach((part) => {
            parts[part.type] = part.value;
        });
        return parts;
    }

    // "2026-11-16": the day in Vietnam (for "today" and the streak).
    function dayKey(date = new Date()) {
        const parts = dateParts(date, { year: 'numeric', month: '2-digit', day: '2-digit' }, 'en-US');
        return `${parts.year}-${parts.month}-${parts.day}`;
    }

    AIPT.i18n = {
        get lang() {
            return lang;
        },
        LANGUAGES,
        t,
        has,
        rich,
        text,
        richText,
        attr,
        apply,
        setLanguage,
        onChange(fn) {
            listeners.push(fn);
        },
        formatNumber,
        formatDate,
        dateParts,
        dayKey,
    };

    // A language chosen on this device whose cookie has gone (cleared, or
    // refused): switch to it, and set the cookie again for the next visit.
    const remembered = AIPT.storage.get(STORAGE_KEY);
    if (LANGUAGES.includes(remembered) && remembered !== lang) setLanguage(remembered);
})();
