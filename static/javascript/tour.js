'use strict';

// The tour (design/wireframes/05-onboarding.html E1-E4; context/design-system.md §2.18): three steps over the
// real controls, wherever the layout puts them (the bar on phones, inline from 768 px): Listen, the mic, the
// sentence card. Each step is a spotlight on the control with the rest of the page dimmed (--dim), and a callout
// card: "Step 1 of 3", a title, a text, Skip · pips · Next. The callout is a modal dialog for assistive
// technology: focus on its title, Tab stays inside, Escape skips. The last step's main action is the microphone
// check (miccheck.js), so that the browser's permission prompt comes with an explanation.
//
// It starts by itself once, on a first visit, when the first sentence is shown (sentenceShown), unless:
// - it was seen or skipped before (the flag aipt.tour; "New learner" clears it);
// - the page is inside an app's own browser: the banner speaks first there, and the tour waits for a real
//   browser (which has its own storage, so the learner meets the tour there);
// - the browser cannot record: its notice speaks first, and two of the three steps would be about a control
//   that does nothing;
// - the browser keeps nothing (storage refused): the tour would come back on every visit;
// - the learner is already busy: a sheet is open, or a recording runs.
// How it works reopens it at any time (start).
(() => {
    const { $, el, icon, i18n, ui, env, storage } = AIPT;

    const SEEN_KEY = 'aipt.tour';
    const PROBE_KEY = 'aipt.probe';
    const PAD = 6; // the spotlight around the control
    const GAP = 12; // between the spotlight and the callout
    const EDGE = 12; // between the callout and the screen's edges
    const MAX_WIDTH = 400;

    const els = {
        root: $('tour'),
        spot: $('tourSpot'),
        callout: $('tourCallout'),
        step: $('tourStep'),
        title: $('tourTitle'),
        text: $('tourText'),
        skip: $('tourSkip'),
        next: $('tourNext'),
        nextIcon: $('tourNextIcon'),
        nextLabel: $('tourNextLabel'),
    };
    const pips = Array.from(els.root.querySelectorAll('.tour-pips i'));

    const wide = () => window.matchMedia('(min-width: 768px)').matches;
    const bold = (key) => i18n.text(el('b'), key);

    // A boxed mark as in the result (~ Almost, ✗ Needs work), named by its status.
    const mark = (status) => el('b', { className: 'tips-mark' }, [
        el('span', { className: `mark mark-${status}`, attrs: { 'aria-hidden': 'true' } },
            [icon(status === 1 ? 'almost' : 'needs-work')]),
        i18n.text(el('span', { className: 'visually-hidden' }), status === 1 ? 'status.almost' : 'status.needsWork'),
    ]);

    // "books" with its s bold and dotted and the ~ mark after it.
    const example = () => el('span', { className: 'tour-example' }, [
        el('span', { attrs: { lang: 'en' } }, [document.createTextNode('book'), el('span', { className: 'wl', text: 's' })]),
        mark(1),
    ]);

    // Each step: the control it shows, and its words (tap on phones, click from 768 px).
    const STEPS = [
        {
            target: () => $('btnListen').closest('.control'),
            title: () => 'tour.listenTitle',
            text: (node) => i18n.richText(node, wide() ? 'tour.listenTextWide' : 'tour.listenText',
                { listen: bold('controls.listen'), slow: bold('card.slow') }),
        },
        {
            target: () => $('btnRecord').closest('.control'),
            title: () => (wide() ? 'tour.micTitleWide' : 'tour.micTitle'),
            text: (node) => (wide()
                ? i18n.richText(node, 'tour.micTextWide', { stop: bold('controls.stop'), space: i18n.text(el('kbd'), 'controls.space') })
                : i18n.richText(node, 'tour.micText', { stop: bold('controls.stop') })),
        },
        {
            target: () => $('sentenceCard'),
            title: () => 'tour.resultTitle',
            text: (node) => i18n.richText(node, wide() ? 'tour.resultTextWide' : 'tour.resultText', {
                almost: mark(1),
                needsWork: mark(2),
                letters: i18n.text(el('b', { className: 'wl' }), 'tour.boldDotted'),
                example: example(),
            }),
        },
    ];

    let index = -1; // the step shown, or -1 when the tour is closed
    let opener = null;
    let autoTried = false;
    let frame = 0;
    let wasWide = wide();

    // ---------------------------------------------------------------- placing
    // A control in the bar fixed at the bottom of phones does not scroll with the page.
    function inFixedBar(node) {
        const zone = $('controlZone');
        return zone.contains(node) && getComputedStyle(zone).position === 'fixed';
    }

    function setBox(node, { left, top, width, height }) {
        node.style.setProperty('left', `${Math.round(left)}px`);
        node.style.setProperty('top', `${Math.round(top)}px`);
        if (width !== undefined) node.style.setProperty('width', `${Math.round(width)}px`);
        if (height !== undefined) node.style.setProperty('height', `${Math.round(height)}px`);
    }

    // The spotlight on the step's control, and the callout below it, or above, whichever has room (above the
    // bar on phones); when neither has, a control in the page is scrolled near the top first (scroll).
    function place(scroll = false) {
        if (index < 0) return;
        const target = STEPS[index].target();
        if (!target) return;
        const viewWidth = document.documentElement.clientWidth;
        const viewHeight = window.innerHeight;
        const width = Math.min(MAX_WIDTH, viewWidth - EDGE * 2);
        els.callout.style.setProperty('width', `${width}px`);
        const height = els.callout.offsetHeight;
        const fits = (rect) => rect.bottom + PAD + GAP + height <= viewHeight - EDGE
            || rect.top - PAD - GAP - height >= EDGE;
        let rect = target.getBoundingClientRect();
        if (scroll && !inFixedBar(target)) {
            const hidden = rect.top < EDGE || rect.bottom > viewHeight - EDGE;
            if (hidden || !fits(rect)) {
                window.scrollBy(0, rect.top - PAD - EDGE);
                rect = target.getBoundingClientRect();
            }
        }
        const box = {
            left: rect.left - PAD, top: rect.top - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2,
        };
        setBox(els.spot, box);
        const below = box.top + box.height + GAP;
        const above = box.top - GAP - height;
        let top;
        if (below + height <= viewHeight - EDGE) top = below;
        else if (above >= EDGE) top = above;
        else top = Math.max(EDGE, viewHeight - EDGE - height);
        const left = Math.max(EDGE, Math.min(box.left + box.width / 2 - width / 2, viewWidth - EDGE - width));
        setBox(els.callout, { left, top });
    }

    // After any change of the layout (a resize, a font, the IPA arriving), on the next frame.
    function schedule() {
        if (index < 0) return;
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
            if (wide() !== wasWide) {
                wasWide = wide();
                write();
            }
            place(false);
        });
    }

    // ---------------------------------------------------------------- steps
    // The step's words. The last step's main action is the microphone check, or Done in a browser that cannot
    // record; its other action is Done instead of Skip.
    function write() {
        const step = STEPS[index];
        const last = index === STEPS.length - 1;
        const check = last && env.canRecord;
        els.root.dataset.step = String(index + 1);
        i18n.text(els.step, 'tour.step', { step: index + 1, total: STEPS.length });
        i18n.text(els.title, step.title());
        step.text(els.text);
        i18n.text(els.skip, last ? 'common.done' : 'common.skip');
        els.skip.hidden = last && !check;
        let label = 'tour.next';
        if (last) label = check ? 'tour.checkMic' : 'common.done';
        i18n.text(els.nextLabel, label);
        els.nextIcon.setAttribute('href', check ? '#i-mic' : last ? '#i-check' : '#i-next');
        pips.forEach((pip, n) => pip.classList.toggle('is-on', n === index));
    }

    function show(next) {
        index = next;
        write();
        place(true);
        ui.focus(els.title, { preventScroll: true });
    }

    // from: the control that started it (How it works), which gets focus back; else Listen.
    function start(from = null) {
        if (index >= 0 || ui.sheetOpen) return false;
        AIPT.audio.stop();
        opener = from;
        wasWide = wide();
        els.root.hidden = false;
        ui.cover(true);
        show(0);
        return true;
    }

    // Done, Skip, Escape, or the check: the tour is not shown by itself again. then(focusBack) opens what comes
    // next instead of moving focus.
    function finish(then = null) {
        if (index < 0) return;
        storage.set(SEEN_KEY, 'seen');
        index = -1;
        cancelAnimationFrame(frame);
        els.root.hidden = true;
        delete els.root.dataset.step;
        ui.cover(false);
        const usable = opener && document.contains(opener) && opener.getClientRects().length > 0;
        const back = usable ? opener : $('btnListen');
        opener = null;
        if (then) then(back);
        else ui.focus(back);
    }

    els.next.addEventListener('click', () => {
        if (index < 0) return;
        if (index < STEPS.length - 1) show(index + 1);
        else if (env.canRecord) finish((back) => AIPT.micCheck.open(back));
        else finish();
    });
    els.skip.addEventListener('click', () => finish());

    document.addEventListener('keydown', (event) => {
        if (index < 0) return;
        if (event.key === 'Escape') {
            event.preventDefault();
            finish();
        } else if (event.key === 'Tab') {
            ui.trapTab(event, els.callout);
        }
    });
    // Focus that lands outside the callout (a screen reader's cursor) comes back to it.
    document.addEventListener('focusin', (event) => {
        if (index >= 0 && !els.callout.contains(event.target)) ui.focus(els.title, { preventScroll: true });
    });

    window.addEventListener('resize', schedule);
    window.addEventListener('scroll', schedule, { passive: true });
    if (window.visualViewport) window.visualViewport.addEventListener('resize', schedule);
    if (window.ResizeObserver) new ResizeObserver(schedule).observe(document.documentElement);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(schedule, () => {});

    // ---------------------------------------------------------------- by itself
    // Somewhere to keep the flag.
    function canRemember() {
        if (!storage.set(PROBE_KEY, '1')) return false;
        storage.remove(PROBE_KEY);
        return true;
    }

    // The page shows a sentence (app.js): on a first visit, the first time, the tour starts by itself.
    function sentenceShown() {
        if (autoTried) return;
        autoTried = true;
        if (storage.get(SEEN_KEY) !== null || env.inApp || !env.canRecord || !canRemember()) return;
        if (ui.sheetOpen || AIPT.recorder.busy) return;
        start(null);
    }

    // "New learner": the next visit is a first one again.
    AIPT.progress.onReset(() => storage.remove(SEEN_KEY));

    AIPT.tour = {
        start,
        sentenceShown,
        get open() {
            return index >= 0;
        },
    };
})();
