#!/usr/bin/env python3
"""
beats.py - turn a Reel script into a timed beat sheet before you record it.

Estimates how long each line takes to say, stacks them into timecodes, and
flags the four things that kill a Reel in the edit: a hook that runs past the
three-second mark, a beat long enough for the viewer to leave, a run of lines
with nothing concrete in them, and a total length that does not match what you
said you were making.

The timings are an estimate from word count at a words-per-minute rate. They
are close enough to plan an edit and not a substitute for recording it. Set
your own rate with --wpm once you have timed yourself reading a script out
loud: most people land between 150 and 200, and the default here is 165.

Languages: the script is detected (or pass --lang en|ar|ru|tr|pl|cs). Words
per minute differ a lot between languages, because a Turkish or Arabic word
carries more than an English one, so the default rate comes from the language
pack (English 165, Arabic 135, Russian 140, Turkish 120, Polish 135, Czech
140). Those non-English rates are starting estimates. Time yourself once and
pass --wpm.

Usage
  python3 beats.py script.txt
  python3 beats.py script.txt --target 30
  python3 beats.py script.txt --wpm 185 --target 45
  python3 beats.py script.txt --lang ar --target 30
  pbpaste | python3 beats.py -
  python3 beats.py script.txt --json
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _import_i18n():
    """Find the shared language layer (skills/ig-lang) wherever it was installed."""
    parent = os.path.dirname(HERE)
    dirs = [os.path.join(parent, "ig-lang")]
    try:
        dirs += [os.path.join(parent, d) for d in sorted(os.listdir(parent))
                 if d.endswith("ig-lang") and d != "ig-lang"]
    except OSError:
        pass
    for d in dirs:
        if os.path.isfile(os.path.join(d, "i18n.py")):
            sys.path.insert(0, d)
            try:
                import i18n as mod
                return mod
            except Exception:
                return None
    return None


i18n = _import_i18n()

WORD_RE = re.compile(r"[A-Za-z0-9$%'’-]+")
SENT_RE = re.compile(r"[^.!?]+[.!?]*")
CONCRETE_RE = re.compile(r"\$\s?\d|\b\d[\d,.]*\b|(?<!^)\b[A-Z][a-z]{2,}\b", re.MULTILINE)
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "with", "that", "this", "it", "is", "are", "was", "were", "be", "been",
    "you", "your", "i", "my", "me", "we", "our", "they", "them", "he", "she",
    "so", "just", "not", "no", "do", "did", "does", "have", "has", "had",
    "will", "can", "at", "as", "by", "from", "out", "up", "off", "one", "all",
}

HOOK_WINDOW = 3.0        # seconds. Past this, the thumb has already decided.
MAX_BEAT = 4.0           # seconds on one idea with no change on screen.
ABSTRACT_RUN = 3         # beats in a row with nothing checkable in them.


def words(text):
    # "$18,000" is one word when it is spoken, so it is one word here too.
    return WORD_RE.findall(re.sub(r"(?<=\d),(?=\d)", "", text))


def pretty(token):
    """Put the thousands separator back for display."""
    return re.sub(r"(\d)(?=(\d{3})+$)", r"\1,", token)


def tc(seconds):
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}"


def split_beats(raw, wps, words=words, sent_re=SENT_RE):
    """One line is one beat, unless a line is too long to be one."""
    beats = []
    for line in [l.strip() for l in raw.splitlines()]:
        if not line:
            continue
        if len(words(line)) / wps <= MAX_BEAT * 1.5:
            beats.append(line)
            continue
        # Long paragraph: break it at sentence ends so the timings mean
        # something, and let the report say it was split.
        parts = [p.strip() for p in sent_re.findall(line) if p.strip()]
        buf = ""
        for part in parts:
            candidate = (buf + " " + part).strip()
            if buf and len(words(candidate)) / wps > MAX_BEAT:
                beats.append(buf)
                buf = part
            else:
                buf = candidate
        if buf:
            beats.append(buf)
    return beats


def _toolkit(pack):
    """The word, sentence, concreteness and loop-matching functions to use.

    English gets the original ones untouched. Other languages get Unicode
    tokens, their own sentence punctuation, their own stopwords, and a loose
    stem for the loop check, because 'контракт' in the hook and 'контракта'
    at the end are the same word to a viewer.
    """
    if pack is None or i18n is None or i18n.is_english(pack):
        return {
            "words": words, "sent_re": SENT_RE,
            "concrete": lambda t: len(CONCRETE_RE.findall(t)),
            "stop": STOPWORDS, "key": lambda w: w.lower(), "show": lambda w: pretty(w.lower()),
        }
    stop = {i18n.norm(s, pack) for s in pack.get("beats", {}).get("stopwords", [])}

    def key(w):
        f = i18n.forms(w, pack)
        k = min(f, key=len) if pack.get("code") == "ar" else f[0]
        return k[:5] if len(k) > 5 and pack.get("code") != "ar" else k

    return {
        "words": i18n.words, "sent_re": i18n.sentence_re(pack, newline=False),
        "concrete": lambda t: len(i18n.concrete(t, pack)),
        "stop": stop, "key": key, "show": lambda w: w,
    }


def analyse(raw, wpm=165, target=None, pack=None):
    kit = _toolkit(pack)
    words = kit["words"]
    wps = wpm / 60.0
    beats = split_beats(raw, wps, words=words, sent_re=kit["sent_re"])
    if not beats:
        return None

    rows, clock = [], 0.0
    for i, text in enumerate(beats):
        n = len(words(text))
        dur = n / wps
        rows.append({
            "n": i + 1,
            "start": round(clock, 2),
            "dur": round(dur, 2),
            "words": n,
            "text": text,
            "concrete": kit["concrete"](text),
            "label": "",
            "flags": [],
        })
        clock += dur
    total = clock

    # Label the structural positions a Reel is actually built around.
    for r in rows:
        if r["n"] == 1 or r["start"] + r["dur"] <= HOOK_WINDOW:
            r["label"] = "HOOK"
    rows[-1]["label"] = "CTA" if rows[-1]["label"] != "HOOK" else "HOOK/CTA"
    half = total / 2
    for r in rows:
        if not r["label"] and r["start"] <= half < r["start"] + r["dur"]:
            r["label"] = "MID"

    notes = []
    if rows[0]["dur"] > HOOK_WINDOW:
        rows[0]["flags"].append(f"hook runs {rows[0]['dur']:.1f}s, past the {HOOK_WINDOW:.0f}s mark")
        notes.append(f"Beat 1 takes {rows[0]['dur']:.1f}s to say. Cut it to "
                     f"{int(HOOK_WINDOW * wps)} words or fewer, or the hook lands after "
                     "the decision has been made.")
    if rows[0]["concrete"] == 0:
        notes.append("Beat 1 has no number and no name in it. Hooks without something "
                     "checkable are the ones that get scrolled.")

    for r in rows:
        if r["dur"] > MAX_BEAT:
            r["flags"].append(f"{r['dur']:.1f}s on one beat")
    long_beats = [r["n"] for r in rows if r["dur"] > MAX_BEAT]
    if long_beats:
        notes.append(f"Beat(s) {', '.join(map(str, long_beats))} run past {MAX_BEAT:.0f}s. "
                     "Either split the line or change what is on screen inside it. "
                     "A static frame is where people leave.")

    run, start = 0, None
    for r in rows:
        if r["concrete"] == 0:
            run += 1
            start = start if start is not None else r["n"]
            if run == ABSTRACT_RUN:
                notes.append(f"Beats {start}-{r['n']} have nothing concrete in them. "
                             "Put a number, a name or a price in one of them.")
        else:
            run, start = 0, None

    # Does the last line hand you back to the first one?
    key, stop = kit["key"], kit["stop"]
    first = {key(w): w for w in words(rows[0]["text"]) if key(w) not in stop}
    last = {key(w) for w in words(rows[-1]["text"]) if key(w) not in stop}
    loop = sorted(kit["show"](first[k]) for k in set(first) & last)
    if loop:
        notes.append(f"Loops: the last beat repeats \"{', '.join(loop[:3])}\" from the hook. "
                     "Second watches are free reach.")
    else:
        notes.append("No loop. The last beat shares no word with the hook, so the video "
                     "ends flat. Echoing one word from beat 1 is the cheapest replay you get.")

    if target:
        delta = total - target
        if abs(delta) <= target * 0.1:
            notes.append(f"Length is on target ({total:.1f}s against {target}s).")
        elif delta > 0:
            notes.append(f"{delta:.1f}s over target. Cut about {int(delta * wps)} words.")
        else:
            notes.append(f"{-delta:.1f}s under target. Either add {int(-delta * wps)} words "
                         "or shoot it short. Short is usually right.")

    out = {
        "wpm": wpm, "target": target,
        "total_seconds": round(total, 2),
        "total_words": sum(r["words"] for r in rows),
        "beats": rows,
        "notes": notes,
    }
    if pack is not None and i18n is not None and not i18n.is_english(pack):
        out["lang"] = pack["code"]
    return out


def render(a, out=sys.stdout):
    head = (f"BEAT SHEET  ·  {a['total_words']} words  ·  ~{a['total_seconds']:.1f}s "
            f"at {a['wpm']} wpm" + (f"  ·  target {a['target']}s" if a["target"] else "")
            + (f"  ·  {a['lang']}" if a.get("lang") else ""))
    print("\n" + head, file=out)
    print("=" * max(len(head), 72), file=out)
    for r in a["beats"]:
        label = f"{r['label']:<8}" if r["label"] else " " * 8
        print(f"  {tc(r['start'])}  {r['dur']:4.1f}s  {label}{r['text']}", file=out)
        for f in r["flags"]:
            print(f"  {'':>6}  {'':>5}  {'':<8}^ {f}", file=out)
    print("-" * max(len(head), 72), file=out)
    for n in a["notes"]:
        print(f"  - {n}", file=out)
    print("", file=out)


def main():
    ap = argparse.ArgumentParser(description="Time a Reel script into a beat sheet.")
    ap.add_argument("input", nargs="?", default="-", help="script file, or - for stdin")
    ap.add_argument("--wpm", type=float, default=None,
                    help="speaking rate (default: the language's, 165 for English)")
    ap.add_argument("--target", type=float, help="target length in seconds")
    ap.add_argument("--lang", default="auto",
                    help="en, ar, ru, tr, pl, cs, or auto to detect (default)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    pack = i18n.resolve(args.lang, raw) if i18n else None
    wpm = args.wpm or (pack.get("wpm", 165) if pack else 165)
    a = analyse(raw, wpm=wpm, target=args.target, pack=pack)
    if not a:
        print("empty script", file=sys.stderr)
        sys.exit(2)
    if args.json:
        print(json.dumps(a, indent=2, ensure_ascii=False))
    else:
        render(a)
    sys.exit(0)


if __name__ == "__main__":
    main()
