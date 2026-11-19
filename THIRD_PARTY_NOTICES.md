# Third-party notices

AI Pronunciation Trainer, English edition, is under the GNU AGPL v3 ([LICENSE](LICENSE)). It is based on
[AI Pronunciation Trainer](https://github.com/Thiagohgl/ai-pronunciation-trainer) by Thiago Lobato (AGPL-3.0).
This file lists what the Docker image and the web page contain that comes from elsewhere, with its licence.
Versions are those of `requirements.lock` and the image built from it (Debian 13 "trixie").

## Models and data

| Component | Where | Licence |
|---|---|---|
| Whisper base, converted for CTranslate2: [Systran/faster-whisper-base](https://huggingface.co/Systran/faster-whisper-base) at commit `ebe41f7` (the weights of [openai/whisper-base](https://huggingface.co/openai/whisper-base)) | `/models/faster-whisper-base` in the image | MIT (the conversion's model card; OpenAI released Whisper's code and weights under MIT) |
| Piper voice `en_US-ljspeech-medium`, [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) v1.0.0 | `/models/piper` in the image | Voice collection MIT; trained on the [LJ Speech dataset](https://keithito.com/LJ-Speech-Dataset/), public domain |
| [Silero VAD](https://github.com/snakers4/silero-vad) v6, bundled with `faster-whisper`: tells whether a recording holds speech before Whisper hears it | `faster_whisper/assets/silero_vad_v6.onnx` | MIT (Silero Team; the wheel ships no copy of the licence text) |
| Practice sentences, [Tatoeba](https://tatoeba.org) | `databases/data_en.csv` | CC BY 2.0 FR, credited in the notice under the page footer. Adapted in 2026-11: sentences screened for school use, a person's name at the start of a sentence replaced by He, She or They, other sentences naming a person removed |
| CMU Pronouncing Dictionary, bundled with `eng_to_ipa` | `eng_to_ipa/resources` | BSD-style licence of Carnegie Mellon University |
| eSpeak NG data and library, bundled with `piper-tts` | `piper/espeak-ng-data`, `piper/espeakbridge.so` | GPL-3.0-or-later |
| Hebrew diacritics model Nakdimon (Elazar Gershuni), bundled with `piper-tts`, not used by this edition | `piper/hebrew/nakdimon.onnx` | MIT (`piper/hebrew/LICENSE`) |
| Arabic diacritics model (a port of libtashkeel), bundled with `piper-tts`, not used | `piper/tashkeel/model.onnx` | Distributed with piper-tts under its licence |
| g2pW-derived code (Chinese), bundled with `piper-tts`, not used | `piper/g2pw_onnx.py` | Apache-2.0 (`piper_tts-1.8.0.dist-info/licenses/licenses/LICENSE.g2pW-Apache-2.0`) |

The German sentences (`databases/data_de.csv`, upstream) are in the repository but not in the image.

## Python packages (requirements.lock)

| Package | Version | Licence |
|---|---|---|
| faster-whisper | 1.2.1 | MIT; it ships the Silero VAD v6 model (see Models and data) |
| ctranslate2 | 4.8.5 | MIT. Its library (`ctranslate2.libs/libctranslate2*.so`) has built in the Intel oneAPI Math Kernel Library (Intel Simplified Software License: redistributable, not open source), oneDNN 3.1.1 (Apache-2.0) and NVIDIA's CUDA runtime (the CUDA Toolkit licence's redistributable part; unused, the server has no GPU); the wheel also ships GCC's OpenMP runtime (`libgomp`, GPL-3.0-or-later with the GCC Runtime Library Exception) |
| av (PyAV, imported by faster-whisper, not used to decode) | 19.0.2 | BSD-3-Clause; its wheel ships FFmpeg 9.0.2's libraries (`av.libs`), built with x264 and x265 and so under GPL-2.0-or-later, and the libraries they use (GnuTLS, Opus, dav1d, libvpx, SVT-AV1, libwebp, libxcb and others, under LGPL, BSD and MIT licences) |
| huggingface-hub | 2.4.0 | Apache-2.0 |
| tokenizers | 0.23.3 | Apache-2.0 |
| hf-xet | 1.8.0 | Apache-2.0 |
| piper-tts | 1.8.0 | GPL-3.0-or-later |
| onnxruntime | 1.31.1 | MIT |
| flatbuffers | 25.12.19 | Apache-2.0 |
| protobuf | 7.36.2 | BSD-3-Clause |
| pathvalidate | 3.3.1 | MIT |
| Flask | 3.1.3 | BSD-3-Clause |
| Werkzeug | 3.1.9 | BSD-3-Clause |
| Jinja2 | 3.1.6 | BSD-3-Clause |
| MarkupSafe | 3.0.4 | BSD-3-Clause |
| itsdangerous | 2.2.0 | BSD-3-Clause |
| click | 8.5.1 | BSD-3-Clause |
| blinker | 1.9.0 | MIT |
| gunicorn | 26.2.0 | MIT |
| numpy | 2.5.4 | BSD-3-Clause (bundled parts: 0BSD, MIT, Zlib, CC0-1.0) |
| pandas | 3.1.1 | BSD-3-Clause |
| python-dateutil | 4.0.0 | BSD-3-Clause (and Apache-2.0 for parts) |
| tzdata | 2026.6 | Apache-2.0 |
| eng-to-ipa | 0.0.2 | MIT ([mphilli/English-to-IPA](https://github.com/mphilli/English-to-IPA)) |
| setuptools | 84.2.1 | MIT |
| filelock | 4.2.9 | MIT |
| fsspec | 2026.9.0 | BSD-3-Clause |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| PyYAML | 6.0.3 | MIT |
| tqdm | 4.70.1 | MPL-2.0 AND MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| httpx2, httpcore2 | 2.16.0 | BSD-3-Clause |
| h11 | 0.16.0 | MIT |
| anyio | 4.16.0 | MIT |
| idna | 3.20 | BSD-3-Clause |
| truststore | 0.10.5 | MIT |

Most packages ship their licence text in their `.dist-info` directory in the image
(`/opt/venv/lib/python3.12/site-packages`). Four do not: eng-to-ipa (MIT, see its repository), flatbuffers
(Apache-2.0, <https://github.com/google/flatbuffers>), tokenizers (Apache-2.0, <https://github.com/huggingface/tokenizers>)
and onnxruntime (MIT), whose `LICENSE` and `ThirdPartyNotices.txt` are in `site-packages/onnxruntime/`.

## System packages and the page

| Component | Licence |
|---|---|
| Python 3.12 (base image `python:3.12.16-slim-trixie`) | PSF-2.0 |
| pip 25.0.1, in the base image (used only to build the image) | MIT |
| Debian 13 packages in the base image | Various free licences; see `/usr/share/doc/*/copyright` in the image |
| FFmpeg 7.1.5 (Debian package `ffmpeg`, built with `--enable-gpl`) and the libraries it pulls in | GPL-2.0-or-later as built; see `/usr/share/doc/ffmpeg/copyright` |
| Caddy 2.11.9 (the proxy container on the server, not in the app image) | Apache-2.0 |
| Fonts Inter 4.001 (latin, latin-ext and vietnamese subsets: the variable wght files of `@fontsource-variable/inter` 5.3.0) and Noto Sans (latin, latin-ext and greek, for the IPA's θ), subset as Google Fonts serves them, in `static/fonts` and served by the app | SIL Open Font License 1.1 (`static/fonts/OFL-Inter.txt`, `OFL-NotoSans.txt`) |
| Icons of the page's inline SVG sprite (`templates/main.html`): the warning, info, offline, clock, refresh, copy, chevron, check, microphone-off, open-in-new, lock, tune, more-vertical, lightbulb, help, star, flame (whatshot), person-add and delete icons are [Material Icons](https://github.com/google/material-design-icons) paths by Google | Apache-2.0 |

The GPL-licensed parts (piper-tts, eSpeak NG, FFmpeg, and the FFmpeg libraries inside PyAV) run in the same image as the AGPL-3.0 app. GPLv3 section 13
and AGPLv3 section 13 allow combining the two; each part keeps its own licence. The source of every Python package
is on PyPI, except onnxruntime's and ctranslate2's (<https://github.com/microsoft/onnxruntime>,
<https://github.com/OpenNMT/CTranslate2>; PyPI has only their wheels). Debian publishes the source of its packages.
