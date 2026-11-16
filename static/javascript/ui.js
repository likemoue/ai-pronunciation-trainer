'use strict';

// Pieces of the interface that the page's parts share (context/design-system.md
// §2 and §4): the page's polite live region, notices and the dock above the
// controls, sheets and dialogs, focus helpers, and the radio group of the
// level chips.
(() => {
    const { el, icon, i18n } = AIPT;

    // ---------------------------------------------------------------- focus
    // focus() without the jump some browsers make; Safari before 15 has no
    // options and scrolls.
    function focus(node, { preventScroll = false } = {}) {
        if (!node || typeof node.focus !== 'function') return;
        try {
            node.focus({ preventScroll });
        } catch (_) {
            node.focus();
        }
    }

    const FOCUSABLE = [
        'a[href]', 'button:not([disabled])', 'input:not([disabled]):not([type="hidden"])',
        'select:not([disabled])', 'textarea:not([disabled])', '[tabindex]:not([tabindex="-1"])',
    ].join(', ');

    // The elements of root that Tab reaches, in order.
    function focusables(root) {
        return Array.from(root.querySelectorAll(FOCUSABLE))
            .filter((node) => node.getClientRects().length > 0 && !node.closest('[hidden], [inert]'));
    }

    // The lowest point of the page that the fixed bar (phones) leaves visible.
    function visibleBottom() {
        const zone = document.getElementById('controlZone');
        if (zone && getComputedStyle(zone).position === 'fixed') return zone.getBoundingClientRect().top;
        return window.innerHeight;
    }

    // ---------------------------------------------------------------- live regions
    const timers = new WeakMap();

    // Say text in a live region once: emptied first, so the same words are
    // read again. The page's region (#pageStatus) by default.
    function announce(text, region = document.getElementById('pageStatus')) {
        if (!region) return;
        clearTimeout(timers.get(region));
        region.textContent = '';
        if (!text) return;
        timers.set(region, setTimeout(() => {
            region.textContent = text;
        }, 60));
    }

    // ---------------------------------------------------------------- notices
    const ICONS = { warning: 'warn', error: 'warn', info: 'info', success: 'check' };

    // A dictionary text, given as 'key' or { key, params }.
    function textNode(tag, className, spec) {
        const node = el(tag, { className });
        const { key, params } = typeof spec === 'string' ? { key: spec } : spec;
        return i18n.text(node, key, params);
    }

    function actionButton(action) {
        const button = el('button', {
            className: `btn btn-secondary btn-sm${action.className ? ` ${action.className}` : ''}`,
            attrs: { type: 'button', id: action.id },
        }, [action.icon ? icon(action.icon) : null, textNode('span', '', action.label)]);
        button.addEventListener('click', action.onClick);
        return button;
    }

    // A notice (§2.9): icon, title, text and actions, in a family: 'warning',
    // 'error', 'info' or 'success'. It stays until the situation changes or the
    // learner acts; never a toast. role 'status', or 'alert' when it blocks.
    // Returns { el, set(spec) }: set() changes it in place, so the dock does
    // not read it as new and a focused action keeps its focus. The actions
    // stay unless the spec gives others ([] for none); `extra` is an element
    // after them (the address to copy by hand).
    function notice(spec) {
        const root = el('div', { attrs: { role: spec.role || 'status', tabindex: '-1' } });
        const body = el('div', { className: 'notice-body' });
        let iconNode = null;
        let actions = null;
        let extra = null;
        root.appendChild(body);

        function set(next) {
            const kind = next.kind || 'warning';
            root.className = `notice notice-${kind}`;
            const freshIcon = icon(next.icon || ICONS[kind], 'notice-icon');
            if (iconNode) iconNode.replaceWith(freshIcon);
            else root.insertBefore(freshIcon, body);
            iconNode = freshIcon;
            body.replaceChildren(textNode('p', 'notice-title', next.title),
                ...(next.text ? [textNode('p', 'notice-text', next.text)] : []));
            if (next.actions) {
                if (actions) actions.remove();
                actions = next.actions.length
                    ? el('div', { className: 'notice-actions' }, next.actions.map(actionButton)) : null;
                if (actions) body.after(actions);
            }
            if (Object.prototype.hasOwnProperty.call(next, 'extra')) {
                if (extra) extra.remove();
                extra = next.extra || null;
                if (extra) root.appendChild(extra);
            }
        }
        set(spec);
        return { el: root, set };
    }

    // The notices docked above the controls (§2.9): one at a time, the first
    // of `order` that is active. The dock is a polite live region, so a notice
    // that comes in is read.
    class Dock {
        constructor(container, order) {
            this.container = container;
            this.order = order;
            this.active = new Map();
            this.shown = '';
            this.forced = '';
        }

        // Activate the notice `name`, made by build() the first time.
        show(name, build) {
            if (!this.active.has(name)) this.active.set(name, build());
            this.forced = '';
            this.render();
            return this.active.get(name);
        }

        hide(name) {
            if (!this.active.delete(name)) return;
            if (this.forced === name) this.forced = '';
            this.render();
        }

        get(name) {
            return this.active.get(name) || null;
        }

        // Show `name` now even if another comes first, and move focus to it:
        // the control the learner tapped points to the notice that explains.
        reveal(name) {
            if (!this.active.has(name)) return;
            this.forced = name;
            this.render();
            focus(this.active.get(name).el);
        }

        render() {
            const top = this.forced || this.order.find((name) => this.active.has(name)) || '';
            if (top === this.shown) return;
            const hadFocus = this.container.contains(document.activeElement);
            this.shown = top;
            this.container.replaceChildren(...(top ? [this.active.get(top).el] : []));
            if (hadFocus && top) focus(this.active.get(top).el, { preventScroll: true });
        }
    }

    // ---------------------------------------------------------------- sheets
    // A bottom sheet below 768 px, a centred dialog from 768 px (§2.8): a fixed
    // header with the title as a heading (tabindex="-1"), a scrolling body,
    // fixed actions. While it is open the page behind is inert (a focus trap
    // where `inert` is missing); focus goes to the title, and back to the
    // opener on close. Escape and [data-sheet-close] dismiss it; a backdrop tap
    // too when closeOnBackdrop. No sheet opens over another.
    const app = document.getElementById('app');
    const supportsInert = 'inert' in HTMLElement.prototype;
    let openSheet = null;

    function setPageInert(on) {
        if (!app) return;
        if (supportsInert) {
            app.inert = on;
        } else if (on) {
            app.setAttribute('aria-hidden', 'true');
        } else {
            app.removeAttribute('aria-hidden');
        }
    }

    // An on-screen keyboard over the bottom of the page (iOS does not resize
    // the layout viewport): the sheet moves up by --keyboard-inset.
    let viewportHandler = null;

    function watchViewport(root) {
        const viewport = window.visualViewport;
        if (!viewport) return;
        viewportHandler = () => {
            const inset = Math.max(0, window.innerHeight - viewport.height - viewport.offsetTop);
            root.style.setProperty('--keyboard-inset', `${Math.round(inset)}px`);
        };
        viewport.addEventListener('resize', viewportHandler);
        viewport.addEventListener('scroll', viewportHandler);
        viewportHandler();
    }

    function unwatchViewport(root) {
        const viewport = window.visualViewport;
        if (viewport && viewportHandler) {
            viewport.removeEventListener('resize', viewportHandler);
            viewport.removeEventListener('scroll', viewportHandler);
        }
        viewportHandler = null;
        root.style.removeProperty('--keyboard-inset');
    }

    class Sheet {
        constructor(root, { closeOnBackdrop = false, onDismiss = null } = {}) {
            this.root = root;
            this.dialog = root.querySelector('[role="dialog"], [role="alertdialog"]');
            this.title = root.querySelector('.sheet-title');
            this.closeOnBackdrop = closeOnBackdrop;
            this.onDismiss = onDismiss || (() => this.close());
            this.opener = null;
            root.querySelectorAll('[data-sheet-close]').forEach((button) => {
                button.addEventListener('click', () => this.dismiss('close'));
            });
            const backdrop = root.querySelector('.backdrop');
            // A tap on the backdrop never takes focus out of the sheet.
            backdrop.addEventListener('mousedown', (event) => event.preventDefault());
            backdrop.addEventListener('click', () => {
                if (this.closeOnBackdrop) this.dismiss('backdrop');
            });
        }

        get isOpen() {
            return openSheet === this;
        }

        open(opener) {
            if (openSheet) return false;
            openSheet = this;
            const active = opener || document.activeElement;
            this.opener = active && active !== document.body ? active : null;
            this.root.hidden = false;
            setPageInert(true);
            document.body.classList.add('sheet-open');
            watchViewport(this.root);
            focus(this.title, { preventScroll: true });
            return true;
        }

        // Close; focus goes to `focusTo`, else back to the opener (or to
        // `fallback` when the opener is gone). restoreFocus: false leaves it
        // to the caller.
        close({ focusTo = null, fallback = null, restoreFocus = true } = {}) {
            if (openSheet !== this) return;
            openSheet = null;
            this.root.hidden = true;
            setPageInert(false);
            document.body.classList.remove('sheet-open');
            unwatchViewport(this.root);
            if (!restoreFocus) return;
            const opener = this.opener && document.contains(this.opener) ? this.opener : fallback;
            focus(focusTo || opener);
        }

        // ✕, Cancel, Escape or the backdrop: what the owner decides.
        dismiss(reason) {
            if (openSheet === this) this.onDismiss(reason);
        }
    }

    document.addEventListener('keydown', (event) => {
        if (!openSheet) return;
        if (event.key === 'Escape') {
            event.preventDefault();
            openSheet.dismiss('escape');
            return;
        }
        // Without inert, Tab would leave the sheet: keep it inside.
        if (event.key === 'Tab' && !supportsInert) {
            const items = focusables(openSheet.dialog);
            if (!items.length) return;
            const first = items[0];
            const last = items[items.length - 1];
            const inside = openSheet.dialog.contains(document.activeElement);
            if (event.shiftKey && (document.activeElement === first || !inside)) {
                event.preventDefault();
                focus(last);
            } else if (!event.shiftKey && (document.activeElement === last || !inside)) {
                event.preventDefault();
                focus(first);
            }
        }
    });

    // Focus that lands outside the open sheet (a click on the page where
    // inert is missing, a screen reader's cursor) comes back to it.
    document.addEventListener('focusin', (event) => {
        if (openSheet && !openSheet.root.contains(event.target)) focus(openSheet.title, { preventScroll: true });
    });

    // ---------------------------------------------------------------- radio group
    // Buttons with role="radio" in a role="radiogroup" (§2.5): one tab stop
    // (the checked one, else the first), arrow keys and Home/End move and
    // choose, a click chooses. onChoose(value, button) runs for every choice.
    function radioGroup(group, { onChoose }) {
        const radios = () => Array.from(group.querySelectorAll('[role="radio"]'));

        function syncTabStops() {
            const all = radios();
            const checked = all.find((radio) => radio.getAttribute('aria-checked') === 'true') || all[0];
            all.forEach((radio) => {
                radio.tabIndex = radio === checked ? 0 : -1;
            });
        }

        // Check the radio with data-value === value (null: none).
        function check(value) {
            radios().forEach((radio) => radio.setAttribute('aria-checked', String(radio.dataset.value === value)));
            syncTabStops();
        }

        group.addEventListener('click', (event) => {
            const radio = event.target.closest('[role="radio"]');
            if (radio && group.contains(radio)) onChoose(radio.dataset.value, radio);
        });

        group.addEventListener('keydown', (event) => {
            const all = radios();
            const index = all.indexOf(document.activeElement);
            if (index < 0) return;
            let next = -1;
            if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % all.length;
            else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index - 1 + all.length) % all.length;
            else if (event.key === 'Home') next = 0;
            else if (event.key === 'End') next = all.length - 1;
            if (next < 0) return;
            event.preventDefault();
            focus(all[next]);
            onChoose(all[next].dataset.value, all[next]);
        });

        syncTabStops();
        return { check };
    }

    AIPT.ui = {
        focus,
        focusables,
        visibleBottom,
        announce,
        notice,
        Dock,
        Sheet,
        radioGroup,
        get sheetOpen() {
            return Boolean(openSheet);
        },
    };
})();
