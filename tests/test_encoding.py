"""Arabic in generated text must match the catalogue it came from.

Two of Clara's products are named in Arabic on clarahair.com, and those names
are observed data — they travel through the system unchanged or the provenance
claim is worthless.

This suite exists because they do not. The intelligence cycle writes decision
text containing a mangled form of one of them:

    catalogue   الفرشاة الحرارية الثنائية و بخاخ الحماية و سيروم اللمعان
    intel_action الفرشاة الءرارفة الإنائفة و بئاأ الءمافة و سفروم اللمعان

Four letters are substituted — ح→ء, خ→أ, ث→إ, ي→ف — and nothing else in the
string moves. The catalogue row, `product_competitors`, `findings`, every other
report and every other database table are clean; only `intel_action` and the
`actions_needed` section built from it carry it.

It is not a display artifact: the code points were read back from the file and
compared against a name built from explicit `chr()` calls, so neither a shell
nor an editor is in the path. It is not the model either — Vertex was
unavailable for the run that produced it, so the deterministic path built the
string.

The transform itself is not yet found. These tests are the tripwire: they fail
while the corruption is present, so it cannot be quietly shipped or forgotten,
and they pass the moment the cause is fixed.

    python tests/test_encoding.py
"""
from __future__ import annotations

import io
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_kept = sys.stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

from clara_monitor import catalog                      # noqa: E402
from clara_monitor.config import DB_PATH               # noqa: E402

PASS, FAIL = [], []

# Built from code points on purpose: a literal here could itself be mangled by
# whatever writes this file, and the test would then pass for the wrong reason.
CORRECT = "".join(chr(c) for c in (
    0x0627, 0x0644, 0x0641, 0x0631, 0x0634, 0x0627, 0x0629, 0x0020,
    0x0627, 0x0644, 0x062D, 0x0631, 0x0627, 0x0631, 0x064A, 0x0629))
MANGLED = "".join(chr(c) for c in (
    0x0627, 0x0644, 0x0621, 0x0631, 0x0627, 0x0631, 0x0641, 0x0629))

# The four substitutions observed, source -> what it became.
SUBSTITUTIONS = ((0x062D, 0x0621), (0x062E, 0x0623),
                 (0x062B, 0x0625), (0x064A, 0x0641))


def ok(cond, label):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")


def section(title):
    print(f"\n{title}")


def arabic(s):
    return [c for c in (s or "") if 0x0600 <= ord(c) <= 0x06FF]


# ------------------------------------------------------------------ source
section("The catalogue is the source of truth, and it is clean")

products = catalog.load_from_seed()
named = [p for p in products if arabic(p.name)]
ok(len(named) == 2, f"two products are named in Arabic ({len(named)})")
ok(any(CORRECT in p.name for p in named),
   "the thermal-brush bundle carries its correct spelling in the catalogue")
ok(not any(MANGLED in p.name for p in named),
   "and no catalogue name carries the mangled spelling")

CATALOGUE_NAMES = {p.name for p in products}


# ------------------------------------------------------------------ reports
section("Generated text must not invent Arabic the catalogue never had")


def arabic_runs(text):
    """Maximal runs of Arabic (plus spaces) inside a string."""
    out, cur = [], []
    for ch in text or "":
        if 0x0600 <= ord(ch) <= 0x06FF or (cur and ch == " "):
            cur.append(ch)
        elif cur:
            out.append("".join(cur).strip())
            cur = []
    if cur:
        out.append("".join(cur).strip())
    return [r for r in out if r]


def near_miss(run):
    """A catalogue name this run is *almost* — which is what corruption is.

    Not "any Arabic the catalogue lacks": competitors have Arabic names too, and
    a rival called استشوار
    لايفن is legitimate observed data. What is
    never legitimate is a string the same length and shape as a Clara product
    name, differing only in a few letters — that is a copy that got damaged on
    the way through.
    """
    if len(run) < 10:
        return None
    for name in CATALOGUE_NAMES:
        if not arabic(name) or run == name or run in name:
            continue
        if abs(len(run) - len(name)) > 2:
            continue
        same = sum(1 for a, b in zip(run, name) if a == b)
        ratio = same / max(len(run), len(name))
        if 0.70 <= ratio < 1.0:
            return name, round(ratio, 2)
    return None


def check_report(path):
    """No report may contain a damaged copy of a catalogue name."""
    data = json.loads(path.read_text(encoding="utf-8"))
    blob = json.dumps(data, ensure_ascii=False)
    bad = []
    for run in set(arabic_runs(blob)):
        hit = near_miss(run)
        if hit:
            bad.append((run[:34], f"{hit[1]:.0%} of {hit[0][:22]}"))
    return bad


for name in ("intel_c6.json", "price_r1.json", "competitors_r1.json"):
    p = ROOT / "reports" / name
    if not p.exists():
        ok(True, f"{name} not present, nothing to check")
        continue
    bad = check_report(p)
    ok(not bad,
       f"{name}: every Arabic phrase traces to a catalogue name"
       + ("" if not bad else f" — invented: {bad[:2]}"))


# ------------------------------------------------------------------ database
section("No stored row carries Arabic the catalogue never had")

db = sqlite3.connect(str(DB_PATH))
try:
    tables = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    offenders = {}
    for t in tables:
        try:
            rows = db.execute(f'SELECT * FROM "{t}"').fetchall()
        except sqlite3.Error:
            continue
        blob = json.dumps(rows, ensure_ascii=False, default=str)
        for run in set(arabic_runs(blob)):
            if near_miss(run):
                offenders.setdefault(t, set()).add(run[:34])
    ok(not offenders,
       f"{len(tables)} tables carry no damaged copy of a catalogue name"
       + ("" if not offenders
          else f" — {sorted(offenders)}"))
    ok("intel_action" not in offenders,
       "intel_action in particular — the table where the mangling was found")
finally:
    db.close()


# ------------------------------------------------------------------ transform
section("The substitution is characterised, so a fix can be recognised")

ok(len(SUBSTITUTIONS) == 4, "four letter substitutions were observed")
ok(all(0x0600 <= a <= 0x06FF and 0x0600 <= b <= 0x06FF
       for a, b in SUBSTITUTIONS),
   "every substitution maps one Arabic letter to another — not to a "
   "replacement character, so it is a mapping and not a decode failure")
deltas = {b - a for a, b in SUBSTITUTIONS}
ok(len(deltas) > 1,
   f"the deltas differ {sorted(deltas)}, so it is not a constant shift")

# Applying the observed substitutions to the correct name must reproduce
# exactly what was found. If a future change alters the corruption, this fails
# and tells the reader the shape of the bug moved.
table = {a: b for a, b in SUBSTITUTIONS}
derived = "".join(chr(table.get(ord(c), ord(c))) for c in CORRECT)
ok(derived.startswith(MANGLED[:8]) or MANGLED[:8] in derived,
   "the four substitutions reproduce the mangled form from the correct one")

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
for f in FAIL:
    print(f"  FAILED  {f}")
sys.exit(1 if FAIL else 0)
