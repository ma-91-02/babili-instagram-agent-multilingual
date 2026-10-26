---
name: ig-lang
description: >-
  Language rules for every ig-* Instagram skill: Arabic (with Iraqi, Gulf,
  Levantine and Egyptian dialects), Russian, Turkish, Polish, Czech and
  English. Use whenever the Instagram work is not in English, when the user
  writes in one of these languages, asks which languages are supported, wants
  to set their language or dialect in voice.md, or wants a language added.
---

# ig-lang

The other twelve skills were written in English. This one says how to run
them in any of six languages without the result reading like a translation.
It also holds the shared code (`i18n.py`) and the language packs
(`lang/<code>.json`) that let the five Python tools count words, find names
and spot stock phrases in scripts other than Latin.

| code | language | default speaking rate | house style the tools keep |
|------|----------|-----------------------|----------------------------|
| en | English | 165 wpm | (reference: original behaviour) |
| ar | Arabic | 135 wpm | «» quotes, ، ؛ ؟, right-to-left marks |
| ru | Russian | 140 wpm | the dash (тире), «ёлочки» |
| tr | Turkish | 120 wpm | %80 written before the number |
| pl | Polish | 135 wpm | „…” quotes, the dash |
| cs | Czech | 140 wpm | „…“ quotes, the dash |

## 1. Decide the language before writing anything

In this order:

1. `language:` in `~/.claude/instagram/voice.md` (for example `ar-IQ`,
   `ru`, `tr`, `pl`, `cs`). That is the audience's language, and it wins.
2. Otherwise, the language the user wrote the request in.
3. Otherwise, ask once: "Which language and which market is this for?"

The language you talk to the user in and the language of the post can be
different. A user can ask in Arabic for a Polish caption. Answer in their
language, write the post in the post's language.

## 2. Write it native. Never translate the English template

The 26 hook formulas in `ig-reel/hooks.json` are shapes, not sentences. Take
the shape and say it the way a person in that market says it out loud.
"Nobody tells you" is:

- Iraqi: محد يكلك… · Gulf: محد يقول لك… · Levantine: ما حدا بيقلك… · Egyptian: محدش هيقولك…
- Russian: Никто вам не скажет… · Turkish: Kimse size söylemez… · Polish: Nikt ci nie powie… · Czech: Nikdo vám neřekne…

If a line only works because the English idiom works, drop the line. A Reel
is said out loud, and a calque is the fastest way to sound like a machine in
a language that is not English.

## 3. Dialect and register

**Arabic.** Spoken Reels go in the dialect of the audience (`ar-IQ` Iraqi,
`ar-SA`/`ar-AE` Gulf, `ar-LB`/`ar-SY` Levantine, `ar-EG` Egyptian), written
the way people type it, including چ and گ where the dialect uses them. Captions,
carousels and DMs can be dialect or plain Modern Standard Arabic, whichever
voice.md says the brand uses. Never mix the two inside one piece. Address:
use what voice.md says; if it says nothing, the plural (انتو / أنتم) speaks
to everyone without guessing anyone's gender.

**Russian.** Brands usually say «вы», lower-case. «Ты» only if voice.md says so.
**Turkish.** «Siz» for brands unless voice.md says «sen».
**Polish.** Brand accounts mostly use «ty» (informal). Follow voice.md.
**Czech.** «Vy» unless voice.md says the brand uses «ty».

Numbers: write them in the digits the audience types. In Iraq both 0-9 and
٠-٩ are read; follow voice.md, and keep one style per post. Prices in the
local currency (دينار، ₽, ₺, zł, Kč), written the local way.

## 4. Running the tools

Every script detects the language of what it is given. Pass `--lang` when
the text is very short or mixed:

```bash
python3 hookscore.py hooks.txt --lang ar
python3 beats.py script.txt --lang ru --target 30
python3 caption.py caption.txt --lang tr --keywords "temizlik,mutfak"
python3 humanize.py draft.txt --lang pl --report
python3 detect.py draft.txt --lang cs
python3 swipe.py captured.tsv            # each hook detected on its own
```

The reports print their labels in English. Read them, then tell the user what
they found in the user's language. Do not paste the English report at a user
who wrote to you in Arabic.

What the tools do differently outside English:

- Words, hashtags (#تنظيف, #уборка) and numbers in any script are counted.
- In Arabic, a brand written in Latin letters (GRASS, Azelit) counts as a
  name, because Arabic has no capitals to find names by.
- The humanizer keeps emoji joiners, Arabic direction marks and each
  language's correct punctuation. It does not convert the Russian dash or
  Polish quotes to English typography.
- In inflected languages many stock words are **flagged, not replaced**: the
  right replacement depends on case, gender and number in that sentence.
  Rewrite those by hand, the same way the structural tells are rewritten.

## 5. What is measured and what is not

The English thresholds come from the original author's test on 74 real
hooks. The Arabic, Russian, Turkish, Polish and Czech word lists and targets
(speaking rate, hook length, pronoun density) were drafted with Claude and
checked against examples in `tests/run_tests.py`. They were not measured on a
corpus of real Reels, and native-speaker marketers have not reviewed them yet. They catch greetings, preambles, stock phrases and
hooks with nothing concrete in them. Treat the numbers as a first pass, and
trust the retention graph over them. If a list is wrong for your market,
edit `lang/<code>.json`. It is meant to be yours.

## 6. Adding a language

Copy `lang/ru.json` (a cased language) or `lang/ar.json` (no capitals,
right-to-left) to `lang/<code>.json`, translate every list, add the code to
`SUPPORTED` and to the detection hints in `i18n.py`, then add a block for it
in `tests/run_tests.py` and run `python3 tests/run_tests.py` until it passes.
