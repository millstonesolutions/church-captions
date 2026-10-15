"""A/B the Bible vocabulary: synthesize sermon sentences with macOS `say`, transcribe them with
no prompt / the old static list / the lexicon prompt + autocorrect, and count names spelled right.

  .venv/bin/python tools/ab_test.py [--voice Samantha] [--model mlx-community/whisper-small.en-mlx]
"""
import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hub"))
from stt import Transcriber  # noqa: E402
from vocab import Vocab      # noqa: E402

# (focus book or "", sentence, words that must come out spelled exactly like this)
CASES = [
    ("PHI", "I urge Euodia and Syntyche to agree in the Lord, and Epaphroditus risked his life for the work.",
     ["Euodia", "Syntyche", "Epaphroditus"]),
    ("", "The prophet Habakkuk waited on the watchtower, while Zephaniah and Haggai spoke to Judah.",
     ["Habakkuk", "Zephaniah", "Haggai"]),
    ("", "Melchizedek, king of Salem, brought out bread and wine to Abram.", ["Melchizedek", "Salem", "Abram"]),
    ("JOH", "Nicodemus came by night, and later Jesus healed a man at the pool of Siloam near Bethesda.",
     ["Nicodemus", "Siloam", "Bethesda"]),
    ("", "Nebuchadnezzar threw Shadrach, Meshach, and Abednego into the furnace.",
     ["Nebuchadnezzar", "Shadrach", "Meshach", "Abednego"]),
    ("REV", "Write to the churches in Thyatira, Sardis, Philadelphia and Laodicea, and beware the Nicolaitans.",
     ["Thyatira", "Sardis", "Laodicea", "Nicolaitans"]),
    ("", "Christ is the propitiation for our sins, and our sanctification is the work of the Spirit.",
     ["propitiation", "sanctification"]),
    ("", "Mephibosheth ate at the king's table, and Zerubbabel rebuilt the temple.",
     ["Mephibosheth", "Zerubbabel"]),
    ("", "Turn with me to Second Thessalonians chapter three, and then to Ecclesiastes.",
     ["Thessalonians", "Ecclesiastes"]),
]
OLD_LIST = ("First Baptist Church Lake Dallas, Denton, Corinthians, Thessalonians, Philippians, Ephesians, "
            "Deuteronomy, Ecclesiastes, Habakkuk, Zephaniah, Nehemiah, Melchizedek, sanctification, justification")


def synth(text: str, voice: str, tmp: Path) -> np.ndarray:
    aiff, raw = tmp / "s.aiff", tmp / "s.f32"
    subprocess.run(["say", "-v", voice, "-r", "165", "-o", str(aiff), text], check=True)
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(aiff), "-ac", "1", "-ar", "16000",
                    "-f", "f32le", str(raw)], check=True)
    return np.fromfile(raw, dtype=np.float32)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voice", default="Samantha")
    ap.add_argument("--model", default="mlx-community/whisper-small.en-mlx")
    a = ap.parse_args()
    stt_cfg = {"backend": "mlx", "model": a.model, "min_logprob": -9, "max_no_speech": 1, "max_compression": 9}

    class Fixed:  # stands in for Vocab with a constant prompt and no correction
        def __init__(self, p): self.p = p
        def prompt(self): return self.p
        def correct(self, t): return t

    vcfg = {"custom": ["First Baptist Church Lake Dallas", "Denton"], "prompt_tokens": 200}
    vocab = Vocab(vcfg, ROOT / "data" / "lexicon.json")
    modes = {"none": Fixed(""), "old list": Fixed(OLD_LIST), "lexicon": vocab}
    score = {m: 0 for m in modes}
    total = sum(len(c[2]) for c in CASES)

    with tempfile.TemporaryDirectory() as td:
        for focus, text, want in CASES:
            audio = synth(text, a.voice, Path(td))
            print(f"\n[{focus or '-'}] {text}")
            for name, v in modes.items():
                if v is vocab:
                    vcfg["focus_book"] = focus
                t = Transcriber(stt_cfg, {}, lambda *_: None, v)
                t._load_model()
                out = t._transcribe(audio)
                hits = [w for w in want if re.search(rf"\b{w}\b", out)]
                score[name] += len(hits)
                print(f"  {name:9s} {len(hits)}/{len(want)}  {out}")
    print("\nNames spelled right:", ", ".join(f"{m} {s}/{total}" for m, s in score.items()))


if __name__ == "__main__":
    main()
