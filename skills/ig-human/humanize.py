#!/usr/bin/env python3
"""
humanize.py - strip the machine fingerprint out of a draft.

Three passes, in this order:

  1. INVISIBLE   delete or normalise the characters a human keyboard never
                 produces: zero-width joiners, word joiners, soft hyphens,
                 BOMs, Unicode tag characters, non-breaking and narrow spaces.
                 These survive copy-paste and are the most mechanical tell in
                 any generated text.
  2. TYPOGRAPHIC em dash -> comma, en dash -> hyphen, curly quotes -> straight,
                 ellipsis -> three dots, bullet -> hyphen.
  3. LEXICAL     replace the slop lexicon in slop.json with plain words,
                 preserving capitalisation and leaving URLs untouched.

Structural tells (rule-of-three, "not just X, it's Y", hashtag walls) are
REPORTED, never auto-rewritten - rewriting a sentence's shape needs judgement,
so that is the model's job, not a regex's.

Languages
  The draft's language is detected, or pass --lang en|ar|ru|tr|pl|cs.
  English uses slop.json exactly as before. The other languages use their own
  lexicon from ../ig-lang/lang/<code>.json, plus three rules that matter
  outside English:

  - Emoji survive. A zero-width joiner inside an emoji sequence (👨‍👩‍👧, ❤️‍🔥)
    is part of the emoji, not a watermark, so it is kept in every language.
  - Direction marks survive in right-to-left text. In Arabic, the LRM/RLM/ALM
    marks are what keep a Latin brand name or a number in the right place.
  - House style survives. The Russian dash, Polish and Czech „quotes“ and
    Arabic «guillemets» are correct typography in those languages and are left
    alone.

  In inflected languages a word can need a different ending in every sentence,
  so many entries are FLAGGED rather than replaced. Those come back in the
  report for a rewrite, like the structural tells.

Usage
  python3 humanize.py draft.txt
  python3 humanize.py draft.txt --report
  python3 humanize.py draft.txt --lang ar --report
  pbpaste | python3 humanize.py - --report
  python3 humanize.py draft.txt --json
  python3 humanize.py draft.txt -o clean.txt
"""

import argparse
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
LEX = os.path.join(HERE, "slop.json")

URL_RE = re.compile(r"https?://\S+|www\.\S+|\S+@\S+\.\S+")
SENT_RE = re.compile(r"[^.!?\n]+[.!?]*")

# Emoji and the joiners that legitimately live inside them.
EMOJI_CHARS = (r"\U0001F000-\U0001FAFF☀-➿⬀-⯿⌀-⏿"
               r"←-⇿〰〽㊗㊙©®‼⁉™ℹ")
ZWJ_IN_EMOJI = re.compile(r"(?<=[" + EMOJI_CHARS + r"️\U0001F3FB-\U0001F3FF])‍(?=[" + EMOJI_CHARS + r"])")
TAG_FLAG = re.compile(r"\U0001F3F4[\U000E0020-\U000E007E]+\U000E007F")
BIDI_MARKS = "‎‏؜‪‫‬‭‮⁦⁧⁨⁩"
ARABIC_LETTER = r"ؠ-يٮ-ۓۺ-ۿ"
ZWNJ_IN_ARABIC = re.compile(r"(?<=[" + ARABIC_LETTER + r"])‌(?=[" + ARABIC_LETTER + r"])")


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

# English structures that do not depend on language, carried into every pack.
NEUTRAL_STRUCTURES = {"rocket", "hashtag-wall", "emoji-bullets"}


def load_lexicon(path=LEX, pack=None):
    """slop.json for English. For another language: that pack's lexicon, with
    slop.json's invisible and typographic tables and its language-neutral
    structures (emoji, hashtag walls)."""
    with open(path, encoding="utf-8") as fh:
        lex = json.load(fh)
    if pack is None or i18n is None or i18n.is_english(pack):
        lex["_pack"] = None
        return lex
    own = pack.get("lexicon", {})
    native = i18n.native_typography(pack)
    return {
        "invisible": lex["invisible"],
        "typographic": [t for t in lex["typographic"] if t["from"] not in native],
        "words": own.get("words", []),
        "phrases": own.get("phrases", []),
        "structures": own.get("structures", [])
        + [s for s in lex["structures"] if s["id"] in NEUTRAL_STRUCTURES],
        "_pack": pack,
    }


def _cp(spec):
    """'U+200B' -> '\\u200b';  'U+E0000-U+E007F' -> (start, end)."""
    if "-" in spec:
        a, b = spec.split("-")
        return (int(a[2:], 16), int(b[2:], 16))
    return int(spec[2:], 16)


def protect_urls(text):
    """Swap URLs for placeholders so no pass rewrites inside a link."""
    found = []

    def stash(m):
        found.append(m.group(0))
        return f"\x00URL{len(found) - 1}\x00"

    return URL_RE.sub(stash, text), found


def restore_urls(text, found):
    for i, url in enumerate(found):
        text = text.replace(f"\x00URL{i}\x00", url)
    return text


def _protect(text, pattern, tag):
    """Swap matches for placeholders. Returns (text, restore_fn, count)."""
    kept = []

    def stash(m):
        kept.append(m.group(0))
        return f"\x00{tag}{len(kept) - 1}\x00"

    text = pattern.sub(stash, text)

    def restore(t):
        for i, s in enumerate(kept):
            t = t.replace(f"\x00{tag}{i}\x00", s)
        return t

    return text, restore, len(kept)


def pass_invisible(text, lex):
    """Delete or space-normalise invisible characters. Returns (text, hits).

    Kept on purpose: the joiner inside an emoji, a subdivision flag's tag
    characters, a non-joiner between two Arabic letters, and direction marks
    in text that contains a right-to-left script.
    """
    hits = []
    text, r1, n1 = _protect(text, ZWJ_IN_EMOJI, "ZWJ")
    text, r2, n2 = _protect(text, TAG_FLAG, "FLAG")
    text, r3, n3 = _protect(text, ZWNJ_IN_ARABIC, "ZWNJ")
    rtl = bool(re.search(r"[֐-ࣿיִ-﷿ﹰ-﻿]", text))
    kept_bidi = 0
    for entry in lex["invisible"]:
        cp = _cp(entry["cp"])
        if isinstance(cp, tuple):
            pattern = "[" + re.escape(chr(cp[0])) + "-" + re.escape(chr(cp[1])) + "]"
        else:
            if rtl and chr(cp) in BIDI_MARKS:
                kept_bidi += text.count(chr(cp))
                continue
            pattern = re.escape(chr(cp))
        n = len(re.findall(pattern, text))
        if n:
            hits.append({"name": entry["cp"] + " " + entry["name"], "count": n,
                         "action": entry["action"]})
            text = re.sub(pattern, "" if entry["action"] == "delete" else " ", text)
    # Any remaining Cf (format) character is invisible by definition.
    stray = [c for c in text if unicodedata.category(c) == "Cf"
             and not (rtl and c in BIDI_MARKS)]
    if stray:
        hits.append({"name": "other invisible format chars", "count": len(stray),
                     "action": "delete"})
        text = "".join(c for c in text if unicodedata.category(c) != "Cf"
                       or (rtl and c in BIDI_MARKS))
    if rtl:
        kept_bidi = sum(text.count(c) for c in BIDI_MARKS)
    text = r3(r2(r1(text)))
    for n, name in ((n1, "emoji joiners (inside emoji sequences)"),
                    (n2, "flag tag sequences"),
                    (n3, "non-joiners between Arabic letters"),
                    (kept_bidi, "direction marks (right-to-left text)")):
        if n:
            hits.append({"name": name, "count": n, "action": "kept"})
    return text, hits


def pass_typographic(text, lex):
    hits = []
    for entry in lex["typographic"]:
        ch = entry["from"]
        n = text.count(ch)
        if not n:
            continue
        hits.append({"name": f"{ch} {entry['name']}", "count": n, "to": entry["to"].strip() or "(space)"})
        if ch == "—":
            # " word — word " and "word—word" both collapse to a comma + space.
            text = re.sub(r"\s*—\s*", ", ", text)
        elif ch == "–":
            text = re.sub(r"\s*–\s*(?=\d)", "-", text)      # 5–10  -> 5-10
            text = re.sub(r"\s+–\s+", ", ", text)            # used as em dash
            text = text.replace("–", "-")
        else:
            text = text.replace(ch, entry["to"])
    # A comma inserted before existing punctuation reads wrong.
    text = re.sub(r",\s*([,.;:!?])", r"\1", text)
    text = re.sub(r",\s*\n", "\n", text)
    return text, hits


def _match_case(src, repl):
    if not repl:
        return repl
    if src.isupper() and len(src) > 1:
        return repl.upper()
    if src[0].isupper():
        return repl[0].upper() + repl[1:]
    return repl


def _cleanup(text, punct=",.;:", end="!?"):
    """Clean up after deletions. Deleting a whole clause leaves orphaned
    punctuation behind ("system. ." or a line that now opens on a comma),
    and that reads worse than the slop did."""
    allp = re.escape(punct + end)
    text = re.sub(r"[ \t]{2,}", " ", text)
    # A line left holding only the "!" of a deleted sentence goes with it.
    text = re.sub(r"(?m)^[ \t]*[" + re.escape(end) + r"]+[ \t]*(?:\n|$)", "", text)
    text = re.sub(r"(?m)^[ \t]*(?:[" + re.escape(punct) + r"]+[ \t]*)+", "", text)
    text = re.sub(r"(?m)^[ \t](?=\S)", "", text)       # one space left by a deletion.
                                                      # Deeper indents are deliberate.
    text = re.sub(r"\s+([" + allp + r"])", r"\1", text)
    text = re.sub(r"[,،]\s*([" + allp + r"])", r"\1", text)  # an em dash became a comma,
                                                      # then the clause after it went
    text = text.replace("...", "\x00ELL\x00")          # protect real ellipses
    text = re.sub(r"\.\s*\.+", ".", text)
    text = re.sub(r"([" + re.escape(end) + r"])\s*\.", r"\1", text)
    text = re.sub(r"\.[ \t]*[" + re.escape(end) + r"]+", ".", text)  # "done. !" -> "done."
    text = text.replace("\x00ELL\x00", "...")
    text = re.sub(r"(?m)^[ \t]+$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def pass_lexical(text, lex):
    """Replace slop words and phrases. Longest first so phrases win.

    Returns (text, hits, flagged). `flagged` holds entries whose replacement
    is null: in an inflected language the right word depends on the sentence,
    so those are reported for a rewrite instead of being swapped by regex.
    """
    pack = lex.get("_pack")
    if pack is None:
        return _pass_lexical_en(text, lex) + ([],)
    hits, flagged = [], []
    entries = sorted(lex["phrases"] + lex["words"],
                     key=lambda e: len(e["find"]), reverse=True)
    for entry in entries:
        pattern = i18n.lex_regex(entry["find"], pack)
        found = list(pattern.finditer(text))
        if not found:
            continue
        if entry["replace"] is None:
            flagged.append({"find": entry["find"], "count": len(found),
                            "family": entry["family"],
                            "seen": sorted({m.group(0).strip() for m in found})[:3]})
            continue
        hits.append({"find": entry["find"], "replace": entry["replace"] or "(deleted)",
                     "count": len(found), "family": entry["family"]})
        repl = entry["replace"]

        def sub(m, repl=repl):
            core = m.group(0)[len(m.group("pre")):]
            if not repl:
                return ""                      # drop a dangling و/ف with the phrase
            return m.group("pre") + _match_case(core, repl)

        text = pattern.sub(sub, text)
    text = _cleanup(text, punct=",.;:،؛", end="!?؟")
    return text, hits, flagged


def _pass_lexical_en(text, lex):
    """The original English pass, unchanged."""
    hits = []
    entries = sorted(lex["phrases"] + lex["words"],
                     key=lambda e: len(e["find"]), reverse=True)
    for entry in entries:
        find = entry["find"]
        pattern = re.compile(r"\b" + re.escape(find).replace(r"\ ", r"\s+") + r"\b",
                             re.IGNORECASE)
        found = pattern.findall(text)
        if not found:
            continue
        hits.append({"find": find, "replace": entry["replace"] or "(deleted)",
                     "count": len(found), "family": entry["family"]})
        text = pattern.sub(lambda m: _match_case(m.group(0), entry["replace"]), text)
    text = _cleanup(text)
    # An em dash that became a comma, followed by a sentence connective, leaves
    # a splice ("is important, also, it's proof"). Promote it to a full stop.
    text = re.sub(r",\s*(also|so|still|basically|in the end)\s*,\s*",
                  lambda m: ". " + m.group(1)[0].upper() + m.group(1)[1:] + ", ", text)
    return text, hits


def scan_structures(text, lex):
    pack = lex.get("_pack")
    sent_re = SENT_RE if pack is None else i18n.sentence_re(pack)
    flags = []
    for s in lex["structures"]:
        try:
            pattern = re.compile(s["regex"], re.MULTILINE)
        except re.error:
            continue
        found = pattern.findall(text)
        if found:
            flags.append({"name": s["name"], "count": len(found), "fix": s["fix"]})
    # Sentence-length uniformity is structural too.
    lens = [len(s.split()) for s in sent_re.findall(text) if len(s.split()) > 2]
    if len(lens) >= 4:
        mean = sum(lens) / len(lens)
        var = sum((n - mean) ** 2 for n in lens) / len(lens)
        cv = (var ** 0.5) / mean if mean else 0
        if cv < 0.35:
            flags.append({
                "name": f"Uniform sentence length (variation {cv:.2f})",
                "count": len(lens),
                "fix": "Break one sentence in half. Let another run long. Machines write even.",
            })
    return flags


def restore_capitals(original, text, pack=None):
    """Deleting an opener leaves the next word lower case.

    Only fix it for writers who capitalise their sentences in the first place:
    a deliberately lower-case voice is a style, not an artefact, and shouting
    over it would be exactly the kind of thing this script exists to stop.
    Scripts without capitals (Arabic) are left alone.
    """
    if pack is not None and not pack.get("cased", True):
        return text
    if pack is None:
        letter, lower = r"[A-Za-z]", r"[a-z]"
    else:
        letter, lower = r"[^\W\d_]", r"[^\W\d_]"
    starts = re.findall(r"(?:^|[.!?]\s+|\n)\s*(" + letter + r")", original)
    if not starts or sum(1 for c in starts if c.isupper()) * 2 < len(starts):
        return text

    def up(m):
        ch = m.group(1)
        if not ch.islower():
            return m.group(0)
        if pack is not None and pack.get("code") == "tr" and ch == "i":
            return m.group(0)[:-1] + "İ"
        return m.group(0)[:-1] + ch.upper()

    return re.sub(r"(?:^|(?<=[.!?] )|(?<=[.!?]\n)|(?<=\n))\s*(" + lower + r")", up, text)


def humanize(text, lex):
    pack = lex.get("_pack")
    raw_for_case = text
    text, urls = protect_urls(text)
    text, inv = pass_invisible(text, lex)
    text, typo = pass_typographic(text, lex)
    text, lexi, flagged = pass_lexical(text, lex)
    text = restore_capitals(raw_for_case, text, pack)
    text = restore_urls(text, urls)
    report = {
        "invisible": inv,
        "typographic": typo,
        "lexical": lexi,
        "structures": scan_structures(text, lex),
    }
    if pack is not None:
        report["flagged"] = flagged
        report["lang"] = pack["code"]
    return text.strip() + "\n", report


def render_report(report, out=sys.stderr):
    def head(title):
        print(f"\n{title}\n" + "-" * len(title), file=out)

    removed = [h for h in report["invisible"] if h["action"] != "kept"]
    kept = [h for h in report["invisible"] if h["action"] == "kept"]
    flagged = report.get("flagged", [])
    total = sum(h["count"] for h in removed) \
        + sum(h["count"] for h in report["typographic"]) \
        + sum(h["count"] for h in report["lexical"])

    head("HUMANIZE REPORT" + (f"  ·  {report['lang']}" if report.get("lang") else ""))
    print(f"{total} machine artefacts removed, "
          f"{len(report['structures'])} structural tells flagged for rewrite"
          + (f", {len(flagged)} stock words flagged" if flagged else ""), file=out)

    if removed:
        head("1. INVISIBLE CHARACTERS")
        for h in removed:
            print(f"  {h['count']:>3}x  {h['name']}  -> {h['action']}", file=out)
    if kept:
        head("1b. KEPT ON PURPOSE  (these are not watermarks)")
        for h in kept:
            print(f"  {h['count']:>3}x  {h['name']}", file=out)
    if report["typographic"]:
        head("2. TYPOGRAPHY")
        for h in report["typographic"]:
            print(f"  {h['count']:>3}x  {h['name']}  -> {h['to']}", file=out)
    if report["lexical"]:
        head("3. SLOP LEXICON")
        for h in report["lexical"]:
            print(f"  {h['count']:>3}x  {h['find']}  -> {h['replace']}   [{h['family']}]", file=out)
    if flagged:
        head("3b. STOCK WORDS LEFT IN PLACE  (rewrite these: the right form depends on the sentence)")
        for h in flagged:
            seen = ", ".join(h["seen"])
            print(f"  {h['count']:>3}x  {h['find']}   [{h['family']}]  seen: {seen}", file=out)
    if report["structures"]:
        head("4. STRUCTURAL TELLS  (not auto-fixed - rewrite these yourself)")
        for h in report["structures"]:
            print(f"  {h['count']:>3}x  {h['name']}\n        {h['fix']}", file=out)
    if not (removed or report["typographic"] or report["lexical"] or flagged or report["structures"]):
        head("CLEAN")
        print("  Nothing to strip.", file=out)
    print("", file=out)


def main():
    ap = argparse.ArgumentParser(description="Strip the machine fingerprint out of a draft.")
    ap.add_argument("input", nargs="?", default="-", help="file, or - for stdin")
    ap.add_argument("-o", "--out", help="write cleaned text here instead of stdout")
    ap.add_argument("--report", action="store_true", help="print what changed, to stderr")
    ap.add_argument("--json", action="store_true", help="emit {text, report} as JSON")
    ap.add_argument("--lexicon", default=LEX, help="path to slop.json")
    ap.add_argument("--lang", default="auto",
                    help="en, ar, ru, tr, pl, cs, or auto to detect (default)")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    pack = i18n.resolve(args.lang, raw) if i18n else None
    lex = load_lexicon(args.lexicon, pack)
    clean, report = humanize(raw, lex)

    if args.json:
        print(json.dumps({"text": clean, "report": report}, indent=2, ensure_ascii=False))
        return
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(clean)
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(clean)
    if args.report:
        render_report(report)


if __name__ == "__main__":
    main()
