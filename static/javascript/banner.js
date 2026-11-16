'use strict';

// The in-app browser banner (design/wireframes/04-in-app-banner.html D1-D8; context/design-system.md §2.14):
// the first thing on the page, in its flow, a notice of the warning family, shown when an app's own browser
// shows the page (AIPT.env.inApp, read from the user agent: nothing is sent anywhere to find out). Teachers share
// the link in Zalo and Messenger groups, and the microphone often fails there.
// - Android: Open in Chrome (an intent link) and Copy link (D1, D2); for the Facebook family (Facebook,
//   Messenger, Instagram, LINE) the ⋮ menu's Open in browser as well, with an arrow to that menu (D5).
// - iPhone: no page can open Safari, so the banner names the app's ••• menu, with an arrow to it at the top
//   right of the screen, and Copy link (D3, D4).
// Where an arrow points at the app's menu, the banner keeps the top right free for it and is dismissed with Not
// now; elsewhere with ✕. Dismissed for this visit only (sessionStorage): it comes back on the next one (D8).
// Copy link confirms "Copied" for 4 s and says so once (D6); where the clipboard is refused, the address waits in a
// selected read-only field (D7). The pieces are inapp.js's, as in the recording sheet's B17 and B18.
(() => {
    const { $, el, icon, i18n, ui, storage } = AIPT;
    const { t } = i18n;

    const DISMISSED_KEY = 'aipt.banner';
    const slot = $('bannerSlot');
    const guide = AIPT.inApp.guidance();
    AIPT.banner = { shown: false };
    if (!slot || !guide || storage.session.get(DISMISSED_KEY) === 'dismissed') return;

    const ios = guide.platform === 'ios';
    // An arrow to the app's own menu: ••• on iPhone, ⋮ for the Facebook family on Android.
    const pointer = ios || guide.menu ? AIPT.inApp.pointer({ menu: !ios }) : null;

    const setIcon = (svg, name) => svg.querySelector('use').setAttribute('href', `#i-${name}`);

    const stateIcon = icon('warn', 'notice-icon banner-icon');
    const title = el('p', { className: 'banner-title', attrs: { id: 'bannerTitle' } });
    const text = el('p', { className: 'banner-text' });
    const address = AIPT.inApp.addressField('banner-field');
    address.hidden = true;
    const actions = el('div', { className: 'banner-actions' });

    const openChrome = guide.openChrome ? el('a', {
        className: 'btn btn-primary btn-sm',
        attrs: { href: AIPT.inApp.chromeIntentUrl() },
    }, [icon('open'), i18n.text(el('span'), 'inapp.openChrome')]) : null;
    const copyIcon = icon('copy');
    const copyLabel = i18n.text(el('span'), 'notice.copyLink');
    const copy = el('button', { className: 'btn btn-secondary btn-sm', attrs: { type: 'button' } }, [copyIcon, copyLabel]);
    const notNow = pointer
        ? i18n.text(el('button', { className: 'text-btn banner-not-now', attrs: { type: 'button' } }), 'banner.notNow') : null;
    const dismissButton = pointer ? null
        : i18n.attr(el('button', { className: 'banner-x', attrs: { type: 'button' } }, [icon('close')]), 'aria-label', 'banner.dismiss');

    // ✕ sits in the corner (style.css) but comes after the actions, for Tab and screen readers.
    const root = el('aside', {
        className: `banner notice-warning${pointer ? ' has-pointer' : ''}`,
        attrs: { 'aria-labelledby': 'bannerTitle', 'data-app': guide.app, 'data-platform': guide.platform },
    }, [stateIcon, el('div', { className: 'banner-body' }, [title, text]), address, actions, dismissButton, pointer]);

    // 'ready' (D1-D5), 'copied' for 4 s (D6), or 'refused': the address to copy by hand (D7).
    let state = 'ready';

    function writeTitle() {
        if (!guide.name) i18n.text(title, 'banner.titleUnnamed');
        else i18n.text(title, ios ? 'banner.titleIos' : 'banner.title', { app: guide.name });
    }

    // What to do: the ••• menu on iPhone ("Open in browser" in Zalo, "Open in Safari" in the others), Chrome or
    // the ⋮ menu for the Facebook family on Android, Chrome elsewhere on Android, the link anywhere else.
    function writeText() {
        if (ios) {
            i18n.richText(text, 'banner.ios', {
                dots: ui.uibit({ text: '•••' }),
                item: ui.uibit({ key: guide.app === 'zalo' ? 'inapp.openInBrowser' : 'inapp.openInSafari' }),
            });
        } else if (guide.menu) {
            AIPT.inApp.chromeOrMenu(text, 'banner.chromeOrMenu');
        } else {
            i18n.text(text, guide.openChrome ? 'banner.chrome' : 'banner.copyElsewhere');
        }
    }

    function render() {
        root.dataset.state = state;
        root.classList.toggle('notice-warning', state === 'ready');
        root.classList.toggle('notice-success', state === 'copied');
        root.classList.toggle('notice-info', state === 'refused');
        setIcon(stateIcon, { ready: 'warn', copied: 'check', refused: 'info' }[state]);
        if (state === 'copied') {
            i18n.text(title, 'notice.linkCopied.title');
            i18n.text(text, 'notice.linkCopied.text');
        } else if (state === 'refused') {
            i18n.text(title, 'notice.copyBlocked.title');
            i18n.text(text, 'notice.copyBlocked.text');
        } else {
            writeTitle();
            writeText();
        }
        // "✓ Copied" (D6).
        setIcon(copyIcon, state === 'copied' ? 'check' : 'copy');
        i18n.text(copyLabel, state === 'copied' ? 'notice.copied' : 'notice.copyLink');
        copy.classList.toggle('is-done', state === 'copied');
        address.hidden = state !== 'refused';
        // Once the clipboard was refused, the address takes the actions' place (D7). Moved only when they
        // change: a button that moves loses its focus.
        const wanted = (state === 'refused' ? [notNow] : [openChrome, copy, notNow]).filter(Boolean);
        const current = Array.from(actions.children);
        if (wanted.length !== current.length || wanted.some((node, index) => node !== current[index])) {
            actions.replaceChildren(...wanted);
        }
        actions.hidden = !wanted.length;
    }

    const copier = AIPT.inApp.copyControl({
        onCopied: () => {
            state = 'copied';
            render();
            ui.announce(t('notice.linkCopied.title'));
        },
        onReset: () => {
            if (state !== 'copied') return;
            state = 'ready';
            render();
        },
        onRefused: () => {
            state = 'refused';
            render();
            AIPT.inApp.selectAddress(address);
        },
    });

    // ✕ or Not now: gone for this visit; focus goes on to the header, the next thing on the page.
    function dismiss() {
        storage.session.set(DISMISSED_KEY, 'dismissed');
        copier.stop();
        const hadFocus = root.contains(document.activeElement);
        root.remove();
        AIPT.banner.shown = false;
        if (hadFocus) ui.focus(ui.focusables(document.querySelector('.topbar'))[0] || $('sentence'));
    }

    copy.addEventListener('click', () => copier.run());
    if (notNow) notNow.addEventListener('click', dismiss);
    if (dismissButton) dismissButton.addEventListener('click', dismiss);

    render();
    slot.appendChild(root);
    AIPT.banner.shown = true;
})();
