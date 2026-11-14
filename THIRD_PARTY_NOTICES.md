# Third-party notices

AI Pronunciation Trainer, English edition, is under the GNU AGPL v3 ([LICENSE](LICENSE)). It is based on
[AI Pronunciation Trainer](https://github.com/Thiagohgl/ai-pronunciation-trainer) by Thiago Lobato (AGPL-3.0).
This file lists what the Docker image and the web page contain that comes from elsewhere, with its licence.
Versions are those of `requirements.lock` and the image built from it (Debian 13 "trixie").

## Models and data

| Component | Where | Licence |
|---|---|---|
| Whisper base, [openai/whisper-base](https://huggingface.co/openai/whisper-base) at commit `e37978b` | `/models/whisper-base` in the image | Apache-2.0 (model card); the Whisper code is MIT |
| Piper voice `en_US-ljspeech-medium`, [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices) v1.0.0 | `/models/piper` in the image | Voice collection MIT; trained on the [LJ Speech dataset](https://keithito.com/LJ-Speech-Dataset/), public domain |
| Practice sentences, [Tatoeba](https://tatoeba.org) | `databases/data_en.csv` | CC BY 2.0 FR, credited in the page footer |
| CMU Pronouncing Dictionary, bundled with `eng_to_ipa` | `eng_to_ipa/resources` | BSD-style licence of Carnegie Mellon University |
| eSpeak NG data and library, bundled with `piper-tts` | `piper/espeak-ng-data`, `piper/espeakbridge.so` | GPL-3.0-or-later |
| Hebrew diacritics model Nakdimon (Elazar Gershuni), bundled with `piper-tts`, not used by this edition | `piper/hebrew/nakdimon.onnx` | MIT (`piper/hebrew/LICENSE`) |
| Arabic diacritics model (a port of libtashkeel), bundled with `piper-tts`, not used | `piper/tashkeel/model.onnx` | Distributed with piper-tts under its licence |
| g2pW-derived code (Chinese), bundled with `piper-tts`, not used | `piper/g2pw_onnx.py` | Apache-2.0 (`piper_tts-1.8.0.dist-info/licenses/licenses/LICENSE.g2pW-Apache-2.0`) |
| Feedback sounds `static/ASR_good.wav`, `ASR_okay.wav`, `ASR_bad.wav` | the page | From the upstream repository, which states no separate source or licence; they are distributed with it under its AGPL-3.0 |

The German sentences (`databases/data_de.csv`, upstream) are in the repository but not in the image.

## Python packages (requirements.lock)

| Package | Version | Licence |
|---|---|---|
| torch (CPU build) | 2.15.0 | BSD-3-Clause, with bundled components under Apache-2.0, BSD and other permissive licences |
| transformers | 5.22.2 | Apache-2.0 |
| huggingface-hub | 2.4.0 | Apache-2.0 |
| tokenizers | 0.23.3 | Apache-2.0 |
| safetensors | 0.8.0 | Apache-2.0 |
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
| dtwalign | 0.1.1 | MIT |
| scipy | 1.18.1 | BSD-3-Clause |
| numba | 0.68.1 | BSD-2-Clause |
| llvmlite | 0.50.0 | BSD-2-Clause, and Apache-2.0 WITH LLVM-exception for LLVM |
| matplotlib | 3.11.2 | Matplotlib licence (PSF-based) |
| seaborn | 0.13.2 | BSD-3-Clause |
| contourpy | 1.4.0 | BSD-3-Clause |
| cycler | 0.12.1 | BSD-3-Clause |
| fonttools | 4.68.0 | MIT |
| kiwisolver | 1.5.1 | BSD-3-Clause |
| pillow | 13.0.0 | MIT-CMU |
| pyparsing | 3.3.3 | MIT |
| networkx | 3.7 | BSD-3-Clause |
| sympy | 1.14.0 | BSD-3-Clause |
| mpmath | 1.3.0 | BSD-3-Clause |
| setuptools | 84.2.1 | MIT |
| filelock | 4.2.9 | MIT |
| fsspec | 2026.9.0 | BSD-3-Clause |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| PyYAML | 6.0.3 | MIT |
| regex | 2026.11.7 | Apache-2.0 AND CNRI-Python |
| tqdm | 4.70.1 | MPL-2.0 AND MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| httpx2, httpcore2 | 2.16.0 | BSD-3-Clause |
| h11 | 0.16.0 | MIT |
| anyio | 4.16.0 | MIT |
| idna | 3.20 | BSD-3-Clause |
| truststore | 0.10.5 | MIT |
| typer | 0.28.0 | MIT |
| rich | 15.0.0 | MIT |
| markdown-it-py | 4.2.0 | MIT |
| mdurl | 0.1.2 | MIT |
| Pygments | 2.21.0 | BSD-2-Clause |
| shellingham | 1.5.4 | ISC |
| annotated-doc | 0.0.5 | MIT |

Most packages ship their licence text in their `.dist-info` directory in the image
(`/opt/venv/lib/python3.12/site-packages`). Three do not: eng-to-ipa (MIT, see its repository), flatbuffers
(Apache-2.0, <https://github.com/google/flatbuffers>) and tokenizers (Apache-2.0, <https://github.com/huggingface/tokenizers>).

## System packages and the page

| Component | Licence |
|---|---|
| Python 3.12 (base image `python:3.12.16-slim-trixie`) | PSF-2.0 |
| pip 25.0.1, in the base image (used only to build the image) | MIT |
| Debian 13 packages in the base image | Various free licences; see `/usr/share/doc/*/copyright` in the image |
| FFmpeg 7.1.5 (Debian package `ffmpeg`, built with `--enable-gpl`) and the libraries it pulls in | GPL-2.0-or-later as built; see `/usr/share/doc/ffmpeg/copyright` |
| Caddy 2.11.9 (the proxy container on the server, not in the app image) | Apache-2.0 |
| Fonts Inter and Noto Sans, loaded by the page from Google Fonts | SIL Open Font License 1.1 |

The GPL-licensed parts (piper-tts, eSpeak NG, FFmpeg) run in the same image as the AGPL-3.0 app. GPLv3 section 13
and AGPLv3 section 13 allow combining the two; each part keeps its own licence. The source of every Python package
is on PyPI (torch's at <https://github.com/pytorch/pytorch>; its CPU wheels come from download.pytorch.org), and
Debian publishes the source of its packages.
