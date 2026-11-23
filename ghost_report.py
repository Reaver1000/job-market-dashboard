"""Ghost-job signals over the job market snapshots.

Three signals, in order of strength today:

1. STALE: a posting still live in the latest sweep whose posted date is old
   (60/90+ days). Best-effort: Greenhouse reports updated_at, so an old date can
   mean dormant. Stale + still live is the ghost-job signature.
2. PERPETUAL HIRERS: companies with the most stale postings live at once, and
   companies whose identical title repeats many times.
3. REPOST CANDIDATES: a URL seen in an early sweep, missing from a later one,
   and back again. Weak evidence until the series is continuous (the 2026-11-19
   and 2026-11-20 sweeps were not preserved); it is reported with that caveat.

Run: python ghost_report.py
"""
import csv
import glob
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DATE_RE = re.compile(r"jobs_snapshot_(\d{4}-\d{2}-\d{2})\.csv$")


def days_between(a, b):
    return (date.fromisoformat(a) - date.fromisoformat(b)).days


def load(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def norm(u):
    return re.sub(r"[?#].*$", "", (u or "")).rstrip("/").lower()


snaps = sorted((m.group(1), p) for p in glob.glob(os.path.join(DATA, "jobs_snapshot_*.csv"))
               for m in [DATE_RE.search(p)] if m)
latest_day, latest_path = snaps[-1]
rows = load(latest_path)
print("latest sweep: %s (%d rows)" % (latest_day, len(rows)))

# ---------------- 1. stale postings ----------------
aged = []
for r in rows:
    p = (r.get("posted") or "").strip()
    if re.match(r"\d{4}-\d{2}-\d{2}$", p):
        age = days_between(latest_day, p)
        if age >= 0:
            aged.append((age, r))

buckets = Counter()
for age, _ in aged:
    if age < 7:
        buckets["fresh (<7d)"] += 1
    elif age < 30:
        buckets["recent (7-30d)"] += 1
    elif age < 60:
        buckets["aging (30-60d)"] += 1
    elif age < 90:
        buckets["stale (60-90d)"] += 1
    else:
        buckets["ghost (90d+)"] += 1
undated = len(rows) - len(aged)

total = len(rows)
print("\n== age of live postings ==")
for k in ["fresh (<7d)", "recent (7-30d)", "aging (30-60d)", "stale (60-90d)", "ghost (90d+)"]:
    n = buckets[k]
    print("  %-18s %5d  (%.1f%%)" % (k, n, 100.0 * n / total))
print("  %-18s %5d  (%.1f%%)" % ("undated", undated, 100.0 * undated / total))

stale_n = buckets["stale (60-90d)"] + buckets["ghost (90d+)"]
print("  stale+ghost combined: %d (%.1f%%)" % (stale_n, 100.0 * stale_n / total))

# ---------------- 2. perpetual hirers ----------------
stale_by_company = Counter()
for age, r in aged:
    if age >= 90:
        stale_by_company[r.get("company", "")] += 1
print("\n== companies with most 90d+ postings still live ==")
for c, n in stale_by_company.most_common(12):
    print("  %-32s %d" % (c, n))

title_dup = Counter((r.get("company", ""), r.get("title", "")) for r in rows)
dupes = [(t, n) for t, n in title_dup.items() if n >= 5]
dupes.sort(key=lambda x: -x[1])
print("\n== identical title+company repeated 5+ times ==")
for (c, t), n in dupes[:8]:
    print("  %dx  %s @ %s" % (n, t[:60], c))

# oldest single ads still live
aged.sort(key=lambda x: -x[0])
print("\n== oldest ads still live ==")
for age, r in aged[:6]:
    print("  %4dd  %s @ %s" % (age, r.get("title", "")[:52], r.get("company", "")[:24]))

# ---------------- 2b. company-relative staleness ----------------
# (idea credited to the Aladdin job-agent builder in the comments of the ghost-jobs
# article: compare a posting's age to the median age of that company's own roles)
co_ages = {}
for age, r in aged:
    co_ages.setdefault(r.get("company", ""), []).append(age)

def median(v):
    s = sorted(v)
    return s[len(s) // 2] if s else None

medians = {c: median(a) for c, a in co_ages.items() if len(a) >= 5}
rel_stale = 0
rel_stale_co = {}
for age, r in aged:
    c = r.get("company", "")
    m = medians.get(c)
    if m is not None and age > 2 * m:
        rel_stale += 1
        rel_stale_co[c] = rel_stale_co.get(c, 0) + 1
print("\n== stale relative to their own company ==")
print("  companies with >=5 dated postings: %d" % len(medians))
print("  postings older than 2x their own company's median age: %d of %d dated (%.1f%%)" % (
    rel_stale, len(aged), 100.0 * rel_stale / max(1, len(aged))))
top_rel = sorted(rel_stale_co.items(), key=lambda x: -x[1])[:8]
for c, n in top_rel:
    print("  %-32s %d (median %dd)" % (c, n, medians.get(c, 0)))


if len(snaps) >= 3:
    presence = defaultdict(set)
    for day, p in snaps:
        for r in load(p):
            u = norm(r.get("url", ""))
            if u:
                presence[u].add(day)
    days = [d for d, _ in snaps]
    # seen in day1, missing in day2, back in day3 (the only gap pattern available
    # with 17/18/21; 19 and 20 were not preserved, so this is a LOWER bound)
    d1, d2, d3 = days[-3], days[-2], days[-1]
    repost = [u for u, s in presence.items() if d1 in s and d2 not in s and d3 in s]
    always = [u for u, s in presence.items() if len(s) == len(days)]
    print("\n== repost candidates (in %s, missing %s, back %s) ==" % (d1, d2, d3))
    print("  count: %d" % len(repost))
    print("  caveat: %s/%s sweeps were not preserved, so absence in one sweep is" % (days[1], days[2] if len(days) > 3 else "the middle"))
    print("  weak evidence (a source hiccup can drop a whole lane for a day).")
    print("\n== postings live in every preserved sweep ==")
    print("  count: %d of %d unique" % (len(always), len(presence)))

    # the strong ghost combo: live in all sweeps AND posted 60d+
    old_live = 0
    for u in always:
        r = next((x for x in rows if norm(x.get("url", "")) == u), None)
        if r and re.match(r"\d{4}-\d{2}-\d{2}$", (r.get("posted") or "").strip()):
            if days_between(latest_day, r["posted"].strip()) >= 60:
                old_live += 1
    print("  ...of those, posted 60d+ and still up: %d" % old_live)
