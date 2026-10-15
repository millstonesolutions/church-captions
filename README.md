# Millstone Solutions Church Captions

Live captions for church services, generated on one Mac in the building. Speech from the sound desk is
transcribed by a local Whisper model and sent to an **OBS overlay**, **phones and tablets** in the room, and
optionally **ProPresenter**. No cloud, no subscription, nothing leaves the LAN.

It knows the Bible: a vocabulary of ~3,300 names, places and uncommon words from the World English Bible keeps
"Epaphroditus", "Nebuchadnezzar" and "propitiation" spelled right, and leans toward the book being preached.

> **Status: early testing.** Tested end to end on Apple Silicon with a built-in microphone and synthesized
> sermon audio. Not yet run through a full live service. Please report what works and what doesn't.

---

## Contents
- [How it fits together](#how-it-fits-together)
- [Requirements](#requirements)
- [Install](#install)
- [Run](#run)
- [Settings page](#settings-page)
- [Audio](#audio)
- [OBS overlay](#obs-overlay)
- [Phones and tablets](#phones-and-tablets)
- [Bitfocus Companion](#bitfocus-companion)
- [ProPresenter 7 (optional)](#propresenter-7-optional)
- [Start on login](#start-on-login)
- [Bible vocabulary](#bible-vocabulary)
- [Tuning accuracy](#tuning-accuracy)
- [Known limits](#known-limits)
- [License](#license)
- [Credits and legal](#credits-and-legal)

## How it fits together

```
Mixer ──USB──▶ Mac (hub/server.py: VAD → local Whisper → WebSocket)
                 ├── /overlay  → OBS Browser Source (transparent lower-third)
                 ├── /reader   → phones and tablets for hard-of-hearing attendees
                 ├── /settings → every setting, applied live (no file editing)
                 ├── /api/*    → Bitfocus Companion start/stop/clear/focus
                 └── (optional) ProPresenter 7 Message via REST API
```

## Requirements

- A Mac with **Apple Silicon** (M1 or later). An 8 GB M1 is enough; Intel Macs work with the slower
  `faster-whisper` CPU backend.
- Python 3.10–3.12 (3.12 recommended; some dependencies lag the newest Python).
- A clean speech feed: a USB audio interface or a mixer's USB card (e.g. X32 X-USB) carrying a speech-only bus.

Memory with each model:
- `whisper-small.en` (default): ~500 MB. Comfortable alongside OBS on an 8 GB Mac.
- `whisper-medium.en`: ~1.5 GB, noticeably better on names, fine if OBS isn't on the same Mac.
- `whisper-large-v3-turbo`: ~1.6 GB and fast, but don't run it on the same 8 GB Mac as OBS.

Start with small; move up only if accuracy bothers you. Latency with small on an M1 is roughly 1–2 s.

## Install

```bash
git clone https://github.com/millstonesolutions/church-captions.git
cd church-captions
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

With [uv](https://docs.astral.sh/uv/): `uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt`.

The first run downloads the Whisper model from Hugging Face (internet needed once; cached after that) and
creates `config.yaml` from `config.example.yaml`. `config.yaml` holds your settings and your settings
password, so it is ignored by git.

## Run

```bash
.venv/bin/python hub/server.py
```

Open `http://<mac-ip>:8787` for Start/Stop/Clear and a live preview. With **Start transcribing when the Mac
boots** on (the default) it begins listening at launch, so a volunteer only needs the Mac powered on.

macOS asks for microphone permission the first time; allow it for Terminal (or whatever launches the hub).

## Settings page

`http://<mac-ip>:8787/settings` has every adjustment: input device, channel and gain with a level meter,
recognition timing, junk filters, the Bible vocabulary, the OBS overlay's look, ProPresenter and the hub
itself. Changes save to `config.yaml` and apply immediately; device, channel and model changes restart the
audio for a moment. Only the web port needs a hub restart.

Set **Settings password** to require a login (user `admin`). Start/Stop/Clear and the Companion API stay open.

## Audio

Route a **speech-only mix bus** (pulpit and lav mics, post-fade, no band) to one USB output channel on the
mixer. On the settings page pick that device and channel. Speech should peak around -20 to -10 dB on the
meter; use the software gain if it doesn't.

No USB card near the desk? Any USB interface fed from a spare output works. Clean speech matters far more
than the model.

## OBS overlay

1. **Sources → + → Browser**.
2. URL: `http://localhost:8787/overlay` if OBS is on the same Mac, otherwise `http://<mac-ip>:8787/overlay`.
3. Width **1920**, height **1080**.
4. Turn **off** "Shutdown source when not visible" and "Control audio via OBS".
5. Put it at the top of the source list in your program scene (or in a nested scene used by every scene).

The overlay is transparent and empty until someone speaks, and clears after a few seconds of silence. Text size,
position, line count, box opacity and fade time are set live on the settings page; URL parameters
(`?lines=2&size=44&bottom=90`) pin a value for one source instead.

## Phones and tablets

On the same network as the Mac, open `http://<mac-ip>:8787/reader`. Large scrolling text, A−/A+ size buttons,
light/dark, and a "↓ Live" button after scrolling back. Late joiners get the last 200 lines.

- **Add to Home Screen** (Share menu) makes it feel like an app.
- For tablets handed to attendees, turn on **Guided Access** (Settings → Accessibility) so they stay on the page.
- Give the Mac a **DHCP reservation** so the address never changes, and print a QR code of the URL.
- **Guest Wi-Fi usually can't reach it** — most guest networks isolate clients. To let members use their own
  phones, allow port 8787 from the guest network to the Mac, and set a settings password first.

## Bitfocus Companion

Generic HTTP module: `GET http://<mac-ip>:8787/api/start`, `/api/stop`, `/api/clear`. Status is
`GET /api/status` (JSON, includes the input level). Set the sermon's book before the message with
`GET /api/focus?book=Romans` (a name or a code like `ROM`; empty clears).

## ProPresenter 7 (optional)

1. ProPresenter → Settings → Network: enable, note the port, set a password if the Mac is reachable by others.
2. Create a **Message** named `Captions` with one text token named `text`, styled as a lower-third.
3. On the settings page turn on **Send captions to a ProPresenter Message** and set the host and port.
   The hub sends the last lines on every finished sentence, throttled.

The trigger and clear endpoints follow https://openapi.propresenter.com/ — confirm them against your Pro7
build; `hub/propresenter.py` is a short file if anything needs adjusting.

## Start on login

```bash
sed "s|__DIR__|$(pwd)|g" launchd/com.millstonesolutions.churchcaptions.plist > ~/Library/LaunchAgents/com.millstonesolutions.churchcaptions.plist
launchctl load ~/Library/LaunchAgents/com.millstonesolutions.churchcaptions.plist
```

Logs go to `captions.log` in the project folder.

## Bible vocabulary

`data/lexicon.json` holds ~3,300 names, places and uncommon words from the World English Bible (public domain),
ranked overall and per book; the 66 books of the Protestant canon are used.

Whisper only reads ~223 prompt tokens and a Bible name costs ~5, so about 40 names fit per line. The hub
spends them where they matter:
1. **Always-boost words** (church name, staff, local places) go first.
2. **The book being preached** — set it on the settings page or from Companion, or the hub picks it up when the
   preacher cites one ("turn to Romans 8", "the book of Ruth"). A passing "the Philippians" doesn't count.
3. **The hardest common Bible words** fill the rest (Pharisees, Nebuchadnezzar, Gentiles, cherubim…).

Every line is then checked against the *whole* lexicon, so a name that wasn't in the prompt but came back as
"Habakuk" is still shown as "Habakkuk". Ordinary English words and unknown names (members, staff) are left
alone. Anything else goes in **Exact replacements** on the settings page.

To rebuild the list (only needed if you change `tools/build_lexicon.py`):

```bash
mkdir -p data/web-src && cd data/web-src
curl -LO https://ebible.org/Scriptures/engwebu_vpl.zip && unzip engwebu_vpl.zip && cd ../..
.venv/bin/python tools/build_lexicon.py
```

`tools/ab_test.py` measures the effect with synthesized sermon sentences. On whisper-small: no prompt 21/26
names right, a short static word list 22/26, lexicon + autocorrect 25/26. A synthetic voice is far cleaner
than a real sanctuary, so treat those as relative, not absolute.

## Tuning accuracy

All on the settings page:
- **Pause that ends a line** — lower (400) for snappier lines, higher (800) if the preacher pauses mid-sentence.
- **Speech detector strictness** — Strict if room noise or music triggers junk lines.
- **Junk filters** — Whisper invents "Thank you." on noise and loops phrases ("the Holy Spirit, the Holy
  Spirit…"). Lines below the confidence floor, likely non-speech or highly repetitive are dropped;
  `/api/status` counts them.

## Known limits

- Whisper runs per utterance, so the in-progress line refreshes about once a second and the finished line lands
  ~0.6 s after the speaker pauses.
- English only.
- When the preacher names a book and its people in the same sentence, that sentence doesn't benefit from the
  book focus yet — the focus switches once the line finishes. Setting the book from Companion beforehand avoids it.
- The spelling fixer works word by word, so a name the model splits in two ("Mephibosha fade") isn't caught —
  add it to Exact replacements if it keeps happening.
- Control endpoints have no auth (Companion needs them simple). Keep the hub on a staff network.

## License
Free for **Christian churches and ministries** (including missions, parachurch ministries, Christian schools and
camps) under the [Church and Ministry Use License](LICENSE). In short:

- **Qualifying churches and ministries** may download it from this repository and use it for free for anything
  they do: services, events, recordings and livestreams. They use it as published, without modifying it
  (changing settings is fine).
- **AV installers and integrators** may set it up and support it for a qualifying church, and charge for their own
  time, but not for the software.
- **Anyone** may read the code, and download, modify and test it to evaluate it or to contribute changes back
  through GitHub pull requests.
- **Everything else** (other organizations, selling it, redistributing it, running modified versions in production)
  needs written permission from Millstone Solutions. Open an issue to ask.
- **Contributions** submitted to the project may be used and relicensed by Millstone Solutions.

This is a source-available license, not an open-source one. The Lato fonts keep their SIL Open Font License;
Python packages and Whisper models are not included and keep their own licenses. The [LICENSE](LICENSE) file is
the binding text; this summary is for convenience.

## Credits and legal
© 2026 Millstone Solutions LLC.

Bible vocabulary derived from the World English Bible (public domain), published by eBible.org. "World English
Bible" is a trademark of eBible.org; this project is not affiliated with or endorsed by eBible.org. Lato is
© Łukasz Dziedzic (SIL OFL 1.1). Whisper is © OpenAI (MIT). OBS Studio, ProPresenter, Bitfocus Companion and X32
are trademarks of their owners. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
