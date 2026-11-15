# Scoring evaluation

Pipeline: phase 3 after its review: a level 50 ms of loud samples cannot set, VAD needs 96 ms of speech, numbers and compounds read alike. What Whisper heard comes from a run of `the commit that adds this run`: Python 3.12.16 on Linux-6.18.33.2-microsoft-standard-WSL2-x86_64-with-glibc2.41 (16 CPUs, avx avx2 fma avx512f); faster_whisper 1.2.1, ctranslate2 4.8.5.
441 recordings, 0.4 s each (median), 175.8 s in all, one at a time.

How to read it: `evaluation/README.md`. Each recording says what was said, word by word; a label agrees with the truth when a word said right is Correct, a mistaken word Almost or Needs work, and a word left out Needs work. Ranges in brackets are 95% intervals.

## Summary

|  | phase 2 (main, 1c4813c) | this run |
|---|---|---|
| Recordings of speech scored (not refused as "no speech") | 389/404 (96.3%) | 404/404 (100.0%) [99.1-100.0] |
| Recordings of noise refused as "no speech" | 6/11 (54.5%) | 10/11 (90.9%) [62.3-98.4] |
| Word labels that agree with the truth (all counted words) | 2627/2935 (89.5%) | 2730/2935 (93.0%) [92.0-93.9] |
| Words said right and labelled Correct | 2542/2741 (92.7%) | 2622/2774 (94.5%) [93.6-95.3] |
| Learners' mistakes flagged (Almost or Needs work) | 73/149 (49.0%) | 96/149 (64.4%) [56.5-71.7] |
| Words left out labelled Needs work | 12/12 (100.0%) | 12/12 (100.0%) [75.7-100.0] |
| Flags that point at a real mistake or missing word (precision) | 85/284 (29.9%) | 108/260 (41.5%) [35.7-47.6] |
| Readings without a mistake with every word Correct | 190/251 (75.7%) | 199/251 (79.3%) [73.8-83.8] |
| Readings without a mistake with a red letter somewhere | 96/251 (38.2%) | 53/251 (21.1%) [16.5-26.6] |
| Words said right with a red letter | 278/2741 (10.1%) | 144/2774 (5.2%) [4.4-6.1] |
| Mean distance between a sentence score and the share of its words said right | 8.9 points | 6.8 points |

## Word labels against the truth

Every counted word (2935: all groups but `wrong` and `no_speech`).

| truth | Correct | Almost | Needs work | no speech |
|---|---|---|---|---|
| ok | 2622 | 20 | 132 | 0 |
| error | 53 | 40 | 56 | 0 |
| missing | 0 | 0 | 12 | 0 |

## By group

- `bank`: Bank sentences (phase 2 parity set): clean, slow, fast, noise, child-like voice, misspelled
- `learner`: Vietnamese learners' typical mistakes, made in the phonemes, and the same sentences read clean
- `edit`: A word left out, the reading stopped early, a word repeated, a filler, a fresh start
- `normalisation`: Read correctly; Whisper may write the words otherwise (2:30, 3-day, OK, Mr., colour, %)
- `soft_tap`: A short phrase spoken softly after a much louder tap on Record
- `long_take`: A short phrase at a normal level, then a long wait before Stop (18-25 s)
- `wrong`: A clean reading scored against another sentence
- `no_speech`: Noise alone, encoded by ffmpeg or recorded by Chrome as the page records

| group | clips | outcome as expected | labels agree | words said right but flagged | mistakes and missing words flagged | mean score | deserved | bias |
|---|---|---|---|---|---|---|---|---|
| `bank` | 191 | 191/191 (100.0%) | 93.5% | 111/1825 (6.1%) | 63/76 (82.9%) | 93.9 | 96.4 | -2.5 |
| `learner` | 126 | 126/126 (100.0%) | 90.8% | 24/619 (3.9%) | 33/73 (45.2%) | 95.5 | 89.4 | 6.1 |
| `edit` | 18 | 18/18 (100.0%) | 93.7% | 7/99 (7.1%) | 12/12 (100.0%) | 83.9 | 88.8 | -4.8 |
| `normalisation` | 20 | 20/20 (100.0%) | 94.3% | 7/122 (5.7%) | - | 95.4 | 100.0 | -4.6 |
| `soft_tap` | 43 | 43/43 (100.0%) | 96.9% | 3/96 (3.1%) | - | 94.3 | 100.0 | -5.7 |
| `long_take` | 6 | 6/6 (100.0%) | 100.0% | 0/13 (0.0%) | - | 100.0 | 100.0 | 0.0 |
| `wrong` | 26 | 26/26 (100.0%) | - | - | 258/266 (97.0%) | 4.1 | 0.0 | 4.1 |
| `no_speech` | 11 | 10/11 (90.9%) | - | - | - | - | - | - |

The deserved score of a reading is the share of its words said right; bias is the mean of score minus deserved score.

## By condition

| group/condition | words | said right but flagged | mistakes flagged | not scored | said right with a red letter |
|---|---|---|---|---|---|
| `bank/child` | 276 | 11/276 (4.0%) | - | - | 3.6% |
| `bank/clean` | 276 | 6/276 (2.2%) | - | - | 2.2% |
| `bank/fast` | 276 | 11/276 (4.0%) | - | - | 3.3% |
| `bank/misspelled` | 245 | 26/169 (15.4%) | 63/76 (82.9%) | - | 13.6% |
| `bank/noise0` | 276 | 39/276 (14.1%) | - | - | 13.4% |
| `bank/noise10` | 276 | 9/276 (3.3%) | - | - | 3.3% |
| `bank/slow` | 276 | 9/276 (3.3%) | - | - | 3.6% |
| `edit/filler` | 11 | 1/11 (9.1%) | - | - | 9.1% |
| `edit/omit` | 49 | 5/41 (12.2%) | 8/8 (100.0%) | - | 12.2% |
| `edit/repeat` | 10 | 0/10 (0.0%) | - | - | 0.0% |
| `edit/restart` | 15 | 0/15 (0.0%) | - | - | 0.0% |
| `edit/stop_early` | 26 | 1/22 (4.5%) | 4/4 (100.0%) | - | 4.5% |
| `learner/clean` | 346 | 12/346 (3.5%) | - | - | 3.2% |
| `learner/dh_d` | 41 | 0/33 (0.0%) | 1/8 (12.5%) | - | 0.0% |
| `learner/final_stop` | 53 | 6/43 (14.0%) | 5/10 (50.0%) | - | 9.3% |
| `learner/multi` | 40 | 1/23 (4.3%) | 7/17 (41.2%) | - | 4.3% |
| `learner/past_ed` | 52 | 1/42 (2.4%) | 6/10 (60.0%) | - | 2.4% |
| `learner/plural_s` | 56 | 0/46 (0.0%) | 8/10 (80.0%) | - | 0.0% |
| `learner/sh_s` | 48 | 3/40 (7.5%) | 4/8 (50.0%) | - | 10.0% |
| `learner/th_t` | 56 | 1/46 (2.2%) | 2/10 (20.0%) | - | 2.2% |
| `long_take/19s` | 3 | 0/3 (0.0%) | - | - | 0.0% |
| `long_take/21s` | 2 | 0/2 (0.0%) | - | - | 0.0% |
| `long_take/23s` | 2 | 0/2 (0.0%) | - | - | 0.0% |
| `long_take/24s` | 2 | 0/2 (0.0%) | - | - | 0.0% |
| `long_take/25.5s` | 3 | 0/3 (0.0%) | - | - | 0.0% |
| `long_take/25s` | 1 | 0/1 (0.0%) | - | - | 0.0% |
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
| `bank/final_stop` | 33 | 23/33 (69.7%) | 10/33 (30.3%) | 23/23 (100.0%) | 23/33 (69.7%) | 10 / 6 / 17 |
| `bank/plural_s` | 13 | 12/13 (92.3%) | 1/13 (7.7%) | 12/12 (100.0%) | 12/13 (92.3%) | 1 / 9 / 3 |
| `bank/th` | 30 | 28/30 (93.3%) | 0/30 (0.0%) | 28/30 (93.3%) | 30/30 (100.0%) | 2 / 3 / 25 |
| `learner/dh_d` | 10 | 1/10 (10.0%) | 9/10 (90.0%) | 1/1 (100.0%) | 1/10 (10.0%) | 9 / 0 / 1 |
| `learner/final_stop` | 12 | 6/12 (50.0%) | 5/12 (41.7%) | 6/7 (85.7%) | 7/12 (58.3%) | 6 / 1 / 5 |
| `learner/past_ed` | 12 | 7/12 (58.3%) | 5/12 (41.7%) | 7/7 (100.0%) | 7/12 (58.3%) | 5 / 6 / 1 |
| `learner/plural_s` | 14 | 11/14 (78.6%) | 3/14 (21.4%) | 11/11 (100.0%) | 11/14 (78.6%) | 3 / 11 / 0 |
| `learner/sh_s` | 11 | 5/11 (45.5%) | 6/11 (54.5%) | 5/5 (100.0%) | 5/11 (45.5%) | 6 / 1 / 4 |
| `learner/th_t` | 14 | 3/14 (21.4%) | 11/14 (78.6%) | 3/3 (100.0%) | 3/14 (21.4%) | 11 / 3 / 0 |

## Where wrong labels come from

- Mistakes labelled Correct: 53; Whisper wrote the reference word for 50 of them (lost by the recogniser) and something else for 3 (lost by the scoring, which still said Correct).
- Words said right but flagged: 152; for 145 the word is nowhere in what Whisper wrote (misheard, or written otherwise: 2:30, okay), for 7 it is there and the alignment or the scoring marked it down.

## Noise and soft speech, recording by recording

| clip | condition | expected | outcome | heard | score |
|---|---|---|---|---|---|
| `tap-01-30db` | 30db | scored | scored | Yes. | 100 |
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
| `tap-chrome-03-52db` | chrome_52db | scored | scored | I am well. | 100 |
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
| `noise-page-05` | page_capture | no speech | scored **(wrong)** | I'm sorry. | 0 |
| `noise-page-06` | page_capture | no speech | no speech |  |  |
| `noise-page-07` | page_capture | no speech | no speech |  |  |

## Text simulation over the bank

Known transcripts for 10671 bank sentences, without audio (`textsim.py`): the alignment and the scoring alone.

| transcript | sentences | every word right | words said right but flagged | a neighbour of the changed word flagged | changed word flagged | a red letter on a word said right |
|---|---|---|---|---|---|---|
| `exact` | 10671 | 10671/10671 (100.0%) | 0/76707 (0.0%) | - | - | 0/10671 (0.0%) |
| `plain` | 10671 | 10668/10671 (100.0%) | 3/76707 (0.0%) | - | - | 1/10671 (0.0%) |
| `drop` | 10641 | 10639/10641 (100.0%) | 2/66006 (0.0%) | 2/10641 (0.0%) | 10641/10641 (100.0%) | 1/10641 (0.0%) |
| `add` | 10641 | 10641/10641 (100.0%) | 0/76647 (0.0%) | 0/10641 (0.0%) | - | 0/10641 (0.0%) |
| `repeat` | 10641 | 10641/10641 (100.0%) | 0/76647 (0.0%) | 0/10641 (0.0%) | - | 0/10641 (0.0%) |
| `substitute` | 10641 | 10632/10641 (99.9%) | 2/66006 (0.0%) | 2/10641 (0.0%) | 10634/10641 (99.9%) | 0/10641 (0.0%) |

## Examples

Mistakes labelled Correct:

- `bank-s04-misspelled` final_stop: said "No one aske your opinion.", heard "No one asked your opinion.": **asked** labelled correct
- `bank-s06-misspelled` final_stop: said "Te ground was covere in snow.", heard "Teak round was covered in snow.": **covered** labelled correct
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

Of 2935 counted words, 143 changed label; 115 went from wrong to right and 12 from right to wrong (McNemar p = 2.82e-22).

| group | outcome as expected | labels agree | said right but flagged | mistakes and missing words flagged | mean score |
|---|---|---|---|---|---|
| `bank` | 100.0% → 100.0% | 92.1% → 93.5% | 6.9% → 6.1% | 68.4% → 82.9% | 92.1 → 93.9 |
| `learner` | 100.0% → 100.0% | 86.6% → 90.8% | 6.6% → 3.9% | 28.8% → 45.2% | 91.3 → 95.5 |
| `edit` | 100.0% → 100.0% | 87.4% → 93.7% | 14.1% → 7.1% | 100.0% → 100.0% | 76.8 → 83.9 |
| `normalisation` | 100.0% → 100.0% | 89.3% → 94.3% | 10.7% → 5.7% | - → - | 89.0 → 95.4 |
| `soft_tap` | 65.1% → 100.0% | 60.4% → 96.9% | 7.9% → 3.1% | - → - | 93.2 → 94.3 |
| `long_take` | 100.0% → 100.0% | 100.0% → 100.0% | 0.0% → 0.0% | - → - | 100.0 → 100.0 |
| `wrong` | 100.0% → 100.0% | - → - | - → - | 98.5% → 97.0% | -0.9 → 4.1 |
| `no_speech` | 54.5% → 90.9% | - → - | - → - | - → - | - → - |

Each cell: phase 2 (main, 1c4813c) → this run.

Wrong before, right now (115; the first 10):

- `bank-s05-misspelled` **gas.** (ok): needs_work → correct
- `bank-s10-clean` **Is** (ok): needs_work → correct
- `bank-s10-noise0` **me?** (ok): needs_work → correct
- `bank-s12-misspelled` **still** (ok): almost → correct
- `bank-s13-noise0` **me?** (ok): needs_work → correct
- `bank-s17-misspelled` **This** (error): correct → almost
- `bank-s17-noise0` **watch** (ok): needs_work → correct
- `bank-s17-noise0` **is** (ok): needs_work → correct
- `bank-s19-misspelled` **two** (ok): needs_work → correct
- `bank-s20-misspelled` **John** (ok): needs_work → correct

Right before, wrong now (12; the first 10):

- `bank-s08-fast` **this** (ok): correct → needs_work
- `bank-s12-noise0` **still** (ok): correct → almost
- `bank-s12-noise0` **at** (ok): correct → needs_work
- `bank-s14-misspelled` **parking** (ok): correct → needs_work
- `bank-s16-fast` **begging** (ok): correct → needs_work
- `bank-s23-misspelled` **doesn't** (ok): correct → almost
- `bank-s26-child` **crossed** (ok): correct → almost
- `learner-34-final_stop` **milk** (error): needs_work → correct
- `learner-47-clean` **Tom** (ok): correct → needs_work
- `learner-57-multi` **thirty** (error): needs_work → correct
