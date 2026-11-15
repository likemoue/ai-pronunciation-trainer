# Scoring evaluation

Pipeline: phase 3, step 3: words read as they are said (numbers, spellings, homophones). What Whisper heard comes from a run of `1c4813c`: Python 3.12.16 on Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.41 (16 CPUs, avx avx2 fma avx512f); faster_whisper 1.2.1, ctranslate2 4.8.5.
435 recordings, 0.46 s each (median), 205.4 s in all, one at a time.

How to read it: `evaluation/README.md`. Each recording says what was said, word by word; a label agrees with the truth when a word said right is Correct, a mistaken word Almost or Needs work, and a word left out Needs work. Ranges in brackets are 95% intervals.

## Summary

|  | step 2 (alignment) | this run |
|---|---|---|
| Recordings of speech scored (not refused as "no speech") | 383/398 (96.2%) | 383/398 (96.2%) [93.9-97.7] |
| Recordings of noise refused as "no speech" | 6/11 (54.5%) | 6/11 (54.5%) [28.0-78.7] |
| Word labels that agree with the truth (all counted words) | 2637/2922 (90.2%) | 2658/2922 (91.0%) [89.9-92.0] |
| Words said right and labelled Correct | 2552/2728 (93.5%) | 2576/2728 (94.4%) [93.5-95.2] |
| Learners' mistakes flagged (Almost or Needs work) | 73/149 (49.0%) | 70/149 (47.0%) [39.1-55.0] |
| Words left out labelled Needs work | 12/12 (100.0%) | 12/12 (100.0%) [75.7-100.0] |
| Flags that point at a real mistake or missing word (precision) | 85/261 (32.6%) | 82/234 (35.0%) [29.2-41.4] |
| Readings without a mistake with every word Correct | 190/251 (75.7%) | 199/251 (79.3%) [73.8-83.8] |
| Readings without a mistake with a red letter somewhere | 64/251 (25.5%) | 51/251 (20.3%) [15.8-25.7] |
| Words said right with a red letter | 171/2728 (6.3%) | 144/2728 (5.3%) [4.5-6.2] |
| Mean distance between a sentence score and the share of its words said right | 7.7 points | 6.7 points |

## Word labels against the truth

Every counted word (2922: all groups but `wrong` and `no_speech`).

| truth | Correct | Almost | Needs work | no speech |
|---|---|---|---|---|
| ok | 2576 | 19 | 133 | 33 |
| error | 79 | 16 | 54 | 0 |
| missing | 0 | 0 | 12 | 0 |

## By group

- `bank`: Bank sentences (phase 2 parity set): clean, slow, fast, noise, child-like voice, misspelled
- `learner`: Vietnamese learners' typical mistakes, made in the phonemes, and the same sentences read clean
- `edit`: A word left out, the reading stopped early, a word repeated, a filler, a fresh start
- `normalisation`: Read correctly; Whisper may write the words otherwise (2:30, 3-day, OK, Mr., colour, %)
- `soft_tap`: A short phrase spoken softly after a much louder tap on Record
- `wrong`: A clean reading scored against another sentence
- `no_speech`: Noise alone, encoded by ffmpeg or recorded by Chrome as the page records

| group | clips | outcome as expected | labels agree | words said right but flagged | mistakes and missing words flagged | mean score | deserved | bias |
|---|---|---|---|---|---|---|---|---|
| `bank` | 191 | 191/191 (100.0%) | 92.8% | 112/1825 (6.1%) | 52/76 (68.4%) | 93.8 | 96.4 | -2.5 |
| `learner` | 126 | 126/126 (100.0%) | 88.4% | 25/619 (4.0%) | 18/73 (24.7%) | 95.4 | 89.4 | 6.1 |
| `edit` | 18 | 18/18 (100.0%) | 93.7% | 7/99 (7.1%) | 12/12 (100.0%) | 83.9 | 88.8 | -4.8 |
| `normalisation` | 20 | 20/20 (100.0%) | 94.3% | 7/122 (5.7%) | - | 95.4 | 100.0 | -4.6 |
| `soft_tap` | 43 | 28/43 (65.1%) | 64.6% | 1/63 (1.6%) | - | 98.9 | 100.0 | -1.1 |
| `wrong` | 26 | 26/26 (100.0%) | - | - | 258/266 (97.0%) | 3.8 | 0.0 | 3.8 |
| `no_speech` | 11 | 6/11 (54.5%) | - | - | - | - | - | - |

The deserved score of a reading is the share of its words said right; bias is the mean of score minus deserved score.

## By condition

| group/condition | words | said right but flagged | mistakes flagged | not scored | said right with a red letter |
|---|---|---|---|---|---|
| `bank/child` | 276 | 11/276 (4.0%) | - | - | 4.0% |
| `bank/clean` | 276 | 7/276 (2.5%) | - | - | 2.2% |
| `bank/fast` | 276 | 10/276 (3.6%) | - | - | 3.3% |
| `bank/misspelled` | 245 | 25/169 (14.8%) | 52/76 (68.4%) | - | 11.8% |
| `bank/noise0` | 276 | 40/276 (14.5%) | - | - | 14.1% |
| `bank/noise10` | 276 | 10/276 (3.6%) | - | - | 3.6% |
| `bank/slow` | 276 | 9/276 (3.3%) | - | - | 3.6% |
| `edit/filler` | 11 | 1/11 (9.1%) | - | - | 9.1% |
| `edit/omit` | 49 | 5/41 (12.2%) | 8/8 (100.0%) | - | 12.2% |
| `edit/repeat` | 10 | 0/10 (0.0%) | - | - | 0.0% |
| `edit/restart` | 15 | 0/15 (0.0%) | - | - | 0.0% |
| `edit/stop_early` | 26 | 1/22 (4.5%) | 4/4 (100.0%) | - | 4.5% |
| `learner/clean` | 346 | 11/346 (3.2%) | - | - | 2.9% |
| `learner/dh_d` | 41 | 0/33 (0.0%) | 1/8 (12.5%) | - | 0.0% |
| `learner/final_stop` | 53 | 7/43 (16.3%) | 6/10 (60.0%) | - | 11.6% |
| `learner/multi` | 40 | 1/23 (4.3%) | 3/17 (17.6%) | - | 4.3% |
| `learner/past_ed` | 52 | 1/42 (2.4%) | 5/10 (50.0%) | - | 2.4% |
| `learner/plural_s` | 56 | 0/46 (0.0%) | 0/10 (0.0%) | - | 0.0% |
| `learner/sh_s` | 48 | 4/40 (10.0%) | 3/8 (37.5%) | - | 12.5% |
| `learner/th_t` | 56 | 1/46 (2.2%) | 0/10 (0.0%) | - | 2.2% |
| `normalisation/clean` | 122 | 7/122 (5.7%) | - | - | 6.6% |
| `soft_tap/30db` | 18 | 0/18 (0.0%) | - | - | 0.0% |
| `soft_tap/40db` | 18 | 1/18 (5.6%) | - | - | 5.6% |
| `soft_tap/48db` | 18 | 0/18 (0.0%) | - | - | 0.0% |
| `soft_tap/chrome_44db` | 4 | 0/4 (0.0%) | - | - | 0.0% |
| `soft_tap/chrome_52db` | 5 | 0/5 (0.0%) | - | - | 0.0% |
| `soft_tap/phase2_refused` | 33 | - | - | 33/33 (100.0%) | - |

## Learners' mistakes by kind

A mistake is caught when its word is Almost or Needs work. "Heard as the word" means Whisper wrote the reference word anyway: its language model corrected the learner, and no scoring of its text can catch that mistake.

| group/mistake | words | caught | heard as the word | caught when heard otherwise | a red letter | Correct / Almost / Needs work |
|---|---|---|---|---|---|---|
| `bank/final_stop` | 33 | 21/33 (63.6%) | 11/33 (33.3%) | 21/22 (95.5%) | 22/33 (66.7%) | 12 / 6 / 15 |
| `bank/plural_s` | 13 | 4/13 (30.8%) | 2/13 (15.4%) | 4/11 (36.4%) | 11/13 (84.6%) | 9 / 1 / 3 |
| `bank/th` | 30 | 27/30 (90.0%) | 0/30 (0.0%) | 27/30 (90.0%) | 30/30 (100.0%) | 3 / 2 / 25 |
| `learner/dh_d` | 10 | 1/10 (10.0%) | 9/10 (90.0%) | 1/1 (100.0%) | 1/10 (10.0%) | 9 / 0 / 1 |
| `learner/final_stop` | 12 | 7/12 (58.3%) | 5/12 (41.7%) | 7/7 (100.0%) | 7/12 (58.3%) | 5 / 1 / 6 |
| `learner/past_ed` | 12 | 5/12 (41.7%) | 5/12 (41.7%) | 5/7 (71.4%) | 7/12 (58.3%) | 7 / 4 / 1 |
| `learner/plural_s` | 14 | 0/14 (0.0%) | 3/14 (21.4%) | 0/11 (0.0%) | 11/14 (78.6%) | 14 / 0 / 0 |
| `learner/sh_s` | 11 | 5/11 (45.5%) | 6/11 (54.5%) | 5/5 (100.0%) | 5/11 (45.5%) | 6 / 2 / 3 |
| `learner/th_t` | 14 | 0/14 (0.0%) | 11/14 (78.6%) | 0/3 (0.0%) | 3/14 (21.4%) | 14 / 0 / 0 |

## Where wrong labels come from

- Mistakes labelled Correct: 79; Whisper wrote the reference word for 52 of them (lost by the recogniser) and something else for 27 (lost by the scoring, which still said Correct).
- Words said right but flagged: 152; for 145 the word is nowhere in what Whisper wrote (misheard, or written otherwise: 2:30, okay), for 7 it is there and the alignment or the scoring marked it down.

## Noise and soft speech, recording by recording

| clip | condition | expected | outcome | heard | score |
|---|---|---|---|---|---|
| `tap-01-30db` | 30db | scored | scored | Yes | 100 |
| `tap-01-40db` | 40db | scored | scored | Yes. | 100 |
| `tap-01-48db` | 48db | scored | scored | Yes | 100 |
| `tap-02-30db` | 30db | scored | scored | Thank you. | 100 |
| `tap-02-40db` | 40db | scored | scored | Thank you. | 100 |
| `tap-02-48db` | 48db | scored | scored | Thank you. | 100 |
| `tap-03-30db` | 30db | scored | scored | It's okay. | 100 |
| `tap-03-40db` | 40db | scored | scored | It's okay. | 100 |
| `tap-03-48db` | 48db | scored | scored | It's okay. | 100 |
| `tap-04-30db` | 30db | scored | scored | Speed up. | 100 |
| `tap-04-40db` | 40db | scored | scored | Speed up. | 100 |
| `tap-04-48db` | 48db | scored | scored | Speed up. | 100 |
| `tap-05-30db` | 30db | scored | scored | I am well | 100 |
| `tap-05-40db` | 40db | scored | scored | I am well. | 100 |
| `tap-05-48db` | 48db | scored | scored | I am well | 100 |
| `tap-06-30db` | 30db | scored | scored | Look at it. | 100 |
| `tap-06-40db` | 40db | scored | scored | Look at it. | 100 |
| `tap-06-48db` | 48db | scored | scored | Look at it. | 100 |
| `tap-07-30db` | 30db | scored | scored | We had lunch. | 100 |
| `tap-07-40db` | 40db | scored | scored | We have lunch. | 80 |
| `tap-07-48db` | 48db | scored | scored | We had the launch. | 90 |
| `tap-08-30db` | 30db | scored | scored | Good morning. | 100 |
| `tap-08-40db` | 40db | scored | scored | Good morning. | 100 |
| `tap-08-48db` | 48db | scored | scored | Good morning. | 100 |
| `tap-chrome-01-44db` | chrome_44db | scored | scored | Thank you. | 100 |
| `tap-chrome-02-44db` | chrome_44db | scored | scored | It's okay. | 100 |
| `tap-chrome-03-52db` | chrome_52db | scored | scored | I am well. | 100 |
| `tap-chrome-04-52db` | chrome_52db | scored | scored | Good morning | 100 |
| `tap-p2-01` | phase2_refused | scored | no speech **(wrong)** |  |  |
| `tap-p2-02` | phase2_refused | scored | no speech **(wrong)** |  |  |
| `tap-p2-03` | phase2_refused | scored | no speech **(wrong)** |  |  |
| `tap-p2-04` | phase2_refused | scored | no speech **(wrong)** |  |  |
| `tap-p2-05` | phase2_refused | scored | no speech **(wrong)** |  |  |
| `tap-p2-06` | phase2_refused | scored | no speech **(wrong)** |  |  |
| `tap-p2-07` | phase2_refused | scored | no speech **(wrong)** |  |  |
| `tap-p2-08` | phase2_refused | scored | no speech **(wrong)** |  |  |
| `tap-p2-09` | phase2_refused | scored | no speech **(wrong)** |  |  |
| `tap-p2-10` | phase2_refused | scored | no speech **(wrong)** |  |  |
| `tap-p2-11` | phase2_refused | scored | no speech **(wrong)** |  |  |
| `tap-p2-12` | phase2_refused | scored | no speech **(wrong)** |  |  |
| `tap-p2-13` | phase2_refused | scored | no speech **(wrong)** |  |  |
| `tap-p2-14` | phase2_refused | scored | no speech **(wrong)** |  |  |
| `tap-p2-15` | phase2_refused | scored | no speech **(wrong)** |  |  |
| `noise-white` | white | no speech | no speech |  |  |
| `noise-quiet` | quiet | no speech | no speech |  |  |
| `noise-hum` | hum | no speech | no speech |  |  |
| `noise-keyboard` | keyboard | no speech | no speech |  |  |
| `noise-page-01` | page_standin | no speech | scored **(wrong)** | I'm sorry. | 0 |
| `noise-page-02` | page_standin | no speech | no speech |  |  |
| `noise-page-03` | page_standin | no speech | no speech |  |  |
| `noise-page-04` | page_standin | no speech | scored **(wrong)** | I'm sorry. | 0 |
| `noise-page-05` | page_capture | no speech | scored **(wrong)** | I'm not sure if I can do it. | 12 |
| `noise-page-06` | page_capture | no speech | scored **(wrong)** | I'm not sure if I can do it. I'm not sure if I can do it. I'm not sure if I can do it. | 25 |
| `noise-page-07` | page_capture | no speech | scored **(wrong)** | I'm going to get you a new car. I'm going to get you a new car. I'm going to get you a new car. | 29 |

## Text simulation over the bank

Known transcripts for 10671 bank sentences, without audio (`textsim.py`): the alignment and the scoring alone.

| transcript | sentences | every word right | words said right but flagged | a neighbour of the changed word flagged | changed word flagged | a red letter on a word said right |
|---|---|---|---|---|---|---|
| `exact` | 10671 | 10671/10671 (100.0%) | 0/76707 (0.0%) | - | - | 0/10671 (0.0%) |
| `plain` | 10671 | 10668/10671 (100.0%) | 3/76707 (0.0%) | - | - | 1/10671 (0.0%) |
| `drop` | 10641 | 10641/10641 (100.0%) | 0/66006 (0.0%) | 0/10641 (0.0%) | 10641/10641 (100.0%) | 0/10641 (0.0%) |
| `add` | 10641 | 10641/10641 (100.0%) | 0/76647 (0.0%) | 0/10641 (0.0%) | - | 0/10641 (0.0%) |
| `repeat` | 10641 | 10641/10641 (100.0%) | 0/76647 (0.0%) | 0/10641 (0.0%) | - | 0/10641 (0.0%) |
| `substitute` | 10641 | 10634/10641 (99.9%) | 0/66006 (0.0%) | 0/10641 (0.0%) | 10634/10641 (99.9%) | 0/10641 (0.0%) |

## Examples

Mistakes labelled Correct:

- `bank-s04-misspelled` final_stop: said "No one aske your opinion.", heard "No one asked your opinion.": **asked** labelled correct
- `bank-s06-misspelled` final_stop: said "Te ground was covere in snow.", heard "Teague round was covered in snow.": **covered** labelled correct
- `bank-s08-misspelled` final_stop: said "Tom staye a tis hotel for three week.", heard "Tom stay at his hotel for three weeks.": **at** labelled correct
- `bank-s08-misspelled` th: said "Tom staye a tis hotel for three week.", heard "Tom stay at his hotel for three weeks.": **this** labelled correct
- `learner-01-th_t` th_t: said "Who do you /tˈɪŋk/ will win?", heard "Who do you think will win?": **think** labelled correct
- `learner-02-th_t` th_t: said "Mary can speak /tɹˈiː/ languages.", heard "Mary can speak three languages.": **three** labelled correct
- `learner-03-th_t` th_t: said "Tom did a foolish /tˈɪŋ/.", heard "Tom did a foolish thing.": **thing.** labelled correct
- `learner-04-th_t` th_t: said "Did I say /sˈʌmtɪŋ/ wrong?", heard "Did I say something wrong?": **something** labelled correct

Words said right but flagged:

- `bank-s01-noise0` (noise0): heard "We have to help talk.": **Tom.** labelled needs_work (aligned with "talk.")
- `bank-s02-misspelled` (misspelled): heard "Tarsa Jelk": **a** labelled needs_work (aligned with "-")
- `bank-s02-misspelled` (misspelled): heard "Tarsa Jelk": **joke.** labelled needs_work (aligned with "Jelk")
- `learner-06-clean` (clean): heard "We can't thank Tom for that.": **can** labelled almost (aligned with "can't")
- `learner-06-th_t` (th_t): heard "We can tank tone for that.": **Tom** labelled needs_work (aligned with "tone")
- `learner-19-clean` (clean): heard "She wore red dress.": **a** labelled needs_work (aligned with "-")
- `edit-07-omit` (omit): heard "Tum to beset by trying to calm down.": **Tom** labelled almost (aligned with "Tum")
- `edit-07-omit` (omit): heard "Tum to beset by trying to calm down.": **took** labelled needs_work (aligned with "to")
- `edit-07-omit` (omit): heard "Tum to beset by trying to calm down.": **a** labelled needs_work (aligned with "-")
- `norm-07` (clean): heard "A small cup of coffee costs Euros 2.": **€2.** labelled needs_work (aligned with "Euros-2.")
- `norm-11` (clean): heard "A small forest broke float between the moss-covered trees.": **brook** labelled almost (aligned with "broke")
- `norm-11` (clean): heard "A small forest broke float between the moss-covered trees.": **flowed** labelled needs_work (aligned with "float")
- `tap-07-40db` (40db): heard "We have lunch.": **had** labelled needs_work (aligned with "have")

## Against step 2 (alignment)

Of 2922 counted words, 29 changed label; 24 went from wrong to right and 3 from right to wrong (McNemar p = 4.92e-05).

| group | outcome as expected | labels agree | said right but flagged | mistakes and missing words flagged | mean score |
|---|---|---|---|---|---|
| `bank` | 100.0% → 100.0% | 92.7% → 92.8% | 6.3% → 6.1% | 68.4% → 68.4% | 93.6 → 93.8 |
| `learner` | 100.0% → 100.0% | 87.3% → 88.4% | 5.8% → 4.0% | 28.8% → 24.7% | 93.0 → 95.4 |
| `edit` | 100.0% → 100.0% | 93.7% → 93.7% | 7.1% → 7.1% | 100.0% → 100.0% | 83.9 → 83.9 |
| `normalisation` | 100.0% → 100.0% | 89.3% → 94.3% | 10.7% → 5.7% | - → - | 89.0 → 95.4 |
| `soft_tap` | 65.1% → 65.1% | 60.4% → 64.6% | 7.9% → 1.6% | - → - | 93.2 → 98.9 |
| `wrong` | 100.0% → 100.0% | - → - | - → - | 97.0% → 97.0% | 1.5 → 3.8 |
| `no_speech` | 54.5% → 54.5% | - → - | - → - | - → - | - → - |

Each cell: step 2 (alignment) → this run.

Wrong before, right now (24; the first 10):

- `bank-s26-noise0` **tall** (ok): needs_work → correct
- `bank-s26-noise0` **tree** (ok): needs_work → correct
- `bank-s29-misspelled` **too** (ok): needs_work → correct
- `learner-11-dh_d` **for** (ok): needs_work → correct
- `learner-11-dh_d` **me.** (ok): needs_work → correct
- `learner-41-clean` **five** (ok): needs_work → correct
- `learner-41-plural_s` **five** (ok): needs_work → correct
- `learner-57-clean` **thirty** (ok): needs_work → correct
- `learner-61-clean` **there** (ok): almost → correct
- `learner-61-multi` **there** (ok): almost → correct

Right before, wrong now (3; the first 10):

- `learner-57-multi` **thirty** (error): needs_work → correct
- `learner-60-multi` **liked** (error): almost → correct
- `learner-62-multi` **Three** (error): needs_work → correct
