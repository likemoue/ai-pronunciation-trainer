'use strict';

// Sound: the AudioContext, the reference voice, playing back parts of a
// recording, and the result chime.
//
// The reference voice is the bank sentence's MP3 (cached by browsers and
// Cloudflare), the server's voice for any other text, or, when the server has
// none or is busy, a voice of the browser's own that runs on the device
// (never one that sends the text to a speech service). One sound plays at a
// time; each owner (the control that asked) hears 'loading', 'playing' and
// 'idle' through onChange. Every new sound or stop() makes the older ones
// stale (a playback token), so a voice still loading never starts playing
// later, for instance into a recording. While the recording sheet is open the
// sound is held (hold(true)): what plays stops, and nothing new starts.
(() => {
    const VOICE_TIMEOUT_MS = 15000;
    const SLOW_RATE = 0.75;

    let context = null;
    let serverVoice = true; // false once the server says it has none
    const cache = new Map(); // text -> object URL of its audio
    let current = null; // { owner, stop(), controller }
    let token = 0;
    let held = false;
    const changeListeners = [];
    const noVoiceListeners = [];

    function getContext() {
        if (!context) {
            const Context = window.AudioContext || window.webkitAudioContext;
            context = new Context();
        }
        if (context.state === 'suspended') context.resume();
        return context;
    }

    function emit(owner, state) {
        changeListeners.forEach((fn) => fn(owner, state));
    }

    // Stop whatever plays or loads; its owner hears 'idle'.
    function stop() {
        token += 1;
        if (current) {
            const playing = current;
            current = null;
            if (playing.controller) playing.controller.abort();
            try {
                if (playing.stop) playing.stop();
            } catch (_) {
                // Already stopped.
            }
            emit(playing.owner, 'idle');
        }
        if (window.speechSynthesis) {
            try {
                window.speechSynthesis.cancel();
            } catch (_) {
                // Nothing to cancel.
            }
        }
    }

    // Hold every sound (on: stop what plays or loads, start nothing new) or
    // let them play again.
    function hold(on) {
        held = Boolean(on);
        if (held) stop();
    }

    // The end of the sound `mine` (if it is still the current one).
    function finish(mine) {
        if (current && current.token === mine) {
            const done = current;
            current = null;
            emit(done.owner, 'idle');
        }
    }

    function remember(text, url) {
        cache.set(text, url);
        if (cache.size > 40) {
            const [oldText, oldUrl] = cache.entries().next().value;
            URL.revokeObjectURL(oldUrl);
            cache.delete(oldText);
        }
    }

    // The server's audio for text: the bank sentence's MP3 (bankUrl), or the
    // voice reading text on request. An object URL, kept for the next time.
    async function serverAudio(text, bankUrl, signal) {
        if (cache.has(text)) return cache.get(text);
        let blob = null;
        if (bankUrl) {
            try {
                blob = await AIPT.fetchBlob(bankUrl, { signal, timeout: VOICE_TIMEOUT_MS });
            } catch (err) {
                if (err.name === 'AbortError') throw err;
                console.warn('The sentence\'s recording did not come; asking the voice instead.', err);
            }
        }
        if (!blob) {
            const data = await AIPT.postJSON(AIPT.API.tts, { value: text, language: AIPT.PRACTICE_LANGUAGE },
                { signal, timeout: VOICE_TIMEOUT_MS });
            const bytes = Uint8Array.from(atob(data.wavBase64), (c) => c.charCodeAt(0));
            blob = new Blob([bytes], { type: 'audio/wav' });
        }
        const url = URL.createObjectURL(blob);
        remember(text, url);
        return url;
    }

    function playUrl(url, slow, owner, mine) {
        const audio = new Audio(url);
        audio.playbackRate = slow ? SLOW_RATE : 1;
        if ('preservesPitch' in audio) audio.preservesPitch = true;
        current = { owner, token: mine, stop: () => audio.pause() };
        audio.addEventListener('ended', () => finish(mine));
        audio.addEventListener('pause', () => finish(mine));
        return audio.play().then(() => {
            if (mine === token) emit(owner, 'playing');
            else audio.pause();
        });
    }

    // A voice of the browser's own that runs on this device (localService):
    // a network voice ("Google US English", the "Online (Natural)" ones)
    // would send the text to a speech service.
    function pickLocalVoice() {
        const voices = window.speechSynthesis.getVoices()
            .filter((voice) => voice.localService && /^en([-_]|$)/i.test(voice.lang || ''));
        const preferred = ['Samantha', 'Alex', 'Microsoft Zira - English (United States)',
            'Microsoft David - English (United States)'];
        for (const name of preferred) {
            const voice = voices.find((candidate) => candidate.name === name);
            if (voice) return voice;
        }
        return voices.find((voice) => /^en[-_]US$/i.test(voice.lang)) || voices[0] || null;
    }

    // Browsers fill the voice list a moment after the page loads.
    function localVoice() {
        const synth = window.speechSynthesis;
        if (!synth || !window.SpeechSynthesisUtterance) return Promise.resolve(null);
        if (synth.getVoices().length) return Promise.resolve(pickLocalVoice());
        return new Promise((resolve) => {
            const done = () => resolve(pickLocalVoice());
            const timer = setTimeout(done, 1000);
            if (typeof synth.addEventListener === 'function') {
                synth.addEventListener('voiceschanged', () => {
                    clearTimeout(timer);
                    done();
                }, { once: true });
            }
        });
    }

    async function speakLocally(text, slow, owner, mine) {
        const voice = await localVoice();
        if (mine !== token || !voice) return false;
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.voice = voice;
        utterance.lang = voice.lang || 'en-US';
        utterance.rate = slow ? 0.65 : 0.9;
        current = { owner, token: mine, stop: () => window.speechSynthesis.cancel() };
        utterance.onstart = () => {
            if (mine === token) emit(owner, 'playing');
        };
        utterance.onend = () => finish(mine);
        utterance.onerror = () => finish(mine);
        window.speechSynthesis.speak(utterance);
        return true;
    }

    // The reference voice reads text: speak(text, { owner, slow, bankUrl }).
    // Resolves true when a voice plays, false when it was stopped or no voice
    // could read it (then onNoVoice listeners hear of it).
    async function speak(text, { owner = '', slow = false, bankUrl = '' } = {}) {
        const clean = String(text || '').trim();
        if (!clean || held) return false;
        stop();
        const mine = token;
        const controller = new AbortController();
        current = { owner, token: mine, controller, stop: null };
        emit(owner, 'loading');

        if (serverVoice) {
            try {
                const url = await serverAudio(clean, bankUrl, controller.signal);
                if (mine !== token) return false;
                await playUrl(url, slow, owner, mine);
                return mine === token;
            } catch (err) {
                if (mine !== token || err.name === 'AbortError') return false;
                // Only "this server has no voice" lasts; anything else (busy,
                // slow, failed, a refused play()) falls back for this text only.
                if (err.code === 'tts_unavailable' || err.status === 404) serverVoice = false;
                console.warn('The server\'s voice could not read this; trying the browser\'s own.', err);
            }
        }

        const played = await speakLocally(clean, slow, owner, mine);
        if (!played && mine === token) {
            finish(mine);
            noVoiceListeners.forEach((fn) => fn());
        }
        return played;
    }

    // Play part of a recording: playBuffer(buffer, { owner, offset, duration }).
    function playBuffer(buffer, { owner = '', offset = 0, duration } = {}) {
        if (held) return;
        stop();
        const mine = token;
        const ctx = getContext();
        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.connect(ctx.destination);
        current = { owner, token: mine, stop: () => source.stop() };
        source.onended = () => finish(mine);
        emit(owner, 'playing');
        source.start(0, Math.max(0, offset), duration);
    }

    // An AudioBuffer of a recording, or null when the browser cannot read it.
    function decode(arrayBuffer) {
        try {
            return getContext().decodeAudioData(arrayBuffer).catch(() => null);
        } catch (_) {
            return Promise.resolve(null);
        }
    }

    // The result chime is synthesised, so the page downloads no sound file:
    // [frequency in Hz, start in s, length in s] for each note.
    const FEEDBACK_NOTES = {
        good: [[784, 0, 0.14], [1047, 0.12, 0.28]], // G5 then C6, rising
        okay: [[659, 0, 0.24]], // E5
        bad: [[392, 0, 0.16], [330, 0.14, 0.3]], // G4 then E4, falling
    };

    function chime(accuracy) {
        if (held) return;
        const notes = FEEDBACK_NOTES[accuracy >= 70 ? 'good' : accuracy >= 30 ? 'okay' : 'bad'];
        let ctx;
        try {
            ctx = getContext();
        } catch (err) {
            console.warn('No audio for the feedback sound', err);
            return;
        }
        const now = ctx.currentTime + 0.02;
        notes.forEach(([frequency, start, length]) => {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine';
            osc.frequency.value = frequency;
            // A soft bell: a quick rise, then an exponential fade.
            gain.gain.setValueAtTime(0.0001, now + start);
            gain.gain.exponentialRampToValueAtTime(0.18, now + start + 0.015);
            gain.gain.exponentialRampToValueAtTime(0.0001, now + start + length);
            osc.connect(gain).connect(ctx.destination);
            osc.start(now + start);
            osc.stop(now + start + length + 0.02);
        });
    }

    AIPT.audio = {
        SLOW_RATE,
        context: getContext,
        speak,
        stop,
        hold,
        playBuffer,
        decode,
        chime,
        // The owner of what plays or loads now ('' when nothing does).
        get owner() {
            return current ? current.owner : '';
        },
        get held() {
            return held;
        },
        onChange(fn) {
            changeListeners.push(fn);
        },
        onNoVoice(fn) {
            noVoiceListeners.push(fn);
        },
    };
})();
