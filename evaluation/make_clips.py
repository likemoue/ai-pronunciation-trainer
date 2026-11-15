"""Make the evaluation set: evaluation/clips/*.webm and evaluation/clips.json.

    python -m evaluation.make_clips                  # make the clips that are missing, write the manifest
    python -m evaluation.make_clips --chrome PATH    # also the clips recorded by Chrome's MediaRecorder

Every recording is synthetic. The voice is Piper's LJ Speech voice (public
domain), the app's own reference voice; the sentences come from the bank
(Tatoeba, CC BY 2.0 FR) or were written for the set. No learner's voice is in
it, and none may be added (CLAUDE.md).

Recordings are encoded as the page sends them: WebM/Opus, mono, 32 kbps. Most
are encoded by ffmpeg; a few are recorded by Chrome itself, the way the page
records, because the browser's encoder and audio processing changed what
Whisper heard (CLAUDE.md, known limits).

Piper samples noise as it speaks, so a text never gives the same audio twice.
The clips are therefore made once and kept in the repository, so that every
run of the harness hears the same recordings: a clip is made again only when
its file is missing. The manifest, which holds what was said and the truth
for every word, is written from the lists below every time.

Mistakes are made in the phonemes, not in the spelling: the sentence is
phonemised by Piper's espeak-ng, the word's phonemes are changed (θ -> t, a
final stop dropped, ...), and the voice reads the changed phonemes. The other
words keep the phonemes espeak-ng gives them in that sentence.
"""
import argparse
import base64
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.join(ROOT, 'evaluation')
CLIPS_DIR = os.path.join(HERE, 'clips')
MANIFEST = os.path.join(HERE, 'clips.json')

# ---------------------------------------------------------------- the set
# Bank sentences of phase 2's parity check, by their number there (s00-s29;
# s03 and s28 left the bank in its 2026-11 review, so they are not here).
# Each is read clean, slowly, fast, under white noise at 10 and 0 dB SNR, by a
# higher (child-like) voice, and with the spelling-level mistakes phase 2
# used; its clean reading is also scored against another sentence ("wrong").
BANK = {
    0: 'Someone will have to tell Tom.',
    1: 'We have to help Tom.',
    2: "That's a joke.",
    4: 'No one asked your opinion.',
    5: 'Tom ran out of gas.',
    6: 'The ground was covered in snow.',
    7: 'Tom is analysing the situation.',
    8: 'Tom stayed at this hotel for three weeks.',
    9: 'What speed can a rowing boat make?',
    10: 'Is Tom looking at me?',
    11: 'Tom is visiting his uncle.',
    12: 'Tom is still at the house.',
    13: 'Why are you asking me?',
    14: 'The parking lot in front of the bank was completely full.',
    15: "You don't know me and I don't know you, either.",
    16: 'Tom saw an old woman begging in the street.',
    17: 'This watch is twice as expensive as that one.',
    18: "Never buy what you don't want because it is cheap.",
    19: "You couldn't get two people more different than Tom and Mary.",
    20: 'Tom and Mary told John that they were interested.',
    21: 'John always tried to live up to the example of Lincoln.',
    22: 'He listened to the music with his eyes closed.',
    23: "That hairy space alien doesn't speak English; he just understands it.",
    24: 'Tom was already gone by the time we got there.',
    25: 'Tom heated up a can of ravioli for dinner.',
    26: 'The troglodytes said bridge when one of them crossed a river, walking on the trunk of a tall tree '
        'that had fallen there by chance. Unfortunately, however, no one knows what that word was.',
    27: 'He who wants to travel the path of wisdom must not fear failure, for no matter how much progress he '
        'makes, his goal remains unattainably far off.',
    29: "There'll always be someone who knows more than you and someone who knows less than you. The world's "
        "too big for that not to happen.",
}
# Phase 2 scored sentence n's clean reading against sentence (n + 7) % 30.
WRONG_OFFSET = 7
BANK_SIZE = 30
# Phase 2's mistakes, made in the spelling read by the voice (the learner
# group below makes them in the phonemes instead).
SPELLING_MISTAKES = [
    ('th', re.compile(r'\bth(?=[aeiouy])'), 't'),
    ('th', re.compile(r'\bTh(?=[aeiouy])'), 'T'),
    ('final_stop', re.compile(r'(?<=[aeiou])([dtkgp])\b'), ''),
    ('plural_s', re.compile(r'(?<=[a-z]{3})s\b'), ''),
    ('sh_s', re.compile(r'\bsh'), 's'),
]

# Bank sentences read with one or more of Vietnamese learners' typical
# mistakes, {word index: mistake}; each is also read clean.
#   th_t        θ said as t       (think -> tink)
#   dh_d        ð said as d       (mother -> moder)
#   sh_s        ʃ said as s       (she -> see)
#   final_stop  final p/b/t/d/k/g dropped   (cake -> kay)
#   plural_s    final -s/-z of a plural or verb dropped   (books -> book)
#   past_ed     final -t/-d of a past tense dropped        (walked -> walk)
LEARNER = [
    ('Who do you think will win?', {3: 'th_t'}),
    ('Mary can speak three languages.', {3: 'th_t'}),
    ('Tom did a foolish thing.', {4: 'th_t'}),
    ('Did I say something wrong?', {3: 'th_t'}),
    ('We have nothing to drink.', {2: 'th_t'}),
    ('We can thank Tom for that.', {2: 'th_t'}),
    ('We both lost our phones.', {1: 'th_t'}),
    ('Tom probably knows the truth.', {4: 'th_t'}),
    ('The ice was thick enough to walk on.', {3: 'th_t'}),
    ('Thank you for remembering my birthday.', {5: 'th_t'}),
    ('Please do this for me.', {2: 'dh_d'}),
    ('How old are they now?', {3: 'dh_d'}),
    ('Do you see those women?', {3: 'dh_d'}),
    ('Tom is visiting his mother.', {4: 'dh_d'}),
    ('Do you have a brother?', {4: 'dh_d'}),
    ('They spoke about the weather.', {4: 'dh_d'}),
    ('Were Tom and Mary together?', {4: 'dh_d'}),
    ('What would I do without you?', {4: 'dh_d'}),
    ('She wore a red dress.', {0: 'sh_s'}),
    ('Do you like eating fish?', {4: 'sh_s'}),
    ('Who is your English teacher?', {3: 'sh_s'}),
    ('Show me what you can do!', {0: 'sh_s'}),
    ('Are you sure you want to do that?', {2: 'sh_s'}),
    ('You need to finish your homework.', {3: 'sh_s'}),
    ('The shirt is made from pure wool.', {1: 'sh_s'}),
    ('The station is two miles away.', {1: 'sh_s'}),
    ('Are you a good cook?', {3: 'final_stop'}),
    ('Tom is baking a cake.', {4: 'final_stop'}),
    ('A dog followed me home.', {1: 'final_stop'}),
    ('This bag is too heavy.', {1: 'final_stop'}),
    ('The soup is still hot.', {4: 'final_stop'}),
    ('The cup is black and white.', {1: 'final_stop'}),
    ('Tom likes to bake bread.', {4: 'final_stop'}),
    ('Tom put milk in his tea.', {2: 'final_stop'}),
    ('This road leads to the airport.', {1: 'final_stop'}),
    ('He tore the book apart.', {3: 'final_stop'}),
    ('Mary has written three books.', {4: 'plural_s'}),
    ('We have many good friends.', {4: 'plural_s'}),
    ('All these eggs are not fresh.', {2: 'plural_s'}),
    ('He planted these trees himself.', {3: 'plural_s'}),
    ('You are five years old.', {3: 'plural_s'}),
    ('We sold Tom one of our cars.', {6: 'plural_s'}),
    ('The boys laughed at Tom.', {1: 'plural_s'}),
    ('Where did you buy flowers?', {4: 'plural_s'}),
    ("It's been raining for two days.", {5: 'plural_s'}),
    ("Why don't we sing some songs together?", {5: 'plural_s'}),
    ('Tom walked through the kitchen.', {1: 'past_ed'}),
    ('Tom helped himself to coffee.', {1: 'past_ed'}),
    ('Mary cleaned her room in a hurry.', {1: 'past_ed'}),
    ('She opened the letter quickly.', {1: 'past_ed'}),
    ('Tom looked at his watch.', {1: 'past_ed'}),
    ('The new plan worked well.', {3: 'past_ed'}),
    ('Tom called me from Boston.', {1: 'past_ed'}),
    ('Tom jumped over the hedge.', {1: 'past_ed'}),
    ('He missed the last train.', {1: 'past_ed'}),
    ('We lived in Paris before.', {1: 'past_ed'}),
    # Several mistakes in one reading, as learners make them.
    ('Tom is nearly thirty years old.', {3: 'th_t', 4: 'plural_s', 5: 'final_stop'}),
    ('We wanted to wash our hands.', {3: 'sh_s', 5: 'plural_s'}),
    ('She has her eyes closed.', {0: 'sh_s', 3: 'plural_s', 4: 'past_ed'}),
    ('He liked climbing trees as a kid.', {1: 'past_ed', 3: 'plural_s', 6: 'final_stop'}),
    ('Those guys over there sell shoes.', {0: 'dh_d', 5: 'sh_s'}),
    ('Three times three is nine.', {0: 'th_t', 2: 'th_t'}),
    ("Do you think that's fair?", {2: 'th_t', 3: 'dh_d'}),
]

# A word left out, a word said twice, a filler or a fresh start: what the
# learner said, as text. The words of the sentence that were not said are
# 'missing'; a repetition or a filler leaves every word 'ok'.
EDITS = [
    ('omit', 'Look through the yellow pages.', {'drop': 3}),
    ('omit', 'The dog ran after a fox.', {'drop': 3}),
    ('omit', 'He eats nothing but bread.', {'drop': 3}),
    ('omit', 'Tom needs to put his things away.', {'drop': 4}),
    ('omit', 'Please put those chairs away.', {'drop': 2}),
    ('omit', 'Trees lose their leaves quickly.', {'drop': 2}),
    ('omit', 'Tom took a sip of tea, trying to calm down.', {'drop': 5}),
    ('omit', 'Luckily, it was warm this week.', {'drop': 0}),
    ('stop_early', 'The glass is full of milk.', {'drop': 5}),
    ('stop_early', 'Tom went to the library every day last week.', {'drop': 8}),
    ('stop_early', 'Breathe deeply through your mouth.', {'drop': 4}),
    ('stop_early', 'We all want to stay healthy.', {'drop': 5}),
    ('repeat', 'Tom looked through the file.', {'said': 'Tom looked through through the file.'}),
    ('repeat', 'Children should obey their parents.', {'said': 'Children should should obey their parents.'}),
    ('filler', 'Mary has more clothes than Tom.', {'said': 'Mary has um more clothes than Tom.'}),
    ('filler', 'The road is under construction.', {'said': 'The road is uh under construction.'}),
    ('restart', 'The sun was hidden by thick clouds.', {'said': 'The sun was, the sun was hidden by thick clouds.'}),
    ('restart', 'Tom hoped to patch things up with Mary.',
     {'said': 'Tom hoped, Tom hoped to patch things up with Mary.'}),
]

# Bank sentences read correctly whose words Whisper may write otherwise:
# digits and times, hyphens, OK, titles, British spellings, symbols.
NORMALISATION = [
    'We need to get home before 2:30.',
    'Tom will be back by 2:30.',
    'Tom left the library at 2:30.',
    'Wait just 3 minutes.',
    "Why are you packing so much stuff? It's only a 3-day trip.",
    'The surface of the earth is 70% water.',
    'A small cup of coffee costs €2.',
    'We were next-door neighbors.',
    'We spent the night at a five-star hotel.',
    'Why are you so hard-headed?',
    'A small forest brook flowed between the moss-covered trees.',
    "We've done OK.",
    'Tom is OK with this.',
    "I'm doing OK.",
    'Any kind of bullying is not okay.',
    'Mr. Jackson is our math teacher.',
    'Mr. Smith lives in Kyoto now.',
    'What colour are her eyes?',
    'Which of these textbooks is your favourite?',
    'He is our neighbour.',
]

# Short phrases, spoken very softly, with the tap on the phone's Record
# button far louder: the voice's peak is this many dB under the tap's.
# The server scales a recording by its peak (pronunciationTrainer.preprocessAudio),
# so the voice stays that quiet for Whisper.
TAP_PHRASES = ['Yes.', 'Thank you.', "It's OK.", 'Speed up.', 'I am well.', 'Look at it.', 'We had lunch.',
               'Good morning.']
TAP_LEVELS_DB = (30, 40, 48)
# The same, recorded through Chrome (its audio processing on, as the page asks).
TAP_CHROME = [('Thank you.', 44), ("It's OK.", 44), ('I am well.', 52), ('Good morning.', 52)]
# Soft phrases after a tap that phase 2's third review round made (with the
# same voice, in the image) and that phase 2's pipeline refuses as no speech:
# the known limit in CLAUDE.md. Their audio was copied from that round and
# cannot be made again here. (phrase, voice, seconds of silence before and
# after, the tap on Record at the start or on Stop at the end, how many dB
# the voice's peak is under the tap, how it was encoded). 'stop, floor 25'
# has a room noise floor 25 dB under the voice instead of 50.
TAP_PHASE2 = [
    ('I am well.', 'normal', 3.0, 3.0, 'start', 44, 'ffmpeg'),
    ("I'm sorry.", 'child', 3.0, 3.0, 'start', 44, 'ffmpeg'),
    ('Look at it.', 'normal', 0.5, 3.0, 'start', 52, 'ffmpeg'),
    ('Yes.', 'child', 1.0, 8.0, 'start', 44, 'ffmpeg'),
    ('Speed up.', 'normal', 1.0, 8.0, 'start', 48, 'ffmpeg'),
    ('Go.', 'normal', 1.0, 8.0, 'start', 48, 'ffmpeg'),
    ('We had lunch.', 'child', 3.0, 3.0, 'start', 48, 'ffmpeg'),
    ('Banana.', 'normal', 8.0, 1.0, 'start', 44, 'ffmpeg'),
    ('Run.', 'child', 1.0, 8.0, 'start', 44, 'ffmpeg'),
    ('Speed up.', 'child', 3.0, 3.0, 'stop', 44, 'chrome-capture'),
    ('I am well.', 'normal', 3.0, 3.0, 'stop', 52, 'chrome-capture'),
    ("I'm sorry.", 'normal', 3.0, 3.0, 'stop', 52, 'chrome-capture'),
    ('Look at it.', 'normal', 1.0, 8.0, 'stop', 52, 'chrome-capture'),
    ('Look at it.', 'child', 3.0, 3.0, 'stop, floor 25', 52, 'chrome-capture'),
    ('I am well.', 'child', 3.0, 3.0, 'stop, floor 25', 52, 'chrome-capture'),
]

# A short phrase at a normal level in a long take: the learner waits before
# pressing Stop (the page records up to 30 s), over a quiet microphone noise
# floor (2e-3, -54 dBFS). A level set by a share of the recording clipped such
# a phrase (the second review round of phase 3). (phrase, seconds before, after)
LONG_TAKES = [('Yes.', 1.0, 24.0), ('Thank you.', 1.0, 20.0), ('Good morning.', 2.0, 22.0), ('I am well.', 1.0, 18.0),
              ('Look at it.', 0.5, 25.0), ('Speed up.', 3.0, 20.0)]

# Noise alone. The reference is the sentence the learner was asked to read.
NOISE_REFERENCE = 'Someone will have to tell Tom.'
# White noise as a page records it: played into MediaRecorder by a stand-in
# microphone (as the production check of 2026-11-15 did: "I'm sorry." 4 of 4),
# and through Chrome's capture path with its audio processing.
PAGE_NOISE = [('chrome-standin', 0.05, 1), ('chrome-standin', 0.15, 2), ('chrome-standin', 0.4, 3),
              ('chrome-standin', 0.15, 4), ('chrome-capture', 0.05, 5), ('chrome-capture', 0.15, 6),
              ('chrome-capture', 0.4, 7)]
PAGE_NOISE_SECONDS = 7.0

# ---------------------------------------------------------------- audio
_voice = None


def voice():
    """Piper's LJ Speech voice, as the app loads it (piperTTS, pinned by sha256)."""
    global _voice
    if _voice is None:
        sys.path.insert(0, ROOT)
        import logging_setup
        logging_setup.configure()
        import piperTTS
        _voice = piperTTS._load_model('en')
    return _voice


def sentence_phonemes(text):
    """espeak-ng's phonemes for text, one string per sentence (as Piper reads it)."""
    return [''.join(phonemes) for phonemes in voice().phonemize(text) if phonemes]


STRESS = 'ˈˌ'
STOPS = 'pbtdkɡ'


def bare(phonemes):
    """Phonemes without stress marks and punctuation (every IPA symbol here is a letter to Python)."""
    return ''.join(ch for ch in phonemes if ch not in STRESS and ch.isalpha())


def word_phonemes(text):
    """The phonemes of each word of text, or None when espeak-ng's words do
    not line up one to one with the text's (it joins "on the" into ɒnðə)."""
    chunks = ' '.join(sentence_phonemes(text)).split()
    return chunks if len(chunks) == len(text.split()) else None


def apply_mistake(chunk, mistake):
    """A word's phonemes (with stress marks and punctuation) with the mistake made."""
    body = chunk.rstrip('.,!?;:')
    tail = chunk[len(body):]
    if mistake == 'th_t':
        changed = body.replace('θ', 't')
    elif mistake == 'dh_d':
        changed = body.replace('ð', 'd')
    elif mistake == 'sh_s':
        changed = re.sub(r'(?<!t)ʃ', 's', body)
    elif mistake == 'final_stop':
        changed = body[:-1] if body[-1] in STOPS else body
    elif mistake == 'plural_s':
        changed = body[:-1] if body[-1] in 'sz' else body
    elif mistake == 'past_ed':
        changed = body[:-1] if body[-1] in 'td' else body
    else:
        raise ValueError(mistake)
    if changed == body:
        raise ValueError(f'{mistake} does not change /{chunk}/')
    return changed + tail


def synthesise(sentences, length_scale=None):
    """Piper reading phonemes (one string per sentence), as voice.synthesize
    does: each sentence on its own, scaled to full range. (float32, rate)."""
    from piper import SynthesisConfig
    v = voice()
    config = SynthesisConfig(length_scale=length_scale)
    parts = []
    for phonemes in sentences:
        audio = v.phoneme_ids_to_audio(v.phonemes_to_ids(list(phonemes)), config)
        peak = float(np.max(np.abs(audio)))
        parts.append(np.clip(audio / peak if peak > 1e-8 else audio, -1, 1).astype(np.float32))
    return np.concatenate(parts), v.config.sample_rate


def say(text, length_scale=None):
    return synthesise(sentence_phonemes(text), length_scale)


def ffmpeg():
    sys.path.insert(0, ROOT)
    import audioPreprocessing
    return audioPreprocessing.ffmpeg_binary()


def pink_noise(n, seed):
    """Noise with a 1/f spectrum, unit standard deviation."""
    x = np.random.default_rng(seed).standard_normal(n)
    spectrum = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n)
    freqs[0] = freqs[1]
    y = np.fft.irfft(spectrum / np.sqrt(freqs), n)
    return (y / y.std()).astype(np.float32)


def voice_level(speech, rate):
    """RMS of the louder half of 20 ms frames: the level of the voice itself."""
    frame = int(rate * 0.02)
    frames = speech[: len(speech) // frame * frame].reshape(-1, frame).astype(np.float64)
    energy = np.sqrt((frames ** 2).mean(axis=1))
    return float(np.sqrt(np.mean(np.sort(energy)[len(energy) // 2:] ** 2)))


def recording(speech, rate, seed, before=0.4, after=0.6, floor_db=50.0):
    """Speech with the silence a learner leaves around it, over a quiet
    microphone noise floor floor_db under the voice."""
    x = np.concatenate([np.zeros(int(before * rate), np.float32), speech, np.zeros(int(after * rate), np.float32)])
    if floor_db is not None:
        x = x + pink_noise(x.size, seed) * voice_level(speech, rate) * 10 ** (-floor_db / 20)
    peak = float(np.max(np.abs(x)))
    return (x / peak).astype(np.float32) if peak > 1 else x.astype(np.float32)


def with_white_noise(x, snr_db, seed):
    """Phase 2's noisy readings: white noise at snr_db under the whole clip's power."""
    noise = np.random.default_rng(seed).standard_normal(len(x)).astype(np.float32)
    noise *= np.sqrt(np.mean(x ** 2) / (10 ** (snr_db / 10)) / np.mean(noise ** 2))
    return x + noise


def tapped(speech, rate, db, seed, before=0.5, after=2.0):
    """A soft phrase after a loud tap on Record (a thump at 0.15 s): the voice's
    peak db under the tap's, over a noise floor 50 dB under the voice."""
    x = np.concatenate([np.zeros(int(before * rate), np.float32), speech, np.zeros(int(after * rate), np.float32)])
    x = x + pink_noise(x.size, seed) * voice_level(speech, rate) * 10 ** (-50 / 20)
    x = x / np.max(np.abs(x)) * 0.7 * 10 ** (-db / 20)
    n = int(rate * 0.03)
    thump = np.random.default_rng(seed + 1).standard_normal(n) * np.exp(-np.arange(n) / (rate * 0.004))
    at = int(rate * 0.15)
    x[at:at + n] += (thump / np.max(np.abs(thump)) * 0.7).astype(np.float32)
    return x.astype(np.float32)


def long_take(speech, rate, seed, before, after, peak=0.4, floor=2e-3):
    """Speech peaking at `peak`, then a long wait, over white noise of RMS `floor`."""
    voice = speech / np.max(np.abs(speech)) * peak
    x = np.concatenate([np.zeros(int(before * rate), np.float32), voice, np.zeros(int(after * rate), np.float32)])
    return (x + np.random.default_rng(seed).standard_normal(x.size) * floor).astype(np.float32)


def child_like(speech, rate, factor=1.3):
    """The voice raised by factor (shorter vocal tract), at the same speed."""
    return filtered(speech, rate, f'asetrate={int(rate * factor)},aresample={rate},atempo={1 / factor:.4f}')


def filtered(samples, rate, af):
    out = subprocess.run([ffmpeg(), '-nostdin', '-loglevel', 'error', '-f', 'f32le', '-ar', str(rate), '-ac', '1',
                          '-i', 'pipe:0', '-af', af, '-ac', '1', '-ar', str(rate), '-f', 'f32le', 'pipe:1'],
                         input=samples.astype('<f4').tobytes(), capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype='<f4').copy()


def wav_bytes(samples, rate):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(samples, -1, 1) * 32767).astype('<i2').tobytes())
    return buffer.getvalue()


def encode(samples, rate, bitrate='32k'):
    """WebM/Opus, mono, 48 kHz: what MediaRecorder sends (the page asks for 32 kbps)."""
    return subprocess.run([ffmpeg(), '-nostdin', '-loglevel', 'error', '-f', 'wav', '-i', 'pipe:0', '-c:a', 'libopus',
                           '-b:a', bitrate, '-ar', '48000', '-ac', '1', '-f', 'webm', 'pipe:1'],
                          input=wav_bytes(samples, rate), capture_output=True, check=True).stdout


def resampled(samples, rate, target):
    if rate == target:
        return samples
    out = subprocess.run([ffmpeg(), '-nostdin', '-loglevel', 'error', '-f', 'f32le', '-ar', str(rate), '-ac', '1',
                          '-i', 'pipe:0', '-ar', str(target), '-f', 'f32le', 'pipe:1'],
                         input=samples.astype('<f4').tobytes(), capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype='<f4').copy()


# ---------------------------------------------------------------- Chrome
# The page's recorder (static/javascript/app.js): getUserMedia({audio:
# {channelCount: 1}}), MediaRecorder with audio/webm;codecs=opus at 32 kbps.
# 'standin' plays the source into the recorder through WebAudio instead of a
# microphone, as the production check's stand-in microphone did.
RECORDER_PAGE = """<!doctype html><meta charset="utf-8"><title>rec</title><script>
(async () => {
  const q = new URLSearchParams(location.search);
  const name = q.get('name'), secs = parseFloat(q.get('secs')), mode = q.get('mode');
  const meta = { name, mode };
  try {
    let stream;
    if (mode === 'standin') {
      const ctx = new AudioContext();
      await ctx.resume();
      const data = await (await fetch('/src/' + name + '.wav')).arrayBuffer();
      const buffer = await ctx.decodeAudioData(data);
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      const destination = ctx.createMediaStreamDestination();
      source.connect(destination);
      source.start(ctx.currentTime + 0.3);
      stream = destination.stream;
    } else {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
      meta.settings = stream.getAudioTracks()[0].getSettings();
    }
    const types = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/webm', 'audio/mp4'];
    const mimeType = types.find((t) => MediaRecorder.isTypeSupported(t)) || '';
    const options = { audioBitsPerSecond: 32000 };
    if (mimeType) options.mimeType = mimeType;
    const recorder = new MediaRecorder(stream, options);
    const chunks = [];
    recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    const stopped = new Promise((resolve) => { recorder.onstop = resolve; });
    recorder.start();
    await new Promise((r) => setTimeout(r, secs * 1000));
    recorder.stop();
    await stopped;
    meta.mimeType = recorder.mimeType;
    meta.userAgent = navigator.userAgent;
    const blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
    const dataUrl = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(reader.error);
      reader.readAsDataURL(blob);
    });
    stream.getTracks().forEach((t) => t.stop());
    await fetch('/save', { method: 'POST', body: JSON.stringify({ meta, dataUrl }) });
  } catch (err) {
    meta.error = String(err);
    await fetch('/save', { method: 'POST', body: JSON.stringify({ meta, dataUrl: '' }) });
  }
})();
</script>"""


def chrome_record(chrome, items):
    """Record each (name, mode, samples, rate) with Chrome as the page would.
    Returns {name: (webm bytes, meta)}."""
    sources, received, done = {}, {}, threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            path = self.path.split('?')[0]
            if path == '/rec.html':
                body, kind = RECORDER_PAGE.encode(), 'text/html; charset=utf-8'
            elif path.startswith('/src/') and path[5:-4] in sources:
                body, kind = sources[path[5:-4]], 'audio/wav'
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            received[data['meta']['name']] = data
            self.send_response(204)
            self.end_headers()
            done.set()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, mode, samples, rate in items:
            # Chrome's fake microphone reads a 16-bit WAV file; 48 kHz, as most microphones.
            samples48 = resampled(samples, rate, 48000)
            wav = wav_bytes(samples48, 48000)
            sources[name] = wav
            source_path = os.path.join(tmp, name + '.wav')
            with open(source_path, 'wb') as f:
                f.write(wav)
            seconds = len(samples48) / 48000 + (0.6 if mode == 'standin' else 0.3)
            url = f'http://127.0.0.1:{server.server_address[1]}/rec.html?name={name}&secs={seconds:.2f}&mode={mode}'
            command = [chrome, '--headless=new', f'--user-data-dir={os.path.join(tmp, "profile")}', '--no-first-run',
                       '--no-default-browser-check', '--disable-extensions', '--disable-background-networking',
                       '--disable-sync', '--use-fake-ui-for-media-stream', '--autoplay-policy=no-user-gesture-required']
            if mode == 'capture':
                command += ['--use-fake-device-for-media-stream', f'--use-file-for-fake-audio-capture={source_path}%noloop']
            done.clear()
            browser = subprocess.Popen(command + [url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                if not done.wait(seconds + 60):
                    raise RuntimeError(f'Chrome did not record {name}')
            finally:
                browser.kill()
                browser.wait()
                time.sleep(0.5)
            data = received[name]
            if not data['dataUrl']:
                raise RuntimeError(f'Chrome could not record {name}: {data["meta"].get("error")}')
            out[name] = (base64.b64decode(data['dataUrl'].partition(',')[2]), data['meta'])
    server.shutdown()
    return out


# ---------------------------------------------------------------- the manifest
def clip(clip_id, group, condition, reference, said, truth, capture='ffmpeg', errors=None, expect='scored',
         source='bank', note=''):
    entry = {'id': clip_id, 'file': f'clips/{clip_id}.webm', 'group': group, 'condition': condition,
             'reference': reference, 'said': said, 'expect': expect, 'truth': truth, 'capture': capture,
             'source': source}
    if errors:
        entry['errors'] = {str(k): v for k, v in sorted(errors.items())}
    if note:
        entry['note'] = note
    return entry


def spelling_mistakes(text):
    """Phase 2's spelling-level mistakes: (the text read, {word index: mistake})."""
    said = text
    for _, pattern, replacement in SPELLING_MISTAKES:
        said = pattern.sub(replacement, said)
    kinds = {}
    for index, (word, new) in enumerate(zip(text.split(), said.split(), strict=True)):
        if word != new:
            kinds[index] = next(kind for kind, pattern, replacement in SPELLING_MISTAKES
                                if pattern.sub(replacement, word) != word)
    return said, kinds


def spelling_truth(text, said):
    """A changed spelling is a mistake only when espeak-ng says the word
    differently ("less" read as "les" sounds the same)."""
    truth = []
    for word, new in zip(text.split(), said.split(), strict=True):
        if word == new:
            truth.append('ok')
        else:
            old_phonemes = bare(''.join(sentence_phonemes(word)))
            new_phonemes = bare(''.join(sentence_phonemes(new)))
            truth.append('ok' if old_phonemes == new_phonemes else 'error')
    return truth


def plan():
    """Every clip of the set: (manifest entry, how to make its audio)."""
    entries = []
    for n, sentence in BANK.items():
        words = len(sentence.split())
        base = f'bank-s{n:02d}'
        ok = ['ok'] * words
        entries.append((clip(f'{base}-clean', 'bank', 'clean', sentence, sentence, ok), ('bank', n, 'clean')))
        entries.append((clip(f'{base}-slow', 'bank', 'slow', sentence, sentence, ok,
                             note='Piper length scale 1.3'), ('bank', n, 'slow')))
        entries.append((clip(f'{base}-fast', 'bank', 'fast', sentence, sentence, ok,
                             note='Piper length scale 0.8'), ('bank', n, 'fast')))
        entries.append((clip(f'{base}-noise10', 'bank', 'noise10', sentence, sentence, ok,
                             note='white noise, 10 dB SNR'), ('bank', n, 'noise10')))
        entries.append((clip(f'{base}-noise0', 'bank', 'noise0', sentence, sentence, ok,
                             note='white noise, 0 dB SNR'), ('bank', n, 'noise0')))
        entries.append((clip(f'{base}-child', 'bank', 'child', sentence, sentence, ok,
                             note='voice raised by 1.3 (child-like), same speed'), ('bank', n, 'child')))
        said, kinds = spelling_mistakes(sentence)
        if kinds:
            truth = spelling_truth(sentence, said)
            errors = {i: kind for i, kind in kinds.items() if truth[i] == 'error'}
            entries.append((clip(f'{base}-misspelled', 'bank', 'misspelled', sentence, said, truth, errors=errors,
                                 note="phase 2's mistakes, made in the spelling the voice reads"),
                            ('bank', n, 'misspelled')))
        other = (n + WRONG_OFFSET) % BANK_SIZE
        if other in BANK:
            wrong = BANK[other]
            entry = clip(f'{base}-wrong', 'wrong', 'other_sentence', wrong, sentence, ['missing'] * len(wrong.split()),
                         note=f'the clean reading of {base}, scored against another sentence')
            entry['file'] = f'clips/{base}-clean.webm'
            entries.append((entry, ('same file', f'{base}-clean')))
    for n, (sentence, mistakes) in enumerate(LEARNER, start=1):
        words = sentence.split()
        base = f'learner-{n:02d}'
        entries.append((clip(f'{base}-clean', 'learner', 'clean', sentence, sentence, ['ok'] * len(words)),
                        ('learner', sentence, {})))
        chunks = word_phonemes(sentence)
        if chunks is None:
            raise SystemExit(f'espeak-ng does not split "{sentence}" into its words')
        said = list(words)
        for index, mistake in mistakes.items():
            said[index] = '/' + apply_mistake(chunks[index], mistake).rstrip('.,!?;:') + '/' + \
                words[index][len(words[index].rstrip('.,!?;:')):]
        kinds = '+'.join(sorted(set(mistakes.values()))) if len(mistakes) > 1 else next(iter(mistakes.values()))
        truth = ['error' if i in mistakes else 'ok' for i in range(len(words))]
        entries.append((clip(f'{base}-{"multi" if len(mistakes) > 1 else kinds}', 'learner',
                             'multi' if len(mistakes) > 1 else kinds, sentence, ' '.join(said), truth,
                             errors=mistakes), ('learner', sentence, mistakes)))
    for n, (kind, sentence, edit) in enumerate(EDITS, start=1):
        words = sentence.split()
        if 'drop' in edit:
            said_words = words[:edit['drop']] + words[edit['drop'] + 1:]
            said = ' '.join(said_words)
            if edit['drop'] == len(words) - 1:
                said = said.rstrip(',') + words[-1][len(words[-1].rstrip('.,!?;:')):]
            elif edit['drop'] == 0:
                said = said[0].upper() + said[1:]
            truth = ['missing' if i == edit['drop'] else 'ok' for i in range(len(words))]
        else:
            said, truth = edit['said'], ['ok'] * len(words)
        entries.append((clip(f'edit-{n:02d}-{kind}', 'edit', kind, sentence, said, truth), ('text', said)))
    for n, sentence in enumerate(NORMALISATION, start=1):
        entries.append((clip(f'norm-{n:02d}', 'normalisation', 'clean', sentence, sentence,
                             ['ok'] * len(sentence.split())), ('text', sentence)))
    for n, phrase in enumerate(TAP_PHRASES, start=1):
        for db in TAP_LEVELS_DB:
            entries.append((clip(f'tap-{n:02d}-{db}db', 'soft_tap', f'{db}db', phrase, phrase,
                                 ['ok'] * len(phrase.split()), source='written',
                                 note=f"spoken softly: the voice's peak {db} dB under a tap on Record"),
                            ('tap', phrase, db)))
    for n, (phrase, db) in enumerate(TAP_CHROME, start=1):
        entries.append((clip(f'tap-chrome-{n:02d}-{db}db', 'soft_tap', f'chrome_{db}db', phrase, phrase,
                             ['ok'] * len(phrase.split()), capture='chrome-capture', source='written',
                             note=f"spoken softly: the voice's peak {db} dB under a tap on Record; recorded by "
                                  'Chrome through its capture path, audio processing on'),
                        ('tap-chrome', phrase, db)))
    for n, (phrase, voice_kind, before, after, tap, db, capture) in enumerate(TAP_PHASE2, start=1):
        where = 'Record' if tap == 'start' else 'Stop'
        entries.append((clip(f'tap-p2-{n:02d}', 'soft_tap', 'phase2_refused', phrase, phrase,
                             ['ok'] * len(phrase.split()), capture=capture, source='written',
                             note=f"spoken softly ({voice_kind} voice) with {before:g} s of silence before and "
                                  f"{after:g} s after, the voice's peak {db} dB under a tap on {where}"
                                  f"{' and a noise floor 25 dB under the voice' if 'floor' in tap else ''}; "
                                  "made by phase 2's third review round, which phase 2 refuses as no speech"),
                        ('imported',)))
    for n, (phrase, before, after) in enumerate(LONG_TAKES, start=1):
        entries.append((clip(f'long-{n:02d}', 'long_take', f'{before + after:g}s', phrase, phrase,
                             ['ok'] * len(phrase.split()), source='written',
                             note=f'said at a normal level {before:g} s into the take, then {after:g} s of a quiet '
                                  'microphone floor before Stop'),
                        ('long', phrase, before, after)))
    for name, said in (('white', 'white noise, 3 s'), ('quiet', 'quiet white noise, 3 s'), ('hum', '50 Hz hum, 3 s'),
                       ('keyboard', 'sparse clicks over a faint noise floor, 4 s')):
        entries.append((clip(f'noise-{name}', 'no_speech', name, NOISE_REFERENCE, f'({said})',
                             ['missing'] * len(NOISE_REFERENCE.split()), expect='no_speech'),
                        ('noise', name)))
    for n, (mode, level, seed) in enumerate(PAGE_NOISE, start=1):
        how = ('played into the page\'s MediaRecorder by a stand-in microphone' if mode == 'chrome-standin'
               else "through Chrome's capture path, audio processing on")
        entries.append((clip(f'noise-page-{n:02d}', 'no_speech', mode.replace('chrome-', 'page_'), NOISE_REFERENCE,
                             f'(white noise, amplitude {level}, {PAGE_NOISE_SECONDS:.0f} s, {how})',
                             ['missing'] * len(NOISE_REFERENCE.split()), capture=mode, expect='no_speech'),
                        ('page-noise', mode, level, seed)))
    return entries


# ---------------------------------------------------------------- making the audio
def bank_audio(n, condition):
    sentence = BANK[n]
    if condition == 'misspelled':
        speech, rate = say(spelling_mistakes(sentence)[0])
    elif condition == 'slow':
        speech, rate = say(sentence, 1.3)
    elif condition == 'fast':
        speech, rate = say(sentence, 0.8)
    else:
        speech, rate = say(sentence)
    if condition == 'child':
        speech = child_like(speech, rate)
    x = recording(speech, rate, seed=n, floor_db=None)
    if condition == 'noise10':
        x = with_white_noise(x, 10, n)
    elif condition == 'noise0':
        x = with_white_noise(x, 0, 100 + n)
    return encode(x, rate)


def learner_audio(sentence, mistakes, seed):
    chunks = word_phonemes(sentence)
    for index, mistake in mistakes.items():
        chunks[index] = apply_mistake(chunks[index], mistake)
    # Back into sentences: espeak-ng ends a sentence after . ? ! (and a title's ".").
    sentences, current = [], []
    for chunk in chunks:
        current.append(chunk)
        if chunk[-1] in '.?!':
            sentences.append(' '.join(current))
            current = []
    if current:
        sentences.append(' '.join(current))
    expected = sentence_phonemes(sentence)
    if not mistakes and sentences != expected:
        raise SystemExit(f'phonemes of "{sentence}" do not survive the round trip: {sentences} != {expected}')
    speech, rate = synthesise(sentences)
    return encode(recording(speech, rate, seed), rate)


def noise_audio(name):
    rate = 16000
    if name == 'white':
        x = np.random.default_rng(1).standard_normal(rate * 3) * 0.05
    elif name == 'quiet':
        x = np.random.default_rng(2).standard_normal(rate * 3) * 0.01
    elif name == 'hum':
        x = 0.05 * np.sin(2 * np.pi * 50 * np.arange(rate * 3) / rate)
    else:
        x = (np.where(np.random.default_rng(3).random(rate * 4) > 0.999, 0.6, 0.0)
             + np.random.default_rng(4).standard_normal(rate * 4) * 0.003)
    return encode(x.astype(np.float32), rate)


def make(entries, chrome=None):
    """Write the audio of every entry whose file is missing."""
    os.makedirs(CLIPS_DIR, exist_ok=True)
    chrome_items, made = [], 0
    for n, (entry, how) in enumerate(entries):
        path = os.path.join(HERE, entry['file'])
        if os.path.exists(path):
            continue
        kind = how[0]
        if kind == 'same file':
            continue  # another clip's audio, made with that clip
        if kind == 'imported':
            print(f'missing {entry["id"]}: copied from phase 2\'s review round, it cannot be made again', flush=True)
            continue
        if kind == 'bank':
            data = bank_audio(how[1], how[2])
        elif kind == 'learner':
            data = learner_audio(how[1], how[2], seed=n)
        elif kind == 'text':
            speech, rate = say(how[1])
            data = encode(recording(speech, rate, seed=n), rate)
        elif kind == 'tap':
            speech, rate = say(how[1])
            data = encode(tapped(speech, rate, how[2], seed=n), rate)
        elif kind == 'long':
            speech, rate = say(how[1])
            data = encode(long_take(speech, rate, n, how[2], how[3]), rate)
        elif kind == 'noise':
            data = noise_audio(how[1])
        elif kind in ('tap-chrome', 'page-noise'):
            if chrome is None:
                print(f'skipped {entry["id"]}: needs --chrome', flush=True)
                continue
            if kind == 'tap-chrome':
                speech, rate = say(how[1])
                chrome_items.append((entry['id'], 'capture', tapped(speech, rate, how[2], seed=n), rate))
            else:
                _, mode, level, seed = how
                rate = 48000
                x = (np.random.default_rng(seed).uniform(-1, 1, int(rate * PAGE_NOISE_SECONDS)) * level)
                chrome_items.append((entry['id'], 'standin' if mode == 'chrome-standin' else 'capture',
                                     x.astype(np.float32), rate))
            continue
        else:
            raise ValueError(kind)
        with open(path, 'wb') as f:
            f.write(data)
        made += 1
        print('made', entry['id'], flush=True)
    if chrome_items:
        for name, (data, meta) in chrome_record(chrome, chrome_items).items():
            with open(os.path.join(CLIPS_DIR, name + '.webm'), 'wb') as f:
                f.write(data)
            made += 1
            print('recorded', name, meta.get('mimeType'), meta.get('userAgent', '')[:60], flush=True)
    return made


def write_manifest(entries):
    manifest = [entry for entry, _ in entries if os.path.exists(os.path.join(HERE, entry['file']))]
    missing = [entry['id'] for entry, _ in entries if not os.path.exists(os.path.join(HERE, entry['file']))]
    with open(MANIFEST, 'w', encoding='utf-8', newline='\n') as f:
        json.dump({'about': 'Synthetic recordings with the truth for every word; see evaluation/README.md.',
                   'clips': manifest}, f, ensure_ascii=False, indent=1)
        f.write('\n')
    return manifest, missing


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--chrome', help='Chrome or Chromium, for the clips the browser records')
    parser.add_argument('--manifest-only', action='store_true', help='write the manifest, make no audio')
    args = parser.parse_args(argv)
    entries = plan()
    if not args.manifest_only:
        print('made', make(entries, args.chrome), 'clips', flush=True)
    manifest, missing = write_manifest(entries)
    print(f'{len(manifest)} clips in {os.path.relpath(MANIFEST, ROOT)}', flush=True)
    if missing:
        print(f'{len(missing)} clips have no audio yet: {", ".join(missing)}', flush=True)
    return 0 if not missing else 1


if __name__ == '__main__':
    sys.exit(main())
