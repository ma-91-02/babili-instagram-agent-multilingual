#!/usr/bin/env python3
"""
detect.py - a five-check panel that scores how machine-written a draft looks.

What this is:  five local heuristics modelled on the signals public AI
detectors actually measure - sentence-length variation, concreteness, stock
vocabulary, typographic fingerprint, and voice. Every score is computed on
your machine from the text alone. Nothing is uploaded.

What this is NOT:  GPTZero, Originality, Copyleaks, Winston or Turnitin.
It does not call their APIs and it cannot promise their verdict. It catches
the things they all key on, which is why fixing them tends to move their
numbers too - but the only honest claim is the one on this line.

Each check returns a HUMAN score from 0 to 100. Higher is better.

Languages: the draft's language is detected, or pass --lang
en|ar|ru|tr|pl|cs. English runs the original five checks unchanged. The other
languages run the same five with their own lexicon, sentence punctuation and
names (in Arabic, a brand in Latin letters counts as a name). Two checks are
adapted, not copied: VOICE drops the English contraction count and measures
person against a lower target for languages that drop pronouns, and
FINGERPRINT does not count a language's own correct punctuation (the Russian
dash, Czech and Polish „quotes“) as a machine tell. These non-English
thresholds are first estimates, not measured on a corpus.

Usage
  python3 detect.py draft.txt
  python3 detect.py draft.txt --lang ar
  pbpaste | python3 detect.py -
  python3 detect.py draft.txt --json
  python3 detect.py before.txt after.txt      # compare two drafts
"""

import argparse
import json
import os
import re
import statistics
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
LEX = os.path.join(HERE, "slop.json")


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
EMOJI_CHARS = (r"\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\u2300-\u23FF"
               r"\u2190-\u21FF\u3030\u303D\u3297\u3299\u00A9\u00AE\u203C\u2049\u2122\u2139")
ZWJ_IN_EMOJI = re.compile(r"(?<=[" + EMOJI_CHARS + r"\uFE0F\U0001F3FB-\U0001F3FF])\u200D(?=[" + EMOJI_CHARS + r"])")
TAG_FLAG = re.compile(r"\U0001F3F4[\U000E0020-\U000E007E]+\U000E007F")
BIDI_MARKS = "\u200E\u200F\u061C\u202A\u202B\u202C\u202D\u202E\u2066\u2067\u2068\u2069"
NEUTRAL_STRUCTURES = {"rocket", "hashtag-wall", "emoji-bullets"}

SENT_RE = re.compile(r"[^.!?\n]+[.!?]*")
WORD_RE = re.compile(r"[A-Za-z']+")
CONTRACTIONS = re.compile(r"\b\w+'(?:s|t|re|ve|ll|d|m)\b", re.IGNORECASE)
PRONOUNS = re.compile(r"\b(i|me|my|mine|we|us|our|you|your)\b", re.IGNORECASE)
NUMBERS = re.compile(r"\b\d[\d,.]*%?\b|\$\d")
PROPER = re.compile(r"(?<![.!?]\s)(?<!^)\b[A-Z][a-z]{2,}\b", re.MULTILINE)


def clamp(n):
    return max(0.0, min(100.0, n))


def scale(value, human, machine):
    """Map value onto 0-100 where `human` -> 100 and `machine` -> 0."""
    if human == machine:
        return 50.0
    return clamp((value - machine) / (human - machine) * 100)


def sentences(text):
    return [s.strip() for s in SENT_RE.findall(text) if len(s.split()) > 2]


def words(text):
    return WORD_RE.findall(text)


def check_burstiness(text):
    """Humans vary sentence length hard. Models write even."""
    lens = [len(s.split()) for s in sentences(text)]
    if len(lens) < 4:
        return 50.0, "too short to judge"
    mean = statistics.mean(lens)
    cv = statistics.pstdev(lens) / mean if mean else 0
    score = scale(cv, human=0.70, machine=0.22)
    return score, f"variation {cv:.2f} across {len(lens)} sentences (want 0.55+)"


def check_specificity(text):
    """Numbers, names and concrete nouns. Slop is abstract."""
    w = words(text)
    if len(w) < 25:
        return 50.0, "too short to judge"
    per100 = 100 / len(w)
    hits = len(NUMBERS.findall(text)) + len(set(PROPER.findall(text)))
    density = hits * per100
    score = scale(density, human=6.0, machine=0.5)
    return score, f"{hits} concrete markers, {density:.1f} per 100 words (want 4+)"


def check_slop(text, lex):
    """Stock vocabulary density against the lexicon."""
    w = words(text)
    if not w:
        return 50.0, "empty"
    hits, found = 0, []
    for entry in lex["words"] + lex["phrases"]:
        pattern = re.compile(r"\b" + re.escape(entry["find"]).replace(r"\ ", r"\s+") + r"\b",
                             re.IGNORECASE)
        n = len(pattern.findall(text))
        if n:
            hits += n
            found.append(entry["find"])
    density = hits * 100 / len(w)
    score = scale(density, human=0.0, machine=4.0)
    detail = f"{hits} stock terms, {density:.1f} per 100 words"
    if found:
        detail += " (" + ", ".join(sorted(found)[:4]) + (", ..." if len(found) > 4 else "") + ")"
    return score, detail


def check_fingerprint(text, pack=None):
    """Characters a phone keyboard does not produce.

    A joiner inside an emoji (👨‍👩‍👧) is part of the emoji, and direction
    marks in right-to-left text are how Arabic keyboards keep a Latin word in
    place, so neither is counted. Neither is a language's own correct
    punctuation."""
    body = TAG_FLAG.sub("", ZWJ_IN_EMOJI.sub("", text))
    rtl = bool(re.search(r"[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]", body))
    invisible = sum(1 for c in body if unicodedata.category(c) == "Cf"
                    and not (rtl and c in BIDI_MARKS))
    native = i18n.native_typography(pack) if (pack is not None and i18n) else set()
    em = 0 if "—" in native else text.count("—")
    curly = sum(text.count(c) for c in "‘’“”" if c not in native)
    ellip = text.count("…")
    nbsp = sum(text.count(c) for c in "   ")
    total = invisible * 4 + em * 2 + curly + ellip + nbsp
    per1k = total * 1000 / max(len(text), 1)
    score = scale(per1k, human=0.0, machine=12.0)
    detail = (f"{invisible} invisible, {em} em dash, {curly} curly quote, "
              f"{ellip} ellipsis, {nbsp} hard space")
    return score, detail


def check_voice(text, lex):
    """Contractions, person, and the shapes models default to."""
    w = words(text)
    if len(w) < 25:
        return 50.0, "too short to judge"
    per100 = 100 / len(w)
    contractions = len(CONTRACTIONS.findall(text)) * per100
    person = len(PRONOUNS.findall(text)) * per100
    tells = 0
    names = []
    for s in lex["structures"]:
        try:
            n = len(re.compile(s["regex"], re.MULTILINE).findall(text))
        except re.error:
            continue
        if n:
            tells += n
            names.append(s["id"])
    bullets = [len(b.split()) for b in re.findall(r"(?m)^\s*[-*•]\s+(.+)$", text)]
    uniform = (len(bullets) >= 3 and statistics.pstdev(bullets) < 1.6)
    score = (scale(contractions, human=3.0, machine=0.0) * 0.35
             + scale(person, human=8.0, machine=1.0) * 0.35
             + clamp(100 - tells * 22) * 0.30)
    if uniform:
        score -= 12
        names.append("uniform-bullets")
    detail = (f"{contractions:.1f} contractions, {person:.1f} personal pronouns "
              f"per 100 words, {tells} structural tell(s)")
    if names:
        detail += " [" + ", ".join(names[:4]) + "]"
    return clamp(score), detail


CHECKS = ["BURSTINESS", "SPECIFICITY", "SLOP DENSITY", "FINGERPRINT", "VOICE"]


def run(text, lex, pack=None):
    if pack is not None and i18n is not None and not i18n.is_english(pack):
        return run_i18n(text, lex, pack)
    results = {}
    results["BURSTINESS"] = check_burstiness(text)
    results["SPECIFICITY"] = check_specificity(text)
    results["SLOP DENSITY"] = check_slop(text, lex)
    results["FINGERPRINT"] = check_fingerprint(text)
    results["VOICE"] = check_voice(text, lex)
    scores = [results[c][0] for c in CHECKS]
    # The weakest check drags the verdict: a detector only needs one signal.
    overall = statistics.mean(scores) * 0.6 + min(scores) * 0.4
    verdict = "PASS" if overall >= 70 and min(scores) >= 55 else (
        "REVIEW" if overall >= 50 else "FLAGGED")
    return results, overall, verdict


# --------------------------------------------------------------------------
# The same five checks for the other languages.
# --------------------------------------------------------------------------

def _i_burstiness(text, pack):
    sent_re = i18n.sentence_re(pack)
    lens = [len(s.split()) for s in sent_re.findall(text) if len(s.split()) > 2]
    if len(lens) < 4:
        return 50.0, "too short to judge"
    mean = statistics.mean(lens)
    cv = statistics.pstdev(lens) / mean if mean else 0
    return scale(cv, human=0.70, machine=0.22), \
        f"variation {cv:.2f} across {len(lens)} sentences (want 0.55+)"


def _i_specificity(text, pack):
    w = i18n.words(text)
    if len(w) < 25:
        return 50.0, "too short to judge"
    hits = len(i18n.numbers(text)) + len(set(i18n.propers(text, pack))) \
        + len(i18n.spoken_number_hits(text, pack))
    density = hits * 100 / len(w)
    return scale(density, human=6.0, machine=0.5), \
        f"{hits} concrete markers, {density:.1f} per 100 words (want 4+)"


def _i_slop(text, pack):
    w = i18n.words(text)
    if not w:
        return 50.0, "empty"
    lex = pack.get("lexicon", {})
    hits, found = 0, []
    for entry in lex.get("words", []) + lex.get("phrases", []):
        n = len(list(i18n.lex_regex(entry["find"], pack).finditer(text)))
        if n:
            hits += n
            found.append(entry["find"])
    density = hits * 100 / len(w)
    detail = f"{hits} stock terms, {density:.1f} per 100 words"
    if found:
        detail += " (" + ", ".join(sorted(found)[:4]) + (", ..." if len(found) > 4 else "") + ")"
    return scale(density, human=0.0, machine=4.0), detail


def _i_voice(text, lex, pack):
    """Person and structure. No contraction count: that is an English signal.
    Languages that drop their pronouns get a lower person target."""
    w = i18n.words(text)
    if len(w) < 25:
        return 50.0, "too short to judge"
    a = pack.get("hook", {}).get("address", {})
    you = i18n.terms(pack, "hook", "address", "you")
    me = i18n.terms(pack, "hook", "address", "me")
    person_hits = sum(1 for t in w if you.hit(t) or me.hit(t)
                      or i18n.suffix_hit(t, pack, a.get("you_suffixes"), a.get("you_exceptions"))
                      or i18n.suffix_hit(t, pack, a.get("me_suffixes"), a.get("me_exceptions")))
    person = person_hits * 100 / len(w)
    target = pack.get("voice", {}).get("pronoun_target", 6.0)
    tells, names = 0, []
    for s in lex["structures"]:
        try:
            n = len(re.compile(s["regex"], re.MULTILINE).findall(text))
        except re.error:
            continue
        if n:
            tells += n
            names.append(s["id"])
    bullets = [len(b.split()) for b in re.findall(r"(?m)^\s*[-*•]\s+(.+)$", text)]
    uniform = (len(bullets) >= 3 and statistics.pstdev(bullets) < 1.6)
    score = (scale(person, human=target, machine=target / 8) * 0.6
             + clamp(100 - tells * 22) * 0.4)
    if uniform:
        score -= 12
        names.append("uniform-bullets")
    detail = (f"{person:.1f} first/second-person words per 100 (want {target:g}+), "
              f"{tells} structural tell(s)")
    if names:
        detail += " [" + ", ".join(names[:4]) + "]"
    return clamp(score), detail


def run_i18n(text, lex, pack):
    own = dict(lex)
    own["structures"] = pack.get("lexicon", {}).get("structures", []) \
        + [s for s in lex["structures"] if s["id"] in NEUTRAL_STRUCTURES]
    results = {
        "BURSTINESS": _i_burstiness(text, pack),
        "SPECIFICITY": _i_specificity(text, pack),
        "SLOP DENSITY": _i_slop(text, pack),
        "FINGERPRINT": check_fingerprint(text, pack),
        "VOICE": _i_voice(text, own, pack),
    }
    scores = [results[c][0] for c in CHECKS]
    overall = statistics.mean(scores) * 0.6 + min(scores) * 0.4
    verdict = "PASS" if overall >= 70 and min(scores) >= 55 else (
        "REVIEW" if overall >= 50 else "FLAGGED")
    return results, overall, verdict


def bar(score, width=24):
    filled = round(score / 100 * width)
    return "#" * filled + "." * (width - filled)


def render(results, overall, verdict, label=None, out=sys.stdout, lang=None):
    title = "AI DETECTION PANEL" + (f"  -  {label}" if label else "") \
        + (f"  ·  {lang}" if lang else "")
    print("\n" + title, file=out)
    print("=" * max(len(title), 62), file=out)
    for name in CHECKS:
        score, detail = results[name]
        print(f"  {name:<13} {bar(score)} {score:5.1f}", file=out)
        print(f"  {'':<13} {detail}", file=out)
    print("-" * 62, file=out)
    print(f"  {'HUMAN SCORE':<13} {bar(overall)} {overall:5.1f}   {verdict}", file=out)
    if verdict != "PASS":
        weakest = min(CHECKS, key=lambda c: results[c][0])
        print(f"\n  Weakest signal: {weakest}. Fix that first.", file=out)
    print("", file=out)


def main():
    ap = argparse.ArgumentParser(description="Score how machine-written a draft looks.")
    ap.add_argument("input", nargs="?", default="-", help="file, or - for stdin")
    ap.add_argument("compare", nargs="?", help="second file, to show before/after")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--lexicon", default=LEX)
    ap.add_argument("--lang", default="auto",
                    help="en, ar, ru, tr, pl, cs, or auto to detect each file (default)")
    args = ap.parse_args()

    lex = json.load(open(args.lexicon, encoding="utf-8"))
    read = lambda p: sys.stdin.read() if p == "-" else open(p, encoding="utf-8").read()

    targets = [(args.input, read(args.input))]
    if args.compare:
        targets.append((args.compare, read(args.compare)))

    def pack_of(text):
        if i18n is None:
            return None
        p = i18n.resolve(args.lang, text)
        return None if i18n.is_english(p) else p

    payload = []
    for name, text in targets:
        pack = pack_of(text)
        results, overall, verdict = run(text, lex, pack)
        row = {
            "source": name,
            "checks": {k: {"score": round(v[0], 1), "detail": v[1]} for k, v in results.items()},
            "human_score": round(overall, 1),
            "verdict": verdict,
        }
        if pack is not None:
            row["lang"] = pack["code"]
        payload.append(row)

    if args.json:
        print(json.dumps(payload if args.compare else payload[0], indent=2, ensure_ascii=False))
        return

    for (name, text), p in zip(targets, payload):
        pack = pack_of(text)
        results, overall, verdict = run(text, lex, pack)
        render(results, overall, verdict, label=os.path.basename(name) if args.compare else None,
               lang=pack["code"] if pack is not None else None)
    if args.compare:
        a, b = payload
        delta = b["human_score"] - a["human_score"]
        print(f"  {a['human_score']:.1f} {a['verdict']}  ->  "
              f"{b['human_score']:.1f} {b['verdict']}   ({delta:+.1f})\n")

    sys.exit(0 if payload[-1]["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
