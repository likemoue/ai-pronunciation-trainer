'use strict';

// Recording, in the sheet of design/wireframes/02-recording-sheet.html (its
// anatomy: dot and "REC", title, timer, ✕; the sentence in its own scroll
// area, the waveform, the hint; fixed actions). The states and their logic
// are today's (preparing, recording, processing, error with Try again, the
// busy server's retries, the 100 s limit); a later step of phase 4 rebuilds
// the states. The backdrop never closes the sheet; ✕, Cancel and Escape do.
(() => {
    const { $, i18n, ui } = AIPT;
    const { t } = i18n;

    const MAX_SECONDS = AIPT.LIMITS.recordingSeconds;
    const SILENCE_RMS = 0.003;
    const MIN_RECORDING_MS = 600;
    // Cloudflare gives up after 125 s (error 524), so stop waiting before that.
    const SCORE_TIMEOUT_MS = 100000;
    // A busy server answers 503 with Retry-After; the recording is sent again
    // by itself this many times, a little after the time the server gave.
    const BUSY_RETRIES = 3;
    // Opus at 32 kbps is plenty for speech recognition and a quarter of the
    // browsers' default: a 30 s recording is about 120 KB.
    const RECORDING_BITS_PER_SECOND = 32000;
    const LONG_TEXT_WORDS = 20;

    const els = {
        sheet: $('recordSheet'),
        dot: $('recDot'),
        label: $('recLabel'),
        title: $('recTitle'),
        timer: $('recTimer'),
        sentence: $('recSentence'),
        canvas: $('waveCanvas'),
        overlay: $('waveOverlay'),
        overlayText: $('waveOverlayText'),
        hint: $('recHint'),
        status: $('recStatus'),
        alert: $('recAlert'),
        cancel: $('recCancel'),
        stop: $('recStop'),
        retry: $('recRetry'),
    };

    let options = { getText: () => '', onResult: () => {}, fallbackFocus: null };

    const rec = {
        phase: 'idle', // idle | preparing | recording | processing | error
        attempt: 0,
        stream: null,
        recorder: null,
        cancelled: false,
        startedAt: 0,
        analyser: null,
        source: null,
        levels: [],
        maxRms: 0,
        lastLoudAt: 0,
        smoothed: 0,
        raf: 0,
        timer: 0,
        sampler: 0,
        abort: null,
        slowTimer: 0,
        warning: '',
    };

    const sheet = new ui.Sheet(els.sheet, { closeOnBackdrop: false, onDismiss: () => cancelRecording() });

    // ---------------------------------------------------------------- the sheet's texts
    const wide = () => window.matchMedia('(min-width: 768px)').matches;

    function setTimer(seconds) {
        els.timer.textContent = `${AIPT.formatClock(seconds)} / ${AIPT.formatClock(MAX_SECONDS)}`;
    }

    // The hint under the waveform: a key, or the recording hint ("Read the
    // sentence, then tap Stop", "click Stop or press Space" from 768 px).
    function setHint(key, params, warning = false) {
        els.hint.classList.toggle('is-warning', warning);
        if (key) {
            i18n.text(els.hint, key, params);
            return;
        }
        els.hint.removeAttribute('data-i18n');
        const stopWord = () => AIPT.el('b', { text: t('controls.stop') });
        els.hint.replaceChildren(wide()
            ? i18n.rich('rec.hintWide', { stop: stopWord, space: () => AIPT.el('kbd', { text: t('controls.space') }) })
            : i18n.rich('rec.hint', { stop: stopWord }));
    }

    function clearHint() {
        els.hint.removeAttribute('data-i18n');
        els.hint.classList.remove('is-warning');
        els.hint.textContent = '';
    }

    function setPhase(phase, messageKey, params) {
        rec.phase = phase;
        rec.warning = '';
        const recording = phase === 'recording';
        els.dot.classList.toggle('is-live', recording);
        els.label.hidden = !recording;
        els.timer.hidden = !recording;
        els.stop.hidden = phase === 'error' || phase === 'processing';
        AIPT.setDisabled(els.stop, !recording);
        els.retry.hidden = phase !== 'error';
        i18n.text(els.cancel, phase === 'error' ? 'common.close' : 'common.cancel');
        els.overlay.hidden = phase === 'recording' || phase === 'idle';
        els.overlay.classList.toggle('is-error', phase === 'error');
        els.overlay.querySelector('.spinner').hidden = phase === 'error';
        els.alert.textContent = '';

        switch (phase) {
            case 'preparing':
                i18n.text(els.title, 'rec.preparing');
                i18n.text(els.overlayText, 'rec.allow');
                clearHint();
                ui.announce(t('rec.preparing'), els.status);
                break;
            case 'recording':
                i18n.text(els.title, 'rec.recording');
                setHint();
                ui.announce(t('rec.recording'), els.status);
                break;
            case 'processing':
                i18n.text(els.title, 'rec.checking');
                i18n.text(els.overlayText, 'rec.checkingShort');
                setHint('rec.checkingHint');
                ui.announce(t('rec.checking'), els.status);
                break;
            case 'error':
                i18n.text(els.title, 'rec.error');
                i18n.text(els.overlayText, messageKey || 'error.unknown', params);
                clearHint();
                ui.announce('', els.status);
                ui.announce(t(messageKey || 'error.unknown', params), els.alert);
                break;
            default:
                break;
        }
    }

    // ---------------------------------------------------------------- open and close
    function openSheet(opener) {
        const text = options.getText();
        els.sentence.textContent = text;
        els.sentence.classList.toggle('is-long', text.split(' ').length > LONG_TEXT_WORDS);
        els.sentence.scrollTop = 0;
        setTimer(0);
        rec.levels = [];
        if (!sheet.open(opener)) return false;
        sizeCanvas();
        drawWave();
        return true;
    }

    function closeSheet(closeOptions) {
        cleanupRecorder();
        if (rec.abort) {
            rec.abort.abort();
            rec.abort = null;
        }
        clearTimeout(rec.slowTimer);
        rec.phase = 'idle';
        sheet.close({ fallback: options.fallbackFocus, ...closeOptions });
    }

    function cleanupRecorder() {
        cancelAnimationFrame(rec.raf);
        clearInterval(rec.timer);
        clearInterval(rec.sampler);
        if (rec.source) {
            try {
                rec.source.disconnect();
            } catch (_) {
                // Already disconnected.
            }
        }
        rec.source = null;
        rec.analyser = null;
        if (rec.stream) rec.stream.getTracks().forEach((track) => track.stop());
        rec.stream = null;
    }

    function pickMimeType() {
        if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return '';
        const candidates = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/mp4'];
        return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || '';
    }

    // ---------------------------------------------------------------- recording
    async function start(opener) {
        if (rec.phase !== 'idle' || !options.getText()) return;
        AIPT.audio.stop();
        if (!openSheet(opener)) return;
        setPhase('preparing');
        rec.cancelled = false;
        rec.attempt += 1;
        const attempt = rec.attempt;
        const ctx = AIPT.audio.context();

        let stream;
        try {
            stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
        } catch (err) {
            console.error(err);
            if (rec.phase !== 'preparing' || attempt !== rec.attempt) return;
            const denied = err && (err.name === 'NotAllowedError' || err.name === 'SecurityError');
            setPhase('error', denied ? 'rec.micBlocked' : 'rec.micMissing');
            AIPT.ui.focus(els.retry, { preventScroll: true });
            return;
        }
        if (rec.phase !== 'preparing' || attempt !== rec.attempt) {
            // The sheet was closed while the browser asked for the microphone.
            stream.getTracks().forEach((track) => track.stop());
            return;
        }

        rec.stream = stream;
        rec.source = ctx.createMediaStreamSource(stream);
        rec.analyser = ctx.createAnalyser();
        rec.analyser.fftSize = 2048;
        rec.source.connect(rec.analyser);

        const mimeType = pickMimeType();
        const recorderOptions = { audioBitsPerSecond: RECORDING_BITS_PER_SECOND };
        if (mimeType) recorderOptions.mimeType = mimeType;
        try {
            rec.recorder = new MediaRecorder(stream, recorderOptions);
        } catch (_) {
            rec.recorder = new MediaRecorder(stream);
        }
        const chunks = [];
        const recorder = rec.recorder;
        recorder.ondataavailable = (event) => {
            if (event.data && event.data.size) chunks.push(event.data);
        };
        recorder.onstop = () => onRecorderStop(attempt, recorder, chunks);
        recorder.start();

        rec.startedAt = performance.now();
        rec.lastLoudAt = rec.startedAt;
        rec.levels = [];
        rec.smoothed = 0;
        rec.maxRms = 0;
        setPhase('recording');
        AIPT.ui.focus(els.stop, { preventScroll: true });

        rec.timer = setInterval(() => {
            const elapsed = (performance.now() - rec.startedAt) / 1000;
            setTimer(elapsed);
            const remaining = MAX_SECONDS - elapsed;
            if (remaining <= 0) {
                stopRecording();
            } else if (remaining <= 5) {
                const seconds = Math.ceil(remaining);
                if (rec.warning !== `stop${seconds}`) {
                    // Spoken once, when it starts, not every second.
                    if (!rec.warning.startsWith('stop')) ui.announce(t('rec.stoppingIn', { seconds }), els.status);
                    rec.warning = `stop${seconds}`;
                    setHint('rec.stoppingIn', { seconds }, true);
                }
            } else if (performance.now() - rec.lastLoudAt > 3500) {
                if (rec.warning !== 'quiet') {
                    rec.warning = 'quiet';
                    setHint('rec.cantHear', null, true);
                    ui.announce(t('rec.cantHear'), els.status);
                }
            } else if (rec.warning) {
                rec.warning = '';
                setHint();
            }
        }, 250);

        rec.sampler = setInterval(sampleLevel, 45);
        loop();
    }

    function stopRecording() {
        if (rec.phase !== 'recording' || !rec.recorder) return;
        clearInterval(rec.timer);
        clearInterval(rec.sampler);
        setPhase('processing');
        AIPT.ui.focus(els.title, { preventScroll: true });
        if (rec.recorder.state !== 'inactive') rec.recorder.stop();
    }

    function cancelRecording() {
        rec.cancelled = true;
        if (rec.recorder && rec.recorder.state !== 'inactive') rec.recorder.stop();
        closeSheet();
    }

    const blobToDataUrl = (blob) => new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(blob);
    });

    // The page's text for a failed check (the server's message is never shown).
    function errorKey(err) {
        if (err.code === 'timeout') return 'error.timeout';
        if (err.code === 'network') return navigator.onLine === false ? 'error.offline' : 'error.network';
        if (err.status === 422) return 'error.no_speech';
        if (err.code && i18n.has(`error.${err.code}`)) return `error.${err.code}`;
        if (err.status === 413) return 'error.audio_too_long';
        if (err.status === 429 || err.status === 503) return 'error.busy';
        if (err.status === 502 || err.status === 504 || err.status === 524) return 'error.timeout';
        return 'error.scoring_failed';
    }

    async function onRecorderStop(attempt, recorder, chunks) {
        if (attempt !== rec.attempt || rec.cancelled) return;
        const durationMs = performance.now() - rec.startedAt;
        const type = recorder.mimeType || 'audio/webm';
        const blob = new Blob(chunks, { type });
        rec.recorder = null;
        cleanupRecorder();
        drawWave(true);

        if (durationMs < MIN_RECORDING_MS || blob.size < 1000) {
            setPhase('error', 'rec.tooShort');
            AIPT.ui.focus(els.retry, { preventScroll: true });
            return;
        }
        if (rec.maxRms < SILENCE_RMS) {
            setPhase('error', 'rec.silent');
            AIPT.ui.focus(els.retry, { preventScroll: true });
            return;
        }

        // Closing the sheet aborts everything (closeSheet); each attempt also
        // has its own time limit, which the waits between attempts do not use up.
        const abort = new AbortController();
        rec.abort = abort;
        const text = options.getText();

        try {
            const [base64Audio, buffer] = await Promise.all([
                blobToDataUrl(blob),
                blob.arrayBuffer().then((data) => AIPT.audio.decode(data)).catch(() => null),
            ]);
            const body = { title: text, base64Audio, language: AIPT.PRACTICE_LANGUAGE };
            let data;
            for (let attemptNumber = 0; ; attemptNumber += 1) {
                try {
                    data = await sendRecording(body, abort.signal);
                    break;
                } catch (err) {
                    const busy = err.status === 503 || err.status === 429;
                    if (!busy || attemptNumber >= BUSY_RETRIES || abort.signal.aborted) throw err;
                    await waitForBusyServer(err.retryAfter || 3, abort.signal, attemptNumber === 0);
                }
            }

            if (!data || data.pronunciation_accuracy === undefined) {
                throw Object.assign(new Error('empty'), { status: 422, code: 'no_speech' });
            }
            // An answer for a sheet that was closed in the meantime belongs to
            // no take any more: it must not close a newer one.
            if (abort.signal.aborted) return;
            closeSheet({ restoreFocus: false });
            options.onResult(data, buffer, text);
        } catch (err) {
            // Only closeSheet aborts this controller: the learner closed the
            // sheet, and it may already show a newer take.
            if (abort.signal.aborted) return;
            console.error(err);
            setPhase('error', errorKey(err));
            AIPT.ui.focus(els.retry, { preventScroll: true });
        } finally {
            // closeSheet cleared the timer of a closed sheet; rec.slowTimer may
            // belong to a newer take by now.
            if (!abort.signal.aborted) clearTimeout(rec.slowTimer);
            if (rec.abort === abort) rec.abort = null;
        }
    }

    // One attempt to score the recording, given up after SCORE_TIMEOUT_MS or
    // when the sheet is closed (the outer signal).
    async function sendRecording(body, outer) {
        clearTimeout(rec.slowTimer);
        rec.slowTimer = setTimeout(() => {
            if (rec.phase === 'processing') setHint('rec.stillChecking');
        }, 8000);
        try {
            return await AIPT.postJSON(AIPT.API.score, body, { signal: outer, timeout: SCORE_TIMEOUT_MS });
        } finally {
            clearTimeout(rec.slowTimer);
        }
    }

    // Wait the time a busy server asked for, plus up to 2 s so that a class
    // that was turned away together does not come back together, counting
    // down in the sheet (announced once). The recording is kept and sent again.
    async function waitForBusyServer(seconds, signal, first) {
        const until = performance.now() + (seconds + Math.random() * 2) * 1000;
        setHint('rec.busyHint');
        if (first) ui.announce(t('rec.busyAnnounce'), els.status);
        for (;;) {
            const left = Math.ceil((until - performance.now()) / 1000);
            if (left <= 0) break;
            i18n.text(els.overlayText, 'rec.busyWait', { seconds: left });
            await AIPT.sleep(Math.min(1000, until - performance.now()), signal);
        }
        i18n.text(els.overlayText, 'rec.checkingShort');
        setHint('rec.checkingHint');
    }

    // ---------------------------------------------------------------- waveform
    const wave = { width: 0, height: 0, dpr: 1, bar: 4, gap: 3 };
    let sampleBuffer = null;

    function sizeCanvas() {
        const rect = els.canvas.getBoundingClientRect();
        wave.dpr = Math.min(window.devicePixelRatio || 1, 2);
        wave.width = Math.max(1, Math.round(rect.width * wave.dpr));
        wave.height = Math.max(1, Math.round(rect.height * wave.dpr));
        els.canvas.width = wave.width;
        els.canvas.height = wave.height;
    }

    function readSamples() {
        const analyser = rec.analyser;
        if (!sampleBuffer || sampleBuffer.length !== analyser.fftSize) sampleBuffer = new Float32Array(analyser.fftSize);
        analyser.getFloatTimeDomainData(sampleBuffer);
        return sampleBuffer;
    }

    // Level metering runs on a timer (not requestAnimationFrame) so silence
    // detection keeps working even if the tab is in the background.
    function sampleLevel() {
        if (rec.phase !== 'recording' || !rec.analyser) return;
        const samples = readSamples();
        let sum = 0;
        for (let i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i];
        const rms = Math.sqrt(sum / samples.length);
        if (rms > rec.maxRms) rec.maxRms = rms;
        const level = Math.min(1, Math.pow(rms * 6, 0.8));
        rec.smoothed = Math.max(level, rec.smoothed * 0.8);
        if (level > 0.06) rec.lastLoudAt = performance.now();
        rec.levels.push(rec.smoothed);
        const maxBars = Math.ceil(wave.width / ((wave.bar + wave.gap) * wave.dpr)) + 1;
        if (rec.levels.length > maxBars) rec.levels.splice(0, rec.levels.length - maxBars);
    }

    function loop() {
        if (rec.phase !== 'recording' || !rec.analyser) return;
        drawWave(false, readSamples());
        rec.raf = requestAnimationFrame(loop);
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
        const { width, height, dpr } = wave;
        ctx.clearRect(0, 0, width, height);
        const mid = height / 2;
        const primary = cssVar('--primary') || '#4f46e5';
        const muted = cssVar('--border') || '#e3e6f0';

        // centre line
        ctx.fillStyle = muted;
        ctx.fillRect(0, mid - dpr / 2, width, dpr);

        // live oscilloscope trace behind the bars
        if (samples && !frozen) {
            ctx.beginPath();
            ctx.lineWidth = 1.5 * dpr;
            ctx.strokeStyle = primary;
            ctx.globalAlpha = 0.25;
            const step = samples.length / width;
            for (let x = 0; x < width; x += 2) {
                const v = samples[Math.floor(x * step)] || 0;
                const y = mid + v * mid * 0.9;
                if (x === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
            }
            ctx.stroke();
            ctx.globalAlpha = 1;
        }

        // scrolling amplitude bars (newest on the right)
        const bar = wave.bar * dpr;
        const gap = wave.gap * dpr;
        const levels = rec.levels;
        ctx.fillStyle = primary;
        for (let i = levels.length - 1, x = width - bar - gap; i >= 0 && x > -bar; i -= 1, x -= bar + gap) {
            const h = Math.max(2 * dpr, levels[i] * (height - 16 * dpr));
            const age = (levels.length - 1 - i) / Math.max(levels.length, 1);
            ctx.globalAlpha = frozen ? 0.35 : Math.max(0.35, 1 - age * 0.8);
            roundRect(ctx, x, mid - h / 2, bar, h, bar / 2);
        }
        ctx.globalAlpha = 1;
    }

    window.addEventListener('resize', () => {
        if (sheet.isOpen) {
            sizeCanvas();
            drawWave(rec.phase !== 'recording');
        }
    });

    // ---------------------------------------------------------------- keys and buttons
    els.stop.addEventListener('click', () => {
        if (!AIPT.isDisabled(els.stop)) stopRecording();
    });
    els.retry.addEventListener('click', () => {
        const opener = sheet.opener;
        closeSheet({ restoreFocus: false });
        start(opener);
    });

    // In the sheet, Space and Enter belong to the focused button, and a key
    // held down does nothing more (its repeats are dropped). Space with focus
    // on no control (the title, the sheet, the page) stops a recording.
    document.addEventListener('keydown', (event) => {
        if (!sheet.isOpen) return;
        if (event.key !== ' ' && event.key !== 'Enter') return;
        if (event.repeat) {
            event.preventDefault();
            return;
        }
        if (event.key === ' ' && !AIPT.isControl(event.target) && rec.phase === 'recording') {
            event.preventDefault();
            stopRecording();
        }
    });

    AIPT.recorder = {
        // getText() gives the sentence to read; onResult(data, buffer, text)
        // gets the score after the sheet has closed (focus is the caller's);
        // fallbackFocus takes focus when the sheet closes and its opener is gone.
        init(given) {
            options = { ...options, ...given };
        },
        start,
        get busy() {
            return rec.phase !== 'idle';
        },
    };
})();
