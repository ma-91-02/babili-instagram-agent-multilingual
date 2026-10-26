#!/usr/bin/env python3
"""
i18n.py - language packs for the ig-* tools.

Every script in this pack was written against English text: words were
counted with an ASCII regex, names were found by their capital letter, and the
lexicon of stock phrases was English. On Arabic, Russian, Turkish, Polish or
Czech text that meant the scripts saw no words at all. This module is the
shared layer that fixes it.

What it gives the scripts:

  detect(text)           which supported language a text is in
  load(code)             the language pack for that code (lang/<code>.json)
  resolve(arg, text)     --lang if given, otherwise detect(text)
  words(text)            Unicode-aware word tokens, any script
  norm(s, pack)          normalised form for matching (Arabic letter variants,
                         Turkish dotted/dotless i, Russian yo)
  TermSet                fast "is this token one of these words or stems"
  propers(text, pack)    names and brands: capitalised words in cased
                         scripts, Latin-script tokens inside Arabic text
  numbers(text)          figures in any digit script, with currency or %
  sentence_re(pack)      sentence splitter that knows the pack's punctuation
  lex_regex(find, pack)  one lexicon entry as a compiled regex

English is the reference. When the pack is English, the scripts keep their
original code paths, so English behaviour is exactly what it was. The other
packs were drafted with Claude and checked against the examples in
tests/run_tests.py. They are first estimates, not measurements on a corpus,
and they have not yet been reviewed by native-speaker marketers.
If one is wrong for your market, edit lang/<code>.json - it is meant to be
yours.

No network, no dependencies, nothing uploaded. Standard library only.
"""

import json
import os
import re
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
LANG_DIR = os.path.join(HERE, "lang")
SUPPORTED = ("en", "ar", "ru", "tr", "pl", "cs")

# --------------------------------------------------------------------------
# Scripts and detection
# --------------------------------------------------------------------------

ARABIC_RE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
LATIN_RE = re.compile(r"[A-Za-zÀ-ɏ]")
RTL_RE = re.compile(r"[֐-ࣿיִ-﷿ﹰ-﻿]")

# Letters that only one of the Latin-script languages uses.
LATIN_MARKERS = {
    "tr": set("ğĞıİşŞ"),
    "pl": set("ąĄęĘłŁńŃśŚźŹżŻ"),
    "cs": set("ěĚřŘůŮďĎňŇťŤ"),
}
# Shared letters that still lean one way.
LATIN_LEANS = {
    "tr": set("çÇöÖüÜ"),
    "pl": set("óÓćĆ"),
    "cs": set("čČšŠžŽáÁéÉíÍúÚýÝ"),
}
# Short, frequent function words. They separate a Polish line without any
# diacritics from an English one.
STOP_HINTS = {
    "en": {"the", "and", "you", "your", "is", "are", "to", "of", "this", "that",
           "it", "for", "with", "my", "i", "what", "how", "why", "don't", "was"},
    "tr": {"ve", "bir", "bu", "için", "çok", "ile", "ama", "gibi", "daha", "ne",
           "nasıl", "neden", "değil", "var", "yok", "sen", "siz", "ben", "mi", "mı"},
    "pl": {"i", "w", "nie", "się", "jest", "to", "na", "że", "jak", "co", "czy",
           "ale", "do", "z", "ty", "masz", "dla", "tylko", "już", "jestem"},
    "cs": {"a", "v", "je", "se", "na", "že", "to", "jak", "co", "proč", "ale",
           "do", "z", "ty", "máš", "pro", "jen", "už", "jsem", "není"},
}


def detect(text):
    """Best guess at the language of `text`. Returns a code in SUPPORTED.

    Script first: enough Arabic letters means Arabic, enough Cyrillic means
    Russian. Inside Latin script, letters only one language uses win, then
    common function words. Anything undecided is English, which is also the
    honest answer for a mixed line with one borrowed word in it.
    """
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "en"
    n = len(letters)
    ar = len(ARABIC_RE.findall(text))
    cy = len(CYRILLIC_RE.findall(text))
    if ar / n >= 0.3:
        return "ar"
    if cy / n >= 0.3:
        return "ru"

    score = {"en": 0.0, "tr": 0.0, "pl": 0.0, "cs": 0.0}
    for code, marks in LATIN_MARKERS.items():
        score[code] += 3 * sum(1 for c in text if c in marks)
    for code, marks in LATIN_LEANS.items():
        score[code] += 1 * sum(1 for c in text if c in marks)
    toks = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)?", text.lower())
    for code, hints in STOP_HINTS.items():
        score[code] += 1.5 * sum(1 for t in toks if t in hints)
    best = max(score, key=score.get)
    return best if score[best] > 0 else "en"


# --------------------------------------------------------------------------
# Packs
# --------------------------------------------------------------------------

_cache = {}


def load(code):
    """Load lang/<code>.json. Unknown codes fall back to English."""
    code = (code or "en").lower().split("-")[0].split("_")[0]
    if code not in SUPPORTED:
        code = "en"
    if code in _cache:
        return _cache[code]
    path = os.path.join(LANG_DIR, code + ".json")
    with open(path, encoding="utf-8") as fh:
        pack = json.load(fh)
    pack["code"] = code
    pack["_terms"] = {}
    _cache[code] = pack
    return pack


def resolve(lang_arg, text):
    """--lang wins. 'auto', empty or None means detect from the text."""
    if lang_arg and lang_arg.lower() not in ("auto", ""):
        return load(lang_arg)
    return load(detect(text))


def is_english(pack):
    return pack is None or pack.get("code") == "en"


# --------------------------------------------------------------------------
# Normalising and tokens
# --------------------------------------------------------------------------

AR_MARKS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
WORD_RE = re.compile(
    r"[$€£₺₽]?[\wؐ-ًؚ-ٰٟۖ-ۭ'’\-]*[\wؐ-ًؚ-ٰٟۖ-ۭ%]"
)


def norm(s, pack):
    """Lower-case and fold the spelling variants people actually type.

    Arabic: drop short vowels and tatweel, alef forms to bare alef, alef
    maqsura to ya, ta marbuta to ha. Turkish: dotted and dotless I lower-case
    to the right letter. Russian: yo to ye.
    """
    code = pack.get("code") if pack else "en"
    if code == "ar":
        s = AR_MARKS.sub("", s)
        s = re.sub("[أإآٱ]", "ا", s)
        s = s.replace("ى", "ي").replace("ة", "ه")
    elif code == "tr":
        s = s.replace("I", "ı").replace("İ", "i")
    elif code == "ru":
        s = s.replace("ё", "е").replace("Ё", "Е")
    return s.lower()


def words(text):
    """Word tokens in any script. Keeps $18,000 and 30% whole."""
    return WORD_RE.findall(re.sub(r"(?<=\d)[,٬](?=\d)", "", text))


def forms(token, pack):
    """The normalised token, plus the forms with Arabic clitics removed.

    Arabic writes 'and', 'the', 'with', 'for' as prefixes on the next word,
    so 'والخسارة' has to be checkable as 'خسارة'.
    """
    t = norm(token.strip("'’-"), pack)
    out = [t]
    for pre in pack.get("clitics", []):
        p = norm(pre, pack)
        if t.startswith(p) and len(t) - len(p) >= 2:
            out.append(t[len(p):])
    return out


class TermSet:
    """Exact words plus stems. An entry ending in '*' matches by prefix, which
    is how one entry covers 'потерял', 'потеряла' and 'потеряли'."""

    def __init__(self, entries, pack):
        self.exact, self.stems = set(), []
        for e in entries or []:
            e = norm(e, pack)
            if e.endswith("*"):
                self.stems.append(e[:-1])
            else:
                self.exact.add(e)
        self.pack = pack

    def hit(self, token):
        for f in forms(token, self.pack):
            if f in self.exact:
                return True
            if any(f.startswith(s) and len(f) >= len(s) for s in self.stems):
                return True
        return False

    def phrase_hit(self, tokens):
        """Multi-word entries, checked against a token list."""
        joined = " ".join(norm(t, self.pack) for t in tokens)
        return any(" " in e and (" " + e + " ") in (" " + joined + " ") for e in self.exact)


def terms(pack, *path):
    """Cached TermSet for pack[path[0]][path[1]]..."""
    key = "/".join(path)
    cache = pack.setdefault("_terms", {})
    if key not in cache:
        node = pack
        for p in path:
            node = node.get(p, {}) if isinstance(node, dict) else {}
        cache[key] = TermSet(node if isinstance(node, list) else [], pack)
    return cache[key]


def suffix_hit(token, pack, suffixes, exceptions):
    """True if the token ends in one of `suffixes` and is not an exception."""
    if not suffixes:
        return False
    exc = {norm(e, pack) for e in exceptions or []}
    for f in forms(token, pack):
        if f in exc:
            continue
        for s in suffixes:
            s = norm(s, pack)
            if f.endswith(s) and len(f) >= len(s) + 2:
                return True
    return False


# --------------------------------------------------------------------------
# Concrete markers
# --------------------------------------------------------------------------

NUMBER_RE = re.compile(
    r"(?:[$€£₺₽]\s?)?\d[\d,٬.]*(?:\s?(?:%|٪))?|[%٪]\s?\d[\d,٬.]*"
)
LATIN_TOKEN_RE = re.compile(r"\b[A-Za-z][A-Za-z0-9&+.\-]{1,}\b")


def numbers(text):
    """Figures in any digit script: 18,000  ١٨٠٠٠  %80  30٪  $12."""
    return [m.strip() for m in NUMBER_RE.findall(text) if any(c.isdigit() for c in m)]


def propers(text, pack):
    """Names, brands and places.

    Cased scripts: a capitalised word of three letters or more that does not
    start a sentence. Arabic has no capitals, so inside Arabic text a word in
    Latin script counts instead: in a caption that is nearly always a brand or
    a product name (GRASS, Azelit, iPhone).
    """
    if not pack.get("cased", True):
        return [t for t in LATIN_TOKEN_RE.findall(text) if len(t) >= 2]
    ends = pack.get("sentence_end", ".!?")
    found = []
    for m in WORD_RE.finditer(text):
        w = m.group(0).strip("'’-$€£₺₽%")
        if len(w) < 3 or not w[0].isupper() or not any(c.islower() for c in w[1:]):
            continue
        before = text[:m.start()].rstrip()
        if not before or before[-1] in ends or before.endswith("\n"):
            continue
        found.append(w)
    return found


def spoken_number_hits(text, pack):
    ts = terms(pack, "numbers", "spoken")
    ms = terms(pack, "numbers", "money")
    return [w for w in words(text) if ts.hit(w) or ms.hit(w)]


def concrete(text, pack):
    """Every checkable thing in the text: figures, names, spoken numbers."""
    return numbers(text) + sorted(set(propers(text, pack))) + spoken_number_hits(text, pack)


# --------------------------------------------------------------------------
# Sentences and lexicon patterns
# --------------------------------------------------------------------------

def sentence_re(pack, newline=True):
    ends = re.escape(pack.get("sentence_end", ".!?"))
    nl = r"\n" if newline else ""
    return re.compile(r"[^" + ends + nl + r"]+[" + ends + r"]*")


def _ar_fuzzy(escaped):
    out = []
    for ch in escaped:
        if ch in "اأإآ":
            out.append("[اأإآ]")
        elif ch in "يى":
            out.append("[يى]")
        elif ch in "هة":
            out.append("[هة]")
        else:
            out.append(ch)
    return "".join(out)


def lex_regex(find, pack):
    """Compile one lexicon entry.

    Every pattern carries a named group `pre` so the caller can put back an
    Arabic 'and' (و), 'so' (ف) or article (ال) prefix it matched on. In the other languages
    `pre` is always empty. A trailing '*' means "and any ending", for languages
    where one word has a dozen forms.
    """
    star = find.endswith("*")
    core = find[:-1] if star else find
    esc = re.escape(core).replace(r"\ ", r"\s+")
    code = pack.get("code") if pack else "en"
    if code == "ar":
        esc = _ar_fuzzy(esc)
    elif code == "ru":
        esc = esc.replace("е", "[её]").replace("Е", "[ЕЁ]")
    if star:
        esc += r"\w*"
    if code == "ar":
        edge = r"\wـً-ٰٟ"
        return re.compile(r"(?<![" + edge + r"])(?P<pre>[وف]?(?:ال)?)" + esc + r"(?![" + edge + r"])",
                          re.IGNORECASE)
    return re.compile(r"(?P<pre>)\b" + esc + (r"\b" if not star else ""), re.IGNORECASE)


# --------------------------------------------------------------------------
# Locating sibling files when a plugin flattens the skill folders
# --------------------------------------------------------------------------

def find_sibling(here, skill, filename=None):
    """Path to a sibling skill folder (or a file in it), wherever the host put it.

    In a repo checkout the skills sit side by side as skills/ig-reel and
    skills/ig-lang. Some plugin hosts mount them as 'plugin:ig-reel' instead.
    Try the plain name first, then anything ending in the skill name.
    """
    parent = os.path.abspath(os.path.join(here, ".."))
    candidates = [os.path.join(parent, skill)]
    try:
        candidates += sorted(os.path.join(parent, d) for d in os.listdir(parent)
                             if d.endswith(skill) and d != skill)
    except OSError:
        pass
    for c in candidates:
        target = os.path.join(c, filename) if filename else c
        if os.path.exists(target):
            return target
    return None


# --------------------------------------------------------------------------
# Small helpers shared by humanize.py and detect.py
# --------------------------------------------------------------------------

def has_rtl(text):
    return bool(RTL_RE.search(text))


def native_typography(pack):
    """Characters that are correct house style in this language, so they are
    neither replaced nor counted as a machine tell (the Russian dash, Polish
    and Czech low-high quotes, guillemets)."""
    return set(pack.get("typography_native", [])) if pack else set()


def describe(pack):
    return f"{pack.get('name', pack.get('code'))} ({pack.get('code')})"


if __name__ == "__main__":
    import sys
    raw = sys.stdin.read() if len(sys.argv) < 2 else open(sys.argv[1], encoding="utf-8").read()
    p = load(detect(raw))
    print(describe(p))
    print("words:", len(words(raw)))
    print("concrete:", concrete(raw, p)[:12])
