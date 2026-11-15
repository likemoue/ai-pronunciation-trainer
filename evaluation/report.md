# Scoring evaluation

Pipeline at `1c4813c`; Python 3.12.16 on Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.41 (16 CPUs, avx avx2 fma avx512f); faster_whisper 1.2.1, ctranslate2 4.8.5.
435 recordings, 0.46 s each (median), 205.4 s in all, one at a time.

How to read it: `evaluation/README.md`. Each recording says what was said, word by word; a label agrees with the truth when a word said right is Correct, a mistaken word Almost or Needs work, and a word left out Needs work. Ranges in brackets are 95% intervals.

## Summary

|  | phase 1 (e4a1693) | this run |
|---|---|---|
| Recordings of speech scored (not refused as "no speech") | 398/398 (100.0%) | 383/398 (96.2%) [93.9-97.7] |
| Recordings of noise refused as "no speech" | 0/11 (0.0%) | 6/11 (54.5%) [28.0-78.7] |
| Word labels that agree with the truth (all counted words) | 2698/2922 (92.3%) | 2614/2922 (89.5%) [88.3-90.5] |
| Words said right and labelled Correct | 2610/2761 (94.5%) | 2529/2728 (92.7%) [91.7-93.6] |
| Learners' mistakes flagged (Almost or Needs work) | 76/149 (51.0%) | 73/149 (49.0%) [41.1-56.9] |
| Words left out labelled Needs work | 12/12 (100.0%) | 12/12 (100.0%) [75.7-100.0] |
| Flags that point at a real mistake or missing word (precision) | 88/239 (36.8%) | 85/284 (29.9%) [24.9-35.5] |
| Readings without a mistake with every word Correct | 196/251 (78.1%) | 190/251 (75.7%) [70.0-80.6] |
| Readings without a mistake with a red letter somewhere | 95/251 (37.8%) | 96/251 (38.2%) [32.5-44.4] |
| Words said right with a red letter | 245/2761 (8.9%) | 278/2728 (10.2%) [9.1-11.4] |
| Mean distance between a sentence score and the share of its words said right | 8.3 points | 9.0 points |

## Word labels against the truth

Every counted word (2922: all groups but `wrong` and `no_speech`).

| truth | Correct | Almost | Needs work | no speech |
|---|---|---|---|---|
| ok | 2529 | 12 | 187 | 33 |
| error | 76 | 15 | 58 | 0 |
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
| `bank` | 191 | 191/191 (100.0%) | 92.1% | 126/1825 (6.9%) | 52/76 (68.4%) | 92.1 | 96.4 | -4.2 |
| `learner` | 126 | 126/126 (100.0%) | 86.6% | 41/619 (6.6%) | 21/73 (28.8%) | 91.3 | 89.4 | 2.0 |
| `edit` | 18 | 18/18 (100.0%) | 87.4% | 14/99 (14.1%) | 12/12 (100.0%) | 76.8 | 88.8 | -12.0 |
| `normalisation` | 20 | 20/20 (100.0%) | 89.3% | 13/122 (10.7%) | - | 89.0 | 100.0 | -11.1 |
| `soft_tap` | 43 | 28/43 (65.1%) | 60.4% | 5/63 (7.9%) | - | 93.2 | 100.0 | -6.8 |
| `wrong` | 26 | 26/26 (100.0%) | - | - | 262/266 (98.5%) | -0.9 | 0.0 | -0.9 |
| `no_speech` | 11 | 6/11 (54.5%) | - | - | - | - | - | - |

The deserved score of a reading is the share of its words said right; bias is the mean of score minus deserved score.

## By condition

| group/condition | words | said right but flagged | mistakes flagged | not scored | said right with a red letter |
|---|---|---|---|---|---|
| `bank/child` | 276 | 11/276 (4.0%) | - | - | 8.3% |
| `bank/clean` | 276 | 7/276 (2.5%) | - | - | 5.8% |
| `bank/fast` | 276 | 10/276 (3.6%) | - | - | 6.9% |
| `bank/misspelled` | 245 | 36/169 (21.3%) | 52/76 (68.4%) | - | 21.9% |
| `bank/noise0` | 276 | 43/276 (15.6%) | - | - | 17.4% |
| `bank/noise10` | 276 | 10/276 (3.6%) | - | - | 7.6% |
| `bank/slow` | 276 | 9/276 (3.3%) | - | - | 7.6% |
| `edit/filler` | 11 | 1/11 (9.1%) | - | - | 9.1% |
| `edit/omit` | 49 | 12/41 (29.3%) | 8/8 (100.0%) | - | 29.3% |
| `edit/repeat` | 10 | 0/10 (0.0%) | - | - | 0.0% |
| `edit/restart` | 15 | 0/15 (0.0%) | - | - | 0.0% |
| `edit/stop_early` | 26 | 1/22 (4.5%) | 4/4 (100.0%) | - | 18.2% |
| `learner/clean` | 346 | 20/346 (5.8%) | - | - | 7.8% |
| `learner/dh_d` | 41 | 3/33 (9.1%) | 1/8 (12.5%) | - | 9.1% |
| `learner/final_stop` | 53 | 7/43 (16.3%) | 6/10 (60.0%) | - | 14.0% |
| `learner/multi` | 40 | 3/23 (13.0%) | 6/17 (35.3%) | - | 17.4% |
| `learner/past_ed` | 52 | 1/42 (2.4%) | 5/10 (50.0%) | - | 2.4% |
| `learner/plural_s` | 56 | 1/46 (2.2%) | 0/10 (0.0%) | - | 6.5% |
| `learner/sh_s` | 48 | 5/40 (12.5%) | 3/8 (37.5%) | - | 12.5% |
| `learner/th_t` | 56 | 1/46 (2.2%) | 0/10 (0.0%) | - | 4.3% |
| `normalisation/clean` | 122 | 13/122 (10.7%) | - | - | 16.4% |
| `soft_tap/30db` | 18 | 1/18 (5.6%) | - | - | 5.6% |
| `soft_tap/40db` | 18 | 2/18 (11.1%) | - | - | 11.1% |
| `soft_tap/48db` | 18 | 1/18 (5.6%) | - | - | 5.6% |
| `soft_tap/chrome_44db` | 4 | 1/4 (25.0%) | - | - | 25.0% |
| `soft_tap/chrome_52db` | 5 | 0/5 (0.0%) | - | - | 0.0% |
| `soft_tap/phase2_refused` | 33 | - | - | 33/33 (100.0%) | - |

## Learners' mistakes by kind

A mistake is caught when its word is Almost or Needs work. "Heard as the word" means Whisper wrote the reference word anyway: its language model corrected the learner, and no scoring of its text can catch that mistake.

| group/mistake | words | caught | heard as the word | caught when heard otherwise | a red letter | Correct / Almost / Needs work |
|---|---|---|---|---|---|---|
| `bank/final_stop` | 33 | 21/33 (63.6%) | 11/33 (33.3%) | 21/22 (95.5%) | 22/33 (66.7%) | 12 / 5 / 16 |
| `bank/plural_s` | 13 | 4/13 (30.8%) | 2/13 (15.4%) | 4/11 (36.4%) | 11/13 (84.6%) | 9 / 1 / 3 |
| `bank/th` | 30 | 27/30 (90.0%) | 0/30 (0.0%) | 27/30 (90.0%) | 30/30 (100.0%) | 3 / 2 / 25 |
| `learner/dh_d` | 10 | 1/10 (10.0%) | 9/10 (90.0%) | 1/1 (100.0%) | 1/10 (10.0%) | 9 / 0 / 1 |
| `learner/final_stop` | 12 | 7/12 (58.3%) | 5/12 (41.7%) | 7/7 (100.0%) | 7/12 (58.3%) | 5 / 1 / 6 |
| `learner/past_ed` | 12 | 6/12 (50.0%) | 5/12 (41.7%) | 6/7 (85.7%) | 7/12 (58.3%) | 6 / 4 / 2 |
| `learner/plural_s` | 14 | 0/14 (0.0%) | 3/14 (21.4%) | 0/11 (0.0%) | 11/14 (78.6%) | 14 / 0 / 0 |
| `learner/sh_s` | 11 | 5/11 (45.5%) | 6/11 (54.5%) | 5/5 (100.0%) | 5/11 (45.5%) | 6 / 2 / 3 |
| `learner/th_t` | 14 | 2/14 (14.3%) | 9/14 (64.3%) | 2/5 (40.0%) | 6/14 (42.9%) | 12 / 0 / 2 |

## Where wrong labels come from

- Mistakes labelled Correct: 76; Whisper wrote the reference word for 50 of them (lost by the recogniser) and something else for 26 (lost by the scoring, which still said Correct).
- Words said right but flagged: 199; for 171 the word is nowhere in what Whisper wrote (misheard, or written otherwise: 2:30, okay), for 28 it is there and the alignment or the scoring marked it down.

## Noise and soft speech, recording by recording

| clip | condition | expected | outcome | heard | score |
|---|---|---|---|---|---|
| `tap-01-30db` | 30db | scored | scored | Yes | 100 |
| `tap-01-40db` | 40db | scored | scored | Yes. | 100 |
| `tap-01-48db` | 48db | scored | scored | Yes | 100 |
| `tap-02-30db` | 30db | scored | scored | Thank you. | 100 |
| `tap-02-40db` | 40db | scored | scored | Thank you. | 100 |
| `tap-02-48db` | 48db | scored | scored | Thank you. | 100 |
| `tap-03-30db` | 30db | scored | scored | It's okay. | 60 |
| `tap-03-40db` | 40db | scored | scored | It's okay. | 60 |
| `tap-03-48db` | 48db | scored | scored | It's okay. | 60 |
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
| `tap-chrome-02-44db` | chrome_44db | scored | scored | It's okay. | 60 |
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
| `noise-page-05` | page_capture | no speech | scored **(wrong)** | I'm not sure if I can do it. | 8 |
| `noise-page-06` | page_capture | no speech | scored **(wrong)** | I'm not sure if I can do it. I'm not sure if I can do it. I'm not sure if I can do it. | 8 |
| `noise-page-07` | page_capture | no speech | scored **(wrong)** | I'm going to get you a new car. I'm going to get you a new car. I'm going to get you a new car. | 8 |

## Text simulation over the bank

Known transcripts for 10671 bank sentences, without audio (`textsim.py`): the alignment and the scoring alone.

| transcript | sentences | every word right | words said right but flagged | a neighbour of the changed word flagged | changed word flagged | a red letter on a word said right |
|---|---|---|---|---|---|---|
| `exact` | 10671 | 9186/10671 (86.1%) | 0/76707 (0.0%) | - | - | 1485/10671 (13.9%) |
| `plain` | 10671 | 8437/10671 (79.1%) | 893/76707 (1.2%) | - | - | 2234/10671 (20.9%) |
| `drop` | 10641 | 3144/10641 (29.5%) | 7166/66006 (10.9%) | 7166/10641 (67.3%) | 10637/10641 (100.0%) | 7497/10641 (70.5%) |
| `add` | 10641 | 9158/10641 (86.1%) | 0/76647 (0.0%) | 0/10641 (0.0%) | - | 1483/10641 (13.9%) |
| `repeat` | 10641 | 9158/10641 (86.1%) | 0/76647 (0.0%) | 0/10641 (0.0%) | - | 1483/10641 (13.9%) |
| `substitute` | 10641 | 9394/10641 (88.3%) | 20/66006 (0.0%) | 20/10641 (0.2%) | 10637/10641 (100.0%) | 1244/10641 (11.7%) |

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

- `bank-s01-noise0` (noise0): heard "We have to help talk.": **Tom.** labelled needs_work (aligned with "-")
- `bank-s02-misspelled` (misspelled): heard "Tarsa Jelk": **a** labelled needs_work (aligned with "-")
- `bank-s02-misspelled` (misspelled): heard "Tarsa Jelk": **joke.** labelled needs_work (aligned with "-")
- `learner-06-clean` (clean): heard "We can't thank Tom for that.": **can** labelled almost (aligned with "can't")
- `learner-06-th_t` (th_t): heard "We can tank tone for that.": **Tom** labelled needs_work (aligned with "tone")
- `learner-11-dh_d` (dh_d): heard "Please do dis-for-me.": **do** labelled needs_work (aligned with "-")
- `edit-01-omit` (omit): heard "Look through the pages.": **the** labelled needs_work (aligned with "-")
- `edit-02-omit` (omit): heard "The dog ran a fox.": **ran** labelled needs_work (aligned with "-")
- `edit-03-omit` (omit): heard "He eats nothing bread.": **nothing** labelled needs_work (aligned with "-")
- `norm-04` (clean): heard "Wait just three minutes.": **3** labelled needs_work (aligned with "three")
- `norm-07` (clean): heard "A small cup of coffee costs Euros 2.": **€2.** labelled needs_work (aligned with "2.")
- `norm-08` (clean): heard "We were next door neighbors.": **next-door** labelled needs_work (aligned with "door")
- `tap-03-30db` (30db): heard "It's okay.": **OK.** labelled needs_work (aligned with "-")
- `tap-03-40db` (40db): heard "It's okay.": **OK.** labelled needs_work (aligned with "-")
- `tap-03-48db` (48db): heard "It's okay.": **OK.** labelled needs_work (aligned with "-")

## Against phase 1 (e4a1693)

Of 2922 counted words, 130 changed label; 18 went from wrong to right and 102 from right to wrong (McNemar p = 1.98e-15).

| group | outcome as expected | labels agree | said right but flagged | mistakes and missing words flagged | mean score |
|---|---|---|---|---|---|
| `bank` | 100.0% → 100.0% | 94.4% → 92.1% | 4.6% → 6.9% | 71.1% → 68.4% | 93.7 → 92.1 |
| `learner` | 100.0% → 100.0% | 87.4% → 86.6% | 5.8% → 6.6% | 30.1% → 28.8% | 91.6 → 91.3 |
| `edit` | 100.0% → 100.0% | 91.0% → 87.4% | 10.1% → 14.1% | 100.0% → 100.0% | 78.8 → 76.8 |
| `normalisation` | 100.0% → 100.0% | 89.3% → 89.3% | 10.7% → 10.7% | - → - | 89.1 → 89.0 |
| `soft_tap` | 100.0% → 65.1% | 91.7% → 60.4% | 8.3% → 7.9% | - → - | 91.5 → 93.2 |
| `wrong` | 100.0% → 100.0% | - → - | - → - | 99.2% → 98.5% | -1.4 → -0.9 |
| `no_speech` | 0.0% → 54.5% | - → - | - → - | - → - | - → - |

Each cell: phase 1 (e4a1693) → this run.

Wrong before, right now (18; the first 10):

- `bank-s05-noise0` **Tom** (ok): needs_work → correct
- `bank-s14-misspelled` **parking** (ok): needs_work → correct
- `bank-s16-misspelled` **in** (ok): needs_work → correct
- `bank-s17-noise0` **twice** (ok): needs_work → correct
- `bank-s21-slow` **tried** (ok): needs_work → correct
- `bank-s26-misspelled` **bridge** (ok): almost → correct
- `bank-s27-fast` **He** (ok): needs_work → correct
- `bank-s27-misspelled` **He** (ok): needs_work → correct
- `learner-11-dh_d` **this** (error): correct → needs_work
- `learner-34-clean` **put** (ok): needs_work → correct

Right before, wrong now (102; the first 10):

- `bank-s05-misspelled` **of** (ok): correct → needs_work
- `bank-s05-misspelled` **gas.** (ok): correct → needs_work
- `bank-s10-clean` **Is** (ok): correct → needs_work
- `bank-s12-misspelled` **Tom** (ok): correct → needs_work
- `bank-s12-misspelled` **is** (ok): correct → needs_work
- `bank-s12-misspelled` **still** (ok): correct → almost
- `bank-s12-misspelled` **house.** (ok): correct → needs_work
- `bank-s12-noise0` **Tom** (ok): correct → needs_work
- `bank-s12-noise0` **is** (ok): correct → needs_work
- `bank-s13-noise10` **Why** (ok): correct → needs_work
