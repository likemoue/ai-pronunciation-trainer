"""The evaluation harness (evaluation/): its arithmetic, its set of recordings,
and the report kept in the repository, which must be the report of this code."""
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import ROOT, requires_ffmpeg

from evaluation import harness, metrics

MANIFEST = harness.load_manifest()


# ---------------------------------------------------------------- arithmetic
@pytest.mark.parametrize('truth,label,expected', [
    ('ok', 'correct', True), ('ok', 'almost', False), ('ok', 'needs_work', False),
    ('error', 'correct', False), ('error', 'almost', True), ('error', 'needs_work', True),
    ('missing', 'correct', False), ('missing', 'almost', False), ('missing', 'needs_work', True),
])
def test_a_label_agrees_with_the_truth(truth, label, expected):
    assert metrics.agrees(truth, label) is expected


def test_the_pipelines_categories_are_the_pages_labels():
    # static/javascript/app.js: CATEGORY_TEXT = ['Correct', 'Almost', 'Needs work']
    assert [metrics.label_name(c) for c in ('0', 1, '2')] == ['correct', 'almost', 'needs_work']


def test_intervals_and_the_mcnemar_test():
    low, high = metrics.wilson(0, 10)
    assert low == 0 and 25 < high < 35
    low, high = metrics.wilson(50, 100)
    assert 40 < low < 50 < high < 60
    assert math.isnan(metrics.wilson(0, 0)[0])
    assert metrics.mcnemar_p(5, 5) == 1.0
    assert metrics.mcnemar_p(10, 0) == pytest.approx(2 / 1024)
    assert metrics.mcnemar_p(0, 0) == 1.0


def _clip(clip_id, reference, truth, group='learner', expect='scored', errors=None):
    return {'id': clip_id, 'reference': reference, 'truth': truth, 'group': group, 'condition': 'c',
            'expect': expect, 'errors': errors or {}}


def test_word_records_count_false_alarms_catches_and_their_causes():
    clips = {c['id']: c for c in [
        _clip('a', 'I think so.', ['ok', 'error', 'ok'], errors={'1': 'th_t'}),
        _clip('b', 'We had lunch.', ['ok', 'missing', 'ok']),
        _clip('c', 'Go home now.', ['ok', 'ok', 'ok']),
        _clip('d', 'Hello there.', ['ok', 'ok']),
        _clip('n', 'Noise.', ['missing'], group='no_speech', expect='no_speech'),
    ]}
    results = {
        # Whisper wrote "think": the mistake is lost by the recogniser.
        'a': {'outcome': 'scored', 'labels': [0, 0, 0], 'letters': ['1', '11111', '11'],
              'matched': ['I', 'think', 'so.'], 'heard': 'I think so.'},
        # The missing word is caught, and its neighbour flagged although Whisper wrote it.
        'b': {'outcome': 'scored', 'labels': [0, 2, 1], 'letters': ['11', '000', '1110'],
              'matched': ['We', '-', 'lunch.'], 'heard': 'We lunch.'},
        # A word said right, misheard.
        'c': {'outcome': 'scored', 'labels': [0, 2, 0], 'letters': ['11', '0000', '111'],
              'matched': ['Go', 'phone', 'now.'], 'heard': 'Go phone now.'},
        'd': {'outcome': 'no_speech'},
        'n': {'outcome': 'no_speech'},
    }
    records = list(metrics.word_records(clips, results))
    assert len(records) == 11  # the noise clip has no words to label
    words = metrics.summarise_words(records)
    a = words['all']
    assert a['words'] == 11 and a['scored_words'] == 9 and a['unscored_words'] == 2
    assert a['confusion']['ok'] == {'correct': 5, 'needs_work': 1, 'almost': 1, 'unscored': 2}
    assert a['false_alarms'] == 2 and a['ok_words'] == 7
    assert a['caught'] == 1 and a['positives'] == 2 and a['flagged'] == 3
    assert a['agree'] == 6
    rates = metrics.rates(a)
    assert rates['recall'] == 50 and rates['precision'] == pytest.approx(100 / 3)
    assert a['ok_red_letter'] == 2
    at = words['attribution']
    assert at == {'missed_errors': 1, 'missed_heard_as_reference': 1, 'missed_heard_differently': 0,
                  'false_alarms': 2, 'false_alarm_misheard': 1, 'false_alarm_heard_right': 1}
    assert words['errors']['learner/th_t']['heard_as_reference'] == 1


def test_sentence_scores_are_judged_by_the_share_of_words_said_right():
    clips = {c['id']: c for c in [_clip('a', 'One two three four.', ['ok', 'ok', 'ok', 'missing']),
                                  _clip('b', 'Five six.', ['ok', 'ok']),
                                  _clip('n', 'Noise.', ['missing'], group='no_speech', expect='no_speech')]}
    results = {'a': {'outcome': 'scored', 'score': 85, 'labels': [0, 0, 0, 2], 'letters': ['1'] * 4},
               'b': {'outcome': 'scored', 'score': 100, 'labels': [0, 0], 'letters': ['1111', '110']},
               'n': {'outcome': 'scored', 'score': 20, 'labels': [2], 'letters': ['0']}}
    s = metrics.summarise_clips(clips, results)
    assert s['learner']['mean_expected'] == pytest.approx(87.5)
    assert s['learner']['bias'] == pytest.approx(5)  # 85 for a reading that deserved 75
    assert s['learner']['tier_right'] == 1  # Excellent instead of Good job
    assert s['learner']['red_clips'] == 1 and s['learner']['all_ok_scored'] == 1
    assert s['no_speech']['outcome_right'] == 0


def test_comparing_two_runs_counts_words_fixed_and_broken():
    clips = {'a': _clip('a', 'A b c.', ['ok', 'error', 'ok'])}
    before = {'a': {'outcome': 'scored', 'labels': [0, 0, 2], 'letters': [], 'matched': []}}
    after = {'a': {'outcome': 'scored', 'labels': [0, 1, 1], 'letters': [], 'matched': []}}
    change = metrics.compare_words(clips, before, after)
    assert change['words'] == 3 and change['changed'] == 2
    assert [(old['index'], new['label']) for old, new in change['fixed']] == [(1, 'almost')]
    assert change['broken'] == []


# ---------------------------------------------------------------- the set
def test_the_set_is_well_formed():
    assert len(MANIFEST) >= 400
    groups = {'bank', 'learner', 'edit', 'normalisation', 'soft_tap', 'wrong', 'no_speech'}
    for clip in MANIFEST.values():
        assert clip['group'] in groups, clip['id']
        assert clip['expect'] in ('scored', 'no_speech'), clip['id']
        assert len(clip['truth']) == len(clip['reference'].split()), clip['id']
        assert set(clip['truth']) <= set(metrics.TRUTHS), clip['id']
        errors = clip.get('errors', {})
        assert sorted(int(i) for i in errors) == [i for i, t in enumerate(clip['truth']) if t == 'error'], clip['id']
        if clip['expect'] == 'no_speech':
            assert clip['group'] == 'no_speech'
    # Every learner sentence is also read clean, and every kind of mistake has enough words.
    learner = [c for c in MANIFEST.values() if c['group'] == 'learner']
    assert sum(c['condition'] == 'clean' for c in learner) * 2 == len(learner)
    kinds = [kind for c in learner for kind in c.get('errors', {}).values()]
    for kind in ('th_t', 'dh_d', 'sh_s', 'final_stop', 'plural_s', 'past_ed'):
        assert kinds.count(kind) >= 8, kind


def test_every_recording_is_in_the_set_and_small():
    folder = os.path.join(ROOT, 'evaluation', 'clips')
    files = {f'clips/{name}' for name in os.listdir(folder)}
    used = {clip['file'] for clip in MANIFEST.values()}
    assert used == files
    sizes = [os.path.getsize(os.path.join(ROOT, 'evaluation', f)) for f in files]
    assert max(sizes) < 100_000
    assert sum(sizes) < 8_000_000


def test_the_sentences_are_fit_for_a_class():
    # The set is in a public repository and its sentences are read by the
    # children's voice of the app: the bank's screening applies to it too.
    import test_content
    removed = {test_content._key(line.split('\t', 1)[1])
               for line in test_content.REMOVED.read_text(encoding='utf-8').splitlines()}
    assert len(removed) >= 350
    for clip in MANIFEST.values():
        for text in (clip['reference'], clip['said']):
            for name, pattern in test_content._PATTERNS.items():
                assert not pattern.search(text), (clip['id'], name, text)
            assert test_content._key(text) not in removed, (clip['id'], text)


def test_bank_sentences_of_the_set_are_still_in_the_bank():
    from evaluation import textsim
    bank = set(textsim.bank_sentences())
    for clip in MANIFEST.values():
        if clip['source'] == 'bank':
            assert clip['reference'] in bank, (clip['id'], clip['reference'])


@requires_ffmpeg
def test_every_recording_decodes_as_an_upload():
    import audioPreprocessing

    def seconds(clip):
        with open(os.path.join(ROOT, 'evaluation', clip['file']), 'rb') as f:
            return audioPreprocessing.decode_audio(f.read(), 16000).shape[-1] / 16000

    with ThreadPoolExecutor(4) as pool:
        durations = dict(zip(MANIFEST, pool.map(seconds, MANIFEST.values()), strict=True))
    for clip_id, duration in durations.items():
        assert 1.0 < duration <= audioPreprocessing.MAX_AUDIO_SECONDS, (clip_id, duration)


# ---------------------------------------------------------------- the committed report
def _committed_run():
    return harness.load_results(os.path.join(ROOT, 'evaluation', harness.REPORT['run']))


def test_the_committed_run_covers_the_set():
    run = _committed_run()
    assert set(run['clips']) == set(MANIFEST)
    for clip_id, result in run['clips'].items():
        assert result['reference'] == MANIFEST[clip_id]['reference'], clip_id


def test_the_committed_run_is_what_this_code_makes_of_what_whisper_heard():
    # A change to the alignment or the scoring changes these labels: run
    # `python -m evaluation.harness rescore` (or `run`), point harness.REPORT
    # at the new run and write the report again (evaluation/README.md).
    run = _committed_run()
    again = harness.rescore(MANIFEST, run['clips'])
    keys = ('outcome', 'score', 'labels', 'letters', 'matched')
    differ = [clip_id for clip_id, result in run['clips'].items()
              if any(result.get(k) != again[clip_id].get(k) for k in keys)]
    assert not differ, f'{len(differ)} clips score differently now, e.g. {differ[:5]}'


def test_the_committed_text_simulation_is_this_codes():
    from evaluation import textsim
    run = _committed_run()
    text = run['text']
    os.chdir(ROOT)
    check = textsim.run(textsim.bank_sentences(), every=text['check_every'], check_every=text['check_every'])
    assert check['check_digest'] == text['check_digest']


def test_the_committed_report_is_the_report_of_the_committed_run():
    with open(os.path.join(ROOT, 'evaluation', harness.REPORT['markdown']), encoding='utf-8') as f:
        assert f.read() == harness.committed_report(), 'run `python -m evaluation.harness report --committed`'


def test_a_rescore_keeps_what_was_not_heard():
    clips = {'a': _clip('a', 'Hello there.', ['ok', 'ok']), 'b': _clip('b', 'Hello there.', ['ok', 'ok']),
             'c': _clip('c', 'Hello there.', ['ok', 'ok'])}
    results = {
        'a': {'reference': 'Hello there.', 'outcome': 'no_speech'},  # the silence check: Whisper never ran
        'b': {'reference': 'Hello there.', 'outcome': 'no_speech', 'asr': {'samples': 16000, 'transcript': '',
                                                                          'words': []}},
        'c': {'reference': 'Hello there.', 'outcome': 'scored',
              'asr': {'samples': 32000, 'transcript': 'Hello there.',
                      'words': [['Hello', 1000.0, 9000.0], ['there.', 9000.0, 20000.0]]}},
    }
    again = harness.rescore(clips, results)
    assert again['a'] == {'reference': 'Hello there.', 'outcome': 'no_speech'}
    assert again['b']['outcome'] == 'no_speech'
    assert again['c']['outcome'] == 'scored' and again['c']['labels'] == [0, 0] and again['c']['score'] == 100
    assert again['c']['matched'] == ['Hello', 'there.']


def test_the_committed_runs_say_what_produced_them():
    for name in (harness.REPORT['run'], harness.REPORT['against']):
        with open(os.path.join(ROOT, 'evaluation', name), encoding='utf-8') as f:
            info = json.load(f)['pipeline']
        assert info['commit'] and 'uncommitted' not in info['commit'], name
        assert info.get('platform', '').startswith('Linux'), name


# ---------------------------------------------------------------- the real models
@pytest.mark.slow
def test_the_harness_scores_recordings_with_the_real_pipeline():
    chosen = {k: MANIFEST[k] for k in ('learner-01-clean', 'learner-01-th_t', 'noise-white')}
    results, timing = harness.run_clips(chosen, progress=False)
    assert timing['clips'] == 3
    assert results['learner-01-clean']['outcome'] == 'scored'
    assert results['learner-01-clean']['asr']['transcript']
    assert len(results['learner-01-th_t']['labels']) == len(MANIFEST['learner-01-th_t']['truth'])
    assert results['noise-white']['outcome'] == 'no_speech'
    # What Whisper heard gives the same labels again without Whisper.
    again = harness.rescore(chosen, results)
    for clip_id in chosen:
        assert again[clip_id].get('labels') == results[clip_id].get('labels'), clip_id
