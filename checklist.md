# Flows to check

Each feature adds the flows it touches. Before a release is called done, walk through them on the public site
right after the deploy (deploy.sh goes from its checks to the switch without stopping). `--rollback` undoes a
release without downtime, except the first deploy with the phase-1 deploy.sh, which leaves no previous colour:
`deploy.sh --rollback-legacy` undoes that one, with downtime. "Auto" means a test, a CI job or a deploy step
already checks it on every change.

## Bank: no person names (2026-11)

The school's rule: "He is a student", not "Tom is a student". 1,925 sentences that began with a name got He,
She or They; 1,344 other sentences with a name were removed (9,318 left: 7,173 easy, 2,081 medium, 64 hard).
The scoring does not change.

- [ ] On the public site, Next a dozen times at each level (Easy, Medium, Hard, Random): no person names, and
      the sentences read naturally ("He ...", "She ...", "They ...").
- [ ] Listen on a changed sentence: its MP3 is made on the first request and plays.
- [x] Auto: `tests/test_content.py` fails on a name (`PERSON_NAMES`), on duplicates and on a level with fewer
      than 50 sentences; `tests/test_evaluation.py` checks the text simulation of the new bank.

## Footer: the iSMART credit (2026-11)

The footer reads "© 2026 iSMART · Developed by Quí (IT Department)" ("Phát triển bởi" in Vietnamese)
in place of the credits to the original project, its source code and Tatoeba. Nothing else changes.

- [ ] The footer in English and Vietnamese, on a phone and on a computer: one line of plain text, no links;
      switching the language changes it in place.
- [x] Auto: `tests/test_i18n.py` renders it in both languages.

Under it, a 10 px line keeps the licence notice the AGPL-3.0 and CC BY 2.0 FR ask for: the original project,
the source code and Tatoeba, as links.

- [ ] The notice in English and Vietnamese, on a 320 px phone and on a computer: small, under the credit,
      the three links open in a new tab; switching the language changes it in place.
- [x] Auto: `tests/test_i18n.py` checks the three links and both licences in both languages.

## Phase 4: frontend, mobile, accessibility, in-app browsers (2026-11)

Built from the approved wireframes (`design/wireframes/`) and `context/design-system.md`. The page is rebuilt; the
API gains two fields (the scoring's `mistake_kinds`, getSample's `category`) and the page's language; scores
and labels do not change. Check every learner flow on a phone
(Chrome Android, Safari iOS) and in Zalo, Facebook and Messenger on both, and on Chrome 109 (Windows 7 labs),
in English and Vietnamese, light and dark.

### Learner flows
- [ ] First visit: the 3-step tour over the real controls, then the 3-second microphone check (nothing uploaded);
      Skip at every step; Escape skips; the tour never comes back by itself; "Show the tour again" and "Check my
      microphone" from How it works (phones) or the header (desktop). It does not start by itself inside an app's
      browser (the banner speaks first), in a browser that cannot record, where the browser keeps nothing
      (private modes that refuse storage), or while a sheet is open; its flag is `aipt.tour` in localStorage.
- [ ] Microphone check: the browser's prompt explained first ("tap Allow", not shown when already allowed), 3 s
      with a moving meter, then "Your microphone works" (Start practising: focus on Listen), "We didn't hear
      anything" with three things to check, or the recording sheet's own steps (blocked in Chrome Android, Safari
      iOS, desktop; no microphone; busy), and inside an app its way out (Open in Chrome, Copy link, the ••• steps).
      The microphone light goes off when it ends; Cancel, ✕ and Escape at every step.
- [ ] Choose a level: the chip is a radio group (arrow keys), the card shows a skeleton, the sentence comes in its
      level; a chip chosen while loading cancels the first request; a failed load shows the error in the card with
      Try again (or a notice above the bar when a sentence is already shown); getSample gives up after 15 s.
- [ ] Listen: the bank sentence's MP3, Stop while it plays, Slow at 0.75x; tapping the mic stops the voice and a
      voice still loading never plays into the recording; a busy or failing voice falls back to a local browser
      voice, and with none a notice says so.
- [ ] Record, phone and desktop: the sheet (phone) or dialog (desktop) with its fixed header and actions; "We can't
      hear you" after 3.5 s of silence; the 5 s countdown and the stop at 30 s; Checking, Still checking, the busy
      server sending again by itself (3 times); the score. The backdrop never closes it; ✕, Cancel and Escape do;
      Space and Enter act on the focused button only; holding Space does not stop at once.
- [ ] Failures: a server or network failure and the 100 s timeout keep the recording (Send again, Record again,
      Close); offline keeps it too and says when the connection is back; no speech (422), too short, interrupted
      (tab hidden, a call, a headset unplugged: nothing is sent); the microphone blocked (steps for Chrome Android,
      Safari iOS, desktop Chrome/Edge), none, busy, other errors. A silent take of 1-4 s says "We couldn't hear any
      words" and is not sent (Chrome makes it smaller than 1 KB, which used to read as too short); under 0.6 s is
      too short.
- [ ] Recording sheet, edge cases: Cancel while the browser still asks for the microphone, then the mic again: the
      new take records (the late answer is let go); a double tap on the mic or on Stop never lands on the buttons
      that replace them; a recording the server cannot read (400) asks for a new take; a microphone blocked in the
      site's settings opens the sheet on the steps at once; turning a tablet redraws the state (tap or click).
- [ ] Result: ring and title by tier (90/70/60; Excellent, Well done, Almost there, Keep practising), the meaning
      line, "Words to practise" (at most 4, "+N more"), the worst word opened, the word detail (Correct and Heard
      IPA, Listen and Replay; "not heard" disables Replay), My recording, the "Heard" line (3 lines, then "more"),
      the legend; ~ and ✗ marks only on Almost and Needs-work words, and the sentence's line height unchanged by
      them; wrong letters bold and dotted; fewer than 35% of the words heard gives "That sounds like a different
      sentence" (no chips); the chime by tier (70/60), none when the score comes late or a recording starts; on
      desktop Try again and Next sentence on the card. Focus goes to the result's title and one sentence is
      announced ("Score 79%. 3 words to practise: written, three, books.").
- [ ] A text read past 30 s: the take stops by itself and the result says the end was not recorded.
- [ ] Typical mistakes: "book" for "books", "tree" for "three", "sip" for "ship" give an Almost word whose detail
      says what to fix, with Listen buttons for both words (EN and VI).
- [ ] My text: the counters count the text as the server will (300 characters, 60 words), the reading time and
      the warning above about 26 s; too long, not English, unreadable characters stop before sending; text pasted
      from Word (curly quotes, cp1252 characters, zero-width spaces) is accepted; the draft comes back; Ctrl/⌘+Enter
      sends; the card says "My text" with Edit; a chip or Next goes back to the bank.
- [ ] Language: EN | VI in the header switches every text in place, is remembered on the device, and the next visit
      opens in that language with no English first (`lang` cookie); the sentence and IPA stay English; numbers and
      dates follow the language; no server message is shown as it comes.
- [ ] Progress: the ★ chip shows today's points (12.5K from 10,000; "245 today · 3 days" from 768 px); the sheet
      shows today, the streak and the last 7 days in Vietnam time (a day starts at midnight in Vietnam, whatever
      the device's zone), words to review (✗ first, at most 12, then Show all); tapping a word practises it alone
      ("Word to review", Back to sentences; a level chip or Next go back too) and its result updates the list; a
      word leaves after two Correct readings; each sentence counts once a day with its best attempt, at its own
      level's multiplier (Random no longer pays x1.3; an older server without getSample's category: the level asked
      for, or Random by word count), and sending the same text again pays nothing more; "That sounds like a
      different sentence" counts for nothing; "New learner" asks first (focus on Cancel), then clears points,
      streak, words, the draft and the tour flag, keeps the language and shows "Progress deleted" with the tour one
      tap away. Two tabs keep one record (`aipt.progress.v1`); a damaged or older record starts again quietly.
- [ ] In-app browsers: the banner names Zalo, Facebook, Messenger, Instagram, LINE or a WebView; Open in Chrome
      (Android intent link), Copy link ("Copied" for 4 s, said once; the address to copy by hand when the
      clipboard is refused), ✕, or Not now where an arrow points at the app's ••• or ⋮ menu, for the visit; when
      recording fails inside an app, the sheet repeats that guidance instead of browser steps.
- [ ] Offline: a notice above the controls, Next disabled, the mic usable; a recording made offline can be sent
      once back online. A browser that cannot record says so before the first tap, with the mic disabled.

### Layout, accessibility, browsers
- [ ] 320, 360 and 390 px wide: no horizontal scroll, sentence and mic in the first screen at 360 x 640, the bar
      fixed with the safe area, and not fixed when the screen is under 480 px tall; 360 x 560 (Zalo's bar).
- [ ] 768 px: inline controls, centred dialogs; 1024 and 1280 px: two columns, the result beside the sentence.
- [ ] Light and dark, every state; reduced motion stops the ring, the count-up and the pulses; 200% text size.
- [ ] Keyboard only: focus order banner, header, chips, sentence, controls, result; sheets trap focus and give it
      back; Space starts recording only when focus is not on a control. Screen reader: one announcement per phase,
      the result in one sentence, marks read as words.
- [ ] Chrome 109 and iOS 15: the focus outline, the sheet overlay and the marks all show (no `color-mix()`, `inert`
      fallback, `:focus-visible` fallback, `100vh` before `100dvh`).

### API and operations
- [ ] The scoring answer has `mistake_kinds`, one per word; scores and labels are unchanged. Auto:
      `tests/test_word_matching.py`, `tests/test_evaluation.py`.
- [ ] `/getSample` answers the sentence's own `category` (1-3), also for Random (0). Auto: `tests/test_api.py`.
- [ ] The page is rendered in the `lang` cookie's language (`Vary: Cookie`); its strings come from `i18n/`; the CSP
      still allows no inline script (the strings are a JSON data block). Auto: `tests/test_i18n.py`.
- [ ] Every script and the stylesheet are versioned by content and cached for a year only under the current
      version. Auto: `tests/test_assets.py`, `tests/test_static.py`.
- [ ] A learner who keeps an old page open across the deploy can still record and get a score (the API only gained
      fields); a new page after `deploy.sh --rollback` still works without them.
- [ ] CI runs ESLint and the Playwright tests (a fake microphone plays the app's own voice into the real image);
      the Node tools stay out of the image. Auto: `ci.yml`, `tests/test_build.py`.

## Phase 3: scoring accuracy (2026-11)

### Step 1: the evaluation harness (`evaluation/`)
Adds no code to the image and changes no learner flow: the page, the API and the scores stay as they are.
- [x] The harness scores the 441 recordings of `evaluation/clips.json` in the image as the server does, and its
      report (`evaluation/report.md`) is the report of the committed run. Auto: `tests/test_evaluation.py` (the run
      is what the code makes of what Whisper heard; the text simulation's digest; the report).
- [x] The set holds only synthetic voices and sentences fit for a class. Auto: `tests/test_evaluation.py` (the
      bank's blocklist and removed sentences, every recording decodes as an upload, size limits).
- [x] CI runs the evaluation tests in the image as well (the set is mounted there, as the tests are).
- [x] Each later step of phase 3 brings its own run and report (`evaluation/runs/phase3-*`), each better than the
      last (commit messages); `evaluation/report.md` compares the last with phase 2.

### Steps 2-5: the scoring (what learners see changes)
The API and the page are unchanged; labels, letter colours and scores change, and the image loses dtwalign.
- [ ] Record and score a sentence of each level on the public site: scores and colours as before for a clean reading,
      no red letter on a word read right (double letters: "will", "all"). Auto: smoke test (deploy.sh), the
      evaluation tests, `tests/test_word_matching.py`.
- [ ] A sentence with a time or a number ("We need to get home before 2:30."): read right, every word Correct.
      Auto: `tests/test_word_matching.py`.
- [ ] Leave a word out: only that word is red. Auto: `tests/test_word_matching.py`, the text simulation.
- [ ] Say "book" for "books": the word is orange (Almost), not green. Auto: `tests/test_word_matching.py`.
- [ ] Noise, or silence with a tap: "We couldn't recognise any speech" rather than a score. Auto: the slow tests
      (noise as WAV and WebM through the real models), `tests/test_whisper_wrapper.py` (the VAD gate).
- [ ] A short phrase said softly: scored, not refused. Auto: the evaluation set (`soft_tap`).
- [ ] The first recording after a deploy is not slow any more (no JIT compilation): `scored` log lines.

## Bank review (2026-11)

- [x] No sentence of the bank is unsuitable for a class: a second review read all 11,028 sentences and removed 357
      (10,671 left), from "Semen is worth bottling." to stereotypes, alcohol, religion and politics.
      Auto: `tests/test_content.py` (the blocklist, now with these topics, and `tests/content_removed_en.tsv`, the
      removed sentences, which must not come back).
- [ ] New sentence in each level after the deploy; every level still has sentences. Auto: `tests/test_content.py`.

## Phase 2: performance (2026-11)

Deployed 2026-11-15 (eec70e3) and walked through the same evening (the boxes below), on the public site in the
built-in browser with a stand-in microphone that plays the server's own voice, and on the server through port 3000.
That evening the server's virtual CPU offered no AVX (`QEMU Virtual CPU version 2.5+`: SSE4.2 at most), so Whisper
took about 2.2 s per recording there, against 0.6-0.8 s on the machine the PR was measured on; the numbers below are
from that CPU. Later the same evening the VM was switched to `cpu: host` (AVX, no AVX2): 1.8 s per recording, and
40 recordings at once 20.6 s at the median, 34.1 s at the 90th percentile and 40.4 s at most (3 sent again). The
site was unavailable for about 2 minutes while the VM restarted.

### Learner flows
- [x] Record and score a sentence of each level: score, letter colours, per-word IPA and playback, with
      faster-whisper. Auto: smoke test, warm-up at build and start, slow tests in the image. Checked once on the
      parity set (Piper readings of 30 bank sentences, 239 clips): see the PR for the numbers. On the public site:
      easy and medium heard word for word, hard with two words misheard (red letters).
- [ ] Noise or silence gives "We couldn't recognise any speech", not an invented sentence. Auto: `tests/test_api.py`
      (silence), the slow tests in the image (white noise as WAV and as the page's WebM/Opus, and hum, through the
      real model; no word after a sentence; a single word before a pause is still scored). By hand, on a phone: tap
      Record and stay silent for 5-8 s. Noise shaped by the browser's noise suppression still gave words in about
      one recording in six in the tests (phase 3: voice activity detection).
      On 2026-11-15: silence never reaches the server (the page says the recording is too short). On the server,
      seeded white noise encoded by ffmpeg gave "no speech" 5 of 5 times as WAV and 4 of 5 as WebM/Opus 32 kbps,
      but white noise recorded by the page in Chromium came back as "I'm sorry." 4 of 4 times, at three levels: the
      learner sees "Keep practising" instead of "We can't hear you" (phase 3).
- [x] A class at once (30-40 recordings within a few seconds): every learner gets a score; anyone the server turns
      away sees "The server is busy - sending your recording again in N s" and gets a score without recording again.
      Auto, in part: `tests/test_queue.py` (503 with Retry-After, places given back). Load test on the server through
      port 3000 on 2026-11-15, 15:02-15:06 UTC: 40 at once, all scored, 10 sent again after a 503, median 24.2 s,
      90th percentile 41.7 s, slowest 46.1 s; 40 over 10 s, all scored, 8 sent again, 22.0 / 39.5 / 43.6 s; 20 at
      once, none sent again, slowest 24.6 s. The page and a sample answered in 0.02 s at most throughout.
- [x] Closing the popup while a recording waits: the server skips it (`"outcome": "client_gone"` in the log).
      A recording behind 8 others, abandoned after 1 s, was skipped 16.6 s later without running Whisper. One
      abandoned while it is being scored is still scored.
- [x] Listen to a bank sentence: an MP3 from `/tts/en/<key>.mp3`, from Cloudflare's cache the second time
      (`cf-cache-status: HIT`). Your own text and single words still use `/getAudioFromText`. Auto: `tests/test_bank_audio.py`.
- [x] The result chime plays (good, okay, needs work) with no sound file downloaded.
- [x] Fonts come from the app (Network tab: no request to Google), the IPA symbols render in Noto Sans, θ included.
      Auto: `tests/test_static.py` (every IPA symbol of the bank is in a served subset). The Greek subset loads for θ.
- [ ] Phone browsers (Chrome Android, Safari iOS, Zalo in-app browser): record at 32 kbps and score once each.

### Operations
- [x] A deploy and the canary during a class at work: the smoke test sends busy recordings again and passes, and
      the learners' recordings are scored while both colours score for about a minute (simulated with two classes
      on 10 CPUs: 80 of 80 scored, the slowest in 26 s; without `GOMP_SPINCOUNT`, 18 of 80 failed). On the server:
      40 recordings over 10 s while deploy.sh started the new colour; the old one scored until 24 s after the switch
      while the new one took the rest: 40 of 40 scored, 15 sent again, median 28.5 s, slowest 54.2 s; Whisper 3.0 s
      per recording instead of 2.2 s; the smoke test through port 3000 waited behind the class and passed (13.9 s).
- [x] After a deploy, a page opened before it keeps working: its old `?v=` assets are answered with `no-cache`, the
      new page gets the new version. Auto: `tests/test_static.py`. The phase 1 page, open across the deploy, took
      a new sentence and scored; it lost only its result sounds (404, phase 2 removed them). Cloudflare turns the
      app's `no-cache` for an old or unknown `?v=` into `max-age=14400` (the zone's browser cache TTL), so after a
      rollback a browser could keep a newer app.js under the old URL for up to 4 hours; a cache rule for this host
      that respects the origin's headers would end that.
- [x] `docker logs`: `scored` lines carry `queue_ahead`, `lock_wait_ms`, `asr_ms`; `busy` outcomes are rare outside a
      class burst.
- [x] Memory per colour (`docker stats`): about 1.1 GiB after warm-up, and under 2.5 GiB after class bursts (each
      waiting recording holds its decoded audio); the colour's limit is 9 GiB. Phase 1, measured the same way, used
      1.5 GiB after warm-up and up to 2.2 GiB after a burst. On the server: 1.08 GiB after warm-up, 1.64 GiB after
      two bursts of 40.
- [x] The image is far smaller than phase 1's 3.9 GB (no torch); a code-only rebuild reuses the dependency and model
      layers. 2.69 GB. A commit that changed only webApp.py, built on the server from `git archive` as deploy.sh
      builds: 36 s (28 s of warm-up); the models (211 MB), Python packages (1.12 GB) and system packages (457 MB)
      layers were the deployed image's own.

## Phase 1: foundation (2026-11)

Walked through on the public site on 2026-11-15 after deploying e4a1693 (the boxes below), except where noted.

### Learner flows (behaviour unchanged; the stack under them changed)
- [x] Open the page: sentence, IPA, audio button, record button; no console errors (CSP). Auto: smoke test (page + CSP header).
- [x] New sentence in each level (easy, medium, hard, random). Auto: smoke test (one level), `tests/test_api.py`.
- [x] Your own text: accepted, refused when too long, not English, or with hidden characters. Auto: `tests/test_api.py`.
- [x] Listen to the reference voice (Piper) for a bank sentence and for your own text. Auto: smoke test (TTS).
- [x] Record and score a sentence: score, letter colours, per-word IPA and playback. Auto: smoke test, warm-up at build
      and start, the slow tests in the image (CI). Checked once: the same 105 recordings scored identically with
      transformers 4.57/torch 2.8 and 5.22/2.15. On 2026-11-15 scored with Piper audio through Cloudflare (no
      microphone in the browser used for the check).
- [x] Silence, a recording over 30 s, an unreadable file: the right message. Auto: `tests/test_api.py`, `tests/test_audio_decode.py`.
- [ ] Phone browsers (Chrome Android, Safari iOS, Zalo in-app browser): record and score once each.

### Operations
- [x] Wait for CI on main to pass; deploy.sh refuses a commit whose CI run failed, was cancelled or is still
      going, and only warns when it cannot ask GitHub or the commit has no run (read its first lines).
- [x] First deploy with the new deploy.sh moves the single container behind Caddy; port 3000 is unavailable for a
      few seconds, once (deploy.sh prints how long: 3.6 s on 2026-11-15). Then `deploy/deploy.sh --status` shows
      the proxy and blue live.
- [x] A normal deploy drops no request in flight, uploads still arriving at the switch included. Auto: deploy
      harness (`deploy/test/`, CI when deploy/ changes).
      Checked on 2026-11-15 with the phase 2 deploy, the public site open in a browser: across five switches (the
      deploy, two rollbacks, `deploy.sh e4a1693` and the deploy of main again), 4,677 requests through port 3000
      (health, page, sample, and recordings uploaded over 3 s each, some still arriving at a switch) and 4,940
      through Cloudflare (health and version, from before the first switch to after the last) all answered 200.
- [x] After the second deploy behind the proxy (the first leaves no previous colour): `deploy/deploy.sh --rollback`
      and back again, then `deploy/deploy.sh <older sha>` (at the phase 2 deploy). Checked on 2026-11-15: each run
      took about 2 minutes, most of it the old colour's 65 s drain; `deploy.sh e4a1693` came wholly from the build
      cache.
- [x] A failed release (staging or through the proxy) leaves the live colour serving and the previous release in
      place for `--rollback`, unless Caddy did not take the switch back or deploy.sh cannot tell whether it did
      (it then leaves both colours running and says so; deploy/RUNBOOK.md). Auto: deploy harness, except those two
      cases, which no scenario reaches.
- [x] Interrupted or killed deploys (Ctrl-C, dropped SSH, SIGKILL) recover. Auto: deploy harness. A reboot during a
      deploy is handled like SIGKILL, but the harness does not test it. Caddy then starts from the files on disk,
      and `upstream.caddy` already names the new colour if the reboot came between deploy.sh writing it and its
      reload; docker starts every colour that was running, the old one during its drain too. After a reboot, run
      `deploy/deploy.sh --status` before anything else, and stop a colour that is not live (deploy/RUNBOOK.md).
- [x] `/healthz`, `/readyz`, `/version` through Cloudflare. Auto: smoke test (`/version` printed), canary.
- [x] Logs: `docker logs ai-pronunciation-trainer-<colour>` shows JSON lines with `rid`; one `scored` line per
      recording; no text or audio in any line. Auto: `tests/test_operations.py`, the slow test that a worker start
      logs only JSON.
- [x] The canary runs every 15 minutes in GitHub Actions and is green; a failure sends an e-mail. (A manual run passed
      on 2026-11-15; GitHub starts the schedule some time after the workflow reaches main.)
- [x] Cloudflare's 125 s limit: a long recording (30 s) still scores well under it. (The longest practice text, 59
      words and 16.5 s of speech, scored in 11.8 s.)
- [x] The container opens no connection to the internet (Hugging Face offline, Hugging Face and ONNX Runtime
      telemetry off). Auto, in part: `tests/test_build.py` checks the image's settings and that ONNX Runtime's
      telemetry is off before onnxruntime is first imported. Checked by hand in this phase with a DNS logger: no
      lookup while a container started and scored. The tests in the image run without network, which shows that
      the app works offline but would not notice an attempt to connect.
- [x] Image rebuild after a code-only change reuses the dependency and model layers (`docker history`; at the
      phase 2 deploy). See phase 2's last box.

### Development
- [x] `scripts/lock.sh --check` passes; `scripts/lock.sh --upgrade` moves to releases at least 7 days old.
- [x] CI is green on the PR: lint, locks, pip-audit, tests, image (smoke test, tests inside, Trivy), deploy harness.
- [x] `pip install -r requirements.txt` and `python -m pytest -q` on a developer machine.
