"""The application funnel: why finding a remote junior role is hard, in numbers.

Takes the current snapshot (data/latest.csv) and narrows it the way a real
job search does, stage by stage:

  live postings
    -> junior-titled (junior / graduate / entry in the title)
    -> and remote
    -> and in a region a Germany/UK-based applicant can work
       (Germany, UK, Europe, EMEA, or genuinely-anywhere remote)
    -> and fresh (posted within 7 days, where a date is known)

Also counts the keyword blind spot (titles like "new grad" or "early careers"
that the junior filter misses) and writes the final pool to
data/apply_pool_YYYY-MM-DD.csv.

Region rules mirror web/app.js with one refinement: a bare "US" token in a
location string counts as United States, so "Remote - US" no longer lands in
the unspecified bucket. The refinement is stated here because it changes the
eligible pool.
"""
import csv
import os
import re
import sys
from datetime import date, datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
LATEST = os.path.join(HERE, "data", "latest.csv")

JUNIOR_RE = re.compile(r"junior|graduate|entry", re.I)
EXTRA_JR_RE = re.compile(r"early career|new grad|university grad|studenten|praktikant|trainee|apprentice", re.I)

REGION_RULES = [
    ("United States", r"united states|\busa\b|u\.s\.|\bus\b|\bamerica\b|new york|san francisco|los angeles|chicago|boston|austin|seattle|denver|atlanta|dallas|miami|philadelphia|phoenix|houston|washington"),
    ("Canada", r"canada|toronto|vancouver|montreal|ottawa|calgary"),
    ("United Kingdom", r"united kingdom|\buk\b|\bengland\b|scotland|wales|london|manchester|birmingham|\bleeds\b|bristol|edinburgh|glasgow"),
    ("Germany", r"germany|deutschland|berlin|munich|münchen|hamburg|frankfurt|cologne|köln|leipzig|stuttgart|düsseldorf|dusseldorf|dresden|nuremberg|heidelberg"),
    ("Europe (other)", r"france|paris|netherlands|amsterdam|spain|madrid|barcelona|italy|milan|rome|poland|warsaw|ireland|dublin|austria|vienna|switzerland|zurich|belgium|brussels|sweden|stockholm|denmark|copenhagen|finland|helsinki|norway|oslo|portugal|lisbon|czech|prague|\beurope\b"),
    ("EMEA", r"emea"),
    ("APAC", r"apac|asia|singapore|japan|tokyo|india|australia|sydney|china|beijing|shanghai|hong kong|korea|taiwan|new zealand|vietnam|thailand|indonesia|philippines|malaysia"),
    ("LATAM", r"latam|brazil|mexico|argentina|colombia|chile|peru"),
    ("Africa", r"africa|nigeria|kenya|egypt|ghana"),
]
ELIGIBLE = {"Germany", "United Kingdom", "Europe (other)", "EMEA", "Remote (unspecified)"}


def region_of(loc):
    s = " %s " % str(loc or "").lower()
    for label, pattern in REGION_RULES:
        if re.search(pattern, s):
            return label
    if re.search(r"remote|anywhere|worldwide|global", s):
        return "Remote (unspecified)"
    return "Unrecognised"


def sanity_checks(rows):
    """Fail loudly on the two failure classes from 2026-11-21/26:
    date parsing coverage, and forced remote flags that the lane's own text
    does not support (the LinkedIn f_WT lesson)."""
    dated = sum(1 for r in rows if (r.get("posted") or "").strip())
    cov = dated / max(1, len(rows))
    assert cov >= 0.95, "dated coverage regressed: %.1f%% of rows carry a date" % (100 * cov)

    lanes = {}
    for r in rows:
        s = r.get("source") or ""
        g = "ats" if s.startswith("ats_") else "linkedin" if s.startswith("linkedin_") else "freehire" if s.startswith("freehire_") else "other"
        v = lanes.setdefault(g, {"n": 0, "remote": 0, "text": 0})
        v["n"] += 1
        if str(r.get("remote")) == "1":
            v["remote"] += 1
        blob = ((r.get("title") or "") + " " + (r.get("location") or "")).lower()
        if "remote" in blob:
            v["text"] += 1
    for g, v in lanes.items():
        if v["n"] < 200:
            continue
        rshare = v["remote"] / v["n"]
        tshare = v["text"] / v["n"]
        if rshare > 0.6 and tshare < 0.1:
            raise AssertionError(
                "lane group %r flags %.0f%% remote while only %.0f%% of its text says remote - forced flags without evidence"
                % (g, 100 * rshare, 100 * tshare))
    print("sanity checks pass: dated %.1f%%, %d lane groups verified (flags backed by text evidence)"
          % (100 * cov, len(lanes)))


def main():
    rows = list(csv.DictReader(open(LATEST, encoding="utf-8", newline="")))
    sanity_checks(rows)
    total = len(rows)
    print("live postings: %d" % total)

    # refine: how many 'Remote - US' style locations exist (the mislabel the
    # dashboard's looser rule hides)
    us_remote = sum(1 for r in rows if re.search(r"remote.*\bus\b|\bus\b.*remote", (r.get("location") or "").lower()))
    print("locations reading 'Remote - US' style: %d (excluded from eligibility via the bare-US rule)" % us_remote)

    dated = [r for r in rows if re.match(r"\d{4}-\d{2}-\d{2}$", (r.get("posted") or "").strip())]
    print("with a posting date: %d (%.0f%%)" % (len(dated), 100.0 * len(dated) / total))

    jr = [r for r in rows if JUNIOR_RE.search(r.get("title") or "")]
    print("\nstage 1: junior-titled            %5d  (%.2f%%)" % (len(jr), 100.0 * len(jr) / total))

    jrr = [r for r in jr if str(r.get("remote")) == "1"]
    print("stage 2: and remote                %5d  (%.2f%% of total)" % (len(jrr), 100.0 * len(jrr) / total))

    for r in rows:
        r["_region"] = region_of(r.get("location"))
    jre = [r for r in jrr if r["_region"] in ELIGIBLE]
    print("stage 3: and eligible region      %5d" % len(jre))
    regions = {}
    for r in jre:
        regions[r["_region"]] = regions.get(r["_region"], 0) + 1
    for k, n in sorted(regions.items(), key=lambda x: -x[1]):
        print("          %-22s %d" % (k, n))

    today = date.today()
    fresh = []
    undated_pool = []
    for r in jre:
        p = (r.get("posted") or "").strip()
        if re.match(r"\d{4}-\d{2}-\d{2}$", p):
            age = (today - datetime.strptime(p, "%Y-%m-%d").date()).days
            if age <= 7:
                fresh.append(r)
        else:
            undated_pool.append(r)
    print("stage 4: and fresh (<=7d, dated)  %5d" % len(fresh))
    print("          undated in pool: %d (freshness unverifiable)" % len(undated_pool))

    pool = fresh + undated_pool
    print("\napply-able pool today: %d ads (%s dated-fresh + %s undated)" % (
        len(pool), len(fresh), len(undated_pool)))

    print("\n== the pool ==")
    for r in pool[:20]:
        print("  %-52s @ %-16s [%s] %s" % (
            (r.get("title") or "")[:52], (r.get("company") or "")[:16],
            r["_region"], (r.get("posted") or "no date")[:10]))

    # keyword blind spot: titles that a 'junior' filter misses
    extra = [r for r in rows if EXTRA_JR_RE.search(r.get("title") or "")
             and not JUNIOR_RE.search(r.get("title") or "")]
    extra_remote = [r for r in extra if str(r.get("remote")) == "1" and region_of(r.get("location")) in ELIGIBLE]
    print("\nkeyword blind spot: %d ads use phrasing like new grad / early careers / trainee "
          "without junior-graduate-entry in the title" % len(extra))
    print("  of those, remote and eligible: %d" % len(extra_remote))
    for r in extra_remote[:10]:
        print("    %-52s @ %s" % ((r.get("title") or "")[:52], (r.get("company") or "")[:18]))

    out = os.path.join(HERE, "data", "apply_pool_%s.csv" % today.isoformat())
    fields = ["title", "company", "location", "remote", "posted", "source", "url", "region", "freshness"]
    for r in pool:
        r["freshness"] = "fresh" if r in fresh else "undated"
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(pool)
    print("\nwrote %s" % out)


if __name__ == "__main__":
    main()
