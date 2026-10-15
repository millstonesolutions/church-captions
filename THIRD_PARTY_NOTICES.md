# Third-party notices

## Lato fonts
`hub/static/fonts/Lato-*.ttf` (version 2.015) are included and used by the overlay and settings pages.
SIL Open Font License 1.1 — see `hub/static/fonts/OFL.txt`.
Copyright (c) 2010-2015 Łukasz Dziedzic, with Reserved Font Name "Lato". Lato is a trademark of tyPoland
Lukasz Dziedzic.

## World English Bible
`data/lexicon.json` is a list of names, places and uncommon words extracted from the World English Bible
(https://ebible.org/engwebu/), which is in the public domain. The Bible text itself is **not** included;
`tools/build_lexicon.py` reads a copy each user downloads from eBible.org (see README).
"World English Bible" is a trademark of eBible.org. This project is not affiliated with, sponsored by or
endorsed by eBible.org.

## Python packages (not included)
Installed by each user from PyPI with `pip install -r requirements.txt`, under their own licenses:
FastAPI (MIT), Uvicorn (BSD-3-Clause), PyYAML (MIT), ruamel.yaml (MIT), HTTPX (BSD-3-Clause),
NumPy (BSD-3-Clause), python-sounddevice (MIT), webrtcvad-wheels (MIT), mlx-whisper (MIT),
faster-whisper (MIT), wordfreq (Apache-2.0; its word-frequency data is CC BY-SA 4.0 and is used only at
build/run time to decide which words are uncommon — none of it is copied into this repository).

## Speech-recognition models (not included)
Whisper models are © OpenAI under the MIT license. The MLX conversions are downloaded from the
`mlx-community` organization on Hugging Face on first run.

## Trademarks
OBS Studio is a trademark of the OBS Project. ProPresenter is a trademark of Renewed Vision. Bitfocus
Companion is a trademark of Bitfocus AS. X32 and X-USB are trademarks of MUSIC Tribe. This project is not
affiliated with, sponsored by or endorsed by any of them.
