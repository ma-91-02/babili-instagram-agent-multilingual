#!/usr/bin/env python3
"""
swipe.py - rank reels you collected by how far they beat their own account,
name the hook formula each one used, and write the swipe file.

The point of this script is one correction: raw views are not evidence. A
2,000,000-follower account doing 400,000 views had a quiet day. A 4,000-
follower account doing 400,000 views found something. This ranks on the
multiple over the account's own baseline, which is the only version of
"went viral" that tells you anything you can copy.

Input is a tab-separated file you fill in while you browse, one reel per row,
with a header line naming the columns:

    account   followers   median   views    hook
    @someone  48000       11000    412000   nobody tells you your first 30 flop

`median` is that account's typical recent views and is the better baseline.
If you only have `followers`, leave median out and the script says so.
`hook` is the first line of the reel, spoken or on screen, in their words.

Languages: every hook is detected on its own (or pass --lang), so one batch
can mix Arabic, Russian, Turkish, Polish, Czech and English reels. Formulas
are named with each language's own patterns from ../ig-lang/lang/<code>.json,
which cover the 16 most common formulas; a hook those do not cover comes back
unclassified rather than guessed.

Usage
  python3 swipe.py captured.tsv
  python3 swipe.py captured.tsv --out ~/.claude/instagram/swipe.md
  python3 swipe.py captured.tsv --lang ar
  python3 swipe.py captured.tsv --json
"""

import argparse
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORD_RE = re.compile(r"[A-Za-z0-9$%'’-]+")


def _sibling(skill):
    """skills/<skill>, or wherever a plugin host mounted it ('plugin:ig-reel')."""
    parent = os.path.dirname(HERE)
    dirs = [os.path.join(parent, skill)]
    try:
        dirs += [os.path.join(parent, d) for d in sorted(os.listdir(parent))
                 if d.endswith(skill) and d != skill]
    except OSError:
        pass
    for d in dirs:
        if os.path.isdir(d):
            return d
    return os.path.join(parent, skill)


REEL_DIR = _sibling("ig-reel")
HOOKS = os.path.join(REEL_DIR, "hooks.json")

try:                                              # optional: score the hooks too
    sys.path.insert(0, REEL_DIR)
    from hookscore import score as score_hook     # noqa: E402
    from hookscore import i18n                    # noqa: E402
except Exception:                                 # ig-viral copied on its own
    score_hook, i18n = None, None


def load_formulas(path, pack=None):
    """The 26 formulas, in classify order. For a non-English pack, each
    formula uses that language's pattern; formulas without one are skipped."""
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    by_id = {h["id"]: h for h in d["hooks"]}
    order = d.get("classify_order") or sorted(by_id)
    if pack is None:
        return [(by_id[i]["id"], by_id[i]["name"],
                 re.compile(by_id[i]["match"], re.IGNORECASE)) for i in order if i in by_id]
    local = pack.get("hook_match", {})
    return [(by_id[i]["id"], by_id[i]["name"],
             re.compile(local[str(i)], re.IGNORECASE)) for i in order
            if i in by_id and str(i) in local]


def classify(hook, formulas):
    if not formulas:
        return None, "unclassified"
    for fid, name, pattern in formulas:
        if pattern.search(hook):
            return fid, name
    return None, "unclassified"


def read_rows(path):
    raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    lines = [l for l in raw.splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not lines:
        return []
    head = [c.strip().lower() for c in lines[0].split("\t")]
    if "views" in head and "hook" in head:
        cols, body = head, lines[1:]
    else:
        cols, body = ["account", "followers", "views", "hook"], lines
    rows = []
    for line in body:
        cells = line.split("\t")
        if len(cells) < len(cols):
            cells += [""] * (len(cols) - len(cells))
        r = dict(zip(cols, [c.strip() for c in cells]))
        try:
            r["views"] = int(re.sub(r"[^\d]", "", r.get("views", "")) or 0)
        except ValueError:
            continue
        for k in ("followers", "median"):
            digits = re.sub(r"[^\d]", "", r.get(k, "") or "")
            r[k] = int(digits) if digits else None
        if r["views"] and r.get("hook"):
            rows.append(r)
    return rows


def analyse(rows, formulas, hooks_path=None, lang="auto"):
    """`formulas` is the English list. Hooks in another language are
    classified with that language's patterns, loaded once per language."""
    used_median = any(r.get("median") for r in rows)
    per_lang = {"en": formulas}
    for r in rows:
        base = r.get("median") or r.get("followers") or 0
        r["baseline"] = base
        r["outlier"] = round(r["views"] / base, 2) if base else None
        pack = i18n.resolve(lang, r["hook"]) if i18n else None
        code = pack["code"] if pack else "en"
        if code not in per_lang:
            per_lang[code] = load_formulas(hooks_path or HOOKS, pack)
        r["lang"] = code
        r["formula_id"], r["formula"] = classify(r["hook"], per_lang[code])
        r["words"] = (len(WORD_RE.findall(r["hook"])) if code == "en"
                      else len(i18n.words(r["hook"])))
        if score_hook:
            _, overall, verdict, _, _ = score_hook(r["hook"], lang)
            r["hook_score"], r["hook_verdict"] = round(overall, 1), verdict
        else:
            r["hook_score"], r["hook_verdict"] = None, None
    ranked = sorted(rows, key=lambda r: -(r["outlier"] or 0))
    third = max(1, len(ranked) // 3)
    top, bottom = ranked[:third], ranked[-third:]

    def med(items, key):
        vals = [i[key] for i in items if i.get(key) is not None]
        return round(statistics.median(vals), 1) if vals else None

    counts = {}
    for r in top:
        counts[r["formula"]] = counts.get(r["formula"], 0) + 1
    return {
        "baseline": "account median" if used_median else "follower count",
        "n": len(ranked),
        "accounts": len({r.get("account", "") for r in ranked}),
        "reels": ranked,
        "top_formulas": sorted(counts.items(), key=lambda kv: -kv[1]),
        "top_hook_score": med(top, "hook_score"),
        "bottom_hook_score": med(bottom, "hook_score"),
        "top_words": med(top, "words"),
        "bottom_words": med(bottom, "words"),
        "unclassified": sum(1 for r in ranked if r["formula"] == "unclassified"),
    }


def render(a, out=sys.stdout):
    head = (f"SWIPE FILE  ·  {a['n']} reels  ·  {a['accounts']} accounts  ·  "
            f"baseline: {a['baseline']}")
    print("\n" + head, file=out)
    print("=" * max(len(head), 78), file=out)
    for r in a["reels"]:
        mult = f"{r['outlier']:.1f}x" if r["outlier"] else "   ?"
        score = f"{r['hook_score']:.0f}" if r["hook_score"] is not None else " -"
        fid = f"#{r['formula_id']:<2}" if r["formula_id"] else "-  "
        tag = f" [{r['lang']}]" if r.get("lang", "en") != "en" else ""
        print(f"  {mult:>7}  hook {score:>3}  {fid} {r['formula'][:22]:<22} "
              f"{r.get('account', '')[:16]:<16} {r['views']:>9,}{tag}", file=out)
        print(f"           \"{r['hook'][:96]}\"", file=out)
    print("-" * max(len(head), 78), file=out)
    print("WHAT IS WORKING IN THIS BATCH", file=out)
    if a["top_formulas"]:
        print("  top third by outlier:  "
              + ", ".join(f"{n} x{c}" for n, c in a["top_formulas"][:4]), file=out)
    if a["top_hook_score"] is not None:
        print(f"  median hook score:     top {a['top_hook_score']:.0f}  "
              f"vs bottom {a['bottom_hook_score']:.0f}", file=out)
    print(f"  median hook length:    top {a['top_words']} words  "
          f"vs bottom {a['bottom_words']} words", file=out)
    print(f"  unclassified:          {a['unclassified']} of {a['n']}. Read those by hand, "
          "they are where a formula you do not have yet is hiding.", file=out)
    print("\n  A hand-collected batch is evidence, not proof. Twelve reels shows you "
          "nothing;\n  forty across six accounts shows you something. Collect more before "
          "you believe it.\n", file=out)


def to_markdown(a):
    lines = ["# Swipe file", "",
             f"{a['n']} reels across {a['accounts']} accounts. "
             f"Ranked by multiple over {a['baseline']}.", ""]
    for r in a["reels"]:
        mult = f"{r['outlier']:.1f}x" if r["outlier"] else "?"
        lines += [f"## {mult}  {r['formula']}  ({r.get('account', '')})",
                  f"- views: {r['views']:,}  baseline: {r['baseline']:,}",
                  f"- hook score: {r['hook_score']}  words: {r['words']}",
                  f"- hook: \"{r['hook']}\"", ""]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Rank collected reels by outlier multiple.")
    ap.add_argument("input", nargs="?", default="-", help="TSV file, or - for stdin")
    ap.add_argument("--hooks", default=HOOKS, help="path to ig-reel/hooks.json")
    ap.add_argument("--out", help="also write the swipe file as markdown here")
    ap.add_argument("--lang", default="auto",
                    help="en, ar, ru, tr, pl, cs, or auto to detect each hook (default)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = read_rows(args.input)
    if not rows:
        print("no usable rows. Need a tab-separated file with at least views and hook.",
              file=sys.stderr)
        sys.exit(2)
    formulas = load_formulas(args.hooks)
    a = analyse(rows, formulas, hooks_path=args.hooks, lang=args.lang)
    if not formulas:
        print("note: hooks.json not found, formulas not named. Pass --hooks.", file=sys.stderr)
    if score_hook is None:
        print("note: hookscore.py not importable, hook scores skipped.", file=sys.stderr)

    if args.json:
        print(json.dumps(a, indent=2, ensure_ascii=False))
    else:
        render(a)
    if args.out:
        path = os.path.expanduser(args.out)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(to_markdown(a))
        print(f"wrote {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
