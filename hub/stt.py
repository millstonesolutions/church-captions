"""Local speech-to-text worker.

Captures audio from a CoreAudio input (the X32's X-USB card shows up here), splits it into
utterances with a VAD, and runs a local model on each utterance. Emits:
  partial  - the utterance so far, re-transcribed roughly once a second while the speaker talks
  final    - the finished utterance once the VAD sees a pause

Every setting is read from the live config dict on each frame, so changes made in the web GUI
take effect immediately. Only device, channel and model changes need a restart (server.py does
that for you).

Backends (pick in config.yaml):
  mlx      - mlx-whisper, runs on the GPU of any Apple Silicon Mac. Default.
  whisper  - faster-whisper (CTranslate2). CPU only on a Mac; use on Intel machines.
"""
import math
import queue
import threading
import time

import numpy as np
import sounddevice as sd
import webrtcvad

# What Whisper says when it hears room noise, applause or a hum rather than speech.
STOCK_HALLUCINATIONS = {"thank you", "thank you.", "thanks for watching", "thanks for watching!", "you",
                        "bye", "bye.", "so", "okay", "amen", "please subscribe", "subtitles by the amara.org community"}

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000


class Transcriber:
    def __init__(self, stt_cfg: dict, audio_cfg: dict, on_segment, vocab=None):
        self.cfg = stt_cfg
        self.audio_cfg = audio_cfg
        self.on_segment = on_segment
        self.vocab = vocab
        self.full_transcript: list[dict] = []
        self.level_db = -120.0          # input level after gain, for the GUI meter
        self.speaking = False
        self.last_error = ""
        self.dropped = 0                # segments rejected as likely hallucinations
        self._q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream = None
        self._model = None
        self._model_key = None
        self._vad = None
        self._vad_level = None

    # ---------- devices ----------
    def list_devices(self):
        out = []
        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                out.append({"index": i, "name": d["name"], "channels": d["max_input_channels"]})
        return out

    def _device_index(self):
        want = self.audio_cfg.get("device")
        if want is None or want == "":
            return None
        if isinstance(want, int):
            return want
        for d in self.list_devices():
            if want.lower() in d["name"].lower():
                return d["index"]
        raise RuntimeError(f"No input device matching '{want}'. Known: {[d['name'] for d in self.list_devices()]}")

    def device_name(self):
        try:
            idx = self._device_index()
            return sd.query_devices(idx if idx is not None else sd.default.device[0])["name"]
        except Exception as e:
            return f"(error: {e})"

    # ---------- model ----------
    def _load_model(self):
        backend = self.cfg.get("backend", "mlx")
        model = self.cfg.get("model", "mlx-community/whisper-small.en-mlx")
        if backend == "mlx":
            import mlx_whisper  # noqa
            self._model = ("mlx", model)
        elif backend == "whisper":
            from faster_whisper import WhisperModel
            self._model = ("whisper", WhisperModel(model, device="cpu", compute_type="int8"))
        else:
            raise ValueError(f"unknown backend {backend}")
        self._model_key = (backend, model)

    def _keep(self, seg: dict) -> bool:
        """Drop segments that look like hallucinations rather than speech."""
        c = self.cfg
        text = seg["text"].strip()
        if not text:
            return False
        if seg["no_speech_prob"] > float(c.get("max_no_speech", 0.6)) and seg["avg_logprob"] < -0.5:
            return False
        if seg["avg_logprob"] < float(c.get("min_logprob", -1.0)):
            return False
        if seg["compression_ratio"] > float(c.get("max_compression", 2.4)):   # "the Holy Spirit, the Holy Spirit..."
            return False
        if text.lower() in STOCK_HALLUCINATIONS and (seg["no_speech_prob"] > 0.15 or seg["avg_logprob"] < -0.4):
            return False
        return True

    def _transcribe(self, audio: np.ndarray) -> str:
        kind, m = self._model
        prompt = (self.vocab.prompt() if self.vocab else "") or None
        if kind == "mlx":
            import mlx_whisper
            r = mlx_whisper.transcribe(audio, path_or_hf_repo=m, language="en",
                                       initial_prompt=prompt, fp16=True,
                                       condition_on_previous_text=False)
            segs = r.get("segments", [])
        else:
            out, _ = m.transcribe(audio, language="en", beam_size=1, vad_filter=False,
                                  initial_prompt=prompt, condition_on_previous_text=False)
            segs = [{"text": x.text, "no_speech_prob": x.no_speech_prob, "avg_logprob": x.avg_logprob,
                     "compression_ratio": x.compression_ratio} for x in out]
        kept = [x for x in segs if self._keep(x)]
        self.dropped += len(segs) - len(kept)
        text = " ".join(x["text"].strip() for x in kept).strip()
        if self.vocab and text:
            text = self.vocab.correct(text)
        return text

    # ---------- lifecycle ----------
    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    def start(self):
        if self.running:
            return
        self.last_error = ""
        if self._model is None or self._model_key != (self.cfg.get("backend", "mlx"), self.cfg.get("model")):
            self._load_model()
        self._stop.clear()
        idx = self._device_index()
        ch = int(self.audio_cfg.get("channel", 0))

        def cb(indata, frames, t, status):
            mono = indata[:, ch] if indata.ndim > 1 else indata[:, 0]
            self._q.put(mono.copy())

        self._stream = sd.InputStream(device=idx, samplerate=SAMPLE_RATE, blocksize=FRAME_SAMPLES,
                                      channels=ch + 1, dtype="float32", callback=cb)
        self._stream.start()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._stream:
            self._stream.stop(); self._stream.close(); self._stream = None
        if self._thread:
            self._thread.join(timeout=5)
        self.level_db = -120.0
        self.speaking = False
        while not self._q.empty():
            self._q.get_nowait()

    # ---------- main loop ----------
    def _loop(self):
        try:
            self._run()
        except Exception as e:                      # surface in the GUI instead of dying silently
            self.last_error = f"{type(e).__name__}: {e}"
            print(f"[stt] {self.last_error}")

    def _run(self):
        utter: list[np.ndarray] = []
        silence_frames = 0
        voiced_frames = 0
        last_partial = 0.0

        while not self._stop.is_set():
            try:
                frame = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            c = self.cfg  # re-read every frame so GUI changes apply live
            gain = 10 ** (float(self.audio_cfg.get("gain_db", 0)) / 20)
            if gain != 1.0:
                frame = frame * gain
            rms = float(np.sqrt(np.mean(frame ** 2))) + 1e-9
            self.level_db = max(self.level_db - 1.5, 20 * math.log10(rms))   # meter with decay

            level = int(c.get("vad_aggressiveness", 2))
            if self._vad is None or self._vad_level != level:
                self._vad, self._vad_level = webrtcvad.Vad(level), level
            pcm16 = (np.clip(frame, -1, 1) * 32767).astype(np.int16).tobytes()
            try:
                is_speech = self._vad.is_speech(pcm16, SAMPLE_RATE)
            except Exception:
                is_speech = True
            self.speaking = is_speech

            if is_speech:
                utter.append(frame); voiced_frames += 1; silence_frames = 0
            elif utter:
                utter.append(frame); silence_frames += 1

            if not utter:
                continue
            dur = len(utter) * FRAME_MS / 1000
            min_silence = int(c.get("end_silence_ms", 600)) // FRAME_MS
            ended = silence_frames >= min_silence or dur >= float(c.get("max_utterance_s", 12))

            if ended:
                if voiced_frames * FRAME_MS >= int(c.get("min_speech_ms", 300)):
                    text = self._transcribe(np.concatenate(utter))
                    if text:
                        self.full_transcript.append({"text": text, "t": time.time()})
                        if self.vocab:
                            self.vocab.observe(text)
                        self.on_segment(text, True)
                utter, silence_frames, voiced_frames = [], 0, 0
            elif time.time() - last_partial >= float(c.get("partial_interval_s", 1.0)) and dur >= 1.0:
                last_partial = time.time()
                text = self._transcribe(np.concatenate(utter))
                if text:
                    self.on_segment(text, False)
