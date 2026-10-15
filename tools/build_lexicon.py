"""Build data/lexicon.json from the World English Bible (public domain, ebible.org/engwebu).

Pulls out the words Whisper is likely to get wrong in a sermon: personal names, places and
uncommon biblical vocabulary (ephod, propitiation, shekels...). Common English is skipped -
the model already knows it, and the prompt budget is too small to waste on it.

  python tools/build_lexicon.py [path/to/engwebu_vpl.txt]

Output
  books     66 Protestant books: code, spoken name, aliases used to spot "turn to ..." in speech
  global    terms ranked for the always-on part of the prompt (hard + frequent first)
  per_book  terms most distinctive to each book, for when that book is being preached
  all       every extracted term, used by the spelling corrector
"""
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from wordfreq import zipf_frequency

ROOT = Path(__file__).resolve().parent.parent
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data/web-src/engwebu_vpl.txt"
OUT = ROOT / "data/lexicon.json"

# code, spoken name, extra aliases (lowercase). Numbered books also match "first/second/third".
BOOKS = [
    ("GEN", "Genesis", []), ("EXO", "Exodus", []), ("LEV", "Leviticus", []), ("NUM", "Numbers", []),
    ("DEU", "Deuteronomy", []), ("JOS", "Joshua", []), ("JDG", "Judges", []), ("RUT", "Ruth", []),
    ("1SA", "1 Samuel", []), ("2SA", "2 Samuel", []), ("1KI", "1 Kings", []), ("2KI", "2 Kings", []),
    ("1CH", "1 Chronicles", []), ("2CH", "2 Chronicles", []), ("EZR", "Ezra", []),
    ("NEH", "Nehemiah", []), ("EST", "Esther", []), ("JOB", "Job", []), ("PSA", "Psalms", ["psalm"]),
    ("PRO", "Proverbs", []), ("ECC", "Ecclesiastes", []),
    ("SOL", "Song of Solomon", ["song of songs"]), ("ISA", "Isaiah", []), ("JER", "Jeremiah", []),
    ("LAM", "Lamentations", []), ("EZE", "Ezekiel", []), ("DAN", "Daniel", []), ("HOS", "Hosea", []),
    ("JOE", "Joel", []), ("AMO", "Amos", []), ("OBA", "Obadiah", []), ("JON", "Jonah", []),
    ("MIC", "Micah", []), ("NAH", "Nahum", []), ("HAB", "Habakkuk", []), ("ZEP", "Zephaniah", []),
    ("HAG", "Haggai", []), ("ZEC", "Zechariah", []), ("MAL", "Malachi", []),
    ("MAT", "Matthew", []), ("MAR", "Mark", []), ("LUK", "Luke", []), ("JOH", "John", []),
    ("ACT", "Acts", []), ("ROM", "Romans", []), ("1CO", "1 Corinthians", []),
    ("2CO", "2 Corinthians", []), ("GAL", "Galatians", []), ("EPH", "Ephesians", []),
    ("PHI", "Philippians", []), ("COL", "Colossians", []), ("1TH", "1 Thessalonians", []),
    ("2TH", "2 Thessalonians", []), ("1TI", "1 Timothy", []), ("2TI", "2 Timothy", []),
    ("TIT", "Titus", []), ("PHM", "Philemon", []), ("HEB", "Hebrews", []), ("JAM", "James", []),
    ("1PE", "1 Peter", []), ("2PE", "2 Peter", []), ("1JO", "1 John", []), ("2JO", "2 John", []),
    ("3JO", "3 John", []), ("JUD", "Jude", []), ("REV", "Revelation", ["revelations"]),
]
ORDINAL = {"1": ["1", "1st", "first", "i"], "2": ["2", "2nd", "second", "ii"], "3": ["3", "3rd", "third", "iii"]}

# Capitalised in scripture but no help to the model, or titles it already writes correctly.
STOP = {"god", "lord", "i", "o", "oh", "amen", "hallelujah", "spirit", "holy", "christ", "jesus",
        "israel", "jerusalem", "egypt", "father", "son", "king", "most", "high", "almighty"}



def aliases(name: str, extra: list[str]) -> list[str]:
    out = {name.lower(), *extra}
    m = re.match(r"(\d) (.+)", name)
    if m:
        out = {f"{o} {m.group(2).lower()}" for o in ORDINAL[m.group(1)]}
    return sorted(out)


def main():
    codes = {b[0] for b in BOOKS}
    cap_mid = Counter()        # capitalised and not at the start of a sentence
    lower = Counter()          # seen in lowercase anywhere
    total = Counter()
    weighted = Counter()       # NT counts triple - most preaching here is from the NT
    nt = {b[0] for b in BOOKS[39:]}
    per_book = defaultdict(Counter)

    for line in SRC.read_text(encoding="utf-8").splitlines():
        code, _, rest = line.partition(" ")
        if code not in codes:
            continue  # Apocrypha / deuterocanon
        text = rest.split(" ", 1)[1] if " " in rest else ""
        sentence_start = True
        for m in re.finditer(r"[A-Za-z][A-Za-z’']*[A-Za-z]|[A-Za-z]|[.!?;:“”\"(]", text):
            tok = m.group()
            if not tok[0].isalpha():
                sentence_start = tok in ".!?“\"("
                continue
            tok = re.sub(r"[’']s$", "", tok).replace("’", "'")
            key = tok.lower()
            total[key] += 1
            weighted[key] += 3 if code in nt else 1
            per_book[code][key] += 1
            if tok[0].isupper():
                if not sentence_start:
                    cap_mid[tok] += 1
            else:
                lower[key] += 1
            sentence_start = False

    terms: dict[str, dict] = {}
    # Proper nouns: capitalised mid-sentence, almost never lowercase, and rare in everyday English.
    for word, c in cap_mid.items():
        key = word.lower()
        if key in STOP or len(key) < 3 or (c < 2 and lower[key]) or lower[key] > c * 0.1:
            continue
        z = zipf_frequency(key, "en")
        if z < 4.0:
            terms[key] = {"w": word, "n": total[key], "z": z}
    # Biblical vocabulary: lowercase words that are rare outside the Bible.
    for key, c in lower.items():
        if key in terms or len(key) < 5 or c < 3 or "'" in key:
            continue
        z = zipf_frequency(key, "en")
        if z < 2.4:
            terms[key] = {"w": key, "n": total[key], "z": z, "lc": True}
    # Spoken book names always count, however common ("Numbers", "Acts").
    for _, name, _ in BOOKS:
        bare = re.sub(r"^\d ", "", name)
        if " " not in bare:
            terms.setdefault(bare.lower(), {"w": bare, "n": 100, "z": zipf_frequency(bare.lower(), "en")})
    for key, t in terms.items():
        t["wn"] = weighted[key] or t["n"]

    # Worth prompting for: said often in the Bible (NT weighted), hard to spell, but not so obscure
    # nobody preaches on it. Everyday-English zipf of ~1.5-3.8 is the sweet spot: Gethsemane,
    # Nicodemus, propitiation. Below that are the Maaseiahs of the genealogies; above it the
    # model already knows the word.
    def score(t):
        fame = 1.0 if 1.5 <= t["z"] < 3.8 else 0.35 if t["z"] < 1.5 else 0.6
        return math.log1p(t["wn"]) * fame

    hard_books = [re.sub(r"^\d ", "", n) for _, n, _ in BOOKS
                  if zipf_frequency(re.sub(r"^\d ", "", n).split()[-1].lower(), "en") < 3.0]
    ranked = sorted(terms.values(), key=score, reverse=True)
    glob = list(dict.fromkeys(hard_books + [t["w"] for t in ranked]))

    book_terms = {}
    for code, counts in per_book.items():
        cand = []
        for key, c in counts.items():
            t = terms.get(key)
            if not t:
                continue
            share = c / t["n"]                      # how much of this word lives in this book
            if c < 2 and share < 1:                 # one-offs only if unique to this book
                continue
            if t.get("lc") and t["z"] >= 2.0:       # plain words the model already spells
                continue
            cand.append(((c + 1) * share * max(0.5, 5.0 - t["z"]), t["w"]))
        book_terms[code] = [w for _, w in sorted(cand, reverse=True)[:80]]

    out = {
        "source": "World English Bible (engwebu), public domain - ebible.org",
        "books": [{"code": c, "name": n, "aliases": aliases(n, x)} for c, n, x in BOOKS],
        "global": glob[:400],
        "per_book": book_terms,
        "all": sorted({t["w"] for t in terms.values()}),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"{len(out['all'])} terms, {len(book_terms)} books -> {OUT}")


if __name__ == "__main__":
    main()
