'use strict';

// The result of a recording, kept working in its new place: the result card
// under the sentence on phones, in the right column from 1024 px. Its
// thresholds and parts are today's; a later step of phase 4 rebuilds the card
// (design/wireframes/03-result-card.html).
(() => {
    const { $, el, i18n, ui } = AIPT;
    const { t } = i18n;

    const STATUS_KEYS = ['status.correct', 'status.almost', 'status.needsWork'];
    const MARKS = ['✓', '~', '✗'];

    const els = {
        app: $('app'),
        sentence: $('sentence'),
        card: $('resultCard'),
        ring: $('scoreRing'),
        score: $('scoreValue'),
        title: $('resultTitle'),
        meaning: $('resultMeaning'),
        heard: $('resultHeard'),
        detail: $('wordDetail'),
        word: $('wdWord'),
        badge: $('wdBadge'),
        refIpa: $('wdRefIpa'),
        heardIpa: $('wdHeardIpa'),
        playRef: $('wdPlayRef'),
        playHeard: $('wdPlayHeard'),
        playback: $('btnPlayback'),
        retry: $('btnResultRetry'),
        next: $('btnResultNext'),
    };

    let result = null;
    let selected = -1;
    let recording = null; // the AudioBuffer of the take, for My recording and Replay
    let countUp = 0;

    const category = (index) => {
        const value = result.categories[index];
        return value === '0' || value === '1' || value === '2' ? Number(value) : 2;
    };
    const status = (index) => t(STATUS_KEYS[category(index)]);

    function tierOf(accuracy) {
        if (accuracy >= 80) return { ring: '', title: 'result.title.excellent' };
        if (accuracy >= 60) return { ring: 'tier-ok', title: 'result.title.good' };
        return { ring: 'tier-bad', title: 'result.title.keep' };
    }

    // The score counting up (800 ms), or at once under reduced motion.
    function showScore(target) {
        cancelAnimationFrame(countUp);
        if (AIPT.reducedMotion()) {
            els.score.textContent = String(target);
            return;
        }
        const start = performance.now();
        const step = (now) => {
            const progress = Math.min(1, (now - start) / 800);
            els.score.textContent = String(Math.round(target * (1 - Math.pow(1 - progress, 3))));
            if (progress < 1) countUp = requestAnimationFrame(step);
        };
        countUp = requestAnimationFrame(step);
    }

    function wordLabel(button) {
        const index = Number(button.dataset.index);
        button.setAttribute('aria-label', t('word.details', { word: result.words[index], status: status(index) }));
    }

    function renderWords(letterFlags) {
        const fragment = document.createDocumentFragment();
        result.words.forEach((word, index) => {
            const button = el('button', {
                className: `word cat-${category(index)}`,
                attrs: { type: 'button', 'data-index': String(index) },
            });
            const flags = letterFlags[index] || '';
            for (let i = 0; i < word.length; i += 1) {
                button.appendChild(el('span', { className: flags[i] === '1' ? 'l-good' : 'l-bad', text: word[i] }));
            }
            wordLabel(button);
            fragment.appendChild(button);
            if (index < result.words.length - 1) fragment.appendChild(document.createTextNode(' '));
        });
        els.sentence.replaceChildren(fragment);
        els.sentence.classList.add('has-result');
    }

    // The heard transcript is English: "Heard: “...”" with the quote in lang="en".
    function renderHeard(heard) {
        if (!heard) {
            i18n.text(els.heard, 'result.nothingHeard');
            return;
        }
        els.heard.removeAttribute('data-i18n');
        els.heard.replaceChildren(i18n.rich('result.heard', {
            text: () => el('span', { text: `“${heard}”`, attrs: { lang: 'en' } }),
        }));
    }

    // data: the answer of /GetAccuracyFromRecordedAudio; text: the sentence
    // that was scored; buffer: the take, decoded (or null).
    function render(data, { text, buffer }) {
        const accuracy = Math.max(0, Math.min(100, parseInt(data.pronunciation_accuracy, 10) || 0));
        const split = (value) => String(value || '').trim().split(' ');
        result = {
            accuracy,
            words: text.split(' '),
            realIpa: split(data.real_transcripts_ipa),
            heardIpa: split(data.matched_transcripts_ipa),
            categories: split(data.pair_accuracy_category),
            startTimes: split(data.start_time).map(parseFloat),
            endTimes: split(data.end_time).map(parseFloat),
            heard: String(data.real_transcript || '').trim(),
        };
        recording = buffer || null;
        selected = -1;

        renderWords(split(data.is_letter_correct_all_words));
        els.detail.hidden = true;

        const tier = tierOf(accuracy);
        els.ring.classList.remove('tier-ok', 'tier-bad');
        if (tier.ring) els.ring.classList.add(tier.ring);
        i18n.text(els.title, tier.title);
        i18n.text(els.meaning, 'result.meaning', { percent: accuracy });
        renderHeard(result.heard);
        els.playback.disabled = !recording;
        els.card.hidden = false;
        els.app.classList.add('has-result');

        els.ring.style.setProperty('--value', '0');
        requestAnimationFrame(() => requestAnimationFrame(() => {
            els.ring.style.setProperty('--value', String(accuracy));
        }));
        showScore(accuracy);
        AIPT.audio.chime(accuracy);
        reveal();
        ui.announce(t('result.announce', { percent: accuracy }));
    }

    // Focus on the result's title, and the page scrolled just enough to show
    // the top of the card above the bar (smoothly unless reduced motion).
    function reveal() {
        ui.focus(els.title, { preventScroll: true });
        const rect = els.card.getBoundingClientRect();
        const bottom = ui.visibleBottom();
        const wanted = rect.top + Math.min(rect.height, 160);
        let delta = 0;
        if (rect.top < 0) delta = rect.top - 12;
        else if (wanted > bottom) delta = wanted - bottom + 12;
        if (delta) window.scrollBy({ top: delta, behavior: AIPT.reducedMotion() ? 'auto' : 'smooth' });
    }

    function clear() {
        cancelAnimationFrame(countUp);
        if (result) AIPT.audio.stop();
        result = null;
        recording = null;
        selected = -1;
        els.card.hidden = true;
        els.detail.hidden = true;
        els.sentence.classList.remove('has-result');
        els.app.classList.remove('has-result');
    }

    function renderDetail() {
        const index = selected;
        const value = category(index);
        const spoken = result.heardIpa[index];
        const heard = Boolean(spoken) && spoken !== '-';
        els.word.textContent = result.words[index];
        els.badge.textContent = `${MARKS[value]} ${status(index)}`;
        els.badge.className = `badge cat-${value}`;
        els.refIpa.textContent = result.realIpa[index] ? `/${result.realIpa[index]}/` : '—';
        if (heard) {
            els.heardIpa.removeAttribute('data-i18n');
            els.heardIpa.textContent = `/${spoken}/`;
            els.heardIpa.setAttribute('lang', 'en');
        } else {
            i18n.text(els.heardIpa, 'detail.notHeard');
            els.heardIpa.removeAttribute('lang');
        }
        const timed = heard && Number.isFinite(result.startTimes[index]) && Number.isFinite(result.endTimes[index]);
        els.playHeard.disabled = !(timed && recording);
    }

    function selectWord(index) {
        if (!result) return;
        selected = index;
        els.sentence.querySelectorAll('.word').forEach((word) => {
            word.classList.toggle('is-selected', Number(word.dataset.index) === index);
        });
        renderDetail();
        els.detail.hidden = false;
    }

    // ---------------------------------------------------------------- playback
    function playWord(index) {
        if (!recording) return;
        const start = result.startTimes[index];
        const end = result.endTimes[index];
        if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return;
        AIPT.audio.playBuffer(recording, { owner: 'heardWord', offset: start, duration: end - start });
    }

    AIPT.audio.onChange((owner, state) => {
        if (owner === 'recording') els.playback.setAttribute('aria-pressed', String(state !== 'idle'));
        if (owner === 'referenceWord') els.playRef.classList.toggle('is-playing', state !== 'idle');
        if (owner === 'heardWord') els.playHeard.classList.toggle('is-playing', state !== 'idle');
    });

    els.sentence.addEventListener('click', (event) => {
        const word = event.target.closest('.word');
        if (word && result) selectWord(Number(word.dataset.index));
    });
    els.playRef.addEventListener('click', () => {
        if (!result || selected < 0) return;
        const word = result.words[selected];
        AIPT.audio.speak(AIPT.stripPunctuation(word) || word, { owner: 'referenceWord' });
    });
    els.playHeard.addEventListener('click', () => {
        if (result && selected >= 0) playWord(selected);
    });
    els.playback.addEventListener('click', () => {
        if (!recording) return;
        if (AIPT.audio.owner === 'recording') AIPT.audio.stop();
        else AIPT.audio.playBuffer(recording, { owner: 'recording' });
    });

    // The names of the words and the detail follow the language.
    i18n.onChange(() => {
        if (!result) return;
        els.sentence.querySelectorAll('.word').forEach(wordLabel);
        if (selected >= 0) renderDetail();
    });

    AIPT.result = {
        // onRetry and onNext: the card's Try again and Next sentence (from 1024 px).
        init({ onRetry, onNext }) {
            els.retry.addEventListener('click', () => onRetry(els.retry));
            els.next.addEventListener('click', () => onNext(els.next));
        },
        render,
        clear,
        get shown() {
            return Boolean(result);
        },
    };
})();
