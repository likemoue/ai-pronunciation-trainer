# Scoring evaluation

Phase 3 changes how recordings are scored. Every such change is judged here first: it is merged only if it makes
the labels of this set more right ([report.md](report.md) is the current pipeline's report).

The harness scores a set of recordings whose truth is known word by word, the way the server scores an upload,
and says how often the pipeline's labels (Correct, Almost, Needs work) agree with what was actually said.

## The set

`clips.json` lists 441 recordings (`clips/`, WebM/Opus at 32 kbps as the page sends them). Each gives the sentence
it is scored against (`reference`), what was actually said (`said`), whether it should be scored or refused as
"no speech" (`expect`), and the truth for every word of the sentence:

- `ok`: said as the dictionary says it;
- `error`: said with a learner's mistake (`errors` names it);
- `missing`: not said at all.

| group | recordings | what they are |
|---|---|---|
| `bank` | 191 | 28 bank sentences of every level (phase 2's parity set), read clean, slowly (length scale 1.3), fast (0.8), under white noise at 10 and 0 dB SNR, by a higher, child-like voice, and with phase 2's spelling-level mistakes |
| `learner` | 126 | 63 bank sentences read with Vietnamese learners' typical mistakes, made in the phonemes: θ→t, ð→d, ʃ→s, a final stop dropped, a plural or verb -s dropped, a past -ed dropped (one per reading, or two or three); each also read clean |
| `edit` | 18 | a word left out, the reading stopped before the last word, a word said twice, a filler ("um"), a fresh start |
| `normalisation` | 20 | read correctly; Whisper may write the words otherwise: 2:30, 3, 70%, €2, hyphens, OK, Mr., British spellings |
| `soft_tap` | 43 | a short phrase spoken softly after a much louder tap on Record (30 to 52 dB louder), 4 of them recorded by Chrome; and 15 that phase 2's third review round made (longer silences, a child-like voice, the tap on Stop, 6 through Chrome) and that phase 2 refuses as no speech, the known limit |
| `long_take` | 6 | a short phrase at a normal level, then 18-25 s of a quiet microphone floor before Stop (the review of phase 3 found a level set by a share of the recording clipped such phrases) |
| `wrong` | 26 | a clean reading scored against another sentence (judged as a whole; its words are not counted) |
| `no_speech` | 11 | noise alone: white noise, quiet noise, hum and clicks encoded by ffmpeg, and white noise recorded by Chrome's MediaRecorder as the page records it (a stand-in microphone, as the production check that heard "I'm sorry." used, and Chrome's capture path with its audio processing) |

**Every recording is synthetic**: Piper's LJ Speech voice (public domain), the app's own reference voice. The
sentences come from the bank (Tatoeba, CC BY 2.0 FR) or were written for the set (`source`), and pass the bank's
screening (`tests/test_evaluation.py`). No learner's voice is in the set, and none may be added: the app never
stores recordings (CLAUDE.md). Consented recordings of real learners, marked by teachers, would be the next step,
in a store of their own, not in this repository.

Mistakes are made in the phonemes, not the spelling: espeak-ng phonemises the sentence (as Piper does), the
word's phonemes are changed (`/θˈɪŋk/` → `/tˈɪŋk/`), and the voice reads the changed phonemes, so the truth is
exactly what was said. Phase 2's spelling-level mistakes (`bank`, `misspelled`) are kept for comparison with its
measurements; a changed spelling counts as a mistake only where espeak-ng says the word differently.

Piper samples noise as it speaks, so a text never gives the same audio twice: the recordings are made once and
kept. `python -m evaluation.make_clips [--chrome PATH]` makes the ones whose file is missing (Chrome records the
page-recorded ones) and writes `clips.json` from the lists in `make_clips.py`.

## Labels and the truth

A label agrees with the truth when a word said right is **Correct**, a mistaken word is **Almost** or **Needs
work** (the page draws the learner's attention to it) and a missing word is **Needs work**. A recording refused
as "no speech" gives its words no label. The report gives:

- how many words agree, and the confusion between truth and label;
- **false alarms**: words said right but flagged; **mistakes caught** (recall) and how many flags point at a real
  mistake (precision), per group, condition and kind of mistake;
- for each mistake, whether Whisper wrote the reference word anyway ("heard as the word": its language model
  corrected the learner, and no scoring of its text can catch it), and for each false alarm whether Whisper
  misheard or the alignment and scoring went wrong;
- red letters on words said right; sentence scores against the share of words said right (the score a reading
  deserves) and the tier the result card shows;
- which recordings of noise were scored, and which soft phrases were refused;
- the text simulation (`textsim.py`): known transcripts for every bank sentence, without audio, with one word
  left out, added, repeated or replaced, which measures the alignment and the scoring alone.

Ranges are 95% Wilson intervals. When two runs are compared, the words fixed and broken are counted, with an exact
McNemar test.

## Running it

The pipeline that counts is the one in the image (the packages, ffmpeg and CTranslate2 of production). Build the
image of the commit and mount the set into it (Git Bash: `export MSYS_NO_PATHCONV=1` first):

```bash
docker build --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t aipt:eval .
docker run --rm --network none --cpus 10 --memory 9g -v "$PWD/evaluation:/app/evaluation" -w /app \
  --entrypoint python aipt:eval -m evaluation.harness run --out evaluation/runs/<name>.json
python -m evaluation.harness report evaluation/runs/<name>.json --against evaluation/runs/phase3-6-review.json
```

On the development machine a run scores the recordings in about 3.5 minutes (0.46 s each) and then simulates
the whole bank in about 10 (`--every 25` for a quick look, `--every 0` to skip it). An older image runs the same
harness: mount the current bank too (`-v "$PWD/databases/data_en.csv:/app/databases/data_en.csv:ro"`), as
`runs/phase1-e4a1693.json` was made (phase 1 takes 1.3 s a recording). Recordings added to the set later are
scored with `run --only <prefix>` and joined to a run with `merge`.

Outside the image, the harness runs with the app's requirements, ffmpeg (`FFMPEG_BINARY`) and the models
(`WHISPER_MODEL`, `PIPER_MODEL_DIR`, downloaded on first use otherwise). Whisper's int8 kernels depend on the CPU
(the production VM has AVX but no AVX2; the runs here were made with AVX-512), so compare runs made on the same
machine.

## Judging a change

- **Alignment, normalisation, IPA comparison** (anything after Whisper): `python -m evaluation.harness rescore
  evaluation/runs/phase3-6-review.json --out evaluation/runs/<name>.json --every 1` (the last full run) scores what Whisper heard in
  each recording again with the checkout's code, in seconds, and prints the words fixed and broken.
- **Anything before or inside Whisper** (voice activity detection, scaling by a robust level instead of the peak,
  Whisper's settings): a full `run` in the image.

Then point `REPORT` in `harness.py` at the new run (and `against` at the run it replaces), write the report with
`python -m evaluation.harness report --committed`, and commit the run with the change. `tests/test_evaluation.py`
fails while the committed run is not what the code makes of what Whisper heard, or the report is not the run's
report; it cannot tell that a full run is due, so a change before Whisper must bring its own.

## The runs

`runs/` keeps every run the report has been judged on: `phase1-e4a1693` and `phase2-1c4813c` (the images of phases
1 and 2), then one per step of phase 3: `phase3-2-alignment` and `phase3-3-normalisation` (rescored from phase 2's
run), `phase3-4-level-vad` (a full run: the step changed what Whisper hears), `phase3-5-known-mistakes`
(rescored from it) and `phase3-6-review` (a full run with the review's fixes and the `long_take` recordings, the
phase as merged). Each commit message gives the words its step fixed and broke. The runs before `phase3-6-review`
lack the `long_take` recordings, except phase 2's, which has them.

## Limits

- The voice is one synthetic adult speaker. Children's voices are only approximated (`bank`, `child`: the voice
  raised by 1.3), and real learners make their mistakes less cleanly and with an accent; the set measures the
  scoring, not how learners sound.
- A reading's truth assumes the voice said the words right; Piper's rare slips count against the pipeline.
- espeak-ng's phonemes for this voice are closer to British than American English (`/kˈɑːz/`), unlike the CMU
  dictionary behind the reference IPA.
