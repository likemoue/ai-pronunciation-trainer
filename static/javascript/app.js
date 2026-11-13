'use strict';

(() => {
    // ---------------------------------------------------------------- config
    const LANGUAGE = 'en';
    const API = {
        sample: '/getSample',
        custom: '/getCustomSample',
        score: '/GetAccuracyFromRecordedAudio',
        tts: '/getAudioFromText',
    };
    const MAX_RECORDING_SECONDS = 30; // one Whisper window
    const SILENCE_RMS = 0.003;
    const MIN_RECORDING_MS = 600;
    const CUSTOM_MAX_CHARS = 300;
    const CUSTOM_MAX_WORDS = 60;
    // Cloudflare gives up after 125 s (error 524), so stop waiting before that.
    const SCORE_TIMEOUT_MS = 100000;
    const CATEGORY_MULTIPLIER = { 0: 1.3, 1: 1, 2: 1.3, 3: 1.6, custom: 1 };
    const CATEGORY_TEXT = ['Correct', 'Almost', 'Needs work'];

    // ---------------------------------------------------------------- dom
    const $ = (id) => document.getElementById(id);
    const els = {
        app: document.querySelector('.app'),
        statPoints: $('statPoints'),
        statSentences: $('statSentences'),
        statAverage: $('statAverage'),
        tabPractice: $('tabPractice'),
        tabCustom: $('tabCustom'),
        panePractice: $('panePractice'),
        paneCustom: $('paneCustom'),
        chips: Array.from(document.querySelectorAll('.chip')),
        btnNext: $('btnNext'),
        customText: $('customText'),
        customCounter: $('customCounter'),
        btnUseCustom: $('btnUseCustom'),
        customError: $('customError'),
        status: $('statusLine'),
        sentence: $('sentence'),
        ipaReference: $('ipaReference'),
        ipaSpokenRow: $('ipaSpokenRow'),
        ipaSpoken: $('ipaSpoken'),
        wordDetail: $('wordDetail'),
        wdWord: $('wdWord'),
        wdBadge: $('wdBadge'),
        wdRefIpa: $('wdRefIpa'),
        wdYourIpa: $('wdYourIpa'),
        wdPlayRef: $('wdPlayRef'),
        wdPlayYours: $('wdPlayYours'),
        btnListen: $('btnListen'),
        slowToggle: $('slowToggle'),
        btnRecord: $('btnRecord'),
        btnPlayback: $('btnPlayback'),
        resultBox: $('resultBox'),
        scoreRing: $('scoreRing'),
        scoreValue: $('scoreValue'),
        resultTitle: $('resultTitle'),
        resultSub: $('resultSub'),
        modal: $('recordModal'),
        recDot: $('recDot'),
        recTitle: $('recTitle'),
        recTimer: $('recTimer'),
        recSentence: $('recSentence'),
        waveCanvas: $('waveCanvas'),
        waveOverlay: $('waveOverlay'),
        waveOverlayText: $('waveOverlayText'),
        recHint: $('recHint'),
        recCancel: $('recCancel'),
        recStop: $('recStop'),
        recRetry: $('recRetry'),
        toast: $('toast'),
    };

    // ---------------------------------------------------------------- state
    const state = {
        mode: 'practice',
        category: 1,
        sentenceCategory: 1,
        text: '',
        ipa: '',
        loading: false,
        result: null,
        selectedWord: -1,
        bestForSentence: null,
        recordingBuffer: null,
        stats: { points: 0, sentences: 0, accuracySum: 0 },
    };

    let audioCtx = null;
    let feedbackSounds = null;
    let serverTts = true;
    const ttsCache = new Map();
    let activePlayback = null; // { stop(), button }

    // ---------------------------------------------------------------- utils
    const normalizeText = (text) => text
        .replace(/[‘’‛′]/g, "'")
        .replace(/[“”‟″]/g, '"')
        .replace(/[–—−]/g, ' - ')
        .replace(/…/g, '...')
        .replace(/\s+/g, ' ')
        .trim()
        .split(' ')
        .filter((token) => /[\p{L}\p{N}]/u.test(token))
        .join(' ');

    const stripPunctuation = (word) => word.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, '');

    async function postJSON(url, body, { signal } = {}) {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
            signal,
        });
        const raw = await res.text();
        let data = null;
        try {
            data = raw ? JSON.parse(raw) : null;
        } catch (_) {
            data = null;
        }
        if (!res.ok) {
            const err = new Error((data && data.error) || `Server error (${res.status})`);
            err.status = res.status;
            err.code = (data && data.code) || '';
            throw err;
        }
        return data;
    }

    function getAudioContext() {
        if (!audioCtx) {
            const Ctx = window.AudioContext || window.webkitAudioContext;
            audioCtx = new Ctx();
        }
        if (audioCtx.state === 'suspended') audioCtx.resume();
        return audioCtx;
    }

    let toastTimer = null;
    function toast(message) {
        els.toast.textContent = message;
        els.toast.hidden = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { els.toast.hidden = true; }, 3800);
    }

    function setStatus(message, isError = false) {
        els.status.textContent = message;
        els.status.classList.toggle('is-error', isError);
    }

    const formatTime = (seconds) => {
        const s = Math.floor(seconds);
        return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
    };

    // ---------------------------------------------------------------- stats
    function renderStats() {
        const { points, sentences, accuracySum } = state.stats;
        els.statPoints.textContent = Math.round(points).toLocaleString('en-US');
        els.statSentences.textContent = sentences;
        els.statAverage.textContent = sentences ? `${Math.round(accuracySum / sentences)}%` : '–';
    }

    // Each sentence counts once, with its best attempt.
    function recordAttempt(accuracy) {
        const multiplier = CATEGORY_MULTIPLIER[state.sentenceCategory] || 1;
        const best = state.bestForSentence;
        if (best === null) {
            state.stats.sentences += 1;
            state.stats.accuracySum += accuracy;
            state.stats.points += accuracy * multiplier;
            state.bestForSentence = accuracy;
        } else if (accuracy > best) {
            state.stats.accuracySum += accuracy - best;
            state.stats.points += (accuracy - best) * multiplier;
            state.bestForSentence = accuracy;
        }
        renderStats();
    }

    // ---------------------------------------------------------------- sentence
    function updateControls() {
        const hasText = Boolean(state.text) && !state.loading;
        els.btnListen.disabled = !hasText;
        els.btnRecord.disabled = !hasText;
        els.btnPlayback.disabled = !state.recordingBuffer || state.loading;
        els.btnNext.disabled = state.loading;
        els.btnUseCustom.disabled = state.loading || !normalizeText(els.customText.value);
    }

    function setLoading(loading) {
        state.loading = loading;
        els.sentence.classList.toggle('is-loading', loading);
        updateControls();
    }

    function setSentence(text, ipa, category) {
        stopPlayback();
        state.text = normalizeText(text);
        state.ipa = ipa || '';
        state.sentenceCategory = category;
        state.result = null;
        state.selectedWord = -1;
        state.bestForSentence = null;
        state.recordingBuffer = null;

        els.sentence.textContent = state.text;
        els.ipaReference.textContent = state.ipa ? `/ ${state.ipa} /` : '';
        els.ipaSpokenRow.hidden = true;
        els.wordDetail.hidden = true;
        els.resultBox.hidden = true;
        updateControls();
    }

    async function loadPracticeSentence() {
        if (state.loading) return;
        setLoading(true);
        setStatus('Loading a new sentence…');
        try {
            const data = await postJSON(API.sample, { category: String(state.category), language: LANGUAGE });
            setSentence(data.real_transcript[0], data.ipa_transcript, state.category);
            setStatus('Listen first, then tap the microphone and read the sentence aloud.');
        } catch (err) {
            console.error(err);
            setStatus('Could not load a sentence. Check your connection and try again.', true);
        } finally {
            setLoading(false);
        }
    }

    async function useCustomText() {
        const text = normalizeText(els.customText.value);
        els.customError.hidden = true;
        if (!text) {
            showCustomError('Please type at least one English word.');
            return;
        }
        if (text.length > CUSTOM_MAX_CHARS) {
            showCustomError(`Please keep it under ${CUSTOM_MAX_CHARS} characters.`);
            return;
        }
        if (text.split(' ').length > CUSTOM_MAX_WORDS) {
            showCustomError(`Please keep it under ${CUSTOM_MAX_WORDS} words.`);
            return;
        }
        if (state.loading) return;
        setLoading(true);
        setStatus('Preparing your text…');
        try {
            const data = await postJSON(API.custom, { text, language: LANGUAGE });
            setSentence(data.real_transcript[0], data.ipa_transcript, 'custom');
            setStatus('Your text is ready. Listen first, then tap the microphone and read it aloud.');
            els.sentence.scrollIntoView({ behavior: 'smooth', block: 'center' });
        } catch (err) {
            console.error(err);
            showCustomError(err.status === 400 ? err.message : 'Could not prepare this text. Please try again.');
            setStatus('');
        } finally {
            setLoading(false);
        }
    }

    function showCustomError(message) {
        els.customError.textContent = message;
        els.customError.hidden = false;
    }

    // ---------------------------------------------------------------- results
    function tierFor(accuracy) {
        if (accuracy >= 80) return { cls: '', title: 'Excellent!', sub: 'Native-like pronunciation. Try a harder sentence.' };
        if (accuracy >= 60) return { cls: 'tier-ok', title: 'Good job', sub: 'Check the orange and red words and try again.' };
        return { cls: 'tier-bad', title: 'Keep practising', sub: 'Listen to the red words, then record again.' };
    }

    function renderResult(data) {
        const accuracy = Math.max(0, Math.min(100, parseInt(data.pronunciation_accuracy, 10) || 0));
        const words = state.text.split(' ');
        const letterFlags = (data.is_letter_correct_all_words || '').trim().split(' ');
        const realIpa = (data.real_transcripts_ipa || '').split(' ');
        const spokenIpa = (data.matched_transcripts_ipa || '').split(' ');
        const categories = (data.pair_accuracy_category || '').split(' ');
        const startTimes = (data.start_time || '').split(' ').map(parseFloat);
        const endTimes = (data.end_time || '').split(' ').map(parseFloat);

        state.result = { accuracy, words, realIpa, spokenIpa, categories, startTimes, endTimes };
        state.selectedWord = -1;

        const fragment = document.createDocumentFragment();
        words.forEach((word, index) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `word cat-${categories[index] || '2'}`;
            button.dataset.index = String(index);
            button.setAttribute('aria-label', `${word}: ${CATEGORY_TEXT[categories[index]] || 'Needs work'}. Show details`);
            const flags = letterFlags[index] || '';
            for (let i = 0; i < word.length; i += 1) {
                const span = document.createElement('span');
                span.textContent = word[i];
                span.className = flags[i] === '1' ? 'l-good' : 'l-bad';
                button.appendChild(span);
            }
            fragment.appendChild(button);
            if (index < words.length - 1) fragment.appendChild(document.createTextNode(' '));
        });
        els.sentence.replaceChildren(fragment);

        els.ipaReference.textContent = data.real_transcripts_ipa ? `/ ${data.real_transcripts_ipa} /` : els.ipaReference.textContent;
        els.ipaSpoken.textContent = data.ipa_transcript ? `/ ${data.ipa_transcript} /` : '(no speech recognised)';
        els.ipaSpokenRow.hidden = false;
        els.wordDetail.hidden = true;

        const tier = tierFor(accuracy);
        els.scoreRing.classList.remove('tier-ok', 'tier-bad');
        if (tier.cls) els.scoreRing.classList.add(tier.cls);
        els.resultTitle.textContent = tier.title;
        const heard = (data.real_transcript || '').trim();
        els.resultSub.textContent = heard ? `${tier.sub} We heard: “${heard}”` : tier.sub;
        els.resultBox.hidden = false;
        els.scoreRing.style.setProperty('--value', '0');
        requestAnimationFrame(() => requestAnimationFrame(() => {
            els.scoreRing.style.setProperty('--value', String(accuracy));
        }));
        animateNumber(els.scoreValue, accuracy);

        recordAttempt(accuracy);
        setStatus('Tap any word to compare your sound with the correct one.');
        playFeedbackSound(accuracy);
    }

    function animateNumber(el, target) {
        const start = performance.now();
        const duration = 800;
        const step = (now) => {
            const t = Math.min(1, (now - start) / duration);
            el.textContent = String(Math.round(target * (1 - Math.pow(1 - t, 3))));
            if (t < 1) requestAnimationFrame(step);
        };
        requestAnimationFrame(step);
    }

    function selectWord(index) {
        const r = state.result;
        if (!r) return;
        state.selectedWord = index;
        els.sentence.querySelectorAll('.word').forEach((w) => {
            w.classList.toggle('is-selected', Number(w.dataset.index) === index);
        });
        const category = r.categories[index] || '2';
        const spoken = r.spokenIpa[index];
        const heard = spoken && spoken !== '-';
        els.wdWord.textContent = r.words[index];
        els.wdBadge.textContent = CATEGORY_TEXT[category] || 'Needs work';
        els.wdBadge.className = `badge cat-${category}`;
        els.wdRefIpa.textContent = r.realIpa[index] ? `/${r.realIpa[index]}/` : '—';
        els.wdYourIpa.textContent = heard ? `/${spoken}/` : 'not heard';
        const hasTiming = heard && Number.isFinite(r.startTimes[index]) && Number.isFinite(r.endTimes[index]);
        els.wdPlayYours.disabled = !(hasTiming && state.recordingBuffer);
        els.wordDetail.hidden = false;
    }

    // ---------------------------------------------------------------- playback
    function stopPlayback() {
        if (activePlayback) {
            const current = activePlayback;
            activePlayback = null;
            try { current.stop(); } catch (_) { /* already stopped */ }
            if (current.button) current.button.classList.remove('is-playing');
        }
        if (window.speechSynthesis) window.speechSynthesis.cancel();
    }

    function trackPlayback(stop, button) {
        stopPlayback();
        activePlayback = { stop, button };
        if (button) button.classList.add('is-playing');
        return () => {
            if (activePlayback && activePlayback.stop === stop) {
                activePlayback = null;
                if (button) button.classList.remove('is-playing');
            }
        };
    }

    async function speak(text, button) {
        const clean = text.trim();
        if (!clean) return;
        const slow = els.slowToggle.checked;
        stopPlayback();

        if (serverTts) {
            try {
                let url = ttsCache.get(clean);
                if (!url) {
                    if (button) button.classList.add('is-playing');
                    const data = await postJSON(API.tts, { value: clean, language: LANGUAGE });
                    const bytes = Uint8Array.from(atob(data.wavBase64), (c) => c.charCodeAt(0));
                    url = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }));
                    ttsCache.set(clean, url);
                    if (ttsCache.size > 40) {
                        const [oldKey, oldUrl] = ttsCache.entries().next().value;
                        URL.revokeObjectURL(oldUrl);
                        ttsCache.delete(oldKey);
                    }
                }
                const audio = new Audio(url);
                audio.playbackRate = slow ? 0.75 : 1;
                if ('preservesPitch' in audio) audio.preservesPitch = true;
                const done = trackPlayback(() => audio.pause(), button);
                audio.addEventListener('ended', done);
                audio.addEventListener('pause', done);
                await audio.play();
                return;
            } catch (err) {
                if (button) button.classList.remove('is-playing');
                // Only a permanent "no server voice" switches to the browser voice for
                // good; a temporary failure falls back for this text only.
                if (err.code === 'tts_unavailable' || err.status === 404) serverTts = false;
                console.warn('Server TTS failed, using the browser voice.', err);
            }
        }
        speakWithBrowser(clean, slow, button);
    }

    let browserVoice = null;
    function pickBrowserVoice() {
        if (!window.speechSynthesis) return null;
        const voices = window.speechSynthesis.getVoices();
        const preferred = ['Google US English', 'Microsoft Aria Online (Natural) - English (United States)',
            'Microsoft Jenny Online (Natural) - English (United States)', 'Samantha', 'Alex'];
        for (const name of preferred) {
            const v = voices.find((voice) => voice.name === name);
            if (v) return v;
        }
        return voices.find((v) => v.lang === 'en-US') || voices.find((v) => v.lang && v.lang.startsWith('en')) || null;
    }
    if (window.speechSynthesis) {
        window.speechSynthesis.onvoiceschanged = () => { browserVoice = pickBrowserVoice(); };
    }

    function speakWithBrowser(text, slow, button) {
        if (!window.speechSynthesis) {
            toast('This browser cannot play the sample voice.');
            return;
        }
        browserVoice = browserVoice || pickBrowserVoice();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'en-US';
        if (browserVoice) utterance.voice = browserVoice;
        utterance.rate = slow ? 0.65 : 0.9;
        const done = trackPlayback(() => window.speechSynthesis.cancel(), button);
        utterance.onend = done;
        utterance.onerror = done;
        window.speechSynthesis.speak(utterance);
    }

    function playBuffer(buffer, button, offset = 0, duration = undefined) {
        const ctx = getAudioContext();
        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.connect(ctx.destination);
        const done = trackPlayback(() => source.stop(), button);
        source.onended = done;
        source.start(0, Math.max(0, offset), duration);
    }

    function playRecording() {
        if (!state.recordingBuffer) return;
        playBuffer(state.recordingBuffer, els.btnPlayback);
    }

    function playRecordedWord(index) {
        const r = state.result;
        if (!r || !state.recordingBuffer) return;
        const start = r.startTimes[index];
        const end = r.endTimes[index];
        if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;
        playBuffer(state.recordingBuffer, els.wdPlayYours, start, end - start);
    }

    async function loadFeedbackSounds() {
        if (feedbackSounds) return feedbackSounds;
        const ctx = getAudioContext();
        const load = async (name) => {
            const res = await fetch(`/static/${name}`);
            return ctx.decodeAudioData(await res.arrayBuffer());
        };
        try {
            const [good, okay, bad] = await Promise.all([load('ASR_good.wav'), load('ASR_okay.wav'), load('ASR_bad.wav')]);
            feedbackSounds = { good, okay, bad };
        } catch (err) {
            console.warn('Could not load feedback sounds', err);
            feedbackSounds = {};
        }
        return feedbackSounds;
    }

    async function playFeedbackSound(accuracy) {
        const sounds = await loadFeedbackSounds();
        const buffer = accuracy >= 70 ? sounds.good : accuracy >= 30 ? sounds.okay : sounds.bad;
        if (!buffer) return;
        const ctx = getAudioContext();
        const source = ctx.createBufferSource();
        const gain = ctx.createGain();
        gain.gain.value = 0.5;
        source.buffer = buffer;
        source.connect(gain).connect(ctx.destination);
        source.start();
    }

    // ---------------------------------------------------------------- recorder
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
        returnFocus: null,
    };

    function setModalPhase(phase, message) {
        rec.phase = phase;
        const recording = phase === 'recording';
        els.recDot.classList.toggle('is-live', recording);
        els.recStop.hidden = phase === 'error' || phase === 'processing';
        els.recStop.disabled = !recording;
        els.recRetry.hidden = phase !== 'error';
        els.recCancel.textContent = phase === 'error' ? 'Close' : 'Cancel';
        els.waveOverlay.hidden = phase === 'recording' || phase === 'idle';
        els.waveOverlay.classList.toggle('is-error', phase === 'error');
        els.recHint.classList.remove('is-warning');
        const spinner = els.waveOverlay.querySelector('.spinner');
        spinner.hidden = phase === 'error';

        switch (phase) {
            case 'preparing':
                els.recTitle.textContent = 'Getting the microphone ready…';
                els.waveOverlayText.textContent = 'Allow microphone access if your browser asks.';
                els.recHint.textContent = '';
                break;
            case 'recording':
                els.recTitle.textContent = 'Recording';
                els.recHint.innerHTML = 'Speak clearly at a normal pace, then tap <strong>Stop</strong> when you finish<span class="desk-only"> (or press <kbd>Space</kbd>)</span>.';
                break;
            case 'processing':
                els.recTitle.textContent = 'Checking your pronunciation';
                els.waveOverlayText.textContent = 'Analysing your pronunciation…';
                els.recHint.textContent = 'This usually takes a few seconds.';
                break;
            case 'error':
                els.recTitle.textContent = 'Something went wrong';
                els.waveOverlayText.textContent = message || 'Please try again.';
                els.recHint.textContent = '';
                break;
            default:
                break;
        }
    }

    function openModal() {
        rec.returnFocus = document.activeElement;
        els.recSentence.textContent = state.text;
        els.recTimer.textContent = '0:00';
        rec.levels = [];
        els.modal.hidden = false;
        els.app.inert = true;
        document.body.classList.add('modal-open');
        sizeCanvas();
        drawWave();
    }

    function closeModal() {
        cleanupRecorder();
        if (rec.abort) {
            rec.abort.abort();
            rec.abort = null;
        }
        clearTimeout(rec.slowTimer);
        rec.phase = 'idle';
        els.modal.hidden = true;
        els.app.inert = false;
        document.body.classList.remove('modal-open');
        const target = rec.returnFocus && document.contains(rec.returnFocus) ? rec.returnFocus : els.btnRecord;
        if (target && typeof target.focus === 'function') target.focus();
    }

    function cleanupRecorder() {
        cancelAnimationFrame(rec.raf);
        clearInterval(rec.timer);
        clearInterval(rec.sampler);
        if (rec.source) {
            try { rec.source.disconnect(); } catch (_) { /* noop */ }
        }
        rec.source = null;
        rec.analyser = null;
        if (rec.stream) rec.stream.getTracks().forEach((t) => t.stop());
        rec.stream = null;
    }

    function pickMimeType() {
        if (!window.MediaRecorder || !MediaRecorder.isTypeSupported) return '';
        const candidates = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/mp4'];
        return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || '';
    }

    async function startRecording() {
        if (!state.text || state.loading || rec.phase !== 'idle') return;
        stopPlayback();

        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) {
            toast(window.isSecureContext
                ? 'This browser cannot record audio. Please use Chrome, Edge, Firefox or Safari.'
                : 'Recording needs a secure (https) connection.');
            return;
        }

        openModal();
        setModalPhase('preparing');
        rec.cancelled = false;
        rec.attempt += 1;
        const attempt = rec.attempt;
        const ctx = getAudioContext();

        let stream;
        try {
            stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
        } catch (err) {
            console.error(err);
            const denied = err && (err.name === 'NotAllowedError' || err.name === 'SecurityError');
            setModalPhase('error', denied
                ? 'Microphone access is blocked. Allow it from the icon in the address bar, then try again.'
                : 'No microphone was found. Connect one and try again.');
            return;
        }
        if (rec.phase !== 'preparing' || attempt !== rec.attempt) {
            // Popup was closed while waiting for permission.
            stream.getTracks().forEach((t) => t.stop());
            return;
        }

        rec.stream = stream;
        rec.source = ctx.createMediaStreamSource(stream);
        rec.analyser = ctx.createAnalyser();
        rec.analyser.fftSize = 2048;
        rec.source.connect(rec.analyser);

        const mimeType = pickMimeType();
        try {
            rec.recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
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
        setModalPhase('recording');
        els.recStop.focus();

        rec.timer = setInterval(() => {
            const elapsed = (performance.now() - rec.startedAt) / 1000;
            els.recTimer.textContent = formatTime(elapsed);
            const remaining = MAX_RECORDING_SECONDS - elapsed;
            if (remaining <= 0) {
                stopRecording();
            } else if (remaining <= 5) {
                els.recHint.textContent = `Stopping automatically in ${Math.ceil(remaining)}s…`;
                els.recHint.classList.add('is-warning');
            } else if (performance.now() - rec.lastLoudAt > 3500) {
                els.recHint.textContent = "We can't hear you – speak a little louder or move closer to the microphone.";
                els.recHint.classList.add('is-warning');
            } else if (els.recHint.classList.contains('is-warning')) {
                setModalPhase('recording');
            }
        }, 250);

        rec.sampler = setInterval(sampleLevel, 45);
        loop();
    }

    function stopRecording() {
        if (rec.phase !== 'recording' || !rec.recorder) return;
        clearInterval(rec.timer);
        clearInterval(rec.sampler);
        setModalPhase('processing');
        if (rec.recorder.state !== 'inactive') rec.recorder.stop();
    }

    function cancelRecording() {
        rec.cancelled = true;
        if (rec.recorder && rec.recorder.state !== 'inactive') rec.recorder.stop();
        closeModal();
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
            setModalPhase('error', 'That recording was too short. Tap “Try again” and read the whole sentence.');
            return;
        }
        if (rec.maxRms < SILENCE_RMS) {
            setModalPhase('error', "We couldn't hear anything. Check that the right microphone is selected and not muted.");
            return;
        }

        const abort = new AbortController();
        rec.abort = abort;
        const timeout = setTimeout(() => abort.abort(), SCORE_TIMEOUT_MS);
        rec.slowTimer = setTimeout(() => {
            if (rec.phase === 'processing') {
                els.recHint.textContent = 'Still working – the first check after a server restart can take up to a minute.';
            }
        }, 8000);

        try {
            const [base64Audio, buffer] = await Promise.all([
                blobToDataUrl(blob),
                blob.arrayBuffer().then((ab) => getAudioContext().decodeAudioData(ab)).catch(() => null),
            ]);
            const data = await postJSON(API.score, {
                title: state.text,
                base64Audio,
                language: LANGUAGE,
            }, { signal: abort.signal });

            if (!data || data.pronunciation_accuracy === undefined) {
                throw Object.assign(new Error('empty'), { status: 422 });
            }
            state.recordingBuffer = buffer;
            closeModal();
            renderResult(data);
            updateControls();
        } catch (err) {
            if (err.name === 'AbortError' && rec.phase === 'idle') return; // closed by user
            console.error(err);
            let message = 'Could not check your recording. Please try again.';
            if (err.name === 'AbortError') message = 'The server took too long to answer. Please try again.';
            else if (err.status === 422) message = "We couldn't recognise any speech. Speak a little louder and try again.";
            else if (err.status === 413) message = 'That recording is too long. Please keep it under 30 seconds.';
            else if (err.status === 429 || err.status === 503) message = 'The server is busy right now. Please try again in a moment.';
            else if (err.status === 502 || err.status === 504 || err.status === 524) message = 'The server took too long to answer. Please try again.';
            else if (err.status === 400 && err.message) message = err.message;
            setModalPhase('error', message);
        } finally {
            clearTimeout(timeout);
            clearTimeout(rec.slowTimer);
            if (rec.abort === abort) rec.abort = null;
        }
    }

    const blobToDataUrl = (blob) => new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(blob);
    });

    // ---------------------------------------------------------------- waveform
    const wave = { width: 0, height: 0, dpr: 1, bar: 4, gap: 3 };
    let sampleBuffer = null;

    function sizeCanvas() {
        const rect = els.waveCanvas.getBoundingClientRect();
        wave.dpr = Math.min(window.devicePixelRatio || 1, 2);
        wave.width = Math.max(1, Math.round(rect.width * wave.dpr));
        wave.height = Math.max(1, Math.round(rect.height * wave.dpr));
        els.waveCanvas.width = wave.width;
        els.waveCanvas.height = wave.height;
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

    function drawWave(frozen = false, samples = null) {
        const ctx = els.waveCanvas.getContext('2d');
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
                if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
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

    window.addEventListener('resize', () => {
        if (!els.modal.hidden) {
            sizeCanvas();
            drawWave(rec.phase !== 'recording');
        }
    });

    // ---------------------------------------------------------------- tabs
    function selectTab(mode) {
        state.mode = mode;
        const practice = mode === 'practice';
        els.tabPractice.classList.toggle('is-active', practice);
        els.tabCustom.classList.toggle('is-active', !practice);
        els.tabPractice.setAttribute('aria-selected', String(practice));
        els.tabCustom.setAttribute('aria-selected', String(!practice));
        els.tabPractice.tabIndex = practice ? 0 : -1;
        els.tabCustom.tabIndex = practice ? -1 : 0;
        els.panePractice.hidden = !practice;
        els.paneCustom.hidden = practice;
        if (!practice) els.customText.focus();
    }

    function selectCategory(category) {
        state.category = category;
        els.chips.forEach((chip) => {
            const active = Number(chip.dataset.category) === category;
            chip.classList.toggle('is-active', active);
            chip.setAttribute('aria-checked', String(active));
        });
        loadPracticeSentence();
    }

    // ---------------------------------------------------------------- events
    els.tabPractice.addEventListener('click', () => selectTab('practice'));
    els.tabCustom.addEventListener('click', () => selectTab('custom'));
    [els.tabPractice, els.tabCustom].forEach((tab) => tab.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
            const next = tab === els.tabPractice ? els.tabCustom : els.tabPractice;
            next.focus();
            next.click();
        }
    }));

    els.chips.forEach((chip) => chip.addEventListener('click', () => selectCategory(Number(chip.dataset.category))));
    els.btnNext.addEventListener('click', loadPracticeSentence);

    els.customText.addEventListener('input', () => {
        const length = els.customText.value.length;
        els.customCounter.textContent = `${length} / ${CUSTOM_MAX_CHARS}`;
        els.customError.hidden = true;
        updateControls();
    });
    els.customText.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            useCustomText();
        }
    });
    els.btnUseCustom.addEventListener('click', useCustomText);

    els.btnListen.addEventListener('click', () => speak(state.text, els.btnListen));
    els.btnRecord.addEventListener('click', startRecording);
    els.btnPlayback.addEventListener('click', playRecording);

    els.sentence.addEventListener('click', (e) => {
        const word = e.target.closest('.word');
        if (word) selectWord(Number(word.dataset.index));
    });
    els.wdPlayRef.addEventListener('click', () => {
        const r = state.result;
        if (r && state.selectedWord >= 0) speak(stripPunctuation(r.words[state.selectedWord]) || r.words[state.selectedWord], els.wdPlayRef);
    });
    els.wdPlayYours.addEventListener('click', () => {
        if (state.selectedWord >= 0) playRecordedWord(state.selectedWord);
    });

    els.recStop.addEventListener('click', stopRecording);
    els.recRetry.addEventListener('click', () => {
        closeModal();
        startRecording();
    });
    els.modal.querySelectorAll('[data-close]').forEach((el) => el.addEventListener('click', cancelRecording));

    document.addEventListener('keydown', (e) => {
        if (!els.modal.hidden) {
            if (e.key === 'Escape') {
                e.preventDefault();
                cancelRecording();
            } else if ((e.key === ' ' || e.key === 'Enter') && rec.phase === 'recording') {
                e.preventDefault();
                stopRecording();
            }
            return;
        }
        if (e.key !== ' ' || e.repeat) return;
        const target = e.target;
        const tag = target && target.tagName;
        if (target && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON', 'A'].includes(tag))) return;
        e.preventDefault();
        startRecording();
    });

    // ---------------------------------------------------------------- start
    renderStats();
    loadPracticeSentence();
})();
