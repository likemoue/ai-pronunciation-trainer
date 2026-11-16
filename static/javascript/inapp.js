'use strict';

// In-app browsers (design/wireframes/04-in-app-banner.html): the app whose own
// browser shows the page (AIPT.env.inApp, read from the user agent: nothing is
// sent anywhere to find out), the ways out of it (Open in Chrome on Android,
// the app's ••• menu on iPhone), and Copy link, with the address in a field to
// copy by hand where the clipboard is refused (design-system §6). The
// recording sheet shows them when the microphone fails inside an app (B17,
// B18; D9, D10); the page's banner (D1-D8) is made of the same pieces.
(() => {
    const { el, i18n, ui, env } = AIPT;

    // How long "Link copied" stays before the control offers Copy link again.
    const COPIED_MS = 4000;

    // The apps' own names, the same in every language ('webview' has none).
    const APP_NAMES = Object.freeze({
        zalo: 'Zalo',
        facebook: 'Facebook',
        messenger: 'Messenger',
        instagram: 'Instagram',
        line: 'LINE',
    });

    // The page's address, without a fragment.
    function pageUrl() {
        const { href } = window.location;
        const hash = href.indexOf('#');
        return hash < 0 ? href : href.slice(0, hash);
    }

    // A link that Android opens in Chrome (D1), or at the same address in the
    // default browser where Chrome is missing.
    function chromeIntentUrl() {
        const url = new URL(pageUrl());
        const scheme = url.protocol.replace(/:$/, '');
        return `intent://${url.host}${url.pathname}${url.search}#Intent;scheme=${scheme};`
            + `package=com.android.chrome;S.browser_fallback_url=${encodeURIComponent(url.href)};end`;
    }

    // What to tell the learner inside this app, or null outside one:
    //   name        the app's name ('' for the WebView of an app not known by name);
    //   platform    'android', 'ios' or 'other';
    //   openChrome  an intent link can open Chrome (Android);
    //   menu        the app's own menu has "Open in browser" too (the Facebook
    //               family on Android, D5).
    function guidance() {
        if (!env.inApp) return null;
        const android = env.platform === 'android';
        return {
            app: env.inApp,
            name: APP_NAMES[env.inApp] || '',
            platform: env.platform,
            openChrome: android,
            menu: android && env.inApp !== 'zalo' && env.inApp !== 'webview',
        };
    }

    // The steps to open the page in Safari through the app's ••• menu (B18,
    // D10), as list items. Menus differ between apps and versions, so the
    // second step names both wordings.
    function safariSteps() {
        return [
            i18n.richText(el('li'), 'inapp.ios1', { dots: ui.uibit({ text: '•••' }) }),
            i18n.richText(el('li'), 'inapp.ios2', {
                openInSafari: ui.uibit({ key: 'inapp.openInSafari' }),
                openInBrowser: ui.uibit({ key: 'inapp.openInBrowser' }),
            }),
        ];
    }

    // node says: open the page in Chrome, or tap ⋮ at the top right, then
    // Open in browser (D5: an app may block the intent link).
    function chromeOrMenu(node) {
        return i18n.richText(node, 'inapp.chromeOrMenu', {
            menu: ui.uibit({ icon: 'more-vert', key: 'inapp.menu' }),
            openInBrowser: ui.uibit({ key: 'inapp.openInBrowser' }),
        });
    }

    // Copy the page's address: true when the clipboard took it, false when
    // the browser refused (some WebViews) or has no clipboard to write to.
    function copyLink() {
        try {
            if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
                return navigator.clipboard.writeText(pageUrl()).then(() => true, () => false);
            }
        } catch (_) {
            // A clipboard that throws instead of refusing: copy by hand.
        }
        return Promise.resolve(false);
    }

    // The address in a read-only field, to copy by hand (D7).
    function addressField(className = '') {
        const field = el('input', {
            className: className ? `address-field ${className}` : 'address-field',
            attrs: { type: 'text', readonly: '', value: pageUrl(), lang: 'en', spellcheck: 'false', autocomplete: 'off' },
        });
        return i18n.attr(field, 'aria-label', 'notice.address');
    }

    // Focus the field with its whole address selected: one long press copies it.
    function selectAddress(field) {
        field.value = pageUrl();
        ui.focus(field, { preventScroll: true });
        try {
            field.setSelectionRange(0, field.value.length);
        } catch (_) {
            field.select();
        }
    }

    // A Copy link control (D6, D7): run() copies the address, then calls
    // onCopied() and, 4 s later, onReset(); or onRefused() when the clipboard
    // is refused. A new run() or stop() drops what an earlier run still had
    // to do. The caller decides what changes on screen and what is said.
    function copyControl({ onCopied = () => {}, onReset = () => {}, onRefused = () => {} } = {}) {
        let token = 0;
        let timer = 0;
        const stop = () => {
            token += 1;
            clearTimeout(timer);
        };
        return {
            run() {
                stop();
                const mine = token;
                return copyLink().then((copied) => {
                    if (mine !== token) return copied;
                    if (!copied) {
                        onRefused();
                        return false;
                    }
                    onCopied();
                    timer = setTimeout(() => {
                        if (mine === token) onReset();
                    }, COPIED_MS);
                    return true;
                });
            },
            stop,
        };
    }

    // The arrow to the app's ••• menu at the top right of the screen (D3,
    // D10), drawn over the page and over a sheet's backdrop. Decorative: the
    // steps say the same.
    function pointer() {
        return el('div', { className: 'inapp-pointer', attrs: { 'aria-hidden': 'true' } }, [
            el('span', { className: 'inapp-pointer-arrow' }),
            i18n.text(el('span', { className: 'inapp-pointer-label' }), 'inapp.pointer'),
        ]);
    }

    AIPT.inApp = {
        COPIED_MS,
        guidance,
        pageUrl,
        chromeIntentUrl,
        safariSteps,
        chromeOrMenu,
        copyLink,
        copyControl,
        addressField,
        selectAddress,
        pointer,
    };
})();
