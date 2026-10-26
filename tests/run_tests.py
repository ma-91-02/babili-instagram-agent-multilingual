#!/usr/bin/env python3
"""
run_tests.py - regression checks for every tool in every language.

    python3 tests/run_tests.py

Standard library only. Runs each script the way a user would (as a command,
with --json) and checks the parts that matter:

  - English output is the same as the upstream repo's README examples, so the
    multilingual layer did not move the numbers the original author measured.
  - Each of the five other languages is detected, scored, linted, cleaned and
    classified with its own rules.
  - Emoji, right-to-left direction marks and each language's own punctuation
    survive the humanizer.
  - Every regex in every language pack compiles.

Exit code 0 means everything passed.
"""

import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SK = os.path.join(ROOT, "skills")
sys.path.insert(0, os.path.join(SK, "ig-lang"))
import i18n  # noqa: E402

PASSED, FAILED = [], []


def check(name, cond, detail=""):
    (PASSED if cond else FAILED).append(name)
    if not cond:
        print(f"FAIL  {name}  {detail}")


def tool(script, text, *args, stdin=False):
    """Run a script on `text` and return (stdout, stderr, code)."""
    path = os.path.join(SK, script)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        tmp = fh.name
    try:
        p = subprocess.run([sys.executable, "-I", path, tmp, *args],
                           capture_output=True, text=True, encoding="utf-8")
        return p.stdout, p.stderr, p.returncode
    finally:
        os.unlink(tmp)


def js(script, text, *args):
    out, err, _ = tool(script, text, *args, "--json")
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        raise SystemExit(f"{script} did not return JSON:\n{out}\n{err}")


# --------------------------------------------------------------------------
# 1. Packs compile
# --------------------------------------------------------------------------
for code in i18n.SUPPORTED:
    p = i18n.load(code)
    rx = [d["regex"] for d in p.get("hook", {}).get("dealbreakers", [])]
    rx += [a["regex"] for a in p.get("caption", {}).get("asks", [])]
    rx += [s["regex"] for s in p.get("lexicon", {}).get("structures", [])]
    rx += list(p.get("hook_match", {}).values())
    bad = []
    for r in rx:
        try:
            re.compile(r, re.MULTILINE)
        except re.error as e:
            bad.append(f"{e}: {r[:60]}")
    for e in p.get("lexicon", {}).get("words", []) + p.get("lexicon", {}).get("phrases", []):
        i18n.lex_regex(e["find"], p)
    check(f"pack {code} compiles ({len(rx)} regexes)", not bad, "; ".join(bad))

# --------------------------------------------------------------------------
# 2. English parity with the upstream README
# --------------------------------------------------------------------------
en_hooks = [
    "Nobody tells you that your first 30 reels are supposed to flop",
    "I lost $18,000 because of one missing contract.",
    "Stop scrolling if you want to grow on Instagram in 2026 🔥",
    "Hey guys, today I wanted to talk about content strategy",
]
res = js("ig-reel/hookscore.py", "\n".join(en_hooks))
scores = {r["hook"]: r["score"] for r in res}
check("en hookscore parity 85.6", scores[en_hooks[0]] == 85.6, scores)
check("en hookscore parity 81.4", scores[en_hooks[1]] == 81.4, scores)
check("en hookscore parity 54.4", scores[en_hooks[2]] == 54.4, scores)
check("en hookscore parity 9.6", scores[en_hooks[3]] == 9.6, scores)
check("en rows carry no lang tag", all("lang" not in r for r in res))

cap = ("I lost $18,000 because of one missing clause in a contract, and the worst part is "
       "that I had read the thing twice before I signed it.\n\nComment CONTRACT and I'll "
       "send you the template.\n\n#freelance #contracts #agencyowner\n")
c = js("ig-caption/caption.py", cap)
st = {x["check"]: x["status"] for x in c["checks"]}
check("en caption first line warns at 125", st["FIRST LINE"] == "WARN")
check("en caption 3 hashtags", len(c["hashtags"]) == 3)
check("en caption one ask", c["asks"] == ["comment a keyword"], c["asks"])

h = js("ig-human/humanize.py", "In today's fast-paced world, this is a game-changer. Let's delve into it.\n")
check("en humanize lexicon still applies", "game-changer" not in h["text"] and "delve" not in h["text"], h["text"])

# --------------------------------------------------------------------------
# 3. Per-language behaviour
# --------------------------------------------------------------------------
L = {
    "ar": {
        "detect": "بقعة دهون على الطباخ من أسبوع؟ رشّة وحدة وتنمسح بدقيقة",
        "strong": "محد يكلك إن أغلب منظفات المطبخ تخرب الطباخ بعد 6 أشهر",
        "weak": "مرحبا يا جماعة اليوم راح نحچي عن التنظيف",
        "caption": "بقعة دهون على الطباخ؟ رشّة وحدة من GRASS وتنمسح بدقيقة.\nاكتب \"سعر\" بالتعليقات ونرسلك العرض.\n#تنظيف #مطبخ #العراق #بغداد #اكسبلور #ترند\n",
        "tags": 6, "ask": "comment a keyword",
        "slop": "في عالم اليوم المتسارع، أصبح التنظيف سهلاً. منظف GRASS ليس مجرد منظف، بل هو حل ثوري.\n",
        "gone": "في عالم اليوم المتسارع",
        "formula": ("محد يكلك إن المنظفات القوية تخرب الطباخ", 3),
    },
    "ru": {
        "detect": "Жирное пятно на плите неделю? Один пшик, и его нет",
        "strong": "Никто не говорит вам, что плита портится за 6 месяцев",
        "weak": "Всем привет, сегодня я расскажу про уборку",
        "caption": "Жирное пятно на плите? Один пшик GRASS — и через минуту его нет.\nНапишите «цена» в комментариях.\n#уборка #кухня #чистота\n",
        "tags": 3, "ask": "comment a keyword",
        "slop": "В современном мире уборка — это не просто рутина, а искусство.\n",
        "gone": "В современном мире",
        "formula": ("Никто не говорит вам, что губка портит плиту", 3),
    },
    "tr": {
        "detect": "Ocağın üstünde bir haftalık yağ lekesi mi var? Tek sıkım yeter",
        "strong": "Kimse size söylemiyor ama ocağınız 6 ayda bozuluyor",
        "weak": "Herkese merhaba, bugünkü videoda temizlikten bahsedeceğim",
        "caption": "Ocakta yağ lekesi mi var? GRASS ile 1 dakikada temiz.\nYorumlara \"fiyat\" yazın, teklifi gönderelim.\n#temizlik #mutfak #keşfet\n",
        "tags": 3, "ask": "comment a keyword",
        "slop": "Günümüzün hızla değişen dünyasında temizlik son derece önemli.\n",
        "gone": "Günümüzün hızla değişen dünyasında",
        "formula": ("Ocağınızı yanlış temizliyorsunuz", 7),
    },
    "pl": {
        "detect": "Tłusta plama na płycie od tygodnia? Jedno psiknięcie i jej nie ma",
        "strong": "Nikt ci nie mówi, że płyta psuje się po 6 miesiącach",
        "weak": "Cześć wszystkim, dzisiaj opowiem o sprzątaniu",
        "caption": "Tłusta plama na płycie? GRASS i po minucie jej nie ma.\nNapisz „cena” w komentarzu.\n#sprzątanie #kuchnia #dlaciebie\n",
        "tags": 3, "ask": "comment a keyword",
        "slop": "W dzisiejszym dynamicznym świecie sprzątanie to wyzwanie. „GRASS” działa w mgnieniu oka.\n",
        "gone": "W dzisiejszym dynamicznym świecie",
        "formula": ("Nie kupuj kolejnego płynu, zanim tego nie zobaczysz", 2),
    },
    "cs": {
        "detect": "Mastná skvrna na desce už týden? Jeden střik a je pryč",
        "strong": "Nikdo vám neřekne, že deska se zničí za 6 měsíců",
        "weak": "Ahoj všichni, dnes vám řeknu něco o úklidu",
        "caption": "Mastná skvrna na desce? GRASS a za minutu je pryč.\nNapište „cena“ do komentářů.\n#úklid #kuchyně #protebe\n",
        "tags": 3, "ask": "comment a keyword",
        "slop": "Stojí za zmínku, že „GRASS“ funguje bez námahy. Sledujte pro víc!\n",
        "gone": "Stojí za zmínku",
        "formula": ("Nejrychlejší způsob, jak vyčistit troubu", 26),
    },
}

for code, t in L.items():
    check(f"{code} detected", i18n.detect(t["detect"]) == code, i18n.detect(t["detect"]))

    rs = js("ig-reel/hookscore.py", t["strong"] + "\n" + t["weak"])
    by = {r["hook"]: r for r in rs}
    s_, w_ = by[t["strong"]], by[t["weak"]]
    check(f"{code} hook strong > weak", s_["score"] > w_["score"] + 40, (s_["score"], w_["score"]))
    check(f"{code} strong hook is STRONG", s_["verdict"] == "STRONG", s_)
    check(f"{code} weak hook flags greeting", any("Greeting" in f for f in w_["flags"]), w_["flags"])
    check(f"{code} weak hook flags preamble", any("preamble" in f for f in w_["flags"]), w_["flags"])
    check(f"{code} hook rows tagged", s_.get("lang") == code)

    c = js("ig-caption/caption.py", t["caption"])
    check(f"{code} caption counts local hashtags", len(c["hashtags"]) == t["tags"], c["hashtags"])
    check(f"{code} caption finds the ask", t["ask"] in c["asks"], c["asks"])
    check(f"{code} caption has something concrete",
          {x["check"]: x["status"] for x in c["checks"]}["HOOK IS CONCRETE"] == "PASS")

    h = js("ig-human/humanize.py", t["slop"])
    check(f"{code} humanize removes the stock opener", t["gone"].lower() not in h["text"].lower(), h["text"])
    check(f"{code} humanize reports its language", h["report"].get("lang") == code)

    d = js("ig-human/detect.py", t["slop"] * 6)
    check(f"{code} detect runs in its language", d.get("lang") == code, d.get("lang"))
    check(f"{code} detect sees the stock terms",
          not d["checks"]["SLOP DENSITY"]["detail"].startswith("0 stock"), d["checks"]["SLOP DENSITY"])

    hook, fid = t["formula"]
    tsv = "account\tfollowers\tmedian\tviews\thook\n@x\t10000\t2000\t50000\t" + hook + "\n"
    sw = js("ig-viral/swipe.py", tsv)
    check(f"{code} swipe names formula #{fid}", sw["reels"][0]["formula_id"] == fid, sw["reels"][0])

    b = js("ig-reel/beats.py", t["strong"] + "\n" + t["weak"] + "\n" + t["strong"])
    check(f"{code} beats uses the language rate", b["wpm"] == i18n.load(code)["wpm"], b["wpm"])
    check(f"{code} beats counts words", b["total_words"] > 10, b["total_words"])

# --------------------------------------------------------------------------
# 4. Things the humanizer must never break
# --------------------------------------------------------------------------
fam = "Our family \U0001F468‍\U0001F469‍\U0001F467 loves it ❤️‍\U0001F525\n"
h = js("ig-human/humanize.py", fam)
check("emoji ZWJ sequences survive (en)", "\U0001F468‍\U0001F469‍\U0001F467" in h["text"]
      and "❤️‍\U0001F525" in h["text"], repr(h["text"]))
h = js("ig-human/humanize.py", "عائلتنا \U0001F468‍\U0001F469‍\U0001F467 تحب GRASS‏ جداً\n")
check("emoji ZWJ survives (ar)", "‍" in h["text"])
check("RTL mark survives in Arabic", "‏" in h["text"], repr(h["text"]))
h = js("ig-human/humanize.py", "Hidden​text with a zero width space​ here.\n")
check("zero-width space still removed (en)", "​" not in h["text"])
h = js("ig-human/humanize.py", "Плита — это не роскошь. «Чистота» — это просто.\n")
check("Russian dash and guillemets kept", "—" in h["text"] and "«" in h["text"], h["text"])
h = js("ig-human/humanize.py", "To nie jest „magia”, tylko chemia. Płyta – czysta.\n")
check("Polish quotes and dash kept", "„" in h["text"] and "”" in h["text"] and "–" in h["text"], h["text"])
h = js("ig-human/humanize.py", "Není to „kouzlo“, je to chemie. Deska – čistá.\n")
check("Czech quotes kept", "„" in h["text"] and "“" in h["text"], h["text"])
h = js("ig-human/humanize.py", "This is great — and it works.\n")
check("English em dash still replaced", "—" not in h["text"], h["text"])

d = js("ig-human/detect.py", fam * 30)
check("emoji joiners not counted as fingerprint (en)",
      d["checks"]["FINGERPRINT"]["detail"].startswith("0 invisible"), d["checks"]["FINGERPRINT"])

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
