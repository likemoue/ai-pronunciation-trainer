'use strict';

// The recording sheet (design/wireframes/02-recording-sheet.html, B1-B21; a
// centred dialog from 768 px, 08-desktop.html H3): a fixed header (the dot and
// "REC", or the icon of the state; the title; the timer; ✕), a body with the
// sentence in its own scroll area, the waveform and a hint, or a message, and
// fixed actions. The backdrop never closes it; ✕, Cancel, Close and Escape do.
//
// One state machine runs it, and names its state on the sheet (data-state):
//   preparing    the browser is asked for the microphone (B1)
//   recording    B2; data-hint="quiet" when it hears nothing (B3), "ending" in the last 5 s (B4)
//   checking     the take is read and sent (B5, B6)
//   busy         the server is busy: the same recording goes again by itself (B7)
//   failed       the server or the connection failed; the recording is kept (B8)
//   offline      the browser is offline; the recording is kept (B9)
//   no-speech    nothing like speech: the server's 422, or the page's own silence check (B10)
//   too-short    under 0.6 s, or under 1 KB and not silent (B11)
//   interrupted  the page was hidden, the track ended or the recorder failed (B12)
//   rejected     the server refused the recording for a reason that sending it again cannot fix
//   mic-blocked, mic-none, mic-busy, mic-error   the microphone did not start (B13-B16)
//   in-app       the microphone failed inside an app's own browser (B17, B18)
// and idle while the sheet is closed; data-detail says which failure or which
// steps, data-tone the family of the state's icon.
//
// Every change goes through transition(attempt, event): an event that the
// state does not expect, or that carries the token of an attempt that is over
// (a newer take began, or the sheet closed), is dropped. Each asynchronous
// step carries its attempt's token: the permission prompt and getUserMedia,
// the recorder's stop, reading the recording, each request and each wait.
(() => {
    const { $, el, icon, i18n, ui, env } = AIPT;
    const { t } = i18n;

    const MAX_SECONDS = AIPT.LIMITS.recordingSeconds;
    // B4: the last seconds count down ("Stopping by itself in 5 s…").
    const ENDING_SECONDS = 5;
    // B3: this long under the speech level (AIPT.audio.SPEECH_LEVEL) says "We can't hear you".
    const QUIET_MS = 3500;
    // The page's own silence check (B10): a take whose loudest moment stays
    // under this is not sent. It counts only when the level was measured.
    const SILENCE_RMS = 0.003;
    const MIN_METERED_SAMPLES = 10;
    // B11: a take shorter or smaller than this is not sent.
    const MIN_RECORDING_MS = 600;
    const MIN_RECORDING_BYTES = 1000;
    // B6: the hint changes when an answer takes this long.
    const STILL_CHECKING_MS = 8000;
    // Cloudflare gives up after 125 s (error 524): each attempt stops waiting before that.
    const SCORE_TIMEOUT_MS = 100000;
    // B7: a busy server (429, 503) gets the same recording again, at most this
    // many times, after its Retry-After (3 s without one) and up to 2 s more,
    // so that a class turned away together does not come back together.
    const BUSY_RETRIES = 3;
    const BUSY_WAIT_SECONDS = 3;
    const BUSY_JITTER_SECONDS = 2;
    // A recorder whose stop never comes counts as an interruption.
    const STOP_TIMEOUT_MS = 5000;
    // A tap this soon after the actions changed was meant for the old ones: a
    // double tap on the mic or on Stop must not land on Cancel.
    const SETTLE_MS = 400;
    // Opus at 32 kbps is plenty for speech recognition and a quarter of the
    // browsers' default: a 30 s recording is about 120 KB.
    const RECORDING_BITS_PER_SECOND = 32000;
    const LONG_TEXT_WORDS = 20;

    const els = {
        root: $('recordSheet'),
        dialog: $('recordSheet').querySelector('[role="dialog"]'),
        dot: $('recDot'),
        label: $('recLabel'),
        icon: $('recIcon'),
        iconUse: $('recIconUse'),
        title: $('recTitle'),
        timer: $('recTimer'),
        take: $('recTake'),
        sentence: $('recSentence'),
        canvas: $('waveCanvas'),
        overlay: $('waveOverlay'),
        spinner: $('waveSpinner'),
        clock: $('waveClock'),
        overlayText: $('waveOverlayText'),
        hint: $('recHint'),
        message: $('recMessage'),
        lead: $('recLead'),
        text: $('recText'),
        steps: $('recSteps'),
        kept: $('recKept'),
        keptText: $('recKeptText'),
        note: $('recNote'),
        copyHelp: $('recCopyHelp'),
        status: $('recStatus'),
        alert: $('recAlert'),
        actions: $('recActions'),
        cancel: $('recCancel'),
        stop: $('recStop'),
        send: $('recSend'),
        recordAgain: $('recRecordAgain'),
        tryAgain: $('recTryAgain'),
        openChrome: $('recOpenChrome'),
        copyLink: $('recCopyLink'),
        copyIcon: $('recCopyIcon'),
        copyLabel: $('recCopyLabel'),
    };
    const ACTIONS = [els.cancel, els.stop, els.send, els.recordAgain, els.tryAgain, els.openChrome, els.copyLink];

    // The address to copy by hand (D7), and the pointer to the app's ••• menu (D10).
    els.address = AIPT.inApp.addressField('rec-address');
    els.copyHelp.appendChild(els.address);
    els.pointer = AIPT.inApp.pointer();
    els.pointer.hidden = true;
    els.root.appendChild(els.pointer);

    let options = { getText: () => '', onResult: () => {}, fallbackFocus: null };

    // The take in the sheet. All of it lives only while the sheet is open:
    // closing drops the recording.
    const take = {
        attempt: 0, // the token: a new take and closing the sheet move it on
        state: 'idle',
        detail: '',
        changedAt: 0,
        text: '',
        // the microphone and the recorder
        stream: null,
        context: null,
        source: null,
        analyser: null,
        recorder: null,
        waitingVisible: false,
        startedAt: 0,
        stoppedAt: 0,
        levels: [],
        smoothed: 0,
        maxRms: 0,
        samples: 0,
        lastLoudAt: 0,
        warning: '', // 'quiet' (B3), 'ending' (B4) or ''
        endingSeconds: 0,
        hitLimit: false, // stopped by itself at 30 s: the result says when the end was not heard (B4)
        ticker: 0,
        sampler: 0,
        raf: 0,
        stopTimer: 0,
        // checking, and sending again
        phase: '', // while checking: 'stopping', 'reading', 'sending' or 'scored'
        duration: 0,
        body: null, // the request, the recording in it as a data URL: kept for Send again
        decoded: null, // a promise of the take as an AudioBuffer (or null), for the result
        request: null, // the AbortController of the request in flight
        slow: false,
        slowTimer: 0,
        busyCount: 0,
        busyUntil: 0,
        busyShown: 0,
        busyTimer: 0,
        answeredAt: 0, // when the score came (performance.now()): the result's chime is not played late
        // Copy link (in-app)
        copied: false,
        copyRefused: false,
    };

    // The microphone permission as the browser tells it before any tap, where
    // it can (navigator.permissions; not every browser knows 'microphone').
    let micPermission = '';

    function watchPermission() {
        try {
            if (!env.canRecord || !navigator.permissions || !navigator.permissions.query) return;
            navigator.permissions.query({ name: 'microphone' }).then((status) => {
                const update = () => {
                    micPermission = status.state;
                };
                update();
                if (typeof status.addEventListener === 'function') status.addEventListener('change', update);
                else status.onchange = update;
            }, () => {});
        } catch (_) {
            // This browser cannot say: the tap asks.
        }
    }

    // ---------------------------------------------------------------- the state machine
    function transition(attempt, event, data = {}) {
        if (attempt !== take.attempt) return false;
        const handlers = MACHINE[take.state] || {};
        const handler = Object.prototype.hasOwnProperty.call(handlers, event) ? handlers[event] : null;
        if (!handler) return false;
        return handler(data, event) !== false;
    }

    // A new state: drawn, then focus and announcements (arrive).
    function enter(state, detail = '') {
        const previous = take.state;
        take.state = state;
        take.detail = detail;
        take.changedAt = performance.now();
        render();
        arrive(previous);
    }

    // idle + open: the mic was tapped. The sheet opens on a new take, or on
    // the blocked state at once when the browser already says the microphone
    // is blocked.
    function open({ opener }) {
        const text = options.getText();
        if (!text) return false;
        // The reference voice stops, one still loading never plays, and no
        // sound starts while the sheet is open.
        AIPT.audio.hold(true);
        take.text = text;
        els.sentence.textContent = text;
        els.sentence.classList.toggle('is-long', text.split(' ').length > LONG_TEXT_WORDS);
        if (!ui.sheetOpen && sheet.open(opener)) {
            newTake({ blocked: micPermission === 'denied' });
            return true;
        }
        AIPT.audio.hold(false);
        return false;
    }

    // A new take (the mic, Record again, Try again): the old one goes, and
    // whatever still runs for it is dropped from now on.
    function newTake({ blocked = false } = {}) {
        take.attempt += 1;
        const attempt = take.attempt;
        resetTake();
        take.levels = [];
        setTimer(0);
        els.sentence.scrollTop = 0;
        try {
            // Made (or resumed) inside the tap, as browsers require.
            AIPT.audio.context();
        } catch (err) {
            console.warn('No audio context', err);
        }
        if (blocked) {
            enter(...micFailure({ name: 'NotAllowedError' }));
            return true;
        }
        enter('preparing');
        sizeCanvas();
        drawWave(true);
        let request;
        try {
            request = navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
        } catch (err) {
            request = Promise.reject(err);
        }
        Promise.resolve(request).then((stream) => {
            // A stream for a take that is over (Cancel while the prompt was open) is let go.
            if (!transition(attempt, 'granted', { stream })) stream.getTracks().forEach((track) => track.stop());
        }, (error) => transition(attempt, 'micFailed', { error }));
        return true;
    }

    // preparing + granted. A page that is hidden right now (an app's
    // permission dialog over it) starts recording when it shows again.
    function granted({ stream }) {
        take.stream = stream;
        if (document.hidden) {
            take.waitingVisible = true;
            return true;
        }
        return startRecording();
    }

    function grantedWhileHidden() {
        if (!take.waitingVisible || !take.stream) return false;
        take.waitingVisible = false;
        return startRecording();
    }

    function startRecording() {
        const attempt = take.attempt;
        const stream = take.stream;
        meter(stream);
        const chunks = [];
        let recorder;
        try {
            recorder = makeRecorder(stream);
            recorder.ondataavailable = (event) => {
                if (event.data && event.data.size) chunks.push(event.data);
            };
            recorder.onstop = () => transition(attempt, 'recorded', { recorder, chunks });
            recorder.onerror = (event) => transition(attempt, 'recorderError', { error: event.error || event });
            recorder.start();
        } catch (error) {
            console.warn('The recorder did not start', error);
            releaseMic();
            enter(...micFailure(error));
            return true;
        }
        stream.getAudioTracks().forEach((track) => {
            track.addEventListener('ended', () => transition(attempt, 'trackEnded'));
        });
        take.recorder = recorder;
        take.startedAt = performance.now();
        take.lastLoudAt = take.startedAt;
        take.levels = [];
        take.smoothed = 0;
        take.maxRms = 0;
        take.samples = 0;
        take.warning = '';
        take.hitLimit = false;
        setTimer(0);
        enter('recording');
        take.ticker = setInterval(() => transition(attempt, 'tick'), 250);
        take.sampler = setInterval(sampleLevel, 45);
        loop();
        return true;
    }

    function makeRecorder(stream) {
        const types = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/mp4'];
        const mimeType = MediaRecorder.isTypeSupported
            ? types.find((type) => MediaRecorder.isTypeSupported(type)) || '' : '';
        const settings = { audioBitsPerSecond: RECORDING_BITS_PER_SECOND };
        if (mimeType) settings.mimeType = mimeType;
        try {
            return new MediaRecorder(stream, settings);
        } catch (_) {
            return new MediaRecorder(stream);
        }
    }

    // recording + tick (4 times a second): the timer; "We can't hear you"
    // after 3.5 s under the speech level (B3), said once until speech comes
    // back; from 25 s the countdown (B4), said once; at 30 s, Stop.
    function tick() {
        const now = performance.now();
        const elapsed = (now - take.startedAt) / 1000;
        setTimer(elapsed);
        const remaining = MAX_SECONDS - elapsed;
        if (remaining <= 0) {
            take.hitLimit = true;
            return stopRecording();
        }
        let warning = '';
        if (remaining <= ENDING_SECONDS) warning = 'ending';
        else if (take.samples > 0 && now - take.lastLoudAt > QUIET_MS) warning = 'quiet';
        const seconds = Math.ceil(remaining);
        if (warning === take.warning && (warning !== 'ending' || seconds === take.endingSeconds)) return true;
        if (warning === 'ending' && take.warning !== 'ending') ui.announce(t('rec.stoppingIn', { seconds }), els.status);
        if (warning === 'quiet') ui.announce(t('rec.cantHear'), els.status);
        take.warning = warning;
        take.endingSeconds = seconds;
        render();
        return true;
    }

    // recording + stop (Stop, Space, or the 30 s limit). The recorder hands
    // over its last data with its stop event ('recorded').
    function stopRecording() {
        const attempt = take.attempt;
        take.stoppedAt = performance.now();
        stopMeters();
        take.phase = 'stopping';
        take.slow = false;
        enter('checking');
        take.stopTimer = setTimeout(() => {
            transition(attempt, 'recorderError', { error: new Error('The recorder did not stop') });
        }, STOP_TIMEOUT_MS);
        try {
            if (take.recorder && take.recorder.state !== 'inactive') take.recorder.stop();
        } catch (error) {
            return interrupt({ error }, 'recorderError');
        }
        return true;
    }

    // checking + recorded: the take is checked here first (too short, or
    // silent: nothing is sent), then read, then sent. Silence comes before
    // the size: Chrome encodes digital silence at about 250 bytes a second
    // (with a 300-byte header), so a silent take of up to 4 s is under 1 KB
    // and would be called too short. A small take whose level was not
    // silent, or was not measured, stays too short.
    function recorded({ recorder, chunks }) {
        if (take.phase !== 'stopping' || recorder !== take.recorder) return false;
        clearTimeout(take.stopTimer);
        const attempt = take.attempt;
        take.recorder = null;
        take.duration = take.stoppedAt - take.startedAt;
        const metered = take.samples >= MIN_METERED_SAMPLES;
        const blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
        releaseMic();
        drawWave(true);
        if (take.duration < MIN_RECORDING_MS) {
            enter('too-short');
            return true;
        }
        if (metered && take.maxRms < SILENCE_RMS) {
            enter('no-speech', 'silent');
            return true;
        }
        if (blob.size < MIN_RECORDING_BYTES) {
            enter('too-short');
            return true;
        }
        take.phase = 'reading';
        take.decoded = blob.arrayBuffer().then((data) => AIPT.audio.decode(data)).catch(() => null);
        readAsDataUrl(blob).then((dataUrl) => transition(attempt, 'read', { dataUrl }), () => {
            transition(attempt, 'failed', { error: Object.assign(new Error('unreadable'), { code: 'bad_audio', status: 0 }) });
        });
        return true;
    }

    const readAsDataUrl = (blob) => new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(blob);
    });

    // checking + read: the recording as the request carries it, kept for Send again.
    function read({ dataUrl }) {
        if (take.phase !== 'reading') return false;
        take.body = { title: take.text, base64Audio: dataUrl, language: AIPT.PRACTICE_LANGUAGE };
        send();
        return true;
    }

    // One attempt to score the recording: given up after 100 s, aborted by
    // Cancel (the server then skips it: client_gone).
    function send() {
        const attempt = take.attempt;
        const controller = new AbortController();
        take.request = controller;
        take.phase = 'sending';
        take.slow = false;
        clearTimeout(take.slowTimer);
        take.slowTimer = setTimeout(() => transition(attempt, 'slow', { controller }), STILL_CHECKING_MS);
        AIPT.postJSON(AIPT.API.score, take.body, { signal: controller.signal, timeout: SCORE_TIMEOUT_MS }).then(
            (data) => transition(attempt, 'answer', { data, controller }),
            (error) => transition(attempt, 'failed', { error, controller }),
        );
    }

    function settleRequest() {
        take.request = null;
        clearTimeout(take.slowTimer);
    }

    // checking + slow (B6): neutral words, said once.
    function slow({ controller }) {
        if (controller !== take.request) return false;
        take.slow = true;
        render();
        ui.announce(t('rec.stillChecking'), els.status);
        return true;
    }

    // checking + answer: the score, once the take is decoded for the result.
    function answer({ data, controller }) {
        if (controller !== take.request) return false;
        settleRequest();
        // An answer that is not the server's JSON (a portal's page, a proxy's)
        // says nothing about the recording: it can be sent again.
        if (!data || typeof data !== 'object') {
            enter('failed', 'network');
            return true;
        }
        if (data.pronunciation_accuracy === undefined) {
            dropRecording();
            enter('no-speech', 'server');
            return true;
        }
        const attempt = take.attempt;
        take.phase = 'scored';
        take.answeredAt = performance.now();
        Promise.resolve(take.decoded).then((buffer) => transition(attempt, 'scored', { data, buffer }));
        return true;
    }

    // checking + scored: the sheet closes and the result takes over (focus is its own).
    function scored({ data, buffer }) {
        if (take.phase !== 'scored') return false;
        const text = take.text;
        const about = { hitLimit: take.hitLimit, answeredAt: take.answeredAt };
        close({ restoreFocus: false });
        options.onResult(data, buffer, text, about);
        return true;
    }

    // Cloudflare's own errors when it cannot reach the app (520-523, 525-527,
    // 530); 524 is its timeout.
    const UNREACHABLE = [502, 520, 521, 522, 523, 525, 526, 527, 530];
    const FAILED_LEADS = {
        network: 'rec.failed.network',
        slow: 'rec.failed.slow',
        server: 'rec.failed.server',
        busy: 'rec.failed.busy',
    };

    // Where a request that failed leads: [state, detail]. The server's message
    // is never shown, only the page's words for its code or status.
    function classify(error) {
        const status = (error && error.status) || 0;
        const code = (error && error.code) || '';
        if (code === 'timeout') return ['failed', 'slow'];
        // No answer at all: offline when the browser says so, else the
        // connection or the server (the page cannot tell which).
        if (code === 'network') return navigator.onLine === false ? ['offline', ''] : ['failed', 'network'];
        if (status === 429 || status === 503) return ['busy', ''];
        if (status === 422 || code === 'no_speech') return ['no-speech', 'server'];
        if (UNREACHABLE.includes(status) || code === 'client_gone') return ['failed', 'network'];
        if (status === 504 || status === 524 || status === 408) return ['failed', 'slow'];
        if (status >= 500) return ['failed', 'server'];
        return ['rejected', code || String(status || 'unknown')];
    }

    // checking + failed: a busy server gets the recording again by itself;
    // a failure that sending again can fix keeps it; the rest asks for a new take.
    function requestFailed({ error, controller }) {
        if (controller && controller !== take.request) return false;
        settleRequest();
        // Only closing the sheet aborts a request, and it ends the attempt first.
        if (error && error.name === 'AbortError') return false;
        console.warn('The recording was not scored', error);
        const [state, detail] = classify(error);
        if (state === 'busy') {
            take.busyCount += 1;
            if (take.busyCount > BUSY_RETRIES) enter('failed', 'busy');
            else waitForBusyServer(error.retryAfter);
            return true;
        }
        if (state !== 'failed' && state !== 'offline') dropRecording();
        enter(state, detail);
        return true;
    }

    // B7: the wait the server asked for and up to 2 s more, counted down on
    // screen; said once, when the first wait starts.
    function waitForBusyServer(retryAfter) {
        const attempt = take.attempt;
        const seconds = (retryAfter > 0 ? retryAfter : BUSY_WAIT_SECONDS) + Math.random() * BUSY_JITTER_SECONDS;
        take.busyUntil = performance.now() + seconds * 1000;
        take.busyShown = Math.ceil(seconds);
        enter('busy');
        take.busyTimer = setInterval(() => transition(attempt, 'busyTick'), 200);
    }

    // busy + busyTick: the countdown, then the same recording again.
    function busyTick() {
        const left = Math.ceil((take.busyUntil - performance.now()) / 1000);
        if (left > 0) {
            if (left !== take.busyShown) {
                take.busyShown = left;
                render();
            }
            return true;
        }
        clearInterval(take.busyTimer);
        take.slow = false;
        enter('checking');
        send();
        return true;
    }

    // failed or offline + sendAgain: the same recording, from the start.
    function sendAgain() {
        if (!take.body) return false;
        take.busyCount = 0;
        take.slow = false;
        enter('checking');
        send();
        return true;
    }

    // offline + online: said, and shown; sending is still the learner's choice.
    function backOnline() {
        if (take.detail === 'online') return false;
        take.detail = 'online';
        render();
        ui.announce(t('rec.backOnline'), els.status);
        return true;
    }

    // recording + hidden, trackEnded, recorderError (and checking + recorderError
    // before the recording is read): the take is cancelled and nothing is sent (B12).
    const INTERRUPTIONS = { hidden: 'hidden', trackEnded: 'ended', recorderError: 'error' };

    function interrupt({ error } = {}, event = '') {
        if (take.state === 'checking' && take.phase !== 'stopping') return false;
        if (error) console.warn('The recording stopped', error);
        stopMeters();
        clearTimeout(take.stopTimer);
        discardRecorder();
        releaseMic();
        dropRecording();
        take.phase = '';
        enter('interrupted', INTERRUPTIONS[event] || 'error');
        return true;
    }

    // preparing + micFailed (B13-B18).
    function micFailed({ error }) {
        console.warn('The microphone did not start', error);
        releaseMic();
        enter(...micFailure(error));
        return true;
    }

    // [state, detail] for a microphone that did not start. Inside an app's
    // own browser every failure gets the way out of the app instead (D9, D10).
    function micFailure(error) {
        const name = (error && error.name) || '';
        if (env.inApp) return ['in-app', ['android', 'ios'].includes(env.platform) ? env.platform : 'other'];
        if (name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError') {
            return ['mic-blocked', blockedGuide()];
        }
        if (name === 'NotFoundError' || name === 'DevicesNotFoundError') return ['mic-none', ''];
        if (name === 'NotReadableError' || name === 'TrackStartError') return ['mic-busy', ''];
        return ['mic-error', name || 'unknown'];
    }

    // Which steps unblock the microphone in this browser (B13, B14, desktop).
    function blockedGuide() {
        if (env.platform === 'android' && env.browser === 'chrome') return 'android';
        if (env.platform === 'ios' && env.browser === 'safari') return 'ios';
        if (env.platform === 'other' && (env.browser === 'chrome' || env.browser === 'edge')) return 'desktop';
        return 'other';
    }

    // in-app + copy, and its answers (copied, then copyReset 4 s later; or copyRefused).
    let copyAttempt = -1;
    const copier = AIPT.inApp.copyControl({
        onCopied: () => transition(copyAttempt, 'copied'),
        onReset: () => transition(copyAttempt, 'copyReset'),
        onRefused: () => transition(copyAttempt, 'copyRefused'),
    });

    function copy() {
        copyAttempt = take.attempt;
        copier.run();
        return true;
    }

    function copied() {
        take.copied = true;
        render();
        ui.announce(t('notice.linkCopied.title'), els.status);
        return true;
    }

    function copyReset() {
        take.copied = false;
        render();
        return true;
    }

    function copyRefused() {
        take.copied = false;
        take.copyRefused = true;
        render();
        AIPT.inApp.selectAddress(els.address);
        return true;
    }

    // ✕, Cancel, Close or Escape in any state, and a score: the attempt ends
    // (whatever still runs for it is dropped), the recording goes, the sheet
    // closes and focus goes back to the mic (or to the result, its own).
    function close({ restoreFocus = true } = {}) {
        take.attempt += 1;
        resetTake();
        take.state = 'idle';
        take.detail = '';
        els.root.dataset.state = 'idle';
        ['detail', 'hint', 'tone'].forEach((name) => setData(name, ''));
        els.pointer.hidden = true;
        AIPT.audio.hold(false);
        sheet.close({ fallback: options.fallbackFocus, restoreFocus });
        return true;
    }

    // Everything a take holds goes: timers, the request, the recorder, the
    // microphone and the recording.
    function resetTake() {
        stopMeters();
        clearTimeout(take.stopTimer);
        clearTimeout(take.slowTimer);
        clearInterval(take.busyTimer);
        if (take.request) take.request.abort();
        take.request = null;
        discardRecorder();
        releaseMic();
        dropRecording();
        copier.stop();
        take.phase = '';
        take.warning = '';
        take.slow = false;
        take.busyCount = 0;
        take.samples = 0;
        take.hitLimit = false;
        take.answeredAt = 0;
        take.copied = false;
        take.copyRefused = false;
        take.waitingVisible = false;
    }

    function stopMeters() {
        clearInterval(take.ticker);
        clearInterval(take.sampler);
        cancelAnimationFrame(take.raf);
    }

    // A recorder stopped without its data being used: its stop event finds
    // no recorder of its own any more and is dropped.
    function discardRecorder() {
        const recorder = take.recorder;
        take.recorder = null;
        if (!recorder) return;
        try {
            if (recorder.state !== 'inactive') recorder.stop();
        } catch (_) {
            // Already stopped.
        }
    }

    function releaseMic() {
        if (take.source) {
            try {
                take.source.disconnect();
            } catch (_) {
                // Already disconnected.
            }
        }
        take.source = null;
        take.analyser = null;
        take.context = null;
        if (take.stream) take.stream.getTracks().forEach((track) => track.stop());
        take.stream = null;
    }

    function dropRecording() {
        take.body = null;
        take.decoded = null;
        take.duration = 0;
    }

    const MACHINE = {
        idle: { open },
        preparing: { granted, visible: grantedWhileHidden, micFailed, cancel: close },
        recording: {
            tick, stop: stopRecording, hidden: interrupt, trackEnded: interrupt, recorderError: interrupt, cancel: close,
        },
        checking: {
            recorded, recorderError: interrupt, read, slow, answer, failed: requestFailed, scored, cancel: close,
        },
        busy: { busyTick, cancel: close },
        failed: { sendAgain, recordAgain: newTake, cancel: close },
        offline: { sendAgain, recordAgain: newTake, online: backOnline, cancel: close },
        'no-speech': { recordAgain: newTake, cancel: close },
        'too-short': { recordAgain: newTake, cancel: close },
        interrupted: { recordAgain: newTake, cancel: close },
        rejected: { recordAgain: newTake, cancel: close },
        'mic-blocked': { tryAgain: newTake, cancel: close },
        'mic-none': { tryAgain: newTake, cancel: close },
        'mic-busy': { tryAgain: newTake, cancel: close },
        'mic-error': { tryAgain: newTake, cancel: close },
        'in-app': { copy, copied, copyReset, copyRefused, cancel: close },
    };

    // ---------------------------------------------------------------- drawing the state
    const wide = () => window.matchMedia('(min-width: 768px)').matches;
    // "0:06" for a take of 5.6 s (a kept recording is at least a second long here).
    const duration = () => AIPT.formatClock(Math.max(1, Math.round(take.duration / 1000)));

    function setData(name, value) {
        if (value) els.root.dataset[name] = value;
        else delete els.root.dataset[name];
    }

    function setTimer(seconds) {
        els.timer.textContent = `${AIPT.formatClock(seconds)} / ${AIPT.formatClock(MAX_SECONDS)}`;
    }

    // What each state shows in its header: the dot (the take's states) or an
    // icon in the colour of its family (design-system §1.3), and so which
    // part of the body: the sentence, waveform and hint, or a message.
    const VIEWS = {
        preparing: {},
        recording: {},
        checking: {},
        busy: {},
        failed: { icon: 'warn', tone: 'error' },
        offline: { icon: 'wifi-off', tone: 'warning' },
        'no-speech': { icon: 'mic-off', tone: 'warning' },
        'too-short': { icon: 'clock', tone: 'warning' },
        interrupted: { icon: 'info', tone: 'info' },
        rejected: { icon: 'warn', tone: 'error' },
        'mic-blocked': { icon: 'mic-off', tone: 'warning' },
        'mic-none': { icon: 'mic-off', tone: 'warning' },
        'mic-busy': { icon: 'mic-off', tone: 'warning' },
        'mic-error': { icon: 'mic-off', tone: 'warning' },
        'in-app': { icon: 'open', tone: 'warning' },
    };

    // Draw the current state (also after a language switch or a resize):
    // nothing here moves focus or speaks.
    function render() {
        const view = VIEWS[take.state];
        if (!view) return;
        const live = take.state === 'recording';
        const message = Boolean(view.icon);
        els.root.dataset.state = take.state;
        setData('detail', take.detail);
        setData('hint', live ? take.warning : '');
        setData('tone', view.tone || '');
        els.dot.hidden = message;
        els.dot.classList.toggle('is-live', live);
        els.label.hidden = !live;
        els.timer.hidden = !live;
        // An <svg> has no `hidden` property: the attribute itself.
        els.icon.toggleAttribute('hidden', !message);
        if (message) els.iconUse.setAttribute('href', `#i-${view.icon}`);
        els.take.hidden = message;
        els.message.hidden = !message;
        if (message) {
            els.steps.hidden = true;
            els.steps.replaceChildren();
            els.kept.hidden = true;
            els.note.hidden = true;
            els.copyHelp.hidden = true;
        }
        els.pointer.hidden = !(take.state === 'in-app' && take.detail === 'ios');
        AIPT.setDisabled(els.stop, take.state !== 'recording');
        RENDER[take.state]();
        if (!message) updateSentenceScroll();
    }

    // The veil over the waveform: a spinner or the clock, and its lines ([key, params]).
    function setOverlay(kind, lines = []) {
        els.overlay.hidden = !kind;
        els.spinner.hidden = kind !== 'spinner';
        els.clock.toggleAttribute('hidden', kind !== 'clock');
        els.overlayText.replaceChildren(...lines.map(([key, params]) => (
            i18n.text(el('span', { className: 'wave-line' }), key, params))));
    }

    // The hint under the waveform: a key, or a warning (icon and bold, B3, B4).
    function setHint(key, params, warning = false) {
        els.hint.classList.toggle('is-warning', warning);
        if (!key) {
            els.hint.replaceChildren();
            return;
        }
        const words = i18n.text(el('span'), key, params);
        els.hint.replaceChildren(...(warning ? [icon('warn'), words] : [words]));
    }

    // "Read the sentence, then tap Stop." ("click Stop or press Space" from 768 px).
    function setReadHint() {
        els.hint.classList.remove('is-warning');
        const stop = i18n.text(el('b'), 'controls.stop');
        els.hint.replaceChildren(wide()
            ? i18n.richText(el('span'), 'rec.hintWide', { stop, space: i18n.text(el('kbd'), 'controls.space') })
            : i18n.richText(el('span'), 'rec.hint', { stop }));
    }

    // The message of the other states: the title, a bold first line, a second line.
    function setMessage(titleKey, leadKey, textKey = '', params) {
        i18n.text(els.title, titleKey, params);
        i18n.text(els.lead, leadKey, params);
        els.text.hidden = !textKey;
        if (textKey) i18n.text(els.text, textKey, params);
        else els.text.replaceChildren();
    }

    function setSteps(items) {
        els.steps.replaceChildren(...items);
        els.steps.hidden = !items.length;
    }

    function showKept() {
        els.kept.hidden = false;
        i18n.text(els.keptText, 'rec.kept', { duration: duration() });
    }

    // The state's actions in their order, which is also the order of focus:
    // [button, kind, layout] with kind 'primary', 'secondary' or 'stop';
    // layout 'full' gives a primary a row of its own, and 'wide' gives the
    // first button of the next row the larger share (B8, B17, B21).
    function setActions(list, cancelKey) {
        const wanted = list.map(([node]) => node);
        ACTIONS.forEach((node) => {
            node.hidden = !wanted.includes(node);
        });
        list.forEach(([node, kind, layout = '']) => {
            node.classList.toggle('btn-primary', kind === 'primary');
            node.classList.toggle('btn-secondary', kind === 'secondary');
            node.classList.toggle('btn-stop', kind === 'stop');
            node.classList.toggle('is-full', layout === 'full');
            node.classList.toggle('is-wide', layout === 'wide');
        });
        // Moved only when the order changes: a node that moves loses its focus.
        const shown = Array.from(els.actions.children).filter((node) => !node.hidden);
        if (shown.some((node, index) => node !== wanted[index])) wanted.forEach((node) => els.actions.appendChild(node));
        i18n.text(els.cancel, cancelKey);
    }

    const takeActions = () => setActions([[els.cancel, 'secondary'], [els.stop, 'stop']], 'common.cancel');
    // B8, B9: Send again on a row of its own, then Record again and Close.
    const keptActions = () => setActions([[els.send, 'primary', 'full'], [els.recordAgain, 'secondary', 'wide'],
        [els.cancel, 'secondary']], 'common.close');
    // B10-B12: Close, then Record again.
    const againActions = () => setActions([[els.cancel, 'secondary'], [els.recordAgain, 'primary']], 'common.close');
    // B13-B16: Close, then Try again.
    const micActions = () => setActions([[els.cancel, 'secondary'], [els.tryAgain, 'primary']], 'common.close');

    const bold = (key) => i18n.text(el('b'), key);
    const step = (key, slots) => i18n.richText(el('li'), key, slots);
    const lockIcon = () => ui.uibit({ icon: 'lock', key: 'rec.ui.lock' });
    const tuneIcon = () => ui.uibit({ icon: 'tune', key: 'rec.ui.tune' });
    const allowIn = (key) => step(key, {
        microphone: ui.uibit({ key: 'rec.ui.microphone' }),
        allow: ui.uibit({ key: 'rec.ui.allow' }),
    });

    // The steps that unblock the microphone: Chrome on Android (B13), Safari
    // on iPhone (B14), Chrome and Edge on a computer.
    const BLOCKED_STEPS = {
        android: () => [
            step('rec.blocked.android1', { lock: lockIcon(), tune: tuneIcon() }),
            step('rec.blocked.android2', {
                permissions: ui.uibit({ key: 'rec.ui.permissions' }),
                microphone: ui.uibit({ key: 'rec.ui.microphone' }),
                allow: ui.uibit({ key: 'rec.ui.allow' }),
            }),
            step('rec.blocked.androidLast', { tryAgain: bold('common.tryAgain') }),
        ],
        ios: () => [
            step('rec.blocked.ios1', { aa: ui.uibit({ text: 'aA' }) }),
            step('rec.blocked.ios2', { websiteSettings: ui.uibit({ key: 'rec.ui.websiteSettings' }) }),
            allowIn('rec.blocked.ios3'),
            step('rec.blocked.iosLast', { tryAgain: bold('common.tryAgain') }),
        ],
        desktop: () => [
            step('rec.blocked.desktop1', { lock: lockIcon(), tune: tuneIcon() }),
            allowIn('rec.blocked.desktop2'),
            step('rec.blocked.desktopLast', { tryAgain: bold('common.tryAgain') }),
        ],
    };
    const BLOCKED_HOW = { android: 'rec.blocked.howChrome', ios: 'rec.blocked.how', desktop: 'rec.blocked.how' };
    const MIC_MESSAGES = {
        'mic-none': { title: 'rec.none.title', lead: 'rec.none.lead', text: 'rec.none.text' },
        'mic-busy': { title: 'rec.micBusy.title', lead: 'rec.micBusy.lead', text: 'rec.micBusy.text' },
        'mic-error': { title: 'rec.micError.title', lead: 'rec.micError.lead', text: '' },
    };

    // The message of a microphone that did not start (B13-B16), here and in
    // the microphone check (E9): the keys of its title, first and second
    // line, and the steps that unblock it in this browser (guide, from
    // micFailure).
    function micMessage(state, guide = '') {
        if (state === 'mic-blocked') {
            return {
                title: 'rec.blocked.title',
                lead: guide === 'ios' ? 'rec.blocked.leadSafari' : 'rec.blocked.lead',
                text: BLOCKED_HOW[guide] || 'rec.blocked.inSettings',
                steps: BLOCKED_STEPS[guide] ? BLOCKED_STEPS[guide]() : [],
            };
        }
        return { ...(MIC_MESSAGES[state] || MIC_MESSAGES['mic-error']), steps: [] };
    }

    function showMicMessage() {
        const message = micMessage(take.state, take.detail);
        setMessage(message.title, message.lead, message.text);
        setSteps(message.steps);
        micActions();
    }

    const RENDER = {
        preparing() {
            i18n.text(els.title, 'rec.preparing');
            setOverlay('spinner', [['rec.allow']]);
            setHint('');
            takeActions();
        },
        recording() {
            i18n.text(els.title, 'rec.recording');
            setOverlay('');
            if (take.warning === 'ending') setHint('rec.stoppingIn', { seconds: take.endingSeconds }, true);
            else if (take.warning === 'quiet') setHint('rec.cantHear', null, true);
            else setReadHint();
            takeActions();
        },
        checking() {
            i18n.text(els.title, 'rec.checking');
            setOverlay('spinner', [['rec.checkingShort']]);
            setHint(take.slow ? 'rec.stillChecking' : 'rec.checkingHint');
            setActions([[els.cancel, 'secondary']], 'common.cancel');
        },
        busy() {
            i18n.text(els.title, 'rec.checking');
            setOverlay('clock', [['rec.busyLine'], ['rec.busyCountdown',
                { seconds: take.busyShown, attempt: take.busyCount, total: BUSY_RETRIES }]]);
            setHint('rec.busyHint');
            setActions([[els.cancel, 'secondary']], 'common.cancel');
        },
        failed() {
            setMessage('rec.failed.title', FAILED_LEADS[take.detail] || FAILED_LEADS.network, 'rec.failed.text');
            showKept();
            keptActions();
        },
        offline() {
            setMessage('rec.offline.title', 'rec.offline.lead', wide() ? 'rec.offline.textWide' : 'rec.offline.text');
            showKept();
            els.note.hidden = take.detail !== 'online';
            keptActions();
        },
        'no-speech'() {
            setMessage('rec.noSpeech.title', 'rec.noSpeech.lead', wide() ? 'rec.noSpeech.textWide' : 'rec.noSpeech.text');
            againActions();
        },
        'too-short'() {
            setMessage('rec.tooShort.title', 'rec.tooShort.lead', wide() ? 'rec.tooShort.textWide' : 'rec.tooShort.text');
            againActions();
        },
        interrupted() {
            setMessage('rec.interrupted.title', 'rec.interrupted.lead', 'rec.interrupted.text');
            againActions();
        },
        rejected() {
            let lead = 'error.unknown';
            if (i18n.has(`error.${take.detail}`)) lead = `error.${take.detail}`;
            else if (take.detail === '413') lead = 'error.audio_too_long';
            setMessage('rec.failed.title', lead);
            againActions();
        },
        'mic-blocked': showMicMessage,
        'mic-none': showMicMessage,
        'mic-busy': showMicMessage,
        'mic-error': showMicMessage,
        // B17 (Android: Open in Chrome, Copy link) and B18 (iPhone: the ••• menu, Copy link).
        'in-app'() {
            const message = AIPT.inApp.failureMessage();
            setMessage(message.title, message.lead, message.text, message.params);
            if (message.ios) {
                setSteps(AIPT.inApp.safariSteps());
                setActions([[els.copyLink, 'primary'], [els.cancel, 'secondary']], 'common.close');
            } else {
                if (message.menu) AIPT.inApp.chromeOrMenu(els.text);
                if (message.openChrome) {
                    els.openChrome.setAttribute('href', AIPT.inApp.chromeIntentUrl());
                    setActions([[els.openChrome, 'primary', 'full'], [els.copyLink, 'secondary', 'wide'],
                        [els.cancel, 'secondary']], 'common.close');
                } else {
                    setActions([[els.copyLink, 'primary'], [els.cancel, 'secondary']], 'common.close');
                }
            }
            // "✓ Link copied" for 4 s (D6); the address to copy by hand when the clipboard is refused (D7).
            i18n.text(els.copyLabel, take.copied ? 'notice.linkCopied.title' : 'notice.copyLink');
            els.copyIcon.setAttribute('href', take.copied ? '#i-check' : '#i-copy');
            els.copyLink.classList.toggle('is-done', take.copied);
            els.copyHelp.hidden = !take.copyRefused;
        },
    };

    // A sentence longer than its area scrolls there (about 35% of the height,
    // B19); it takes focus then, so that keys scroll it too.
    function updateSentenceScroll() {
        if (els.sentence.scrollHeight > els.sentence.clientHeight + 1) els.sentence.setAttribute('tabindex', '0');
        else els.sentence.removeAttribute('tabindex');
    }

    // ---------------------------------------------------------------- focus and announcements
    // When a state begins (design-system §4): focus on the title on open and
    // while checking, on Stop while recording, on the primary action of the
    // other states; the sheet's polite region says each phase once, and the
    // alert region gives the message of an error.
    function arrive(previous) {
        const state = take.state;
        if (state === 'preparing') {
            ui.focus(els.title, { preventScroll: true });
        } else if (state === 'recording') {
            ui.focus(els.stop, { preventScroll: true });
            ui.announce(t('rec.recording'), els.status);
        } else if (state === 'checking') {
            // Sending again after a busy wait: nothing new to say.
            if (previous === 'busy') return;
            ui.focus(els.title, { preventScroll: true });
            ui.announce(t('rec.checkingAnnounce'), els.status);
        } else if (state === 'busy') {
            if (take.busyCount === 1) ui.announce(t('rec.busyAnnounce'), els.status);
        } else {
            ui.announce('', els.status);
            ui.focus(primaryAction(), { preventScroll: true });
            const parts = [els.title, els.lead, els.text, els.kept]
                .filter((node) => !node.hidden && node.textContent.trim())
                .map((node) => node.textContent.trim());
            ui.announce(parts.join(' '), els.alert);
        }
    }

    function primaryAction() {
        const shown = ACTIONS.filter((node) => !node.hidden);
        return shown.find((node) => node.classList.contains('btn-primary')) || shown[0] || els.title;
    }

    // ---------------------------------------------------------------- the level and the waveform
    const wave = { width: 0, height: 0, dpr: 1, bar: 4, gap: 3 };
    let sampleBuffer = null;

    // The level meter, on the page's audio context; none where it fails.
    function meter(stream) {
        try {
            const context = AIPT.audio.context();
            const source = context.createMediaStreamSource(stream);
            const analyser = context.createAnalyser();
            analyser.fftSize = 2048;
            source.connect(analyser);
            take.context = context;
            take.source = source;
            take.analyser = analyser;
        } catch (err) {
            console.warn('No level meter for this take', err);
        }
    }

    function sizeCanvas() {
        const rect = els.canvas.getBoundingClientRect();
        wave.dpr = Math.min(window.devicePixelRatio || 1, 2);
        wave.width = Math.max(1, Math.round(rect.width * wave.dpr));
        wave.height = Math.max(1, Math.round(rect.height * wave.dpr));
        els.canvas.width = wave.width;
        els.canvas.height = wave.height;
    }

    function readSamples() {
        const analyser = take.analyser;
        if (!sampleBuffer || sampleBuffer.length !== analyser.fftSize) sampleBuffer = new Float32Array(analyser.fftSize);
        analyser.getFloatTimeDomainData(sampleBuffer);
        return sampleBuffer;
    }

    // The level is measured on a timer, not on animation frames, so that the
    // silence checks keep their pace. A context that is not running measures
    // nothing (iOS can suspend it): those moments do not count.
    function sampleLevel() {
        if (take.state !== 'recording' || !take.analyser) return;
        if (take.context && take.context.state !== 'running') return;
        const samples = readSamples();
        let sum = 0;
        for (let i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i];
        const rms = Math.sqrt(sum / samples.length);
        take.samples += 1;
        if (rms > take.maxRms) take.maxRms = rms;
        const level = AIPT.audio.levelOf(rms);
        take.smoothed = Math.max(level, take.smoothed * 0.8);
        if (level > AIPT.audio.SPEECH_LEVEL) take.lastLoudAt = performance.now();
        take.levels.push(take.smoothed);
        const maxBars = Math.ceil(wave.width / ((wave.bar + wave.gap) * wave.dpr)) + 1;
        if (take.levels.length > maxBars) take.levels.splice(0, take.levels.length - maxBars);
    }

    function loop() {
        if (take.state !== 'recording' || !take.analyser) return;
        drawWave(false, readSamples());
        take.raf = requestAnimationFrame(loop);
    }

    function cssVar(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }

    function roundRect(ctx, x, y, w, h, r) {
        const radius = Math.min(r, h / 2, w / 2);
        ctx.beginPath();
        ctx.moveTo(x + radius, y);
        ctx.arcTo(x + w, y, x + w, y + h, radius);
        ctx.arcTo(x + w, y + h, x, y + h, radius);
        ctx.arcTo(x, y + h, x, y, radius);
        ctx.arcTo(x, y, x + w, y, radius);
        ctx.closePath();
        ctx.fill();
    }

    function drawWave(frozen = false, samples = null) {
        const ctx = els.canvas.getContext('2d');
        if (!ctx) return;
        const { width, height, dpr } = wave;
        ctx.clearRect(0, 0, width, height);
        const mid = height / 2;
        const primary = cssVar('--primary') || '#4f46e5';
        const muted = cssVar('--border') || '#e3e6f0';

        // centre line
        ctx.fillStyle = muted;
        ctx.fillRect(0, mid - dpr / 2, width, dpr);

        // live trace behind the bars
        if (samples && !frozen) {
            ctx.beginPath();
            ctx.lineWidth = 1.5 * dpr;
            ctx.strokeStyle = primary;
            ctx.globalAlpha = 0.25;
            const stepX = samples.length / width;
            for (let x = 0; x < width; x += 2) {
                const v = samples[Math.floor(x * stepX)] || 0;
                const y = mid + v * mid * 0.9;
                if (x === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            ctx.stroke();
            ctx.globalAlpha = 1;
        }

        // scrolling level bars, the newest on the right
        const bar = wave.bar * dpr;
        const gap = wave.gap * dpr;
        const levels = take.levels;
        ctx.fillStyle = primary;
        for (let i = levels.length - 1, x = width - bar - gap; i >= 0 && x > -bar; i -= 1, x -= bar + gap) {
            const h = Math.max(2 * dpr, levels[i] * (height - 16 * dpr));
            const age = (levels.length - 1 - i) / Math.max(levels.length, 1);
            ctx.globalAlpha = frozen ? 0.35 : Math.max(0.35, 1 - age * 0.8);
            roundRect(ctx, x, mid - h / 2, bar, h, bar / 2);
        }
        ctx.globalAlpha = 1;
    }

    // ---------------------------------------------------------------- the sheet, keys and buttons
    const sheet = new ui.Sheet(els.root, {
        closeOnBackdrop: false,
        onDismiss: () => transition(take.attempt, 'cancel'),
    });

    // A tap on an action, unless it came right after the actions changed (it
    // was meant for the old ones). Keys (a click with detail 0) always count.
    function onTap(node, event) {
        node.addEventListener('click', (clickEvent) => {
            if (clickEvent.detail > 0 && performance.now() - take.changedAt < SETTLE_MS) {
                clickEvent.preventDefault();
                return;
            }
            if (event && !AIPT.isDisabled(node)) transition(take.attempt, event);
        });
    }
    onTap(els.cancel, 'cancel');
    onTap(els.stop, 'stop');
    onTap(els.send, 'sendAgain');
    onTap(els.recordAgain, 'recordAgain');
    onTap(els.tryAgain, 'tryAgain');
    onTap(els.copyLink, 'copy');
    onTap(els.openChrome, ''); // the link itself opens Chrome

    // In the sheet, Space and Enter belong to the focused button, and a key
    // held down does nothing more (its repeats are dropped). While
    // recording, Space stops when focus is on the dialog (its title, or
    // after a click inside it) or on the page's body; on Stop, the button's
    // own click does it; anywhere else (Cancel, ✕, the sentence) it is that
    // element's.
    document.addEventListener('keydown', (event) => {
        if (!sheet.isOpen) return;
        if (event.key !== ' ' && event.key !== 'Spacebar' && event.key !== 'Enter') return;
        if (event.repeat) {
            event.preventDefault();
            return;
        }
        const target = event.target;
        const onDialog = target === els.dialog || target === els.title || target === document.body
            || target === document.documentElement;
        if (event.key !== 'Enter' && onDialog && take.state === 'recording') {
            event.preventDefault();
            transition(take.attempt, 'stop');
        }
    });

    document.addEventListener('visibilitychange', () => {
        transition(take.attempt, document.hidden ? 'hidden' : 'visible');
    });
    window.addEventListener('online', () => transition(take.attempt, 'online'));

    window.addEventListener('resize', () => {
        if (!sheet.isOpen) return;
        sizeCanvas();
        drawWave(take.state !== 'recording');
        render();
    });
    i18n.onChange(() => {
        if (sheet.isOpen) render();
    });

    watchPermission();

    AIPT.recorder = {
        // getText() gives the sentence to read; onResult(data, buffer, text,
        // { hitLimit, answeredAt }) gets the score after the sheet has closed
        // (focus is the caller's): hitLimit when the take stopped by itself at
        // 30 s, answeredAt when the answer came (performance.now()).
        // fallbackFocus takes focus when the sheet closes and its opener is gone.
        init(given) {
            options = { ...options, ...given };
        },
        // The mic was tapped: opener gets focus back when the sheet closes.
        start(opener) {
            return transition(take.attempt, 'open', { opener });
        },
        get busy() {
            return take.state !== 'idle';
        },
        get state() {
            return take.state;
        },
        // For the microphone check (miccheck.js, E9): the same state and steps
        // for a microphone that did not start, and what the browser says of the
        // permission before any tap ('granted', 'denied', 'prompt' or '').
        micFailure,
        micMessage,
        get micPermission() {
            return micPermission;
        },
    };
})();
