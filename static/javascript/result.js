'use strict';

// The result card (design/wireframes/03-result-card.html C1-C7, 01-main-mobile.html A5, A6 and A13,
// 08-desktop.html H2; context/design-system.md §2.10-2.13 and §3): under the sentence on phones, in the
// right column from 1024 px. In order: the score ring, a title and a line saying what the number means; a
// note when the take stopped at 30 s before the end of the text; a "done" line, or the words to practise
// (at most 4 chips, then "+N more") and the detail of one word (its IPA with Listen, what was heard with
// Replay), with a hint when the server names a learner's typical mistake (Q3); My recording, what was
// heard, the legend; from 1024 px Try again and Next sentence. The sentence itself becomes one button per
// word: letters heard as written in the Correct colour, the others bold and dotted, and a boxed mark after
// Almost and Needs-work words (none after Correct ones, Q2).
//
// After each score, AIPT.result.onScored listeners get what the progress module keeps (see `scored`).
(() => {
    const { $, el, icon, i18n, ui } = AIPT;
    const { t } = i18n;

    // pair_accuracy_category, per word: 0 Correct, 1 Almost, 2 Needs work (design-system §1.3).
    const STATUS_KEYS = ['status.correct', 'status.almost', 'status.needsWork'];
    const MARK_ICONS = ['correct', 'almost', 'needs-work'];
    // A word of the sentence that nothing heard was paired with (WordMatching.WORD_NOT_FOUND_TOKEN).
    const NOT_HEARD = '-';
    // mistake_kinds, per word (WordMatching.known_mistake), or '-' for none.
    const MISTAKES = ['ending', 'th', 'sh'];
    // §3 (Q1): the titles change at 90, 70 and 60; the ring (style.css, data-tier) and the chime at 70 and 60.
    const TITLES = {
        excellent: 'result.title.excellent',
        good: 'result.title.good',
        almost: 'result.title.almost',
        keep: 'result.title.keep',
        different: 'result.title.different',
    };
    const CHIMES = { excellent: 'good', good: 'good', almost: 'okay', keep: 'bad', different: 'bad' };
    // C6: fewer than this share of the sentence's words heard at all is another sentence.
    const DIFFERENT_BELOW = 0.35;
    const MAX_CHIPS = 4;
    const COUNT_UP_MS = 800;
    // Replay plays a little more than a word's span: Whisper's word times are tight.
    const REPLAY_BEFORE_S = 0.05;
    const REPLAY_AFTER_S = 0.1;
    // An ending left out is a sound or two (/s/, /z/, /t/, /d/, /ɪz/, /ɪd/): anything longer is not one.
    const MAX_ENDING_SOUNDS = 3;

    const LETTER = /[\p{L}\p{N}]/u;

    const els = {
        app: $('app'),
        sentence: $('sentence'),
        card: $('resultCard'),
        ring: $('scoreRing'),
        score: $('scoreValue'),
        title: $('resultTitle'),
        meaning: $('resultMeaning'),
        cutOff: $('resultCutOff'),
        done: $('resultDone'),
        practise: $('practise'),
        chips: $('wordChips'),
        detail: $('wordDetail'),
        word: $('wdWord'),
        badge: $('wdBadge'),
        badgeIcon: $('wdBadgeIcon'),
        badgeText: $('wdBadgeText'),
        refIpa: $('wdRefIpa'),
        heardIpa: $('wdHeardIpa'),
        playRef: $('wdPlayRef'),
        playHeard: $('wdPlayHeard'),
        hint: $('wdHint'),
        hintLead: $('wdHintLead'),
        hintTip: $('wdHintTip'),
        hintWord: $('wdHintWord'),
        hintWordText: $('wdHintWordText'),
        hintHeard: $('wdHintHeard'),
        hintHeardText: $('wdHintHeardText'),
        playback: $('btnPlayback'),
        heard: $('resultHeard'),
        heardMore: $('btnHeardMore'),
        heardMoreLabel: $('heardMoreLabel'),
        retry: $('btnResultRetry'),
        next: $('btnResultNext'),
    };

    // The sounds of the card, by their owner in AIPT.audio, and the button that shows each one.
    const PLAYERS = new Map([
        ['recording', els.playback],
        ['referenceWord', els.playRef],
        ['heardWord', els.playHeard],
        ['hintWord', els.hintWord],
        ['hintHeard', els.hintHeard],
    ]);
    const DETAIL_OWNERS = ['referenceWord', 'heardWord', 'hintWord', 'hintHeard'];

    let result = null; // the score shown, or null
    let selected = -1; // the index of the word whose detail is open
    let expanded = false; // "+N more" was tapped
    let recording = null; // the take as an AudioBuffer, for My recording and Replay (null: none)
    let countUp = 0;
    let fitFrame = 0;
    const scoredListeners = [];

    // ---------------------------------------------------------------- the answer
    // The server's lists hold one item per word of the sentence, separated by spaces. An item can be empty
    // (the IPA of a word not heard), so they are split without trimming: a word not heard at either end
    // keeps every other word in its place.
    const items = (value) => (value === undefined || value === null ? [] : String(value).split(' '));

    // A word's IPA as the detail shows it, without the punctuation around the word ("bʊks." is /bʊks/).
    const trimIpa = (ipa) => String(ipa || '').replace(/^[^\p{L}\p{M}\p{N}]+|[^\p{L}\p{M}\p{N}]+$/gu, '');
    // An IPA to compare: no stress marks (ˈ ˌ), letters only.
    const bareIpa = (ipa) => trimIpa(ipa).replace(/[\u{2C8}\u{2CC}]/gu, '').replace(/[^\p{L}\p{M}]/gu, '');
    // A word's letters to compare: lower case, letters and digits only.
    const lettersOf = (word) => Array.from(String(word || '').toLowerCase()).filter((ch) => LETTER.test(ch)).join('');

    // Each word of the sentence as the card uses it.
    function parseWords(data, text) {
        const categories = items(data.pair_accuracy_category);
        const mistakes = items(data.mistake_kinds);
        const letters = items(data.is_letter_correct_all_words);
        const heard = items(data.matched_transcripts);
        const refIpa = items(data.real_transcripts_ipa);
        const heardIpa = items(data.matched_transcripts_ipa);
        const starts = items(data.start_time);
        const ends = items(data.end_time);
        return text.split(' ').map((written, index) => {
            // One flag per character, as Python counts them (code points): 1 heard as written, 0 not.
            const flags = letters[index] || '';
            let total = 0;
            let right = 0;
            Array.from(written).forEach((ch, i) => {
                if (!LETTER.test(ch)) return;
                total += 1;
                if (flags[i] !== '0') right += 1;
            });
            const category = categories[index];
            const token = heard[index];
            const wasHeard = Boolean(token) && token !== NOT_HEARD;
            return {
                index,
                written, // as the sentence has it: "books."
                plain: AIPT.stripPunctuation(written) || written, // "books"
                status: category === '0' || category === '1' || category === '2' ? Number(category) : 2,
                mistake: MISTAKES.includes(mistakes[index]) ? mistakes[index] : '',
                flags,
                share: total ? right / total : 1, // of its letters, heard as written
                heard: wasHeard ? token : '', // what was heard in its place
                refIpa: trimIpa(refIpa[index]),
                heardIpa: wasHeard ? trimIpa(heardIpa[index]) : '',
                start: parseFloat(starts[index]),
                end: parseFloat(ends[index]),
            };
        });
    }

    function tierOf(accuracy) {
        if (accuracy >= 90) return 'excellent';
        if (accuracy >= 70) return 'good';
        if (accuracy >= 60) return 'almost';
        return 'keep';
    }

    const keyOf = (word) => word.plain.toLowerCase();

    // The words to practise (§2.13): Needs work before Almost, then by the share of their letters heard,
    // then in the sentence's order; a word that comes twice is one chip (its worst reading).
    function practiseList(words) {
        const seen = new Set();
        return words.filter((word) => word.status > 0)
            .sort((a, b) => (b.status - a.status) || (a.share - b.share) || (a.index - b.index))
            .filter((word) => {
                if (seen.has(keyOf(word))) return false;
                seen.add(keyOf(word));
                return true;
            });
    }

    // ---------------------------------------------------------------- the sentence
    const statusText = (status) => t(STATUS_KEYS[status]);

    // A boxed mark (§2.10), drawn from the sprite: ~ Almost, ✗ Needs work.
    const mark = (status) => el('span', { className: `mark mark-${status}`, attrs: { 'aria-hidden': 'true' } },
        [icon(MARK_ICONS[status])]);

    // "books, Almost, show details". The name is read instead of the letters, so it takes the
    // interface's language (the sentence around it is English).
    function labelWord(button) {
        const word = result.words[Number(button.dataset.index)];
        button.setAttribute('aria-label', t('word.details', { word: word.plain, status: statusText(word.status) }));
        button.setAttribute('lang', i18n.lang);
    }

    // One word: any punctuation before it, the button (its letters, then its mark), any punctuation after
    // it, in a group that never breaks across lines, so the mark always stays with its word.
    function wordGroup(word) {
        const chars = Array.from(word.written);
        let first = 0;
        while (first < chars.length && !LETTER.test(chars[first])) first += 1;
        let last = chars.length;
        while (last > first && !LETTER.test(chars[last - 1])) last -= 1;
        if (first >= last) {
            first = 0;
            last = chars.length;
        }
        const button = el('button', {
            className: 'w',
            attrs: {
                type: 'button',
                'data-index': String(word.index),
                'data-status': String(word.status),
                'data-mistake': word.mistake || null,
            },
        });
        // Runs of letters heard as written, and of letters not (.wl: bold, dotted).
        let run = '';
        let wrong = false;
        const flush = () => {
            if (run) button.appendChild(wrong ? el('span', { className: 'wl', text: run }) : document.createTextNode(run));
            run = '';
        };
        for (let i = first; i < last; i += 1) {
            const bad = word.flags[i] === '0';
            if (bad !== wrong) {
                flush();
                wrong = bad;
            }
            run += chars[i];
        }
        flush();
        if (word.status > 0) button.appendChild(mark(word.status));
        labelWord(button);
        const group = el('span', { className: 'wg' });
        if (first > 0) group.appendChild(document.createTextNode(chars.slice(0, first).join('')));
        group.appendChild(button);
        if (last < chars.length) group.appendChild(document.createTextNode(chars.slice(last).join('')));
        return group;
    }

    function renderSentence() {
        const fragment = document.createDocumentFragment();
        result.words.forEach((word, index) => {
            if (index) fragment.appendChild(document.createTextNode(' '));
            fragment.appendChild(wordGroup(word));
        });
        els.sentence.replaceChildren(fragment);
        els.sentence.classList.add('has-result');
    }

    // ---------------------------------------------------------------- the head
    // The score counting up (800 ms), or at once under reduced motion. The number is decoration
    // (the ring is aria-hidden): the title and the announcement say the score.
    function showScore(target) {
        cancelAnimationFrame(countUp);
        if (AIPT.reducedMotion()) {
            els.score.textContent = String(target);
            return;
        }
        const start = performance.now();
        const step = (now) => {
            const progress = Math.min(1, (now - start) / COUNT_UP_MS);
            els.score.textContent = String(Math.round(target * (1 - Math.pow(1 - progress, 3))));
            if (progress < 1) countUp = requestAnimationFrame(step);
        };
        countUp = requestAnimationFrame(step);
    }

    function renderHead() {
        els.card.dataset.tier = result.tier;
        i18n.text(els.title, TITLES[result.tier]);
        if (result.different) i18n.text(els.meaning, 'result.meaningDifferent');
        else i18n.text(els.meaning, 'result.meaning', { percent: result.accuracy });
        // The ring fills from empty (900 ms, style.css; at once under reduced motion).
        els.ring.style.setProperty('--value', '0');
        requestAnimationFrame(() => requestAnimationFrame(() => {
            if (result) els.ring.style.setProperty('--value', String(result.accuracy));
        }));
        showScore(result.accuracy);
    }

    // ---------------------------------------------------------------- words to practise
    function labelChips() {
        els.chips.querySelectorAll('.word-chip[data-index]').forEach((chip) => {
            const word = result.words[Number(chip.dataset.index)];
            chip.setAttribute('aria-label', t('word.chip', { word: word.plain, status: statusText(word.status) }));
        });
    }

    // At most 4 chips, then "+N more", which shows the others in place.
    function renderChips() {
        const list = result.practise;
        const shown = expanded ? list : list.slice(0, MAX_CHIPS);
        const chips = shown.map((word) => el('button', {
            className: 'word-chip',
            attrs: {
                type: 'button',
                'data-index': String(word.index),
                'data-status': String(word.status),
                'aria-pressed': 'false',
            },
        }, [
            icon(MARK_ICONS[word.status], `chip-mark chip-mark-${word.status}`),
            el('span', { text: word.plain, attrs: { lang: 'en' } }),
        ]));
        if (list.length > shown.length) {
            const more = el('button', { className: 'word-chip word-chip-more', attrs: { type: 'button', 'data-more': '' } });
            chips.push(i18n.text(more, 'result.more', { count: list.length - shown.length }));
        }
        els.chips.replaceChildren(...chips);
        labelChips();
    }

    function expand() {
        const first = result.practise[MAX_CHIPS];
        expanded = true;
        renderChips();
        markSelection();
        if (first) ui.focus(els.chips.querySelector(`.word-chip[data-index="${first.index}"]`));
    }

    // The selected word: highlighted in the sentence, and its chip pressed (a word that comes twice has
    // one chip, pressed for either).
    function markSelection() {
        const word = selected >= 0 ? result.words[selected] : null;
        els.sentence.querySelectorAll('.w').forEach((button) => {
            button.classList.toggle('is-selected', Number(button.dataset.index) === selected);
        });
        els.chips.querySelectorAll('.word-chip[data-index]').forEach((chip) => {
            const pressed = Boolean(word) && keyOf(result.words[Number(chip.dataset.index)]) === keyOf(word);
            chip.setAttribute('aria-pressed', String(pressed));
        });
    }

    function select(index) {
        if (!result || !result.words[index]) return;
        if (index !== selected && DETAIL_OWNERS.includes(AIPT.audio.owner)) AIPT.audio.stop();
        selected = index;
        markSelection();
        renderDetail();
        els.detail.hidden = false;
    }

    // ---------------------------------------------------------------- the word's detail
    const canReplay = (word) => Boolean(recording) && Boolean(word.heard)
        && Number.isFinite(word.start) && Number.isFinite(word.end) && word.end > word.start;

    function labelDetail(word) {
        els.playRef.setAttribute('aria-label', t('detail.listenLabel', { word: word.plain }));
        els.playHeard.setAttribute('aria-label', t('detail.replayLabel', { word: word.plain }));
    }

    function renderDetail() {
        const word = result.words[selected];
        els.word.textContent = word.plain;
        els.badge.className = `badge badge-${word.status}`;
        els.badgeIcon.setAttribute('href', `#i-${MARK_ICONS[word.status]}`);
        i18n.text(els.badgeText, STATUS_KEYS[word.status]);
        els.refIpa.textContent = word.refIpa ? `/${word.refIpa}/` : '—';
        if (word.heard) {
            els.heardIpa.removeAttribute('data-i18n');
            els.heardIpa.textContent = word.heardIpa ? `/${word.heardIpa}/` : `“${AIPT.stripPunctuation(word.heard) || word.heard}”`;
            els.heardIpa.setAttribute('lang', 'en');
            els.heardIpa.classList.remove('is-none');
        } else {
            // Not heard: nothing to cut from the recording (C5).
            i18n.text(els.heardIpa, 'detail.notHeard');
            els.heardIpa.removeAttribute('lang');
            els.heardIpa.classList.add('is-none');
        }
        AIPT.setDisabled(els.playHeard, !canReplay(word));
        labelDetail(word);
        renderHint(word);
    }

    // ---------------------------------------------------------------- the typical-mistake hint (Q3)
    // The word heard, as the hint shows it: without punctuation, and in lower case where the sentence
    // writes the word so (Whisper capitalises the start of what it heard: "Tree").
    function heardForHint(word) {
        const heard = AIPT.stripPunctuation(word.heard) || word.heard;
        return word.plain === word.plain.toLowerCase() ? heard.toLowerCase() : heard;
    }

    // The letter that "th" (or "sh") of the written word was said as: the one that, in place of one of
    // its occurrences, gives the word heard (WordMatching.known_mistake, on the letters as written), or ''.
    function saidAs(written, heard, letters, sounds) {
        const real = lettersOf(written);
        const said = lettersOf(heard);
        for (let at = real.indexOf(letters); at >= 0; at = real.indexOf(letters, at + 1)) {
            const sound = sounds.find((each) => real.slice(0, at) + each + real.slice(at + letters.length) === said);
            if (sound) return sound;
        }
        return '';
    }

    // The sound an ending left out stands for: the end of the reference IPA that the IPA of the word heard
    // lacks (/bʊks/ against /bʊk/: s; /ˈwɔntɪd/ against /wɔnt/: ɪd), or '' when the two do not show it.
    function endingSound(word) {
        const reference = bareIpa(word.refIpa);
        const heard = bareIpa(word.heardIpa);
        if (!heard || reference.length <= heard.length || !reference.startsWith(heard)) return '';
        const rest = reference.slice(heard.length);
        return Array.from(rest).length <= MAX_ENDING_SOUNDS ? rest : '';
    }

    // "book-s": the written word cut where the word heard ends, or null when it does not end there.
    function endingSplit(written, heard) {
        const chars = Array.from(written);
        const said = lettersOf(heard);
        if (!said || chars.length <= said.length) return null;
        const base = chars.slice(0, said.length).join('');
        const ending = chars.slice(said.length);
        if (lettersOf(base) !== said || !ending.every((ch) => LETTER.test(ch))) return null;
        return { base, ending: ending.join('') };
    }

    // One hint at a time, in the selected word's detail, and only on an Almost word whose mistake the
    // server names (ending, th, sh): what it sounds like, a tip, and the two words to listen to.
    function renderHint(word) {
        const kind = word.status === 1 && word.heard ? word.mistake : '';
        els.hint.hidden = !kind;
        if (!kind) return;
        const heard = heardForHint(word);
        const english = (text) => el('i', { className: 'hint-word', text, attrs: { lang: 'en' } });
        const arrow = el('span', { className: 'hint-arrow' },
            [icon('next'), i18n.text(el('span', { className: 'visually-hidden' }), 'hint.arrow')]);
        const pair = { heard: english(heard), arrow, word: english(word.plain) };
        if (kind === 'ending') {
            const sound = endingSound(word);
            if (sound) {
                const ipa = el('span', { className: 'hint-ipa', text: `/${sound}/`, attrs: { lang: 'en' } });
                i18n.richText(els.hintLead, 'hint.ending', { sound: ipa, ...pair });
            } else {
                i18n.richText(els.hintLead, 'hint.endingNoSound', pair);
            }
            const split = endingSplit(word.plain, heard);
            if (split) {
                const said = el('span', { attrs: { lang: 'en' } }, [document.createTextNode(`${split.base}-`),
                    el('b', { text: split.ending })]);
                i18n.richText(els.hintTip, 'hint.endingTip', { split: said });
            } else {
                i18n.text(els.hintTip, 'hint.endingTipPlain');
            }
        } else if (kind === 'th') {
            const letter = saidAs(word.plain, heard, 'th', ['t', 'd', 's', 'f']);
            if (letter) i18n.richText(els.hintLead, 'hint.th', pair, { letter });
            else i18n.richText(els.hintLead, 'hint.thUnclear', pair);
            i18n.text(els.hintTip, 'hint.thTip');
        } else {
            // The scorer names "sh" only when it was said as "s".
            i18n.richText(els.hintLead, 'hint.sh', pair);
            i18n.text(els.hintTip, 'hint.shTip');
        }
        els.hintWordText.textContent = word.plain;
        els.hintHeardText.textContent = heard;
        labelHint();
    }

    function labelHint() {
        els.hintWord.setAttribute('aria-label', t('hint.listen', { word: els.hintWordText.textContent }));
        els.hintHeard.setAttribute('aria-label', t('hint.listen', { word: els.hintHeardText.textContent }));
    }

    // ---------------------------------------------------------------- what was heard
    // "Heard: “…”", cut after 3 lines with "more" (C7).
    function renderHeard() {
        if (result.heard) {
            i18n.richText(els.heard, 'result.heard', {
                text: el('span', { text: `“${result.heard}”`, attrs: { lang: 'en' } }),
            });
        } else {
            i18n.text(els.heard, 'result.nothingHeard');
        }
        els.heardMore.setAttribute('aria-expanded', 'false');
        i18n.text(els.heardMoreLabel, 'result.heardMore');
        els.heard.classList.add('is-clamped');
    }

    // "more" only when the text is longer than 3 lines (measured: it depends on the width and the language).
    function fitHeard() {
        if (!result || els.card.hidden || els.heardMore.getAttribute('aria-expanded') === 'true') return;
        els.heardMore.hidden = els.heard.scrollHeight <= els.heard.clientHeight + 1;
    }

    // ---------------------------------------------------------------- showing a score
    // Focus on the result's title, and the page scrolled just enough to show the top of the card above
    // the bar (smoothly unless reduced motion).
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

    // One announcement for screen readers (§4): "Score 79%. 3 words to practise: written, three, books.",
    // and the note of a take stopped at 30 s.
    function announcement() {
        const percent = result.accuracy;
        const list = result.practise;
        let text;
        if (result.different) {
            text = t('result.announceDifferent', { percent });
        } else if (list.length) {
            const names = list.slice(0, MAX_CHIPS).map((word) => word.plain).join(', ');
            const words = list.length > MAX_CHIPS ? t('result.andMore', { words: names, count: list.length - MAX_CHIPS }) : names;
            text = t('result.announce', { percent, count: list.length, words });
        } else if (result.cutOff) {
            text = t('result.announceScore', { percent });
        } else {
            text = t('result.announceDone', { percent });
        }
        return result.cutOff ? `${text} ${t('result.cutOff')}` : text;
    }

    // What the progress module keeps of a score (wireframes page 6): the text, where it came from ('bank',
    // 'custom', or 'word' for a word practised alone), the bank sentence's own level (1-3, from the page), the
    // score, whether it was another sentence (C6: it counts for nothing), and each word's status (0, 1 or 2),
    // with reached: false for the words after a take stopped at 30 s (never read, so no word to review).
    function scored() {
        const payload = {
            text: result.text,
            source: result.source,
            level: result.level,
            accuracy: result.accuracy,
            different: result.different,
            words: result.words.map((word) => ({ word: word.plain, status: word.status, reached: word.reached })),
        };
        scoredListeners.forEach((fn) => {
            try {
                fn(payload);
            } catch (err) {
                console.error(err);
            }
        });
    }

    // data: the answer of /GetAccuracyFromRecordedAudio; text: the sentence that was scored; buffer: the
    // take, decoded (or null); source: 'bank', 'custom' or 'word'; level: the bank sentence's own level (1-3);
    // hitLimit: the take was stopped at 30 s; answeredAt: when the answer came (performance.now()), for the
    // chime.
    function render(data, {
        text, buffer = null, source = 'bank', level = 1, hitLimit = false, answeredAt = performance.now(),
    }) {
        const accuracy = Math.max(0, Math.min(100, parseInt(data.pronunciation_accuracy, 10) || 0));
        const words = parseWords(data, text);
        // B4: a take stopped by itself at 30 s can end before the text does. The words after the last one
        // heard were then never reached: the card says so, and they count neither for "a different
        // sentence" nor as words to practise (their marks and details stay: "not heard").
        let reachedEnd = words.length;
        if (hitLimit) {
            while (reachedEnd > 0 && !words[reachedEnd - 1].heard) reachedEnd -= 1;
        }
        words.forEach((word) => {
            word.reached = word.index < reachedEnd;
        });
        const reached = words.slice(0, reachedEnd);
        const heardCount = reached.filter((word) => word.heard).length;
        const different = heardCount < DIFFERENT_BELOW * Math.max(1, reached.length);
        result = {
            text,
            source,
            level,
            accuracy,
            words,
            different,
            tier: different ? 'different' : tierOf(accuracy),
            // Another sentence gets no chips: every word would be one (C6).
            practise: different ? [] : practiseList(reached),
            heard: String(data.real_transcript || '').trim(),
            cutOff: reachedEnd < words.length,
        };
        recording = buffer || null;
        selected = -1;
        expanded = false;

        renderSentence();
        renderHead();
        els.cutOff.hidden = !result.cutOff;
        // "Nothing to practise" only for a text read to its end.
        els.done.hidden = result.different || result.cutOff || result.practise.length > 0;
        els.practise.hidden = !result.practise.length;
        renderChips();
        els.detail.hidden = true;
        // The worst word's detail opens by itself.
        if (result.practise.length) select(result.practise[0].index);
        AIPT.setDisabled(els.playback, !recording);
        renderHeard();
        els.card.hidden = false;
        els.app.classList.add('has-result');
        fitHeard();

        AIPT.audio.chime(CHIMES[result.tier], { since: answeredAt });
        reveal();
        ui.announce(announcement());
        scored();
    }

    function clear() {
        cancelAnimationFrame(countUp);
        if (result) AIPT.audio.stop();
        result = null;
        recording = null;
        selected = -1;
        expanded = false;
        els.card.hidden = true;
        els.detail.hidden = true;
        delete els.card.dataset.tier;
        els.sentence.classList.remove('has-result');
        els.app.classList.remove('has-result');
    }

    // ---------------------------------------------------------------- sounds
    // A word read by the reference voice; a second tap stops it.
    function toggleSpeak(owner, text) {
        if (AIPT.audio.owner === owner) AIPT.audio.stop();
        else if (text) AIPT.audio.speak(text, { owner });
    }

    function togglePlay(owner, options) {
        if (AIPT.audio.owner === owner) AIPT.audio.stop();
        else AIPT.audio.playBuffer(recording, { owner, ...options });
    }

    AIPT.audio.onChange((owner, state) => {
        const button = PLAYERS.get(owner);
        if (!button) return;
        button.dataset.state = state;
        button.setAttribute('aria-pressed', String(state !== 'idle'));
    });

    els.playRef.addEventListener('click', () => {
        if (result && selected >= 0) toggleSpeak('referenceWord', result.words[selected].plain);
    });
    // The word's span of the recording (start_time, end_time), with a little around it.
    els.playHeard.addEventListener('click', () => {
        if (!result || selected < 0 || AIPT.isDisabled(els.playHeard)) return;
        const word = result.words[selected];
        if (!canReplay(word)) return;
        const offset = Math.max(0, word.start - REPLAY_BEFORE_S);
        const end = Math.min(recording.duration, word.end + REPLAY_AFTER_S);
        togglePlay('heardWord', { offset, duration: Math.max(0.05, end - offset) });
    });
    els.hintWord.addEventListener('click', () => toggleSpeak('hintWord', els.hintWordText.textContent));
    els.hintHeard.addEventListener('click', () => toggleSpeak('hintHeard', els.hintHeardText.textContent));
    els.playback.addEventListener('click', () => {
        if (recording && !AIPT.isDisabled(els.playback)) togglePlay('recording', {});
    });

    // ---------------------------------------------------------------- choosing a word
    els.sentence.addEventListener('click', (event) => {
        const button = event.target.closest('.w');
        if (button && result && els.sentence.contains(button)) select(Number(button.dataset.index));
    });
    els.chips.addEventListener('click', (event) => {
        const chip = event.target.closest('.word-chip');
        if (!chip || !result) return;
        if (chip.hasAttribute('data-more')) expand();
        else select(Number(chip.dataset.index));
    });
    els.heardMore.addEventListener('click', () => {
        const open = els.heardMore.getAttribute('aria-expanded') !== 'true';
        els.heardMore.setAttribute('aria-expanded', String(open));
        els.heard.classList.toggle('is-clamped', !open);
        i18n.text(els.heardMoreLabel, open ? 'result.heardLess' : 'result.heardMore');
    });

    // Names with a word in them follow the language; the length of the heard line too.
    i18n.onChange(() => {
        if (!result) return;
        els.sentence.querySelectorAll('.w').forEach(labelWord);
        labelChips();
        if (selected >= 0) labelDetail(result.words[selected]);
        if (!els.hint.hidden) labelHint();
        fitHeard();
    });
    window.addEventListener('resize', () => {
        cancelAnimationFrame(fitFrame);
        fitFrame = requestAnimationFrame(fitHeard);
    });

    AIPT.result = {
        // onRetry and onNext: the card's Try again and Next sentence (from 1024 px).
        init({ onRetry, onNext }) {
            els.retry.addEventListener('click', () => onRetry(els.retry));
            els.next.addEventListener('click', () => onNext(els.next));
        },
        render,
        clear,
        // fn({ text, source, level, accuracy, different, words: [{ word, status, reached }] }) after each score.
        onScored(fn) {
            scoredListeners.push(fn);
        },
        get shown() {
            return Boolean(result);
        },
    };
})();
