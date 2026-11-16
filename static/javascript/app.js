'use strict';

// The page itself (design/wireframes 01, 07, 08): the level chips, the
// sentence card with Listen · Mic · Next (a bar fixed at the bottom of phones,
// inline from 768 px), the notices docked above them, the My text sheet, the
// language switch and the Space shortcut. Loaded last: it wires the parts the
// other scripts provide.
(() => {
    const { $, i18n, ui, storage, env } = AIPT;
    const { t } = i18n;

    const SAMPLE_TIMEOUT_MS = 15000;
    const LONG_TEXT_WORDS = 20;
    const WORDS_PER_MINUTE = 110;
    // The recording stops at 30 s; above about 26 s of reading the text may not fit.
    const LONG_READ_SECONDS = 26;
    const DRAFT_KEY = 'aipt.draft';

    const els = {
        app: $('app'),
        levels: $('levels'),
        card: $('sentenceCard'),
        cardLabel: $('cardLabel'),
        cardLabelText: $('cardLabelText'),
        btnMyText: $('btnMyText'),
        myTextLabel: $('myTextLabel'),
        skeleton: $('sentenceSkeleton'),
        sentence: $('sentence'),
        ipa: $('ipa'),
        loadError: $('loadError'),
        btnRetryLoad: $('btnRetryLoad'),
        slowToggle: $('slowToggle'),
        btnShowIpa: $('btnShowIpa'),
        showIpaLabel: $('showIpaLabel'),
        playingNote: $('playingNote'),
        playingText: $('playingText'),
        zone: $('controlZone'),
        dock: $('dock'),
        btnListen: $('btnListen'),
        listenLabel: $('listenLabel'),
        btnRecord: $('btnRecord'),
        micLabel: $('micLabel'),
        btnNext: $('btnNext'),
        langButtons: Array.from(document.querySelectorAll('.lang-btn')),
        // My text
        myTextSheet: $('myTextSheet'),
        field: $('customText'),
        countChars: $('countChars'),
        countWords: $('countWords'),
        countTime: $('countTime'),
        message: $('customMessage'),
        messageIcon: $('customMessageIcon'),
        messageText: $('customMessageText'),
        myTextStatus: $('myTextStatus'),
        myTextAlert: $('myTextAlert'),
        btnUseCustom: $('btnUseCustom'),
        useCustomLabel: $('useCustomLabel'),
    };

    const state = {
        category: '1', // the level asked for: '1' easy, '2' medium, '3' hard, '0' random
        mode: 'bank', // 'bank' or 'custom' (My text)
        text: '',
        ipa: '',
        ttsUrl: '', // the bank sentence's MP3
        ipaOpen: true,
        loading: false,
        loadController: null,
        loadFailed: false,
        offline: navigator.onLine === false,
        listen: 'idle', // the Listen button: 'idle', 'loading' or 'playing'
    };

    const words = (text) => (text ? text.split(' ').length : 0);

    // ---------------------------------------------------------------- notices
    // One docked notice at a time (design-system §2.9): a failed new sentence
    // (the learner just asked for it), then cannot record > offline > no voice.
    const dock = new ui.Dock(els.dock, ['loadFailed', 'cannotRecord', 'offline', 'noVoice']);

    // Copy link in a notice (AIPT.inApp.copyControl): "Link copied" for 4 s,
    // then back to what it said; where the clipboard is refused, the address
    // in a selected read-only field to copy by hand (§6). The dock is a polite
    // live region: the new words are read as they change.
    function copyLinkAction(getItem, base) {
        const label = () => getItem().el.querySelector('.notice-actions .btn span');
        const copier = AIPT.inApp.copyControl({
            onCopied: () => {
                getItem().set({ ...base, kind: 'success', icon: 'check', title: 'notice.linkCopied.title', text: 'notice.linkCopied.text' });
                if (label()) i18n.text(label(), 'notice.copied');
            },
            onReset: () => {
                getItem().set(base);
                if (label()) i18n.text(label(), 'notice.copyLink');
            },
            onRefused: () => {
                const field = AIPT.inApp.addressField('notice-field');
                getItem().set({ ...base, title: 'notice.copyBlocked.title', text: 'notice.copyBlocked.text', actions: [], extra: field });
                AIPT.inApp.selectAddress(field);
            },
        });
        return { label: 'notice.copyLink', icon: 'copy', onClick: () => copier.run() };
    }

    function cannotRecordNotice() {
        const base = env.secure
            ? { kind: 'warning', icon: 'mic-off', title: 'notice.cantRecord.title', text: 'notice.cantRecord.text' }
            : { kind: 'warning', icon: 'mic-off', title: 'notice.insecure.title', text: 'notice.insecure.text' };
        // The action reads `item` when tapped, once it exists.
        const item = ui.notice({ ...base, actions: env.secure ? [copyLinkAction(() => item, base)] : [] });
        return item;
    }

    const offlineNotice = () => ui.notice({
        kind: 'warning', icon: 'wifi-off', title: 'notice.offline.title', text: 'notice.offline.text',
    });

    const noVoiceNotice = () => ui.notice({
        kind: 'info', icon: 'info', title: 'notice.noVoice.title', text: 'notice.noVoice.text',
    });

    const loadFailedNotice = () => ui.notice({
        kind: 'error', icon: 'wifi-off', title: 'notice.loadFailed.title', text: 'notice.loadFailed.text',
        actions: [{ label: 'common.tryAgain', icon: 'refresh', onClick: () => loadSentence() }],
    });

    // ---------------------------------------------------------------- the card
    function renderCard() {
        const custom = state.mode === 'custom';
        els.cardLabel.classList.toggle('is-badge', custom);
        i18n.text(els.cardLabelText, custom ? 'card.myText' : 'card.eyebrow');
        i18n.text(els.myTextLabel, custom ? 'card.edit' : 'card.myText');
        i18n.attr(els.btnMyText, 'aria-label', custom ? 'card.editLabel' : null);

        const hasText = Boolean(state.text);
        els.card.setAttribute('aria-busy', String(state.loading));
        els.skeleton.hidden = !state.loading;
        els.sentence.hidden = state.loading || !hasText;
        const long = words(state.text) > LONG_TEXT_WORDS;
        els.btnShowIpa.hidden = state.loading || !hasText || !long || !state.ipa;
        els.btnShowIpa.setAttribute('aria-expanded', String(state.ipaOpen));
        i18n.text(els.showIpaLabel, state.ipaOpen ? 'card.hideIpa' : 'card.showIpa');
        els.ipa.hidden = state.loading || !hasText || !state.ipa || (long && !state.ipaOpen);
        els.loadError.hidden = state.loading || hasText || !state.loadFailed;
        // No sentence could load: nothing to play slowly (wireframes A3).
        els.slowToggle.closest('.toggle').hidden = !state.loading && !hasText;
    }

    function renderSentence() {
        els.sentence.textContent = state.text;
        els.sentence.classList.toggle('is-long', words(state.text) > LONG_TEXT_WORDS);
        els.ipa.textContent = state.ipa ? `/ ${state.ipa} /` : '';
    }

    function setSentence({ text, ipa, ttsUrl = '', mode }) {
        AIPT.audio.stop();
        AIPT.result.clear();
        state.text = AIPT.normalizeText(text || '');
        state.ipa = ipa || '';
        state.ttsUrl = ttsUrl;
        state.mode = mode;
        // Above 20 words the IPA starts folded, so the text stays near the top.
        state.ipaOpen = words(state.text) <= LONG_TEXT_WORDS;
        renderSentence();
        renderCard();
        renderControls();
    }

    // ---------------------------------------------------------------- the controls
    function renderListen() {
        const active = state.listen !== 'idle';
        els.btnListen.dataset.state = state.listen;
        els.btnListen.setAttribute('aria-pressed', String(active));
        i18n.text(els.listenLabel, active ? 'controls.stop' : 'controls.listen');
        const playing = state.listen === 'playing';
        els.playingNote.hidden = !playing;
        if (playing) {
            if (els.slowToggle.checked) i18n.text(els.playingText, 'card.playingSlow', { rate: AIPT.audio.SLOW_RATE });
            else i18n.text(els.playingText, 'card.playing');
        }
    }

    function renderControls() {
        const ready = Boolean(state.text) && !state.loading;
        AIPT.setDisabled(els.btnListen, !ready);
        AIPT.setDisabled(els.btnRecord, !ready || !env.canRecord);
        AIPT.setDisabled(els.btnNext, state.loading || state.offline);
        els.btnRecord.classList.toggle('is-blocked', !env.canRecord);
        let mic = 'controls.speak';
        if (!env.canRecord) mic = 'controls.cantRecord';
        else if (AIPT.result.shown) mic = 'controls.tryAgain';
        i18n.text(els.micLabel, mic);
        renderListen();
    }

    // ---------------------------------------------------------------- loading a sentence
    // A bank sentence of the level asked for. A new choice cancels the request
    // in flight; it gives up after 15 s. While it loads the card shows a
    // skeleton; when it fails, the card says so (no sentence yet) or, when a
    // sentence is shown, it stays and a notice docks above the controls.
    async function loadSentence() {
        if (state.loadController) state.loadController.abort();
        const controller = new AbortController();
        state.loadController = controller;
        AIPT.audio.stop();
        state.loading = true;
        dock.hide('loadFailed');
        renderCard();
        renderControls();
        ui.announce(t('card.loading'));
        try {
            const data = await AIPT.postJSON(AIPT.API.sample,
                { category: state.category, language: AIPT.PRACTICE_LANGUAGE },
                { signal: controller.signal, timeout: SAMPLE_TIMEOUT_MS });
            if (state.loadController !== controller) return;
            state.loading = false;
            state.loadFailed = false;
            setSentence({ text: data.real_transcript[0], ipa: data.ipa_transcript, ttsUrl: data.tts_url || '', mode: 'bank' });
            ui.announce(t('card.ready'));
        } catch (err) {
            if (state.loadController !== controller || (err && err.name === 'AbortError')) return;
            console.error(err);
            state.loading = false;
            state.loadFailed = true;
            // A sentence already shown stays (with its result); the error docks
            // above the controls, unless being offline already says why.
            if (state.text && !state.offline) dock.show('loadFailed', loadFailedNotice);
            renderCard();
            renderControls();
        } finally {
            if (state.loadController === controller) state.loadController = null;
        }
    }

    // Back to the bank, at the level last chosen (a chip, Next, or Try again).
    function goToBank() {
        levels.check(state.category);
        loadSentence();
    }

    const levels = ui.radioGroup(els.levels, {
        onChoose: (value) => {
            state.category = value;
            goToBank();
        },
    });

    // ---------------------------------------------------------------- the controls' actions
    // A control waiting for a sentence says why when tapped (it is aria-disabled).
    function sayWhyNotReady() {
        ui.announce(t(state.loading ? 'controls.wait' : 'card.loadFailed'));
    }

    function listen() {
        if (AIPT.isDisabled(els.btnListen)) {
            sayWhyNotReady();
            return;
        }
        if (state.listen !== 'idle') {
            AIPT.audio.stop();
            return;
        }
        AIPT.audio.speak(state.text, {
            owner: 'listen',
            slow: els.slowToggle.checked,
            bankUrl: state.mode === 'bank' ? state.ttsUrl : '',
        });
    }

    function record(opener) {
        if (!env.canRecord) {
            dock.reveal('cannotRecord');
            return;
        }
        if (!state.text || state.loading) {
            sayWhyNotReady();
            return;
        }
        AIPT.audio.stop();
        AIPT.recorder.start(opener || els.btnRecord);
    }

    function next() {
        if (AIPT.isDisabled(els.btnNext)) {
            if (state.offline) dock.reveal('offline');
            else sayWhyNotReady();
            return;
        }
        goToBank();
    }

    AIPT.audio.onChange((owner, audioState) => {
        if (owner !== 'listen') return;
        state.listen = audioState;
        renderListen();
        if (audioState === 'playing') {
            dock.hide('noVoice');
            ui.announce(t('card.playing'));
        }
    });

    AIPT.audio.onNoVoice(() => dock.show('noVoice', noVoiceNotice));

    // ---------------------------------------------------------------- My text
    const myText = {
        sheet: new ui.Sheet(els.myTextSheet, { closeOnBackdrop: true, onDismiss: () => closeMyText() }),
        controller: null,
        loading: false,
        problem: '', // what the message says now: a problem code, 'failed', 'long' (the warning) or ''
        serverProblem: '', // the server's code for the text as it was sent (cleared when it changes)
        failed: false, // the last try got no usable answer: the same text can be sent again
    };

    // The field grows with its text to about 40% of the screen (CSS
    // max-height), then scrolls.
    function autosize() {
        const field = els.field;
        const borders = field.offsetHeight - field.clientHeight;
        field.style.setProperty('height', 'auto');
        field.style.setProperty('height', `${field.scrollHeight + borders}px`);
    }

    function showMessage(kind, key, params) {
        els.message.hidden = !kind;
        els.message.classList.toggle('is-error', kind === 'error');
        els.message.classList.toggle('is-warning', kind === 'warning');
        if (!kind) {
            els.messageText.textContent = '';
            els.messageText.removeAttribute('data-i18n');
            return;
        }
        els.messageIcon.setAttribute('href', kind === 'warning' ? '#i-clock' : '#i-warn');
        i18n.text(els.messageText, key, params);
    }

    // The counters (after normalizeText, as the server counts), the reading
    // time, and the warning or the first problem, checked in the page first.
    function updateMyText() {
        const check = AIPT.checkText(els.field.value);
        const { chars, tooManyChars, tooManyWords } = check;
        const count = check.words;
        i18n.text(els.countChars, 'mytext.chars', { count: chars, max: AIPT.LIMITS.chars });
        i18n.text(els.countWords, 'mytext.words', { count, max: AIPT.LIMITS.words });
        els.countChars.classList.toggle('is-over', tooManyChars);
        els.countWords.classList.toggle('is-over', tooManyWords);
        const seconds = Math.round((count / WORDS_PER_MINUTE) * 60);
        // The reading time, until the text is too long to send anyway.
        els.countTime.hidden = !count || tooManyChars || tooManyWords;
        if (count) i18n.text(els.countTime, 'mytext.readTime', { seconds: Math.max(1, seconds) });

        const empty = !els.field.value.trim();
        let problem = empty ? '' : check.problem || myText.serverProblem;
        if (problem === 'text_too_long' && check.problem === 'text_too_long') {
            showMessage('error', 'mytext.tooLong', {
                chars: t('count.characters', { count: chars }),
                words: t('count.words', { count }),
                maxChars: AIPT.LIMITS.chars,
                maxWords: AIPT.LIMITS.words,
            });
        } else if (problem === 'empty') {
            showMessage('error', 'mytext.empty');
        } else if (problem) {
            showMessage('error', `error.${problem}`, { maxChars: AIPT.LIMITS.chars, maxWords: AIPT.LIMITS.words });
        } else if (myText.failed && !empty) {
            problem = 'failed';
            showMessage('error', 'mytext.failed');
        } else if (seconds > LONG_READ_SECONDS) {
            problem = 'long';
            showMessage('warning', 'mytext.longWarning');
        } else {
            showMessage('');
        }

        // A problem with the text itself; 'failed' (no answer) can be sent again.
        const isError = Boolean(problem) && problem !== 'long' && problem !== 'failed';
        els.field.setAttribute('aria-invalid', String(isError));
        // Native disabled only while the field is empty (§2.2); a text with a
        // problem keeps the button focusable, and a tap points to the problem.
        els.btnUseCustom.disabled = empty && !myText.loading;
        AIPT.setDisabled(els.btnUseCustom, isError && !myText.loading);
        // A new message is read once, not at every key press.
        if (problem !== myText.problem) {
            myText.problem = problem;
            if (problem === 'long') ui.announce(els.messageText.textContent, els.myTextStatus);
            else if (problem) ui.announce(els.messageText.textContent, els.myTextAlert);
        }
        return { ...check, blocked: isError };
    }

    function setMyTextLoading(loading) {
        myText.loading = loading;
        els.field.readOnly = loading;
        els.btnUseCustom.querySelector('.spinner').hidden = !loading;
        i18n.text(els.useCustomLabel, loading ? 'mytext.preparing' : 'mytext.submit');
        els.btnUseCustom.setAttribute('aria-busy', String(loading));
    }

    function openMyText() {
        if (myText.sheet.isOpen || AIPT.ui.sheetOpen) return;
        const draft = storage.get(DRAFT_KEY, '');
        if (draft && !els.field.value) els.field.value = draft;
        myText.serverProblem = '';
        myText.failed = false;
        myText.problem = '';
        updateMyText();
        if (!myText.sheet.open(els.btnMyText)) return;
        autosize();
    }

    // Cancel, ✕, Escape or a backdrop tap: the draft stays (it is saved as typed).
    function closeMyText(closeOptions) {
        if (myText.controller) myText.controller.abort();
        myText.controller = null;
        setMyTextLoading(false);
        myText.sheet.close({ fallback: els.btnMyText, ...closeOptions });
    }

    async function useMyText() {
        if (myText.loading) return;
        const check = updateMyText();
        if (!check.text || check.blocked) {
            ui.focus(els.field);
            if (els.messageText.textContent) ui.announce(els.messageText.textContent, els.myTextAlert);
            return;
        }
        const controller = new AbortController();
        myText.controller = controller;
        myText.failed = false;
        setMyTextLoading(true);
        updateMyText();
        try {
            const data = await AIPT.postJSON(AIPT.API.custom, { text: check.text, language: AIPT.PRACTICE_LANGUAGE },
                { signal: controller.signal, timeout: SAMPLE_TIMEOUT_MS });
            if (myText.controller !== controller) return;
            myText.controller = null;
            // A level chosen before may still be loading: this text wins.
            if (state.loadController) state.loadController.abort();
            state.loadController = null;
            state.loading = false;
            state.loadFailed = false;
            dock.hide('loadFailed');
            setSentence({ text: data.real_transcript[0], ipa: data.ipa_transcript, mode: 'custom' });
            levels.check(null);
            setMyTextLoading(false);
            closeMyText({ focusTo: els.sentence });
            ui.announce(t('mytext.ready'));
        } catch (err) {
            if (myText.controller !== controller || (err && err.name === 'AbortError')) return;
            console.error(err);
            myText.controller = null;
            setMyTextLoading(false);
            // The server's codes, in the page's words; anything else (no answer,
            // a timeout, a server error): the same text can be sent again.
            const known = ['text_too_long', 'text_not_english', 'text_bad_characters'];
            if (known.includes(err.code)) myText.serverProblem = err.code;
            else if (err.code === 'invalid_request') myText.serverProblem = 'empty';
            else myText.failed = true;
            myText.problem = '';
            updateMyText();
            ui.focus(myText.failed ? els.btnUseCustom : els.field);
        }
    }

    els.field.addEventListener('input', () => {
        storage.set(DRAFT_KEY, els.field.value);
        myText.serverProblem = '';
        myText.failed = false;
        updateMyText();
        autosize();
    });
    els.field.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            useMyText();
        }
    });
    els.btnUseCustom.addEventListener('click', useMyText);
    els.btnMyText.addEventListener('click', openMyText);
    window.addEventListener('resize', () => {
        if (myText.sheet.isOpen) autosize();
    });

    // ---------------------------------------------------------------- wiring
    els.btnListen.addEventListener('click', listen);
    els.btnRecord.addEventListener('click', () => record(els.btnRecord));
    els.btnNext.addEventListener('click', next);
    els.btnRetryLoad.addEventListener('click', () => loadSentence());
    els.slowToggle.addEventListener('change', () => {
        if (state.listen === 'playing') renderListen();
    });
    els.btnShowIpa.addEventListener('click', () => {
        state.ipaOpen = !state.ipaOpen;
        renderCard();
    });

    AIPT.recorder.init({
        getText: () => state.text,
        fallbackFocus: els.btnRecord,
        onResult: (data, buffer, text) => {
            AIPT.result.render(data, { text, buffer });
            renderControls();
        },
    });
    AIPT.result.init({ onRetry: (button) => record(button), onNext: next });

    // Space starts recording when focus is not on a control (sheets handle
    // their own keys).
    document.addEventListener('keydown', (event) => {
        if (event.key !== ' ' || event.repeat || event.defaultPrevented) return;
        if (ui.sheetOpen || event.ctrlKey || event.metaKey || event.altKey) return;
        if (AIPT.isControl(event.target)) return;
        event.preventDefault();
        record(els.btnRecord);
    });

    // Offline: a notice above the controls; Next waits for the connection,
    // the mic stays usable.
    function setOffline(offline) {
        const wasOffline = state.offline;
        state.offline = offline;
        if (offline) {
            dock.hide('loadFailed');
            dock.show('offline', offlineNotice);
        } else {
            dock.hide('offline');
        }
        renderControls();
        // Back online with no sentence on the card: fetch one.
        if (wasOffline && !offline && !state.text && !state.loading) loadSentence();
    }
    window.addEventListener('offline', () => setOffline(true));
    window.addEventListener('online', () => setOffline(false));

    // EN | VI: the whole page switches in place (i18n.setLanguage).
    function renderLanguage() {
        els.langButtons.forEach((button) => {
            button.setAttribute('aria-pressed', String(button.dataset.lang === i18n.lang));
        });
    }
    els.langButtons.forEach((button) => {
        button.addEventListener('click', () => i18n.setLanguage(button.dataset.lang));
    });
    i18n.onChange(() => {
        renderLanguage();
        if (myText.sheet.isOpen) updateMyText();
    });

    // The page keeps room for the fixed bar and any notice docked above it,
    // and focus scrolls clear of them (--bar-space, style.css).
    function measureBar() {
        const fixed = getComputedStyle(els.zone).position === 'fixed';
        const height = fixed ? Math.ceil(els.zone.getBoundingClientRect().height) : 0;
        document.documentElement.style.setProperty('--bar-space', `${height}px`);
    }
    if (window.ResizeObserver) new ResizeObserver(measureBar).observe(els.zone);
    window.addEventListener('resize', measureBar);

    // ---------------------------------------------------------------- start
    renderLanguage();
    if (!env.canRecord) dock.show('cannotRecord', cannotRecordNotice);
    if (state.offline) setOffline(true);
    renderCard();
    renderControls();
    measureBar();
    loadSentence();
})();
