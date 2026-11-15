"""How well a run of the scoring pipeline labels the words of the evaluation set.

Every recording of the set says, for each word of the sentence it is scored
against, what the speaker actually did with that word (the truth):

    ok       the word was said as the dictionary says it
    error    the word was said, but with a learner's mistake (th -> t, a final
             consonant or plural -s dropped, ...)
    missing  the word was not said at all

The pipeline gives each word one of three labels, which the page shows as
colours: Correct (0, green), Almost (1, orange) and Needs work (2, red). A
label agrees with the truth when

    ok       -> Correct
    error    -> Almost or Needs work (the learner is told to look at the word)
    missing  -> Needs work

A recording the pipeline refuses as "no speech" gives its words no label at
all ("unscored"): the learner sees "We can't hear you" instead of a score.

Everything here is plain Python on the results of a run (harness.py), so the
numbers can be checked without the models.
"""
import math
import re
import statistics
from collections import Counter, defaultdict

LABELS = ('correct', 'almost', 'needs_work')
UNSCORED = 'unscored'
TRUTHS = ('ok', 'error', 'missing')
# Groups whose words count in the word-level totals. A recording of another
# sentence ('wrong') is judged as a whole: what the page should say there is
# "you read a different sentence", not a colour per word. Noise has no words.
WORD_GROUPS_EXCLUDED = ('wrong', 'no_speech')
# A sentence's score can be below 0 (more letters wrong than the sentence
# has); the page shows it as 0, in the last tier.
TIERS = ((80, 'excellent'), (60, 'good'), (-math.inf, 'keep_practising'))


def label_name(category) -> str:
    """The pipeline's category (0, 1, 2, as int or str) as a label name."""
    return LABELS[int(category)]


def agrees(truth: str, label: str) -> bool:
    if truth == 'ok':
        return label == 'correct'
    if truth == 'error':
        return label in ('almost', 'needs_work')
    if truth == 'missing':
        return label == 'needs_work'
    raise ValueError(f'unknown truth {truth!r}')


def flagged(label: str) -> bool:
    """The page draws the learner's attention to the word."""
    return label in ('almost', 'needs_work')


def tier(score: float) -> str:
    """What the result card says: Excellent (80+), Good job (60+), Keep practising."""
    return next(name for threshold, name in TIERS if score >= threshold)


def normalise_word(word: str) -> str:
    """A word as it is compared with what Whisper wrote: lower case, letters and digits only."""
    return re.sub(r'[^\w]', '', word.lower())


def wilson(successes: int, total: int, z: float = 1.96):
    """95% Wilson score interval of a proportion, as (low, high) in percent."""
    if total == 0:
        return (math.nan, math.nan)
    p = successes / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return (100 * max(0.0, centre - margin), 100 * min(1.0, centre + margin))


def mcnemar_p(fixed: int, broken: int) -> float:
    """Two-sided exact McNemar test: the chance of a split at least this uneven
    between words a change fixed and words it broke, if the change made no
    difference."""
    n = fixed + broken
    if n == 0:
        return 1.0
    k = min(fixed, broken)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def word_records(clips: dict, results: dict):
    """One record per word of every scored-or-refused clip that has a truth.

    clips: id -> manifest entry; results: id -> result of the run. Yields
    dicts with the clip's group and condition, the truth, the label (or
    UNSCORED), whether a letter of the word was drawn red, whether the word
    the alignment paired with it is the reference word itself (heard_same),
    and whether the reference word is anywhere in what Whisper wrote
    (in_transcript).
    """
    for clip_id, clip in clips.items():
        result = results.get(clip_id)
        if result is None or clip['expect'] != 'scored':
            continue
        words = clip['reference'].split()
        scored = result['outcome'] == 'scored'
        labels = result.get('labels') or []
        letters = result.get('letters') or []
        matched = result.get('matched') or []
        transcript = {normalise_word(w) for w in (result.get('heard') or '').split()}
        for index, (word, truth) in enumerate(zip(words, clip['truth'], strict=True)):
            record = {'clip': clip_id, 'group': clip['group'], 'condition': clip.get('condition', ''),
                      'index': index, 'word': word, 'truth': truth,
                      'error_type': (clip.get('errors') or {}).get(str(index), ''),
                      'label': UNSCORED, 'red_letter': None, 'heard_same': None, 'heard': None,
                      'in_transcript': None}
            if scored and index < len(labels):
                record['label'] = label_name(labels[index])
                record['in_transcript'] = normalise_word(word) in transcript
                if index < len(letters):
                    record['red_letter'] = '0' in letters[index]
                if index < len(matched):
                    record['heard'] = matched[index]
                    record['heard_same'] = normalise_word(matched[index]) == normalise_word(word)
            yield record


def counts_for(records) -> dict:
    """Totals of a set of word records (see summarise_words)."""
    confusion = {truth: Counter() for truth in TRUTHS}
    for r in records:
        confusion[r['truth']][r['label']] += 1
    scored = [r for r in records if r['label'] != UNSCORED]
    positives = [r for r in scored if r['truth'] != 'ok']
    negatives = [r for r in scored if r['truth'] == 'ok']
    tp = sum(flagged(r['label']) for r in positives)
    fp = sum(flagged(r['label']) for r in negatives)
    agree = sum(agrees(r['truth'], r['label']) for r in scored)
    ok_red = sum(bool(r['red_letter']) for r in negatives)
    error_red = sum(bool(r['red_letter']) for r in positives if r['truth'] == 'error')
    return {
        'words': len(records),
        'scored_words': len(scored),
        'unscored_words': len(records) - len(scored),
        'agree': agree,
        'confusion': {truth: dict(confusion[truth]) for truth in TRUTHS},
        'ok_words': len(negatives),
        'false_alarms': fp,
        'positives': len(positives),
        'caught': tp,
        'flagged': tp + fp,
        'ok_red_letter': ok_red,
        'error_words': sum(r['truth'] == 'error' for r in scored),
        'error_red_letter': error_red,
    }


def rates(c: dict) -> dict:
    """Percentages from counts_for(): agreement, false alarms, recall, precision, F1."""
    def pct(num, den):
        return 100 * num / den if den else math.nan
    recall = pct(c['caught'], c['positives'])
    precision = pct(c['caught'], c['flagged'])
    f1 = (2 * recall * precision / (recall + precision)
          if c['positives'] and c['flagged'] and recall + precision else math.nan)
    return {
        'agreement': pct(c['agree'], c['words']),
        'agreement_scored': pct(c['agree'], c['scored_words']),
        'false_alarm': pct(c['false_alarms'], c['ok_words']),
        'recall': recall,
        'precision': precision,
        'f1': f1,
        'ok_red_letter': pct(c['ok_red_letter'], c['ok_words']),
        'error_red_letter': pct(c['error_red_letter'], c['error_words']),
    }


def summarise_words(records) -> dict:
    """Word-level totals: over the words that count (see WORD_GROUPS_EXCLUDED),
    per group, per condition of the learner group and per kind of mistake."""
    records = list(records)
    counted = [r for r in records if r['group'] not in WORD_GROUPS_EXCLUDED]
    by_group = defaultdict(list)
    for r in records:
        by_group[r['group']].append(r)
    by_error = defaultdict(list)
    for r in counted:
        if r['truth'] == 'error':
            by_error[f"{r['group']}/{r['error_type'] or 'unspecified'}"].append(r)
    by_condition = defaultdict(list)
    for r in counted:
        by_condition[f"{r['group']}/{r['condition']}"].append(r)
    return {
        'all': counts_for(counted),
        'groups': {group: counts_for(rs) for group, rs in sorted(by_group.items())},
        'conditions': {key: counts_for(rs) for key, rs in sorted(by_condition.items())},
        'errors': {kind: error_breakdown(rs) for kind, rs in sorted(by_error.items())},
        'attribution': attribution(counted),
    }


def error_breakdown(records) -> dict:
    """For mistaken words: labels given, and whether Whisper wrote the reference
    word anyway (it "heard through" the mistake) or something else."""
    scored = [r for r in records if r['label'] != UNSCORED]
    return {
        'words': len(records),
        'labels': dict(Counter(r['label'] for r in records)),
        'caught': sum(flagged(r['label']) for r in scored),
        'heard_as_reference': sum(bool(r['heard_same']) for r in scored),
        'caught_when_heard_differently': sum(flagged(r['label']) for r in scored if r['heard_same'] is False),
        'heard_differently': sum(r['heard_same'] is False for r in scored),
        'red_letter': sum(bool(r['red_letter']) for r in scored),
    }


def attribution(records) -> dict:
    """Where wrong labels come from.

    A missed mistake whose word Whisper wrote as the reference word was lost
    by the recogniser (its language model "corrected" the learner); one that
    Whisper wrote differently was lost by the scoring, which still called it
    Correct. A false alarm on a word said right is the recogniser's when the
    word is nowhere in what Whisper wrote (misheard, or written otherwise:
    2:30, okay), and the alignment's or the scoring's when it is there but was
    paired with something else, or marked down anyway.
    """
    scored = [r for r in records if r['label'] != UNSCORED]
    misses = [r for r in scored if r['truth'] == 'error' and not flagged(r['label'])]
    alarms = [r for r in scored if r['truth'] == 'ok' and flagged(r['label'])]
    return {
        'missed_errors': len(misses),
        'missed_heard_as_reference': sum(bool(r['heard_same']) for r in misses),
        'missed_heard_differently': sum(r['heard_same'] is False for r in misses),
        'false_alarms': len(alarms),
        'false_alarm_misheard': sum(r['in_transcript'] is False for r in alarms),
        'false_alarm_heard_right': sum(bool(r['in_transcript']) for r in alarms),
    }


def expected_score(truth) -> float:
    """The score a sentence deserves: the share of its words said right."""
    return 100 * sum(t == 'ok' for t in truth) / len(truth)


def summarise_clips(clips: dict, results: dict) -> dict:
    """Outcomes (scored / no speech) and sentence scores, per group."""
    groups = defaultdict(lambda: {'clips': 0, 'outcome_right': 0, 'outcomes': Counter(), 'score_errors': [],
                                  'scores': [], 'expected': [], 'tier_right': 0, 'tiered': 0, 'red_clips': 0,
                                  'all_ok_clips': 0, 'all_ok_scored': 0})
    for clip_id, clip in clips.items():
        result = results.get(clip_id)
        if result is None:
            continue
        g = groups[clip['group']]
        g['clips'] += 1
        g['outcomes'][result['outcome']] += 1
        g['outcome_right'] += result['outcome'] == clip['expect']
        if clip['expect'] != 'scored' or result['outcome'] != 'scored':
            continue
        expected = expected_score(clip['truth'])
        score = float(result['score'])
        g['scores'].append(score)
        g['expected'].append(expected)
        g['score_errors'].append(score - expected)
        g['tiered'] += 1
        g['tier_right'] += tier(score) == tier(expected)
        if all(t == 'ok' for t in clip['truth']):
            g['all_ok_scored'] += 1
            g['red_clips'] += any('0' in letters for letters in result.get('letters') or [])
    for clip_id, clip in clips.items():
        if clip_id in results and clip['expect'] == 'scored' and all(t == 'ok' for t in clip['truth']):
            groups[clip['group']]['all_ok_clips'] += 1
    out = {}
    for name, g in sorted(groups.items()):
        errors = g['score_errors']
        out[name] = {
            'clips': g['clips'], 'outcome_right': g['outcome_right'], 'outcomes': dict(g['outcomes']),
            'scored': len(g['scores']),
            'mean_score': statistics.mean(g['scores']) if g['scores'] else math.nan,
            'mean_expected': statistics.mean(g['expected']) if g['expected'] else math.nan,
            'bias': statistics.mean(errors) if errors else math.nan,
            'mae': statistics.mean(abs(e) for e in errors) if errors else math.nan,
            'tier_right': g['tier_right'], 'tiered': g['tiered'],
            'all_ok_clips': g['all_ok_clips'], 'all_ok_scored': g['all_ok_scored'], 'red_clips': g['red_clips'],
        }
    return out


def compare_words(clips: dict, before: dict, after: dict) -> dict:
    """Words whose label went from wrong to right (fixed) or right to wrong
    (broken) between two runs, over the words that count, with examples."""
    old = {(r['clip'], r['index']): r for r in word_records(clips, before) if r['group'] not in WORD_GROUPS_EXCLUDED}
    new = {(r['clip'], r['index']): r for r in word_records(clips, after) if r['group'] not in WORD_GROUPS_EXCLUDED}
    fixed, broken, changed = [], [], 0
    for key in sorted(old.keys() & new.keys()):
        a, b = old[key], new[key]
        if a['label'] != b['label']:
            changed += 1
        was = a['label'] != UNSCORED and agrees(a['truth'], a['label'])
        now = b['label'] != UNSCORED and agrees(b['truth'], b['label'])
        if now and not was:
            fixed.append((a, b))
        elif was and not now:
            broken.append((a, b))
    return {'words': len(old.keys() & new.keys()), 'changed': changed, 'fixed': fixed, 'broken': broken,
            'p': mcnemar_p(len(fixed), len(broken))}
