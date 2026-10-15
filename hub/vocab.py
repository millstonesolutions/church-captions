"""Biblical vocabulary: picks Whisper's prompt words and fixes near-miss spellings.

Whisper only reads the last ~223 tokens of a prompt, and a name like "Epaphroditus" costs ~5,
so the prompt holds roughly 40 names - nowhere near the 3,000+ in data/lexicon.json. So:
  1. Prompt = custom vocabulary + words from the book being preached + the global top list,
     packed to a token budget. The book comes from the GUI/Companion, or is detected when the
     preacher says "Philippians chapter 4" / "the book of Habakkuk".
  2. Every line is then checked against the full lexicon, so a name outside the prompt that
     comes back as "Habakuk" or "Melchisedek" is still spelled right on screen.
"""
import difflib
import json
import re
import threading
import time
from pathlib import Path

from wordfreq import zipf_frequency

NUM_WORDS = ("one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
             "fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|"
             "seventy|eighty|ninety|hundred")


class Vocab:
    def __init__(self, cfg: dict, lexicon_path: Path):
        self.cfg = cfg                       # the live `vocab` section of config.yaml
        self._lock = threading.Lock()
        self.lex = json.loads(lexicon_path.read_text()) if lexicon_path.exists() else \
            {"books": [], "global": [], "per_book": {}, "all": []}
        self.books = {b["code"]: b for b in self.lex["books"]}
        self.auto_focus: list[tuple[str, float]] = []   # (code, when) newest first
        self._build_matchers()
        self._tok = None
        self._prompt_cache = (None, "")
        self.last_corrections: list[str] = []

    # ---------- setup ----------
    def _build_matchers(self):
        alias = {}
        for b in self.lex["books"]:
            for a in b["aliases"]:
                alias[a] = b["code"]
        names = "|".join(sorted((re.escape(a) for a in alias), key=len, reverse=True))
        cue_after = rf"(?:\s+chapter|\s+\d|\s+(?:{NUM_WORDS})\b)"
        # Only a *cited* book changes focus ("Romans 8", "book of Ruth"), not a passing mention -
        # otherwise every "Paul wrote to the Philippians" would yank the prompt around.
        self._book_re = re.compile(rf"\b(?:book of\s+(?P<a>{names})\b|(?P<b>{names}){cue_after})",
                                   re.IGNORECASE)
        self._alias = alias
        self._lexset = {w.lower(): w for w in self.lex["all"]}
        self._by_initial: dict[str, list[str]] = {}
        for k in self._lexset:
            self._by_initial.setdefault(k[0], []).append(k)

    def _tokens(self, text: str) -> int:
        if self._tok is None:
            try:
                from mlx_whisper.tokenizer import get_tokenizer
                self._tok = get_tokenizer(multilingual=False).encode
            except Exception:
                self._tok = lambda s: s.split() * 2   # rough fallback: ~2 tokens per word
        return len(self._tok(text))

    # ---------- focus ----------
    def observe(self, text: str):
        """Called with each finished line: notice cited books."""
        if not self.cfg.get("auto_detect_book", True):
            return
        found = []
        for m in self._book_re.finditer(text):
            code = self._alias.get((m.group("a") or m.group("b")).lower())
            if code and code not in found:
                found.append(code)
        if found:
            with self._lock:
                now = time.time()
                keep = [(c, t) for c, t in self.auto_focus if c not in found]
                self.auto_focus = ([(c, now) for c in reversed(found)] + keep)[:3]

    def focus_codes(self) -> list[str]:
        """Manual focus first, then recent detections that haven't expired."""
        ttl = float(self.cfg.get("focus_minutes", 45)) * 60
        now = time.time()
        codes = []
        manual = self.cfg.get("focus_book") or ""
        if manual in self.books:
            codes.append(manual)
        with self._lock:
            for c, t in self.auto_focus:
                if now - t < ttl and c not in codes:
                    codes.append(c)
        return codes[:2]

    def clear_auto_focus(self):
        with self._lock:
            self.auto_focus = []

    # ---------- prompt ----------
    def prompt(self) -> str:
        if not self.cfg.get("use_lexicon", True):
            words = list(self.cfg.get("custom", []))
            return ", ".join(words) + "." if words else ""
        focus = self.focus_codes()
        key = (tuple(focus), tuple(self.cfg.get("custom", [])), int(self.cfg.get("prompt_tokens", 200)))
        if self._prompt_cache[0] == key:
            return self._prompt_cache[1]

        budget = key[2]
        ordered = list(self.cfg.get("custom", []))
        for i, code in enumerate(focus):
            b = self.books[code]
            ordered.append(re.sub(r"^\d ", "", b["name"]))
            share = 25 if i == 0 else 10          # primary book gets the lion's share
            ordered += self.lex["per_book"].get(code, [])[:share]
        ordered += self.lex["global"]

        out, seen, used = [], set(), self._tokens(" Glossary:")
        for w in ordered:
            k = w.lower()
            if k in seen:
                continue
            cost = self._tokens(" " + w + ",")
            if used + cost > budget:
                if len(out) > 8 and w in self.lex["global"]:
                    break
                continue
            out.append(w); seen.add(k); used += cost
        text = "Glossary: " + ", ".join(out) + "." if out else ""
        self._prompt_cache = (key, text)
        return text

    # ---------- correction ----------
    def correct(self, text: str) -> str:
        fixes = self.cfg.get("corrections") or {}
        for wrong, right in fixes.items():
            text = re.sub(rf"\b{re.escape(wrong)}\b", right, text, flags=re.IGNORECASE)
        if not self.cfg.get("autocorrect", True) or not self._lexset:
            return text
        cutoff = float(self.cfg.get("autocorrect_strictness", 0.84))
        made = []

        def fix(m):
            w = m.group()
            k = w.lower()
            if len(k) < 5 or k in self._lexset or zipf_frequency(k, "en") >= 2.5:
                return w                          # short, already right, or ordinary English
            pool = [c for c in self._by_initial.get(k[0], []) if abs(len(c) - len(k)) <= 2]
            best = difflib.get_close_matches(k, pool, n=1, cutoff=cutoff)
            if not best:
                return w
            right = self._lexset[best[0]]
            if w[0].isupper() and right[0].islower():
                right = right[0].upper() + right[1:]
            made.append(f"{w}→{right}")
            return right

        text = re.sub(r"[A-Za-z]+", fix, text)
        if made:
            self.last_corrections = (made + self.last_corrections)[:20]
        return text

    def state(self) -> dict:
        p = self.prompt()
        return {"focus": self.focus_codes(), "prompt": p, "prompt_tokens": self._tokens(" " + p) if p else 0,
                "lexicon_terms": len(self.lex["all"]), "recent_corrections": self.last_corrections,
                "books": [{"code": b["code"], "name": b["name"]} for b in self.lex["books"]]}
