"""Score the evaluation set with this checkout's pipeline and say how right its labels are.

    python -m evaluation.harness run --out FILE [--only PREFIX] [--every N]
    python -m evaluation.harness rescore FILE --out FILE
    python -m evaluation.harness report FILE [--md FILE] [--against FILE --against-name NAME]
    python -m evaluation.harness report --committed
    python -m evaluation.harness compare BEFORE AFTER

run      scores every clip of evaluation/clips.json the way the server does
         (lambdaSpeechToScore.score: decoding, the silence check, Whisper, the
         alignment and the scoring), then the text simulation over the bank
         (textsim.py). The results keep what Whisper heard in each clip.
rescore  scores what Whisper heard again, without Whisper: enough to judge a
         change to the alignment or the scoring, in seconds.
report   the report (Markdown) of a results file, optionally against another;
         --committed writes evaluation/report.md from REPORT below.
compare  the words a change fixed and broke, between two results files.

Run from the repository root, with the models where the app finds them
(WHISPER_MODEL, PIPER_MODEL_DIR) and FFMPEG_BINARY when ffmpeg is not on the
PATH. Inside an image of the app, mount evaluation/ (and the bank) into /app:
see evaluation/README.md.
"""
import argparse
import json
import logging
import math
import os
import platform
import statistics
import subprocess
import sys
import time
from collections import defaultdict

from evaluation import metrics

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MANIFEST = os.path.join(HERE, 'clips.json')
FORMAT = 1
# The report kept in the repository (evaluation/report.md): the run of the
# pipeline in this checkout, against the run it should be judged against.
# tests/test_evaluation.py checks that the run is what this checkout's
# alignment and scoring make of what Whisper heard, and that report.md is its
# report. A change to the scoring adds its own run here and points REPORT at it.
REPORT = {'run': 'runs/phase3-2-alignment.json', 'against': 'runs/phase2-1c4813c.json',
          'against_name': 'phase 2 (1c4813c)', 'markdown': 'report.md'}


def load_manifest(path=MANIFEST):
    with open(path, encoding='utf-8') as f:
        return {clip['id']: clip for clip in json.load(f)['clips']}


def load_results(path):
    with open(path, encoding='utf-8') as f:
        doc = json.load(f)
    if doc.get('format') != FORMAT:
        raise SystemExit(f'{path}: results format {doc.get("format")}, this harness reads {FORMAT}')
    return doc


def save(doc, path):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write('\n')


def _app():
    """Import the app's modules as a worker does: logging first (CLAUDE.md),
    then ONNX Runtime through piperTTS, then the scoring."""
    if 'lambdaSpeechToScore' in sys.modules:
        return sys.modules['lambdaSpeechToScore']
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import logging_setup
    logging_setup.configure()
    import piperTTS
    if hasattr(piperTTS, 'import_onnxruntime'):
        piperTTS.import_onnxruntime()
    import lambdaSpeechToScore
    return lambdaSpeechToScore


def _git(*args):
    try:
        return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, timeout=10,
                              check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ''


def _cpu_flags():
    try:
        with open('/proc/cpuinfo', encoding='utf-8') as f:
            flags = next((line.split(':', 1)[1].split() for line in f if line.startswith('flags')), [])
        return ' '.join(flag for flag in ('avx', 'avx2', 'fma', 'avx512f') if flag in flags) or 'no AVX'
    except OSError:
        return ''


def pipeline_info():
    """What produced a run: the code, the recogniser and the machine."""
    info = {'commit': os.environ.get('GIT_SHA') or _git('rev-parse', '--short', 'HEAD') or 'unknown',
            'python': platform.python_version(), 'platform': platform.platform(terse=True),
            'machine': platform.machine(), 'cpu_flags': _cpu_flags(), 'cpus': os.cpu_count()}
    # The app's modules are the top-level ones (Dockerfile: COPY *.py).
    if info['commit'] != 'unknown' and _git('status', '--porcelain', '--untracked-files=no', '--', ':(glob)*.py'):
        info['commit'] += ' (with uncommitted changes)'
    for module in ('faster_whisper', 'ctranslate2', 'transformers', 'torch', 'numpy'):
        if module in sys.modules:
            info[module] = getattr(sys.modules[module], '__version__', '?')
    for name in ('WHISPER_COMPUTE_TYPE', 'WHISPER_CPU_THREADS', 'OMP_NUM_THREADS'):
        if os.environ.get(name):
            info[name] = os.environ[name]
    return info


class Recorder:
    """Keeps what the recogniser heard for each recording (its transcript and
    word times), by wrapping the ASR model's processAudio."""

    def __init__(self, asr):
        self.asr = asr
        self.heard = None
        original = asr.processAudio

        def processAudio(audio):
            self.heard = None
            original(audio)
            self.heard = {'samples': int(audio.shape[-1]), 'transcript': asr.getTranscript(),
                          'words': [[w.get('word', ''), round(float(w['start_ts']), 1), round(float(w['end_ts']), 1)]
                                    for w in asr.getWordLocations()]}

        asr.processAudio = processAudio


class ReplayASR:
    """Stands in for Whisper with what it heard in a recording (Recorder)."""

    def __init__(self):
        self.heard = None

    def processAudio(self, audio):
        pass

    def getTranscript(self):
        return self.heard['transcript']

    def getWordLocations(self):
        return [{'word': word, 'start_ts': start, 'end_ts': end, 'tag': 'processed'}
                for word, start, end in self.heard['words']]


def response_fields(response):
    """What a run keeps of the page's answer, per word of the sentence."""
    return {'score': int(response['pronunciation_accuracy']),
            'labels': [int(c) for c in response['pair_accuracy_category'].split()],
            'letters': response['is_letter_correct_all_words'].split(),
            'matched': response['matched_transcripts'].split(),
            'heard': response['real_transcript'].strip()}


def run_clips(clips, progress=True, warm_up=None):
    """Score each clip as the server does. warm_up: a clip of clear speech to
    score first, unrecorded (default: the first clean reading of clips)."""
    lambdaSpeechToScore = _app()
    import audioPreprocessing
    decode_errors = tuple(getattr(audioPreprocessing, name) for name in ('AudioDecodeError', 'AudioTooLongError')
                          if hasattr(audioPreprocessing, name))
    recorder = Recorder(lambdaSpeechToScore._get_trainer('en').asr_model)

    def read(clip):
        with open(os.path.join(HERE, clip['file']), 'rb') as f:
            return f.read()

    # The first full pass pays Whisper's first forward pass (and, before phase
    # 3, the alignment's JIT compilation), as a worker's warm-up does.
    if warm_up is None:
        warm_up = next((c for c in clips.values() if c.get('condition') == 'clean'), None)
    if warm_up is not None:
        lambdaSpeechToScore.score(warm_up['reference'], read(warm_up), 'en')
    results, seconds = {}, []
    for n, (clip_id, clip) in enumerate(clips.items(), start=1):
        recorder.heard = None
        started = time.perf_counter()
        result = {'reference': clip['reference']}
        try:
            result.update({'outcome': 'scored', **response_fields(
                lambdaSpeechToScore.score(clip['reference'], read(clip), 'en'))})
        except lambdaSpeechToScore.NoSpeechError:
            result['outcome'] = 'no_speech'
        except decode_errors as e:
            result.update({'outcome': 'bad_audio', 'error': repr(e)})
        seconds.append(time.perf_counter() - started)
        if recorder.heard is not None:
            result['asr'] = recorder.heard
        results[clip_id] = result
        if progress:
            print(f"[{n}/{len(clips)}] {clip_id}: {result['outcome']} {result.get('score', '')} "
                  f"{result.get('heard', '')!r}", file=sys.stderr, flush=True)
    timing = {'clips': len(seconds), 'median_s': round(statistics.median(seconds), 2),
              'total_s': round(sum(seconds), 1)}
    return results, timing


def rescore(clips, results):
    """Score what Whisper heard in each clip again, with this checkout's
    alignment and scoring. A clip Whisper never heard (refused by the silence
    check, or unreadable) keeps its outcome."""
    _app()
    import pronunciationTrainer
    import RuleBasedModels

    from evaluation import textsim
    asr = ReplayASR()
    trainer = pronunciationTrainer.PronunciationTrainer(asr, RuleBasedModels.EngPhonemConverter())
    out = {}
    for clip_id, old in results.items():
        result = {'reference': clips[clip_id]['reference'] if clip_id in clips else old['reference']}
        heard = old.get('asr')
        if heard is None:
            result['outcome'] = old['outcome']
        elif not any(ch.isalnum() for ch in heard['transcript']):
            result['outcome'] = 'no_speech'
        else:
            asr.heard = heard
            response = textsim.score_transcript(trainer, result['reference'], textsim.silence(heard['samples']))
            result.update({'outcome': 'scored', **response_fields(response)})
        if heard is not None:
            result['asr'] = heard
        out[clip_id] = result
    return out


def text_section(every=1, check_every=25):
    _app()
    from evaluation import textsim
    os.chdir(ROOT)  # the bank is read from databases/
    return textsim.run(textsim.bank_sentences(), every=every, check_every=check_every, progress=True)


# ---------------------------------------------------------------- the report
def pct(value, digits=1):
    return '-' if value is None or (isinstance(value, float) and math.isnan(value)) else f'{value:.{digits}f}%'


def frac(num, den, interval=False):
    if not den:
        return '-'
    text = f'{num}/{den} ({100 * num / den:.1f}%)'
    if interval:
        low, high = metrics.wilson(num, den)
        text += f' [{low:.1f}-{high:.1f}]'
    return text


def num(value, digits=1):
    return '-' if value is None or (isinstance(value, float) and math.isnan(value)) else f'{value:.{digits}f}'


def table(header, rows):
    lines = ['| ' + ' | '.join(header) + ' |', '|' + '|'.join('---' for _ in header) + '|']
    lines += ['| ' + ' | '.join(str(cell) for cell in row) + ' |' for row in rows]
    return '\n'.join(lines)


GROUP_TITLES = {
    'bank': 'Bank sentences (phase 2 parity set): clean, slow, fast, noise, child-like voice, misspelled',
    'learner': "Vietnamese learners' typical mistakes, made in the phonemes, and the same sentences read clean",
    'edit': 'A word left out, the reading stopped early, a word repeated, a filler, a fresh start',
    'normalisation': 'Read correctly; Whisper may write the words otherwise (2:30, 3-day, OK, Mr., colour, %)',
    'soft_tap': 'A short phrase spoken softly after a much louder tap on Record',
    'wrong': 'A clean reading scored against another sentence',
    'no_speech': 'Noise alone, encoded by ffmpeg or recorded by Chrome as the page records',
}


def summary(clips, doc):
    results = doc['clips']
    records = list(metrics.word_records(clips, results))
    words = metrics.summarise_words(records)
    sentences = metrics.summarise_clips(clips, results)
    return records, words, sentences


def headline(clips, doc):
    """The few numbers a change should move, as {name: (count, total)} or values."""
    records, words, sentences = summary(clips, doc)
    a = words['all']
    present = [c for c in clips.values() if c['id'] in doc['clips']]
    speech = [c for c in present if c['expect'] == 'scored' and c['group'] not in ('wrong',)]
    speech_scored = sum(doc['clips'][c['id']]['outcome'] == 'scored' for c in speech)
    noise = [c for c in present if c['expect'] == 'no_speech']
    noise_refused = sum(doc['clips'][c['id']]['outcome'] == 'no_speech' for c in noise)
    # Readings without a mistake, under any condition (noise, speed, voice).
    clean = [c for c in clips.values() if c['expect'] == 'scored' and c['group'] in ('bank', 'learner', 'normalisation')
             and all(t == 'ok' for t in c['truth']) and doc['clips'].get(c['id'], {}).get('outcome') == 'scored']
    clean_red = sum(any('0' in x for x in doc['clips'][c['id']]['letters']) for c in clean)
    clean_all_correct = sum(all(x == 0 for x in doc['clips'][c['id']]['labels']) for c in clean)
    errors = [r for r in records if r['group'] not in metrics.WORD_GROUPS_EXCLUDED and r['truth'] == 'error'
              and r['label'] != metrics.UNSCORED]
    missing = [r for r in records if r['group'] not in metrics.WORD_GROUPS_EXCLUDED and r['truth'] == 'missing'
               and r['label'] != metrics.UNSCORED]
    deviations = [abs(float(doc['clips'][c['id']]['score']) - metrics.expected_score(c['truth']))
                  for c in clips.values() if c['expect'] == 'scored' and c['group'] not in ('wrong',)
                  and doc['clips'].get(c['id'], {}).get('outcome') == 'scored']
    return {
        'speech_scored': (speech_scored, len(speech)),
        'noise_refused': (noise_refused, len(noise)),
        'agree': (a['agree'], a['words']),
        'ok_correct': (a['ok_words'] - a['false_alarms'], a['ok_words']),
        'errors_caught': (sum(metrics.flagged(r['label']) for r in errors), len(errors)),
        'missing_caught': (sum(r['label'] == 'needs_work' for r in missing), len(missing)),
        'precision': (a['caught'], a['flagged']),
        'clean_all_correct': (clean_all_correct, len(clean)),
        'clean_red_letter': (clean_red, len(clean)),
        'ok_red_letter': (a['ok_red_letter'], a['ok_words']),
        'score_mae': statistics.mean(deviations) if deviations else math.nan,
    }


HEADLINE_ROWS = [
    ('speech_scored', 'Recordings of speech scored (not refused as "no speech")', True),
    ('noise_refused', 'Recordings of noise refused as "no speech"', True),
    ('agree', 'Word labels that agree with the truth (all counted words)', True),
    ('ok_correct', 'Words said right and labelled Correct', True),
    ('errors_caught', "Learners' mistakes flagged (Almost or Needs work)", True),
    ('missing_caught', 'Words left out labelled Needs work', True),
    ('precision', 'Flags that point at a real mistake or missing word (precision)', True),
    ('clean_all_correct', 'Readings without a mistake with every word Correct', True),
    ('clean_red_letter', 'Readings without a mistake with a red letter somewhere', True),
    ('ok_red_letter', 'Words said right with a red letter', True),
]


def render(clips, doc, against=None, against_name='other'):
    records, words, sentences = summary(clips, doc)
    head = headline(clips, doc)
    info = doc['pipeline']
    out = ['# Scoring evaluation', '']
    machine = (f"Python {info.get('python')} on {info.get('platform')} ({info.get('cpus')} CPUs"
               f"{', ' + info['cpu_flags'] if info.get('cpu_flags') else ''}); "
               + ', '.join(f'{k} {info[k]}' for k in ('faster_whisper', 'ctranslate2', 'transformers', 'torch')
                           if k in info))
    if info.get('name'):
        heard = info.get('asr_commit', info.get('commit'))
        out.append(f"Pipeline: {info['name']}. What Whisper heard comes from a run of `{heard}`: {machine}.")
    else:
        out.append(f"Pipeline at `{info.get('commit')}`; {machine}.")
    timing = doc.get('timing')
    if timing:
        added = doc.get('added', [])
        clips_timed = timing['clips'] + sum(a.get('clips', 0) for a in added)
        total = timing['total_s'] + sum(a.get('total_s', 0) for a in added)
        out.append(f"{clips_timed} recordings, {timing['median_s']} s each (median), {total:.1f} s in all, "
                   'one at a time.')
    out += ['', 'How to read it: `evaluation/README.md`. Each recording says what was said, word by word; '
                'a label agrees with the truth when a word said right is Correct, a mistaken word Almost or '
                'Needs work, and a word left out Needs work. Ranges in brackets are 95% intervals.', '']
    rows = []
    for key, title, interval in HEADLINE_ROWS:
        n, d = head[key]
        row = [title, frac(n, d, interval)]
        if against is not None:
            n2, d2 = headline(clips, against)[key]
            row.insert(1, frac(n2, d2))
        rows.append(row)
    mae_row = ['Mean distance between a sentence score and the share of its words said right',
               num(head['score_mae']) + ' points']
    if against is not None:
        mae_row.insert(1, num(headline(clips, against)['score_mae']) + ' points')
    rows.append(mae_row)
    out += ['## Summary', '',
            table(['', against_name, 'this run'] if against is not None else ['', 'this run'], rows), '']

    a = words['all']
    out += ['## Word labels against the truth', '',
            f"Every counted word ({a['words']}: all groups but `wrong` and `no_speech`).", '',
            table(['truth', 'Correct', 'Almost', 'Needs work', 'no speech'],
                  [[truth] + [a['confusion'][truth].get(label, 0) for label in metrics.LABELS + (metrics.UNSCORED,)]
                   for truth in metrics.TRUTHS]), '']

    rows = []
    for group in GROUP_TITLES:
        if group not in sentences:
            continue
        s = sentences[group]
        g = words['groups'].get(group)
        r = metrics.rates(g) if g else {}
        rows.append([f'`{group}`', s['clips'], frac(s['outcome_right'], s['clips']),
                     pct(r.get('agreement')) if g and group not in metrics.WORD_GROUPS_EXCLUDED else '-',
                     frac(g['false_alarms'], g['ok_words']) if g and g['ok_words'] else '-',
                     frac(g['caught'], g['positives']) if g and g['positives'] else '-',
                     num(s['mean_score']), num(s['mean_expected']), num(s['bias'])])
    out += ['## By group', '', '\n'.join(f'- `{g}`: {t}' for g, t in GROUP_TITLES.items() if g in sentences), '',
            table(['group', 'clips', 'outcome as expected', 'labels agree', 'words said right but flagged',
                   'mistakes and missing words flagged', 'mean score', 'deserved', 'bias'], rows), '',
            'The deserved score of a reading is the share of its words said right; bias is the mean of '
            'score minus deserved score.', '']

    rows = []
    for key, c in words['conditions'].items():
        r = metrics.rates(c)
        rows.append([f'`{key}`', c['words'], frac(c['false_alarms'], c['ok_words']),
                     frac(c['caught'], c['positives']) if c['positives'] else '-', frac(c['unscored_words'], c['words'])
                     if c['unscored_words'] else '-', pct(r['ok_red_letter'])])
    out += ['## By condition', '',
            table(['group/condition', 'words', 'said right but flagged', 'mistakes flagged', 'not scored',
                   'said right with a red letter'], rows), '']

    rows = []
    for kind, e in words['errors'].items():
        scored = e['words'] - e['labels'].get(metrics.UNSCORED, 0)
        rows.append([f'`{kind}`', e['words'], frac(e['caught'], scored), frac(e['heard_as_reference'], scored),
                     frac(e['caught_when_heard_differently'], e['heard_differently']), frac(e['red_letter'], scored),
                     ' / '.join(str(e['labels'].get(label, 0)) for label in metrics.LABELS)])
    out += ["## Learners' mistakes by kind", '',
            'A mistake is caught when its word is Almost or Needs work. "Heard as the word" means Whisper wrote '
            'the reference word anyway: its language model corrected the learner, and no scoring of its text '
            'can catch that mistake.', '',
            table(['group/mistake', 'words', 'caught', 'heard as the word', 'caught when heard otherwise',
                   'a red letter', 'Correct / Almost / Needs work'], rows), '']

    at = words['attribution']
    out += ['## Where wrong labels come from', '',
            f"- Mistakes labelled Correct: {at['missed_errors']}; Whisper wrote the reference word for "
            f"{at['missed_heard_as_reference']} of them (lost by the recogniser) and something else for "
            f"{at['missed_heard_differently']} (lost by the scoring, which still said Correct).",
            f"- Words said right but flagged: {at['false_alarms']}; for {at['false_alarm_misheard']} the word is "
            f"nowhere in what Whisper wrote (misheard, or written otherwise: 2:30, okay), for "
            f"{at['false_alarm_heard_right']} it is there and the alignment or the scoring marked it down.", '']

    rows = []
    for clip_id, clip in clips.items():
        if clip['group'] not in ('no_speech', 'soft_tap'):
            continue
        r = doc['clips'].get(clip_id)
        if r is None:
            continue
        rows.append([f'`{clip_id}`', clip['condition'], clip['expect'].replace('_', ' '),
                     r['outcome'].replace('_', ' ') + ('' if r['outcome'] == clip['expect'] else ' **(wrong)**'),
                     repr(r.get('heard', ''))[1:-1] if r.get('heard') else '', r.get('score', '')])
    out += ['## Noise and soft speech, recording by recording', '',
            table(['clip', 'condition', 'expected', 'outcome', 'heard', 'score'], rows), '']

    text = doc.get('text')
    if text:
        t = text['totals']
        rows = []
        for variant in ('exact', 'plain', 'drop', 'add', 'repeat', 'substitute'):
            v = t.get(variant)
            if not v:
                continue
            rows.append([f'`{variant}`', v['sentences'], frac(v['sentences_all_right'], v['sentences']),
                         frac(v['false_alarms'], v['ok_words']),
                         frac(v.get('sentences_with_neighbour_flagged', 0), v['sentences'])
                         if variant in ('drop', 'add', 'repeat', 'substitute') else '-',
                         frac(v.get('target_flagged', 0), v.get('targets', 0)) if v.get('targets') else '-',
                         frac(v['sentences_with_ok_red_letter'], v['sentences'])])
        out += ['## Text simulation over the bank', '',
                f"Known transcripts for {text['sentences']} bank sentences, without audio (`textsim.py`): the "
                'alignment and the scoring alone.', '',
                table(['transcript', 'sentences', 'every word right', 'words said right but flagged',
                       'a neighbour of the changed word flagged', 'changed word flagged',
                       'a red letter on a word said right'], rows), '']

    examples, alarms = [], []
    shown = {'miss': defaultdict(int), 'alarm': defaultdict(int)}
    for r in records:
        if r['group'] in metrics.WORD_GROUPS_EXCLUDED or r['label'] == metrics.UNSCORED:
            continue
        heard = doc['clips'][r['clip']].get('heard', '')
        # A few of each group, in the set's order.
        if r['truth'] == 'error' and not metrics.flagged(r['label']) and shown['miss'][r['group']] < 4:
            shown['miss'][r['group']] += 1
            examples.append(f"- `{r['clip']}` {r['error_type']}: said \"{clips[r['clip']]['said']}\", heard "
                            f"\"{heard}\": **{r['word']}** labelled {r['label']}")
        if r['truth'] == 'ok' and metrics.flagged(r['label']) and shown['alarm'][r['group']] < 3:
            shown['alarm'][r['group']] += 1
            alarms.append(f"- `{r['clip']}` ({r['condition']}): heard \"{heard}\": **{r['word']}** labelled "
                          f"{r['label']} (aligned with \"{r['heard']}\")")
    out += ['## Examples', '', 'Mistakes labelled Correct:', ''] + (examples or ['- none']) + \
           ['', 'Words said right but flagged:', ''] + (alarms or ['- none']) + ['']

    if against is not None:
        change = metrics.compare_words(clips, against['clips'], doc['clips'])
        _, old_words, old_sentences = summary(clips, against)
        rows = []
        for group in GROUP_TITLES:
            if group not in sentences or group not in old_sentences:
                continue
            row = [f'`{group}`']
            for key in ('outcome', 'agree', 'alarms', 'caught', 'score'):
                cells = []
                for w, s in ((old_words, old_sentences), (words, sentences)):
                    g, c = w['groups'].get(group), s[group]
                    if key == 'outcome':
                        cells.append(pct(100 * c['outcome_right'] / c['clips']))
                    elif key == 'agree':
                        cells.append(pct(metrics.rates(g)['agreement'])
                                     if g and group not in metrics.WORD_GROUPS_EXCLUDED else '-')
                    elif key == 'alarms':
                        cells.append(pct(metrics.rates(g)['false_alarm']) if g and g['ok_words'] else '-')
                    elif key == 'caught':
                        cells.append(pct(metrics.rates(g)['recall']) if g and g['positives'] else '-')
                    else:
                        cells.append(num(c['mean_score']))
                row.append(' → '.join(cells))
            rows.append(row)
        out += [f'## Against {against_name}', '',
                f"Of {change['words']} counted words, {change['changed']} changed label; {len(change['fixed'])} went "
                f"from wrong to right and {len(change['broken'])} from right to wrong (McNemar p = "
                f"{change['p']:.3g}).", '',
                table(['group', 'outcome as expected', 'labels agree', 'said right but flagged',
                       'mistakes and missing words flagged', 'mean score'], rows), '',
                f'Each cell: {against_name} → this run.', '']
        for title, pairs in (('Wrong before, right now', change['fixed']), ('Right before, wrong now', change['broken'])):
            lines = [f"- `{old['clip']}` **{old['word']}** ({old['truth']}): {old['label']} → {new['label']}"
                     for old, new in pairs[:10]]
            out += [f'{title} ({len(pairs)}; the first 10):', ''] + (lines or ['- none']) + ['']
    return '\n'.join(out).rstrip() + '\n'


def committed_report():
    """evaluation/report.md as REPORT says it should read."""
    doc = load_results(os.path.join(HERE, REPORT['run']))
    against = load_results(os.path.join(HERE, REPORT['against'])) if REPORT.get('against') else None
    return render(load_manifest(), doc, against, REPORT.get('against_name', ''))


def describe_change(clips, before, after, limit=40):
    change = metrics.compare_words(clips, before, after)
    lines = [f"{change['words']} counted words; {change['changed']} changed label; fixed {len(change['fixed'])}, "
             f"broke {len(change['broken'])} (McNemar p = {change['p']:.3g})"]
    for title, pairs in (('fixed', change['fixed']), ('broken', change['broken'])):
        for old, new in pairs[:limit]:
            lines.append(f"  {title}: {old['clip']} word {old['index']} {old['word']!r} ({old['truth']}): "
                         f"{old['label']} -> {new['label']}")
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('run')
    p.add_argument('--out', required=True)
    p.add_argument('--name', default='', help='what the run is of, for the report')
    p.add_argument('--only', default='', help='only clips whose id starts with this')
    p.add_argument('--every', type=int, default=1, help='text simulation: every Nth bank sentence (0: none)')
    p = sub.add_parser('rescore')
    p.add_argument('results')
    p.add_argument('--out', required=True)
    p.add_argument('--name', default='', help='what the run is of, for the report')
    p.add_argument('--every', type=int, default=None, help='text simulation too, every Nth bank sentence')
    p = sub.add_parser('report')
    p.add_argument('results', nargs='?')
    p.add_argument('--committed', action='store_true', help='write evaluation/report.md from REPORT')
    p.add_argument('--md', default='')
    p.add_argument('--against', default='')
    p.add_argument('--against-name', default='')
    p = sub.add_parser('compare')
    p.add_argument('before')
    p.add_argument('after')
    p = sub.add_parser('merge', help="add a run's clips (recordings new to the set) to a run of the same pipeline")
    p.add_argument('base')
    p.add_argument('addition')
    p.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    clips = load_manifest()
    _app()
    # One "scored" line per clip would drown the progress.
    logging.getLogger('aipt').setLevel(logging.WARNING)

    if args.command == 'run':
        chosen = {k: v for k, v in clips.items() if k.startswith(args.only)}
        results, timing = run_clips(chosen, warm_up=next(c for c in clips.values() if c['condition'] == 'clean'))
        doc = {'format': FORMAT, 'pipeline': {**pipeline_info(), **({'name': args.name} if args.name else {})},
               'timing': timing, 'clips': results}
        if args.every:
            doc['text'] = text_section(every=args.every)
        save(doc, args.out)
        print(render(clips, doc))
    elif args.command == 'rescore':
        old = load_results(args.results)
        # Whisper and the machine are those of the old run; the labels are this checkout's.
        pipeline = {**old['pipeline'], 'commit': pipeline_info()['commit'],
                    'asr_commit': old['pipeline'].get('asr_commit', old['pipeline'].get('commit'))}
        pipeline.pop('name', None)
        if args.name:
            pipeline['name'] = args.name
        doc = {'format': FORMAT, 'pipeline': pipeline, 'clips': rescore(clips, old['clips'])}
        for key in ('timing', 'added'):  # how long Whisper's run took
            if key in old:
                doc[key] = old[key]
        if args.every:
            doc['text'] = text_section(every=args.every)
        elif 'text' in old:
            doc['text'] = old['text']
        save(doc, args.out)
        print(describe_change(clips, old['clips'], doc['clips']))
    elif args.command == 'report' and args.committed:
        with open(os.path.join(HERE, REPORT['markdown']), 'w', encoding='utf-8', newline='\n') as f:
            f.write(committed_report())
    elif args.command == 'report':
        if not args.results:
            parser.error('report needs a results file, or --committed')
        doc = load_results(args.results)
        against = load_results(args.against) if args.against else None
        text = render(clips, doc, against, args.against_name or os.path.basename(args.against))
        if args.md:
            with open(args.md, 'w', encoding='utf-8', newline='\n') as f:
                f.write(text)
        else:
            print(text)
    elif args.command == 'compare':
        before, after = load_results(args.before), load_results(args.after)
        print(describe_change(clips, before['clips'], after['clips']))
    elif args.command == 'merge':
        base, addition = load_results(args.base), load_results(args.addition)
        asr = [doc['pipeline'].get('asr_commit', doc['pipeline'].get('commit')) for doc in (base, addition)]
        if asr[0] != asr[1] or base['pipeline'].get('platform') != addition['pipeline'].get('platform'):
            raise SystemExit(f'not the same pipeline: {asr[0]} and {asr[1]}')
        base['clips'].update(addition['clips'])
        base['clips'] = {k: base['clips'][k] for k in clips if k in base['clips']}  # the manifest's order
        base.setdefault('added', []).append(addition.get('timing', {}))
        save(base, args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
