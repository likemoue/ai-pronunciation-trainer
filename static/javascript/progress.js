'use strict';

// Progress, kept in this browser only (design/wireframes/06-progress-sheet.html, F1-F7): today's points,
// sentences and average, the streak, the last 7 days and the words to review. "Today", the streak and the dates
// follow Vietnam time (context/design-system.md §5). The ★ chip in the header shows today's points (12.5K from
// 10,000) and, from 768 px, the streak; it opens the progress sheet (a bottom sheet on phones, a dialog from
// 768 px). "New learner" asks first (an alertdialog above the sheet), then clears the record; the page clears the
// My text draft and the tour's flag (onReset) and keeps the language.
//
// Points, after each score (AIPT.result.onScored): each text counts once a day, with its best attempt. An attempt
// that beats today's best for that text adds only the difference, and the same text sent again adds nothing. A
// bank sentence pays at its own level (Easy x1, Medium x1.3, Hard x1.6); the learner's own text and a single word
// x1. "That sounds like a different sentence" counts for nothing: no points, no words, no streak.
//
// Words to review: the words marked ~ or ✗ (only words the take reached), ✗ first, then the most recently missed;
// a word leaves after two Correct readings since it was last missed. Only a word that can be practised alone
// enters the list (one word the server would take as English text: not "2:30").
//
// One versioned record in localStorage, through AIPT.storage, read defensively: anything it does not recognise
// is dropped quietly, and a record of another version starts again from empty. It stays small: 31 days, 500
// texts a day (by a short hash, not the text), 200 words.
//   aipt.progress.v1 = {
//     v: 1,
//     days:   { '2026-11-16': [points, sentences, sum of their best scores] },
//     today:  { day: '2026-11-16', texts: { h1x2y3z: [best score, points paid] } },
//     streak: { count: 3, last: '2026-11-16' },        // days in a row with a scored sentence, and the last one
//     words:  [{ w: 'they', s: 2, ok: 0, at: 1763280000000 }],
//   }                                                   // s the last mark (1 ~, 2 ✗), ok Correct readings since,
//                                                       // at when it was last missed (ms)
(() => {
    const { $, el, icon, i18n, ui, storage } = AIPT;
    const { t } = i18n;

    const KEY = 'aipt.progress.v1';
    const VERSION = 1;
    const DAYS_KEPT = 31;
    const TEXTS_PER_DAY = 500;
    const WORDS_KEPT = 200;
    const WORDS_SHOWN = 12;
    const CORRECT_TO_LEAVE = 2;
    const MAX_WORD_CHARS = 40;
    const COMPACT_FROM = 10000;
    // A bank sentence's own level (1 Easy, 2 Medium, 3 Hard); anything else pays x1.
    const MULTIPLIERS = { 1: 1, 2: 1.3, 3: 1.6 };
    const STATUS_KEYS = { 1: 'status.almost', 2: 'status.needsWork' };
    const MARK_ICONS = { 1: 'almost', 2: 'needs-work' };
    // "Mon 16 Nov", "Thứ Hai 16/11": the parts that progress.date puts together, in each language's form.
    const DATE_FORMATS = {
        en: ['en-GB', { weekday: 'short', day: 'numeric', month: 'short' }],
        vi: ['vi', { weekday: 'long', day: 'numeric', month: 'numeric' }],
    };
    const DAY = /^\d{4}-\d{2}-\d{2}$/;
    const HASH = /^h[0-9a-z]{1,7}$/;
    const wide = window.matchMedia('(min-width: 768px)');

    const els = {
        slot: $('progressSlot'),
        root: $('progressSheet'),
        today: $('progressToday'),
        points: $('statPoints'),
        pointsLabel: $('statPointsLabel'),
        sentences: $('statSentences'),
        sentencesLabel: $('statSentencesLabel'),
        average: $('statAverage'),
        streak: $('progressStreak'),
        streakHint: $('progressStreakHint'),
        week: $('progressWeek'),
        chips: $('reviewChips'),
        hint: $('reviewHint'),
        newLearner: $('btnNewLearner'),
        confirm: $('confirmNewLearner'),
        delete: $('confirmDelete'),
    };

    let options = { onPractiseWord: () => {} };
    const resetListeners = [];
    let progress = null; // the record as last read or written
    let memory = null; // the record, where the browser refuses to keep it
    let expanded = false; // "Show all" was tapped
    let shownDay = '';

    // ---------------------------------------------------------------- days
    // A day ('2026-11-16') moved by n days: arithmetic on a date in UTC, so no clock and no time zone.
    function shiftDay(day, n) {
        const [year, month, date] = day.split('-').map(Number);
        return new Date(Date.UTC(year, month - 1, date + n)).toISOString().slice(0, 10);
    }

    // 0 for a Sunday, as Date.getUTCDay counts (progress.day.0 is "Sun").
    function weekdayOf(day) {
        const [year, month, date] = day.split('-').map(Number);
        return new Date(Date.UTC(year, month - 1, date)).getUTCDay();
    }

    // ---------------------------------------------------------------- the record
    const isObject = (value) => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
    const isCount = (value) => Number.isInteger(value) && value >= 0 && value <= 1e9;

    const empty = () => ({ v: VERSION, days: {}, today: { day: '', texts: {} }, streak: { count: 0, last: '' }, words: [] });

    // A word that can be practised alone: one word the server takes as English text (the page's own check).
    function practisable(word) {
        if (typeof word !== 'string' || !word) return false;
        const check = AIPT.checkText(word);
        return !check.problem && check.words === 1 && check.text === word && check.chars <= MAX_WORD_CHARS;
    }

    // The days kept, the texts of today and the words, each within its bound (the oldest go first).
    function trim(record) {
        const days = Object.keys(record.days).sort();
        days.slice(0, Math.max(0, days.length - DAYS_KEPT)).forEach((day) => {
            delete record.days[day];
        });
        // Keys that start with a letter keep their order of insertion.
        const texts = Object.keys(record.today.texts);
        texts.slice(0, Math.max(0, texts.length - TEXTS_PER_DAY)).forEach((hash) => {
            delete record.today.texts[hash];
        });
        if (record.words.length > WORDS_KEPT) {
            record.words.sort((a, b) => b.at - a.at);
            record.words.length = WORDS_KEPT;
        }
        return record;
    }

    // What the record holds that this version knows; anything else is dropped. Another version starts empty.
    function sanitize(data) {
        const record = empty();
        if (!isObject(data) || data.v !== VERSION) return record;
        if (isObject(data.days)) {
            Object.keys(data.days).forEach((day) => {
                const totals = data.days[day];
                if (DAY.test(day) && Array.isArray(totals) && totals.length === 3 && totals.every(isCount)) {
                    record.days[day] = totals.slice();
                }
            });
        }
        if (isObject(data.today) && DAY.test(data.today.day) && isObject(data.today.texts)) {
            record.today.day = data.today.day;
            Object.keys(data.today.texts).forEach((hash) => {
                const entry = data.today.texts[hash];
                if (HASH.test(hash) && Array.isArray(entry) && entry.length === 2 && entry.every(isCount)) {
                    record.today.texts[hash] = entry.slice();
                }
            });
        }
        const streak = data.streak;
        if (isObject(streak) && isCount(streak.count) && DAY.test(streak.last)) {
            record.streak = { count: streak.count, last: streak.last };
        }
        if (Array.isArray(data.words)) {
            const seen = new Set();
            data.words.forEach((entry) => {
                if (!isObject(entry) || !practisable(entry.w) || (entry.s !== 1 && entry.s !== 2)) return;
                if (!isCount(entry.ok) || !Number.isFinite(entry.at)) return;
                const key = entry.w.toLowerCase();
                if (seen.has(key)) return;
                seen.add(key);
                record.words.push({ w: entry.w, s: entry.s, ok: Math.min(entry.ok, CORRECT_TO_LEAVE - 1), at: entry.at });
            });
        }
        return trim(record);
    }

    function read() {
        const raw = storage.get(KEY);
        if (raw === null) return memory ? sanitize(JSON.parse(JSON.stringify(memory))) : empty();
        try {
            return sanitize(JSON.parse(raw));
        } catch (_) {
            return empty();
        }
    }

    // Kept in localStorage; where the browser refuses, for this page only.
    function write(record) {
        memory = storage.set(KEY, JSON.stringify(record)) ? null : record;
    }

    // ---------------------------------------------------------------- a score
    // A text as it is said: lower case and without punctuation ("Hello world." and "hello world" are one text).
    const spoken = (text) => String(text || '').toLowerCase().split(/\s+/).map(AIPT.stripPunctuation)
        .filter(Boolean).join(' ');

    // A short name for a text (FNV-1a, 32 bits): two of a day's 500 texts share one about once in 30,000 such
    // days. The leading letter keeps the record's keys in their order of insertion.
    function hashOf(text) {
        let hash = 0x811c9dc5;
        for (let i = 0; i < text.length; i += 1) {
            hash ^= text.charCodeAt(i);
            hash = Math.imul(hash, 0x01000193);
        }
        return `h${(hash >>> 0).toString(36)}`;
    }

    // A scored day extends the streak when it follows the last one, else starts one. A day before the last one
    // (a clock set back) changes nothing.
    function extendStreak(record, day) {
        const { count, last } = record.streak;
        if (last && last >= day) return;
        record.streak = { count: last === shiftDay(day, -1) ? count + 1 : 1, last: day };
    }

    // The streak as it stands today: alive while its last day is today or yesterday.
    function streakOf(record, today) {
        const { count, last } = record.streak;
        if (count > 0 && (last === today || last === shiftDay(today, -1))) return { count, today: last === today };
        return { count: 0, today: false };
    }

    // The form a word is shown in: its lower-case form once it has been seen so ("They" at the start of a
    // sentence is "they"), else as first seen ("Mary", "I").
    const preferred = (current, seen) => (seen === seen.toLowerCase() || !current ? seen : current);

    // Each word of the take once, with its worst mark; the words after a take cut at 30 s were never read.
    function reviewWords(record, words) {
        if (!Array.isArray(words)) return;
        const readings = new Map();
        words.forEach((item) => {
            if (!isObject(item) || item.reached === false || ![0, 1, 2].includes(item.status)) return;
            const word = AIPT.normalizeText(String(item.word || ''));
            if (!word || word.indexOf(' ') >= 0) return;
            const key = word.toLowerCase();
            const seen = readings.get(key);
            readings.set(key, {
                form: preferred(seen && seen.form, word),
                status: seen ? Math.max(seen.status, item.status) : item.status,
            });
        });
        const now = Date.now();
        readings.forEach(({ form, status }, key) => {
            const index = record.words.findIndex((entry) => entry.w.toLowerCase() === key);
            const entry = index >= 0 ? record.words[index] : null;
            if (entry) entry.w = preferred(entry.w, form);
            if (status === 0) {
                if (!entry) return;
                entry.ok += 1;
                if (entry.ok >= CORRECT_TO_LEAVE) record.words.splice(index, 1);
            } else if (entry) {
                Object.assign(entry, { s: status, ok: 0, at: now });
            } else if (practisable(form)) {
                record.words.push({ w: form, s: status, ok: 0, at: now });
            }
        });
    }

    // payload: { text, source 'bank' | 'custom' | 'word', level, accuracy, different, words: [{ word, status,
    // reached }] } (result.js). Read again first: another tab of this browser may have scored meanwhile.
    function scored(payload) {
        if (!isObject(payload) || payload.different) return;
        const accuracy = Math.round(Number(payload.accuracy));
        const text = spoken(payload.text);
        if (!Number.isFinite(accuracy) || !text) return;
        const score = Math.max(0, Math.min(100, accuracy));
        const record = read();
        const day = i18n.dayKey();
        if (record.today.day !== day) record.today = { day, texts: {} };
        const multiplier = payload.source === 'bank' ? MULTIPLIERS[payload.level] || 1 : 1;
        const points = Math.round(score * multiplier);
        const totals = record.days[day] || [0, 0, 0];
        const hash = hashOf(text);
        const entry = record.today.texts[hash];
        if (!entry) {
            record.today.texts[hash] = [score, points];
            totals[0] += points;
            totals[1] += 1;
            totals[2] += score;
        } else {
            if (points > entry[1]) {
                totals[0] += points - entry[1];
                entry[1] = points;
            }
            if (score > entry[0]) {
                totals[2] += score - entry[0];
                entry[0] = score;
            }
        }
        record.days[day] = totals;
        extendStreak(record, day);
        reviewWords(record, payload.words);
        write(trim(record));
        progress = record;
        render();
    }

    // ---------------------------------------------------------------- the chip
    const chipShort = el('span', { className: 'progress-chip-short' });
    const chipLong = el('span', { className: 'progress-chip-long' });
    const chip = el('button', {
        className: 'progress-chip',
        attrs: { type: 'button', id: 'btnProgress', 'aria-haspopup': 'dialog' },
    }, [icon('star', 'progress-chip-star'), chipShort, chipLong]);
    els.slot.appendChild(chip);

    // Today's points as the chip shows them: 12.5K from 10,000, so the header never overflows.
    const chipPoints = (points) => (points >= COMPACT_FROM
        ? i18n.formatNumber(points, { notation: 'compact', maximumFractionDigits: 1 })
        : i18n.formatNumber(points));

    function renderChip(day) {
        const points = (progress.days[day] || [0])[0];
        const streak = streakOf(progress, day).count;
        const shown = chipPoints(points);
        chipShort.textContent = shown;
        // From 768 px: "245 today · 3 days".
        const parts = [el('span', { text: t('progress.chipToday', { points: shown }) })];
        if (streak) {
            parts.push(el('span', { className: 'progress-chip-dot', text: '·', attrs: { 'aria-hidden': 'true' } }),
                icon('flame', 'progress-chip-flame'), el('span', { text: t('progress.chipDays', { count: streak }) }));
        }
        chipLong.replaceChildren(...parts);
        chip.setAttribute('aria-label', streak
            ? t('progress.chipLabelStreak', { points: shown, count: streak })
            : t('progress.chipLabel', { points: shown }));
    }

    // ---------------------------------------------------------------- the sheet
    // "Today · Mon 16 Nov" in Vietnam time.
    function todayLabel() {
        const [locale, format] = DATE_FORMATS[i18n.lang] || DATE_FORMATS.en;
        const parts = i18n.dateParts(new Date(), format, locale);
        return t('progress.today', {
            date: t('progress.date', { weekday: parts.weekday || '', day: parts.day || '', month: parts.month || '' }),
        });
    }

    function renderToday(day) {
        const [points, sentences, sum] = progress.days[day] || [0, 0, 0];
        els.today.textContent = todayLabel();
        els.points.textContent = i18n.formatNumber(points);
        i18n.text(els.pointsLabel, 'progress.points', { count: points });
        els.sentences.textContent = i18n.formatNumber(sentences);
        i18n.text(els.sentencesLabel, 'progress.sentences', { count: sentences });
        if (sentences) {
            els.average.textContent = `${i18n.formatNumber(Math.round(sum / sentences))}%`;
        } else {
            els.average.replaceChildren(el('span', { text: '–', attrs: { 'aria-hidden': 'true' } }),
                i18n.text(el('span', { className: 'visually-hidden' }), 'progress.noAverage'));
        }
        const streak = streakOf(progress, day);
        if (streak.count) i18n.text(els.streak, 'progress.streak', { count: streak.count });
        else i18n.text(els.streak, 'progress.noStreak');
        // No streak: how to start one; a streak not yet extended today: how to keep it.
        els.streakHint.hidden = streak.today;
        if (!streak.today) i18n.text(els.streakHint, streak.count ? 'progress.keepStreak' : 'progress.startStreak');
    }

    // The last 7 days, today last: the day's name, ✓ when a sentence was scored, and today outlined.
    function renderWeek(today) {
        const days = [];
        for (let back = 6; back >= 0; back -= 1) {
            const day = shiftDay(today, -back);
            const done = Boolean(progress.days[day] && progress.days[day][1] > 0);
            const said = [t(done ? 'progress.dayDone' : 'progress.dayMissed')];
            if (!back) said.push(t('progress.dayToday'));
            days.push(el('li', { className: `week-day${done ? ' is-done' : ''}${back ? '' : ' is-today'}` }, [
                el('span', { className: 'week-name', text: t(`progress.day.${weekdayOf(day)}`) }),
                el('span', { className: 'week-mark', attrs: { 'aria-hidden': 'true' } }, done ? [icon('check')] : []),
                el('span', { className: 'visually-hidden', text: `, ${said.join(', ')}` }),
            ]));
        }
        els.week.replaceChildren(...days);
    }

    // ✗ before ~, then the most recently missed.
    const reviewList = () => progress.words.slice().sort((a, b) => (b.s - a.s) || (b.at - a.at));

    function wordChip(entry) {
        const button = el('button', {
            className: 'word-chip',
            attrs: {
                type: 'button',
                'data-word': entry.w,
                'data-status': String(entry.s),
                lang: i18n.lang,
                'aria-label': t('progress.wordLabel', { word: entry.w, status: t(STATUS_KEYS[entry.s]) }),
            },
        }, [icon(MARK_ICONS[entry.s], `chip-mark chip-mark-${entry.s}`), el('span', { text: entry.w, attrs: { lang: 'en' } })]);
        return button;
    }

    // At most 12 chips, then "Show all (N)", which shows every word in place (F3).
    function renderWords() {
        const list = reviewList();
        const shown = expanded ? list : list.slice(0, WORDS_SHOWN);
        const chips = shown.map(wordChip);
        if (list.length > shown.length) {
            chips.push(el('button', {
                className: 'word-chip word-chip-more',
                text: t('progress.showAll', { count: list.length }),
                attrs: { type: 'button', 'data-more': '' },
            }));
        }
        els.chips.replaceChildren(...chips);
        els.chips.hidden = !list.length;
        let hint = list.length ? 'progress.reviewHint' : 'progress.reviewEmpty';
        if (wide.matches) hint += 'Wide';
        i18n.text(els.hint, hint);
        els.hint.classList.toggle('is-empty', !list.length);
    }

    function renderSheet(day) {
        renderToday(day);
        renderWeek(day);
        renderWords();
    }

    function render() {
        const day = i18n.dayKey();
        shownDay = day;
        renderChip(day);
        if (sheet.isOpen) renderSheet(day);
    }

    const sheet = new ui.Sheet(els.root, { closeOnBackdrop: true });
    const confirm = new ui.Confirm(els.confirm);

    function open() {
        progress = read();
        expanded = false;
        shownDay = i18n.dayKey();
        renderChip(shownDay);
        renderSheet(shownDay);
        sheet.open(chip);
    }

    // A word of the list, practised alone (F6): the sheet closes and the page takes over (focus too).
    function practise(word) {
        sheet.close({ restoreFocus: false });
        options.onPractiseWord(word);
    }

    // "New learner", confirmed: points, streak and words go; the page clears the draft and the tour's flag.
    function reset() {
        storage.remove(KEY);
        memory = null;
        progress = empty();
        expanded = false;
        confirm.close({ restoreFocus: false });
        sheet.close({ restoreFocus: false });
        render();
        resetListeners.forEach((fn) => {
            try {
                fn();
            } catch (err) {
                console.error(err);
            }
        });
    }

    chip.addEventListener('click', open);
    els.chips.addEventListener('click', (event) => {
        const button = event.target.closest('.word-chip');
        if (!button || !els.chips.contains(button)) return;
        if (!button.hasAttribute('data-more')) {
            practise(button.dataset.word);
            return;
        }
        expanded = true;
        renderWords();
        const first = els.chips.querySelectorAll('.word-chip[data-word]')[WORDS_SHOWN];
        ui.focus(first || els.chips.querySelector('.word-chip'));
    });
    els.newLearner.addEventListener('click', () => confirm.open(els.newLearner));
    els.delete.addEventListener('click', () => {
        if (confirm.isOpen) reset();
    });

    // Another tab of this browser scored, or cleared; a new day began (in Vietnam) while the page stayed open.
    window.addEventListener('storage', (event) => {
        if (event.key !== null && event.key !== KEY) return;
        progress = read();
        render();
    });
    const checkDay = () => {
        if (i18n.dayKey() !== shownDay) render();
    };
    setInterval(checkDay, 60000);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) checkDay();
    });
    i18n.onChange(render);
    wide.addEventListener('change', () => {
        if (sheet.isOpen) renderWords();
    });

    AIPT.result.onScored(scored);
    progress = read();
    render();

    AIPT.progress = {
        // onPractiseWord(word): a word of the list was tapped; the sheet is closed, focus is the page's.
        init(given) {
            options = { ...options, ...given };
        },
        // fn() after "New learner" cleared the progress.
        onReset(fn) {
            resetListeners.push(fn);
        },
        open,
    };
})();
