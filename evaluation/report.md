# Scoring evaluation

Pipeline: phase 3, step 5: a learner's typical mistake is never Correct. What Whisper heard comes from a run of `2f25672`: Python 3.12.16 on Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.41 (16 CPUs, avx avx2 fma avx512f); faster_whisper 1.2.1, ctranslate2 4.8.5.
435 recordings, 0.45 s each (median), 197.7 s in all, one at a time.

How to read it: `evaluation/README.md`. Each recording says what was said, word by word; a label agrees with the truth when a word said right is Correct, a mistaken word Almost or Needs work, and a word left out Needs work. Ranges in brackets are 95% intervals.

## Summary

|  | phase 2 (main, 1c4813c) | this run |
|---|---|---|
| Recordings of speech scored (not refused as "no speech") | 383/398 (96.2%) | 398/398 (100.0%) [99.0-100.0] |
| Recordings of noise refused as "no speech" | 6/11 (54.5%) | 10/11 (90.9%) [62.3-98.4] |
| Word labels that agree with the truth (all counted words) | 2614/2922 (89.5%) | 2714/2922 (92.9%) [91.9-93.8] |
| Words said right and labelled Correct | 2529/2728 (92.7%) | 2609/2761 (94.5%) [93.6-95.3] |
| Learners' mistakes flagged (Almost or Needs work) | 73/149 (49.0%) | 93/149 (62.4%) [54.4-69.8] |
| Words left out labelled Needs work | 12/12 (100.0%) | 12/12 (100.0%) [75.7-100.0] |
| Flags that point at a real mistake or missing word (precision) | 85/284 (29.9%) | 105/257 (40.9%) [35.0-47.0] |
| Readings without a mistake with every word Correct | 190/251 (75.7%) | 198/251 (78.9%) [73.4-83.5] |
| Readings without a mistake with a red letter somewhere | 96/251 (38.2%) | 53/251 (21.1%) [16.5-26.6] |
| Words said right with a red letter | 278/2728 (10.2%) | 146/2761 (5.3%) [4.5-6.2] |
| Mean distance between a sentence score and the share of its words said right | 9.0 points | 6.9 points |

## Word labels against the truth

Every counted word (2922: all groups but `wrong` and `no_speech`).

| truth | Correct | Almost | Needs work | no speech |
|---|---|---|---|---|
| ok | 2609 | 21 | 131 | 0 |
| error | 56 | 39 | 54 | 0 |
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
| `bank` | 191 | 191/191 (100.0%) | 93.4% | 111/1825 (6.1%) | 61/76 (80.3%) | 94.0 | 96.4 | -2.3 |
| `learner` | 126 | 126/126 (100.0%) | 90.6% | 24/619 (3.9%) | 32/73 (43.8%) | 95.5 | 89.4 | 6.2 |
| `edit` | 18 | 18/18 (100.0%) | 93.7% | 7/99 (7.1%) | 12/12 (100.0%) | 83.9 | 88.8 | -4.8 |
| `normalisation` | 20 | 20/20 (100.0%) | 94.3% | 7/122 (5.7%) | - | 95.4 | 100.0 | -4.6 |
| `soft_tap` | 43 | 43/43 (100.0%) | 96.9% | 3/96 (3.1%) | - | 94.3 | 100.0 | -5.7 |
| `wrong` | 26 | 26/26 (100.0%) | - | - | 258/266 (97.0%) | 3.8 | 0.0 | 3.8 |
| `no_speech` | 11 | 10/11 (90.9%) | - | - | - | - | - | - |

The deserved score of a reading is the share of its words said right; bias is the mean of score minus deserved score.

## By condition

| group/condition | words | said right but flagged | mistakes flagged | not scored | said right with a red letter |
|---|---|---|---|---|---|
| `bank/child` | 276 | 12/276 (4.3%) | - | - | 4.0% |
| `bank/clean` | 276 | 6/276 (2.2%) | - | - | 2.2% |
| `bank/fast` | 276 | 10/276 (3.6%) | - | - | 2.9% |
| `bank/misspelled` | 245 | 23/169 (13.6%) | 61/76 (80.3%) | - | 12.4% |
| `bank/noise0` | 276 | 40/276 (14.5%) | - | - | 14.1% |
| `bank/noise10` | 276 | 11/276 (4.0%) | - | - | 3.6% |
| `bank/slow` | 276 | 9/276 (3.3%) | - | - | 3.6% |
| `edit/filler` | 11 | 1/11 (9.1%) | - | - | 9.1% |
| `edit/omit` | 49 | 5/41 (12.2%) | 8/8 (100.0%) | - | 12.2% |
| `edit/repeat` | 10 | 0/10 (0.0%) | - | - | 0.0% |
| `edit/restart` | 15 | 0/15 (0.0%) | - | - | 0.0% |
| `edit/stop_early` | 26 | 1/22 (4.5%) | 4/4 (100.0%) | - | 4.5% |
| `learner/clean` | 346 | 12/346 (3.5%) | - | - | 3.2% |
| `learner/dh_d` | 41 | 0/33 (0.0%) | 1/8 (12.5%) | - | 0.0% |
| `learner/final_stop` | 53 | 5/43 (11.6%) | 5/10 (50.0%) | - | 9.3% |
| `learner/multi` | 40 | 1/23 (4.3%) | 8/17 (47.1%) | - | 4.3% |
| `learner/past_ed` | 52 | 1/42 (2.4%) | 5/10 (50.0%) | - | 2.4% |
| `learner/plural_s` | 56 | 0/46 (0.0%) | 8/10 (80.0%) | - | 0.0% |
| `learner/sh_s` | 48 | 4/40 (10.0%) | 4/8 (50.0%) | - | 12.5% |
| `learner/th_t` | 56 | 1/46 (2.2%) | 1/10 (10.0%) | - | 2.2% |
| `normalisation/clean` | 122 | 7/122 (5.7%) | - | - | 6.6% |
| `soft_tap/30db` | 18 | 0/18 (0.0%) | - | - | 0.0% |
| `soft_tap/40db` | 18 | 1/18 (5.6%) | - | - | 5.6% |
| `soft_tap/48db` | 18 | 0/18 (0.0%) | - | - | 0.0% |
| `soft_tap/chrome_44db` | 4 | 0/4 (0.0%) | - | - | 0.0% |
| `soft_tap/chrome_52db` | 5 | 0/5 (0.0%) | - | - | 0.0% |
| `soft_tap/phase2_refused` | 33 | 2/33 (6.1%) | - | - | 6.1% |

## Learners' mistakes by kind

A mistake is caught when its word is Almost or Needs work. "Heard as the word" means Whisper wrote the reference word anyway: its language model corrected the learner, and no scoring of its text can catch that mistake.

| group/mistake | words | caught | heard as the word | caught when heard otherwise | a red letter | Correct / Almost / Needs work |
|---|---|---|---|---|---|---|
| `bank/final_stop` | 33 | 22/33 (66.7%) | 11/33 (33.3%) | 22/22 (100.0%) | 22/33 (66.7%) | 11 / 7 / 15 |
| `bank/plural_s` | 13 | 11/13 (84.6%) | 2/13 (15.4%) | 11/11 (100.0%) | 11/13 (84.6%) | 2 / 8 / 3 |
| `bank/th` | 30 | 28/30 (93.3%) | 0/30 (0.0%) | 28/30 (93.3%) | 30/30 (100.0%) | 2 / 3 / 25 |
| `learner/dh_d` | 10 | 1/10 (10.0%) | 9/10 (90.0%) | 1/1 (100.0%) | 1/10 (10.0%) | 9 / 0 / 1 |
| `learner/final_stop` | 12 | 6/12 (50.0%) | 5/12 (41.7%) | 6/7 (85.7%) | 7/12 (58.3%) | 6 / 1 / 5 |
| `learner/past_ed` | 12 | 6/12 (50.0%) | 6/12 (50.0%) | 6/6 (100.0%) | 6/12 (50.0%) | 6 / 5 / 1 |
| `learner/plural_s` | 14 | 11/14 (78.6%) | 3/14 (21.4%) | 11/11 (100.0%) | 11/14 (78.6%) | 3 / 11 / 0 |
| `learner/sh_s` | 11 | 6/11 (54.5%) | 5/11 (45.5%) | 6/6 (100.0%) | 6/11 (54.5%) | 5 / 2 / 4 |
| `learner/th_t` | 14 | 2/14 (14.3%) | 12/14 (85.7%) | 2/2 (100.0%) | 2/14 (14.3%) | 12 / 2 / 0 |

## Where wrong labels come from

- Mistakes labelled Correct: 56; Whisper wrote the reference word for 53 of them (lost by the recogniser) and something else for 3 (lost by the scoring, which still said Correct).
- Words said right but flagged: 152; for 145 the word is nowhere in what Whisper wrote (misheard, or written otherwise: 2:30, okay), for 7 it is there and the alignment or the scoring marked it down.

## Noise and soft speech, recording by recording

| clip | condition | expected | outcome | heard | score |
|---|---|---|---|---|---|
| `tap-01-30db` | 30db | scored | scored | Yes. | 100 |
| `tap-01-40db` | 40db | scored | scored | Yes | 100 |
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
| `tap-05-30db` | 30db | scored | scored | I am well. | 100 |
| `tap-05-40db` | 40db | scored | scored | I am well. | 100 |
| `tap-05-48db` | 48db | scored | scored | I am well. | 100 |
| `tap-06-30db` | 30db | scored | scored | Look at it. | 100 |
| `tap-06-40db` | 40db | scored | scored | Look at it. | 100 |
| `tap-06-48db` | 48db | scored | scored | Look at it. | 100 |
| `tap-07-30db` | 30db | scored | scored | We had lunch. | 100 |
| `tap-07-40db` | 40db | scored | scored | We have lunch. | 80 |
| `tap-07-48db` | 48db | scored | scored | We had to launch. | 90 |
| `tap-08-30db` | 30db | scored | scored | Good morning! | 100 |
| `tap-08-40db` | 40db | scored | scored | Good morning. | 100 |
| `tap-08-48db` | 48db | scored | scored | Good morning. | 100 |
| `tap-chrome-01-44db` | chrome_44db | scored | scored | Thank you. | 100 |
| `tap-chrome-02-44db` | chrome_44db | scored | scored | It's okay. | 100 |
| `tap-chrome-03-52db` | chrome_52db | scored | scored | I am well | 100 |
| `tap-chrome-04-52db` | chrome_52db | scored | scored | Good morning | 100 |
| `tap-p2-01` | phase2_refused | scored | scored | I am well. | 100 |
| `tap-p2-02` | phase2_refused | scored | scored | I'm sorry. | 100 |
| `tap-p2-03` | phase2_refused | scored | scored | Look at it. | 100 |
| `tap-p2-04` | phase2_refused | scored | scored | Yes. | 100 |
| `tap-p2-05` | phase2_refused | scored | scored | Speed up. | 100 |
| `tap-p2-06` | phase2_refused | scored | scored | Down. | -50 |
| `tap-p2-07` | phase2_refused | scored | scored | We had lunch. | 100 |
| `tap-p2-08` | phase2_refused | scored | scored | BAM! Then owner. | 33 |
| `tap-p2-09` | phase2_refused | scored | scored | Run! | 100 |
| `tap-p2-10` | phase2_refused | scored | scored | Speed up! | 100 |
| `tap-p2-11` | phase2_refused | scored | scored | I am well. | 100 |
| `tap-p2-12` | phase2_refused | scored | scored | I'm sorry. | 100 |
| `tap-p2-13` | phase2_refused | scored | scored | Look at it. | 100 |
| `tap-p2-14` | phase2_refused | scored | scored | Look at it. | 100 |
| `tap-p2-15` | phase2_refused | scored | scored | I am well. | 100 |
| `noise-white` | white | no speech | no speech |  |  |
| `noise-quiet` | quiet | no speech | no speech |  |  |
| `noise-hum` | hum | no speech | no speech |  |  |
| `noise-keyboard` | keyboard | no speech | no speech |  |  |
| `noise-page-01` | page_standin | no speech | no speech |  |  |
| `noise-page-02` | page_standin | no speech | no speech |  |  |
| `noise-page-03` | page_standin | no speech | no speech |  |  |
| `noise-page-04` | page_standin | no speech | no speech |  |  |
| `noise-page-05` | page_capture | no speech | scored **(wrong)** | I'm not sure if I'm going to get it right. | 12 |
| `noise-page-06` | page_capture | no speech | no speech |  |  |
| `noise-page-07` | page_capture | no speech | no speech |  |  |

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
- `tap-p2-06` (phase2_refused): heard "Down.": **Go.** labelled needs_work (aligned with "Down.")
- `tap-p2-08` (phase2_refused): heard "BAM! Then owner.": **Banana.** labelled needs_work (aligned with "BAM!")

## Against phase 2 (main, 1c4813c)

Of 2922 counted words, 141 changed label; 114 went from wrong to right and 14 from right to wrong (McNemar p = 1.16e-20).

| group | outcome as expected | labels agree | said right but flagged | mistakes and missing words flagged | mean score |
|---|---|---|---|---|---|
| `bank` | 100.0% → 100.0% | 92.1% → 93.4% | 6.9% → 6.1% | 68.4% → 80.3% | 92.1 → 94.0 |
| `learner` | 100.0% → 100.0% | 86.6% → 90.6% | 6.6% → 3.9% | 28.8% → 43.8% | 91.3 → 95.5 |
| `edit` | 100.0% → 100.0% | 87.4% → 93.7% | 14.1% → 7.1% | 100.0% → 100.0% | 76.8 → 83.9 |
| `normalisation` | 100.0% → 100.0% | 89.3% → 94.3% | 10.7% → 5.7% | - → - | 89.0 → 95.4 |
| `soft_tap` | 65.1% → 100.0% | 60.4% → 96.9% | 7.9% → 3.1% | - → - | 93.2 → 94.3 |
| `wrong` | 100.0% → 100.0% | - → - | - → - | 98.5% → 97.0% | -0.9 → 3.8 |
| `no_speech` | 54.5% → 90.9% | - → - | - → - | - → - | - → - |

Each cell: phase 2 (main, 1c4813c) → this run.

Wrong before, right now (114; the first 10):

- `bank-s05-misspelled` **of** (ok): needs_work → correct
- `bank-s05-misspelled` **gas.** (ok): needs_work → correct
- `bank-s10-clean` **Is** (ok): needs_work → correct
- `bank-s10-noise0` **me?** (ok): needs_work → correct
- `bank-s12-misspelled` **still** (ok): almost → correct
- `bank-s13-noise0` **me?** (ok): needs_work → correct
- `bank-s17-misspelled` **This** (error): correct → almost
- `bank-s17-misspelled` **watch** (ok): needs_work → correct
- `bank-s17-misspelled` **is** (ok): needs_work → correct
- `bank-s17-noise0` **watch** (ok): needs_work → correct

Right before, wrong now (14; the first 10):

- `bank-s08-fast` **this** (ok): correct → needs_work
- `bank-s12-noise0` **still** (ok): correct → almost
- `bank-s12-noise0` **at** (ok): correct → needs_work
- `bank-s14-misspelled` **parking** (ok): correct → needs_work
- `bank-s16-noise0` **old** (ok): correct → needs_work
- `bank-s26-child` **crossed** (ok): correct → almost
- `bank-s26-child` **chance.** (ok): correct → almost
- `bank-s26-noise10` **there** (ok): correct → almost
- `bank-s26-noise10` **by** (ok): correct → needs_work
- `learner-34-final_stop` **milk** (error): needs_work → correct
