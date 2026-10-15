# CLAUDE.md — Church Captions

Local live captions for church services (Python, FastAPI, mlx-whisper, Apple Silicon). Owner: Heath
(church AV/IT). Church-use license (Millstone Solutions LLC). Target: an 8 GB M1 Mac at the church,
fed from an X32 over X-USB; developed on a MacBook Pro.

## Layout
- `hub/server.py` — FastAPI app: pages, WebSocket fan-out, control API, and the settings `SCHEMA`.
  The settings page is generated from `SCHEMA`; POST `/api/config` only accepts keys listed there,
  coerced and clamped. `ui` picks the control (`channel` dropdown, `segmented`, `number`); numeric
  fields default to slider + box.
- `hub/stt.py` — audio capture → webrtcvad → whisper per utterance. Reads `self.cfg` every frame so
  GUI changes are live; device/channel/model changes restart it (`restart: "stt"` in the schema).
  `_keep()` drops hallucinated segments (confidence, no-speech, compression ratio, stock phrases).
- `hub/vocab.py` — builds Whisper's prompt from the lexicon and fixes near-miss spellings.
- `tools/build_lexicon.py` — WEB verse-per-line text → `data/lexicon.json`. `tools/ab_test.py` A/Bs it.
- `config.example.yaml` is committed; `config.yaml` is created from it on first run and is gitignored
  (it holds the settings password).

## Things that bit us
- **Whisper reads only the last ~223 prompt tokens** (`decoding.py`: `prompt_tokens[-(n_ctx//2 - 1):]`),
  and a Bible name costs ~5 tokens. A long vocabulary list is silently truncated, which is why the
  prompt is packed to `vocab.prompt_tokens` and the full lexicon is used for correction instead.
- Book focus only changes on a *cited* book ("Romans 8", "book of Ruth"), never a bare mention, or every
  "Paul wrote to the Philippians" would swap the prompt.
- Whisper invents "Thank you." and loops ("the Holy Spirit, the Holy Spirit…") on room noise. Keep the
  `_keep()` filters; the stock-phrase drop only applies when the segment is borderline, so a real
  "thank you" from the pulpit survives.
- `ruamel.yaml` round-trips `config.yaml` so the GUI keeps its comments, but it re-indents lists —
  don't string-match YAML list layout.
- The hub was started as `.venv/bin/python hub/server.py` (relative), so `pkill -f church-captions/...`
  misses it. Stop it by port: `kill $(lsof -ti tcp:8787 -sTCP:LISTEN)`.
- Strictness labels: webrtcvad's default is 2, labelled "Normal". Don't relabel so the default reads as
  anything else — volunteers will "fix" it.
- Brand (FBC kit) on the pages: black, white, cyan `#02CAF2`, blue `#097DDB`, grays; Lato. **No red.**

## Dev loop
```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
nohup .venv/bin/python hub/server.py < /dev/null > captions.log 2>&1 &
.venv/bin/python tools/ab_test.py            # vocabulary A/B with `say` audio, no mic needed
say "Turn with me to Philippians chapter four"  # live test through the mic
curl -s localhost:8787/api/transcript
```
