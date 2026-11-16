'use strict';

// The microphone check (design/wireframes/05-onboarding.html E5-E9): the browser's permission prompt explained
// first (E5), then 3 s of level metering in the browser with a decorative meter (E6; Web Audio: nothing is
// recorded and nothing is sent), then "Your microphone works" (E7: Start practising, focus on Listen), "We didn't
// hear anything" (E8: the same speech level as the recording sheet's "We can't hear you"), or the recording
// sheet's own words and steps for a microphone that did not start (E9; B13-B16), and inside an app's own browser
// its way out (B17, B18). A bottom sheet on phones, a dialog from 768 px; opened from the tour's last step and
// from How it works. Its state is on the sheet (data-state):
//   intro        before the browser asks (E5)
//   asking       the browser asks for the microphone
//   listening    3 s of metering (E6)
//   works        speech was heard (E7)
//   silent       nothing above the speech level (E8)
//   mic-blocked, mic-none, mic-busy, mic-error, in-app   the microphone did not start (E9, B13-B18)
// and idle while it is closed; data-detail says which steps, data-tone the family of the header's icon.
(() => {
    const { $, el, icon, i18n, ui, env } = AIPT;
    const { t } = i18n;

    const LISTEN_MS = 3000;
    const SAMPLE_MS = 45;
    // Speech for about 0.15 s of the 3 s ("hello"), not a single click.
    const SPEECH_SAMPLES = 3;

    const els = {
        root: $('micCheck'),
        dot: $('micDot'),
        icon: $('micIcon'),
        iconUse: $('micIconUse'),
        title: $('micTitle'),
        timer: $('micTimer'),
        done: $('micDoneMark'),
        msg: $('micMsg'),
        meter: $('micMeter'),
        hint: $('micHint'),
        tips: $('micTips'),
        message: $('micMessage'),
        lead: $('micLead'),
        text: $('micText'),
        steps: $('micSteps'),
        copyHelp: $('micCopyHelp'),
        status: $('micStatus'),
        alert: $('micAlert'),
        actions: $('micActions'),
        skip: $('micSkip'),
        start: $('micStart'),
        tryAgain: $('micTryAgain'),
        practise: $('micPractise'),
        openChrome: $('micOpenChrome'),
        copyLink: $('micCopyLink'),
        copyIcon: $('micCopyIcon'),
        copyLabel: $('micCopyLabel'),
    };
    const ACTIONS = [els.skip, els.start, els.tryAgain, els.practise, els.openChrome, els.copyLink];
    const bars = Array.from(els.meter.children);

    // The address to copy by hand (D7), and the arrow to the app's ••• menu (D10).
    els.address = AIPT.inApp.addressField('rec-address');
    els.copyHelp.appendChild(els.address);
    els.pointer = AIPT.inApp.pointer();
    els.pointer.hidden = true;
    els.root.appendChild(els.pointer);

    const check = {
        attempt: 0, // moves on with each try and on close: what still runs for an older one is dropped
        state: 'idle',
        detail: '',
        stream: null,
        waiting: null, // a stream granted while the page was hidden (an app's permission dialog over it)
        context: null,
        source: null,
        analyser: null,
        samples: null,
        startedAt: 0,
        secondsLeft: 0,
        heard: 0,
        smoothed: 0,
        sampler: 0,
        ticker: 0,
        copied: false,
        copyRefused: false,
    };

    const wide = () => window.matchMedia('(min-width: 768px)').matches;

    // ---------------------------------------------------------------- the microphone
    function stopTracks(stream) {
        if (stream) stream.getTracks().forEach((track) => track.stop());
    }

    function release() {
        clearInterval(check.sampler);
        clearInterval(check.ticker);
        if (check.source) {
            try {
                check.source.disconnect();
            } catch (_) {
                // Already disconnected.
            }
        }
        check.source = null;
        check.analyser = null;
        check.context = null;
        stopTracks(check.stream);
        stopTracks(check.waiting);
        check.stream = null;
        check.waiting = null;
    }

    // Start the check, Try again: the browser is asked for the microphone (its prompt, the first time).
    function ask() {
        release();
        check.attempt += 1;
        const attempt = check.attempt;
        try {
            // Made (or resumed) inside the tap, as browsers require.
            AIPT.audio.context();
        } catch (err) {
            console.warn('No audio context', err);
        }
        enter('asking');
        let request;
        try {
            request = navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
        } catch (err) {
            request = Promise.reject(err);
        }
        Promise.resolve(request).then((stream) => {
            if (attempt !== check.attempt || check.state !== 'asking') {
                stopTracks(stream);
            } else if (document.hidden) {
                check.waiting = stream;
            } else {
                listen(stream);
            }
        }, (error) => {
            if (attempt !== check.attempt || check.state !== 'asking') return;
            console.warn('The microphone did not start', error);
            enter(...AIPT.recorder.micFailure(error));
        });
    }

    // 3 s of the microphone's level, on the page's audio context: never recorded, never sent.
    function listen(stream) {
        const attempt = check.attempt;
        check.stream = stream;
        try {
            const context = AIPT.audio.context();
            check.source = context.createMediaStreamSource(stream);
            check.analyser = context.createAnalyser();
            check.analyser.fftSize = 2048;
            check.source.connect(check.analyser);
            check.context = context;
        } catch (err) {
            console.warn('No level meter for the check', err);
            release();
            enter('mic-error', 'meter');
            return;
        }
        stream.getAudioTracks().forEach((track) => {
            track.addEventListener('ended', () => {
                if (attempt !== check.attempt || check.state !== 'listening') return;
                release();
                enter('mic-error', 'ended');
            });
        });
        check.heard = 0;
        check.smoothed = 0;
        check.startedAt = performance.now();
        check.secondsLeft = Math.ceil(LISTEN_MS / 1000);
        enter('listening');
        check.sampler = setInterval(() => sample(attempt), SAMPLE_MS);
        check.ticker = setInterval(() => tick(attempt), 200);
    }

    // The level, as the recording sheet measures it; a context that is not running measures nothing.
    function sample(attempt) {
        if (attempt !== check.attempt || check.state !== 'listening' || !check.analyser) return;
        if (check.context && check.context.state !== 'running') return;
        const size = check.analyser.fftSize;
        if (!check.samples || check.samples.length !== size) check.samples = new Float32Array(size);
        check.analyser.getFloatTimeDomainData(check.samples);
        let sum = 0;
        for (let i = 0; i < size; i += 1) sum += check.samples[i] * check.samples[i];
        const level = AIPT.audio.levelOf(Math.sqrt(sum / size));
        if (level > AIPT.audio.SPEECH_LEVEL) check.heard += 1;
        check.smoothed = Math.max(level, check.smoothed * 0.8);
        drawMeter(check.smoothed);
    }

    // The seconds left (the timer and the hint change once a second, and are not read out), then the outcome.
    function tick(attempt) {
        if (attempt !== check.attempt || check.state !== 'listening') return;
        const left = Math.ceil((LISTEN_MS - (performance.now() - check.startedAt)) / 1000);
        if (left > 0) {
            if (left !== check.secondsLeft) {
                check.secondsLeft = left;
                render();
            }
            return;
        }
        const heard = check.heard >= SPEECH_SAMPLES;
        release();
        enter(heard ? 'works' : 'silent');
    }

    // The meter: as many bars lit as the level reaches. Decorative: the hint and the outcome say it in words.
    function drawMeter(level) {
        const lit = Math.round(Math.min(1, level) * bars.length);
        bars.forEach((bar, index) => bar.classList.toggle('is-lit', index < lit));
    }

    // ---------------------------------------------------------------- Copy link (in-app)
    let copyAttempt = -1;
    const copier = AIPT.inApp.copyControl({
        onCopied: () => {
            if (copyAttempt !== check.attempt || check.state !== 'in-app') return;
            check.copied = true;
            render();
            ui.announce(t('notice.linkCopied.title'), els.status);
        },
        onReset: () => {
            if (copyAttempt !== check.attempt) return;
            check.copied = false;
            render();
        },
        onRefused: () => {
            if (copyAttempt !== check.attempt || check.state !== 'in-app') return;
            check.copied = false;
            check.copyRefused = true;
            render();
            AIPT.inApp.selectAddress(els.address);
        },
    });

    // ---------------------------------------------------------------- states
    // The header's icon (or the live dot) and its family (design-system §1.3).
    const VIEWS = {
        intro: { icon: 'mic' },
        asking: { icon: 'mic' },
        listening: { dot: true },
        works: { icon: 'check', tone: 'success' },
        silent: { icon: 'mic-off', tone: 'warning' },
        'mic-blocked': { icon: 'mic-off', tone: 'warning' },
        'mic-none': { icon: 'mic-off', tone: 'warning' },
        'mic-busy': { icon: 'mic-off', tone: 'warning' },
        'mic-error': { icon: 'mic-off', tone: 'warning' },
        'in-app': { icon: 'open', tone: 'warning' },
    };

    function setData(name, value) {
        if (value) els.root.dataset[name] = value;
        else delete els.root.dataset[name];
    }

    // The state's actions in their order (also the order of focus): [button, kind, layout] as in the recording
    // sheet; Skip's label is the state's (Skip, Cancel or Close).
    function setActions(list, skipKey = 'common.skip') {
        const wanted = list.map(([node]) => node);
        ACTIONS.forEach((node) => {
            node.hidden = !wanted.includes(node);
        });
        list.forEach(([node, kind, layout = '']) => {
            node.classList.toggle('btn-primary', kind === 'primary');
            node.classList.toggle('btn-secondary', kind === 'secondary');
            node.classList.toggle('is-full', layout === 'full');
            node.classList.toggle('is-wide', layout === 'wide');
        });
        // Moved only when the order changes: a node that moves loses its focus.
        const shown = Array.from(els.actions.children).filter((node) => !node.hidden);
        if (shown.some((node, index) => node !== wanted[index])) wanted.forEach((node) => els.actions.appendChild(node));
        i18n.text(els.skip, skipKey);
    }

    function setHint(key, { params, slots, icon: iconName = '' } = {}) {
        if (!key) {
            els.hint.hidden = true;
            els.hint.replaceChildren();
            return;
        }
        els.hint.hidden = false;
        const words = slots ? i18n.richText(el('span'), key, slots, params) : i18n.text(el('span'), key, params);
        els.hint.replaceChildren(...(iconName ? [icon(iconName), words] : [words]));
    }

    function setMessage(titleKey, leadKey, textKey = '', params) {
        i18n.text(els.title, titleKey, params);
        i18n.text(els.lead, leadKey, params);
        els.text.hidden = !textKey;
        if (textKey) i18n.text(els.text, textKey, params);
        else els.text.replaceChildren();
    }

    function setSteps(node, items) {
        node.replaceChildren(...items);
        node.hidden = !items.length;
    }

    const RENDER = {
        // E5: what happens, and the browser's prompt explained before it comes (unless it was allowed before).
        intro() {
            i18n.text(els.title, 'mic.title');
            els.msg.hidden = false;
            i18n.text(els.msg, 'mic.intro');
            els.meter.hidden = false;
            drawMeter(0);
            if (AIPT.recorder.micPermission === 'granted') setHint('');
            else setHint(wide() ? 'mic.allowWide' : 'mic.allow', { slots: { allow: i18n.text(el('b'), 'rec.ui.allow') }, icon: 'info' });
            setActions([[els.skip, 'secondary'], [els.start, 'primary']]);
        },
        asking() {
            RENDER.intro();
            setActions([[els.skip, 'secondary']], 'common.cancel');
        },
        // E6: "Listening… say hello", the seconds left, the meter.
        listening() {
            i18n.text(els.title, 'mic.listening');
            els.timer.textContent = t('mic.timer', { seconds: check.secondsLeft });
            els.meter.hidden = false;
            setHint('mic.keepTalking', { params: { count: check.secondsLeft } });
            setActions([[els.skip, 'secondary']], 'common.cancel');
        },
        // E7.
        works() {
            i18n.text(els.title, 'mic.works');
            els.done.hidden = false;
            els.msg.hidden = false;
            i18n.text(els.msg, 'mic.worksText');
            setHint('mic.tip');
            setActions([[els.practise, 'primary']]);
        },
        // E8: a flat meter and what to check.
        silent() {
            i18n.text(els.title, 'mic.silent');
            els.meter.hidden = false;
            drawMeter(0);
            setSteps(els.tips, ['mic.silent1', wide() ? 'mic.silent2Wide' : 'mic.silent2', 'mic.silent3']
                .map((key) => i18n.text(el('li'), key)));
            setActions([[els.skip, 'secondary'], [els.tryAgain, 'primary']]);
        },
        // E9, B13-B16: the recording sheet's words and steps.
        'mic-blocked': showMicMessage,
        'mic-none': showMicMessage,
        'mic-busy': showMicMessage,
        'mic-error': showMicMessage,
        // B17, B18: the way out of the app.
        'in-app'() {
            const message = AIPT.inApp.failureMessage();
            els.message.hidden = false;
            setMessage(message.title, message.lead, message.text, message.params);
            if (message.ios) {
                setSteps(els.steps, AIPT.inApp.safariSteps());
                setActions([[els.copyLink, 'primary'], [els.skip, 'secondary']], 'common.close');
            } else {
                if (message.menu) AIPT.inApp.chromeOrMenu(els.text);
                if (message.openChrome) {
                    els.openChrome.setAttribute('href', AIPT.inApp.chromeIntentUrl());
                    setActions([[els.openChrome, 'primary', 'full'], [els.copyLink, 'secondary', 'wide'],
                        [els.skip, 'secondary']], 'common.close');
                } else {
                    setActions([[els.copyLink, 'primary'], [els.skip, 'secondary']], 'common.close');
                }
            }
            i18n.text(els.copyLabel, check.copied ? 'notice.linkCopied.title' : 'notice.copyLink');
            els.copyIcon.setAttribute('href', check.copied ? '#i-check' : '#i-copy');
            els.copyLink.classList.toggle('is-done', check.copied);
            els.copyHelp.hidden = !check.copyRefused;
        },
    };

    function showMicMessage() {
        const message = AIPT.recorder.micMessage(check.state, check.detail);
        els.message.hidden = false;
        setMessage(message.title, message.lead, message.text);
        setSteps(els.steps, message.steps);
        setActions([[els.skip, 'secondary'], [els.tryAgain, 'primary']]);
    }

    // Draw the state (also after a language switch or a resize): nothing here moves focus or speaks.
    function render() {
        const view = VIEWS[check.state];
        if (!view) return;
        els.root.dataset.state = check.state;
        setData('detail', check.detail);
        setData('tone', view.tone || '');
        els.dot.hidden = !view.dot;
        // An <svg> has no `hidden` property: the attribute itself.
        els.icon.toggleAttribute('hidden', Boolean(view.dot));
        if (view.icon) els.iconUse.setAttribute('href', `#i-${view.icon}`);
        els.timer.hidden = check.state !== 'listening';
        // Nothing is lost by a stray tap, except while the browser asks or the check listens.
        sheet.closeOnBackdrop = check.state !== 'asking' && check.state !== 'listening';
        els.done.hidden = true;
        els.msg.hidden = true;
        els.meter.hidden = true;
        els.tips.hidden = true;
        els.message.hidden = true;
        els.steps.hidden = true;
        els.copyHelp.hidden = true;
        setHint('');
        els.pointer.hidden = !(check.state === 'in-app' && check.detail === 'ios');
        RENDER[check.state]();
    }

    // A new state: drawn, then focus and what is said (design-system §4): the title while the browser asks; the
    // main action of an outcome; the sheet's polite region says the listening once, its alert region a failure.
    function enter(state, detail = '') {
        check.state = state;
        check.detail = detail;
        if (state !== 'in-app') {
            check.copied = false;
            check.copyRefused = false;
        }
        render();
        if (state === 'intro' || state === 'asking') {
            ui.focus(els.title, { preventScroll: true });
            ui.announce('', els.status);
        } else if (state === 'listening') {
            ui.announce(t('mic.listeningAnnounce'), els.status);
        } else {
            ui.focus(primaryAction(), { preventScroll: true });
            // Only what is shown: a hidden part (or one inside the hidden message) may keep an earlier failure's words.
            const parts = [els.title, els.msg, els.lead, els.text]
                .filter((node) => !node.closest('[hidden]') && node.textContent.trim())
                .map((node) => node.textContent.trim());
            if (state === 'works') ui.announce(parts.join(' '), els.status);
            else ui.announce(parts.join(' '), els.alert);
        }
    }

    function primaryAction() {
        const shown = ACTIONS.filter((node) => !node.hidden);
        return shown.find((node) => node.classList.contains('btn-primary')) || shown[0] || els.title;
    }

    // ---------------------------------------------------------------- the sheet
    const sheet = new ui.Sheet(els.root, { closeOnBackdrop: true, onDismiss: () => close() });

    // Open on the explanation (E5). Not in a browser that cannot record: its notice says why.
    function open(opener) {
        if (!env.canRecord || ui.sheetOpen) return false;
        // The reference voice stops, and nothing plays while the microphone listens.
        AIPT.audio.hold(true);
        if (!sheet.open(opener)) {
            AIPT.audio.hold(false);
            return false;
        }
        check.attempt += 1;
        enter('intro');
        return true;
    }

    // ✕, Skip, Cancel, Close, Escape, a backdrop tap, Start practising: the microphone is let go at once.
    function close({ focusTo = null } = {}) {
        check.attempt += 1;
        release();
        copier.stop();
        check.state = 'idle';
        check.detail = '';
        check.copied = false;
        check.copyRefused = false;
        els.root.dataset.state = 'idle';
        setData('detail', '');
        setData('tone', '');
        els.pointer.hidden = true;
        AIPT.audio.hold(false);
        sheet.close({ focusTo, fallback: $('btnListen') });
    }

    els.start.addEventListener('click', () => {
        if (check.state === 'intro') ask();
    });
    els.tryAgain.addEventListener('click', () => {
        if (check.state === 'silent' || check.state.startsWith('mic-')) ask();
    });
    // E7: back to the page, on Listen.
    els.practise.addEventListener('click', () => close({ focusTo: $('btnListen') }));
    els.skip.addEventListener('click', () => close());
    els.copyLink.addEventListener('click', () => {
        if (check.state !== 'in-app') return;
        copyAttempt = check.attempt;
        copier.run();
    });

    // A page hidden while the check listens measures nothing: back to the start. A stream granted while it was
    // hidden starts the check when it shows again.
    document.addEventListener('visibilitychange', () => {
        if (document.hidden && check.state === 'listening') {
            release();
            enter('intro');
        } else if (!document.hidden && check.state === 'asking' && check.waiting) {
            const stream = check.waiting;
            check.waiting = null;
            listen(stream);
        }
    });
    window.addEventListener('resize', () => {
        if (sheet.isOpen) render();
    });
    i18n.onChange(() => {
        if (sheet.isOpen) render();
    });

    AIPT.micCheck = {
        // Opened from How it works and from the tour; opener gets focus back on close (Listen after Start practising).
        open,
        get state() {
            return check.state;
        },
    };
})();
