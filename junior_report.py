"""Junior-titled ads versus the experience they actually demand.

Scans the public ATS boards from the remote-job-engine watchlist (Greenhouse,
Ashby, Lever, Workable; no keys required), keeps postings whose TITLE says
junior, graduate or entry, and parses the description for years-of-experience
requirements. The answer to "how many supposedly junior roles want senior
people" is then a count, not a vibe.

Extraction rules, deliberately conservative:

- Only "X years" mentions tied to experience count: "5+ years of experience",
  "experience: 3 years", "minimum of 4 years", "at least two years".
- Ranges count at their top end ("3-5 years" scores 5): the bar to clear is
  the top of the stated range.
- When several requirements are stated, the MAXIMUM wins: a posting asking
  for both "2 years" and "7 years" is scored 7.
- Numbers written as words (one..twelve) are understood.
- "No stated bar" is reported as its own bucket. Plenty of genuinely junior
  ads never state a number, so that bucket is not assumed to be hostile.

Run: python junior_report.py            (takes a few minutes, 16 workers)
Output: a report plus data/junior_ads_YYYY-MM-DD.csv
"""
import csv
import html as htmllib
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BOARDS_URL = "https://raw.githubusercontent.com/Reaver1000/remote-job-engine/master/pipeline/boards.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

JUNIOR_RE = re.compile(r"junior|graduate|entry", re.I)
WORDS = {w: n for n, w in enumerate(
    ["one", "two", "three", "four", "five", "six", "seven", "eight",
     "nine", "ten", "eleven", "twelve"], start=1)}
NUM = r"(\d{1,2}|%s)\s*\+?" % "|".join(WORDS)
CONTEXT = re.compile(
    r"(?:minimum(?:\s+of)?|at\s+least)\s+" + NUM + r"\s*years|"
    + NUM + r"\s*(?:-\s*" + NUM + r"\s*)?years?(?:'|’s)?\s+(?:of\s+)?(?:relevant\s+|professional\s+|prior\s+|work(?:ing)?\s+|hands-on\s+)?experience|"
    + r"experience(?:\s*[:\-])?\s*(?:of\s+|with\s+)?(?:at\s+least\s+|minimum(?:\s+of)?\s*)?" + NUM + r"\s*years|"
    + NUM + r"\s*\+?\s*yrs?\b(?=\W|$)",
    re.I,
)


def word_to_int(w):
    w = (w or "").strip().lower()
    if w.isdigit():
        return int(w)
    return WORDS.get(w)


def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</li>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = htmllib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def provider_boards():
    data = get_json(BOARDS_URL)
    pairs = []
    for prov in ("greenhouse", "ashby", "lever", "workable"):
        for slug in data.get(prov, []):
            pairs.append((prov, slug))
    return pairs


def fetch_board(prov, slug):
    """Return a list of (title, url, posted, description) for junior-titled jobs."""
    try:
        if prov == "greenhouse":
            data = get_json("https://boards-api.greenhouse.io/v1/boards/%s/jobs?content=true" % slug)
            raw = [(j.get("title") or "", j.get("absolute_url") or "",
                    str(j.get("updated_at") or "")[:10], j.get("content") or "")
                   for j in data.get("jobs", [])]
        elif prov == "ashby":
            data = get_json("https://api.ashbyhq.com/posting-api/job-board/%s" % slug)
            raw = [(j.get("title") or "", j.get("jobUrl") or "",
                    str(j.get("publishedAt") or "")[:10], j.get("descriptionPlain") or "")
                   for j in data.get("jobs", [])]
        elif prov == "lever":
            data = get_json("https://api.lever.co/v0/postings/%s?mode=json" % slug)
            raw = []
            for j in (data if isinstance(data, list) else []):
                created = j.get("createdAt")
                posted = ""
                if created:
                    try:
                        posted = time.strftime("%Y-%m-%d", time.gmtime(int(created) / 1000))
                    except Exception:
                        pass
                raw.append((j.get("text") or "", j.get("hostedUrl") or "",
                            posted, j.get("descriptionPlain") or j.get("description") or ""))
        else:  # workable
            data = get_json("https://apply.workable.com/api/v1/widget/accounts/%s?details=true" % slug)
            raw = [(j.get("title") or "", j.get("url") or "",
                    str(j.get("published_on") or "")[:10], j.get("description") or "")
                   for j in data.get("jobs", [])]

        out = []
        for title, url, posted, desc in raw:
            if JUNIOR_RE.search(title or ""):
                out.append((title, url, posted, strip_html(desc)))
        return out
    except Exception:
        return None  # dead slug or hiccup; fail quietly like the daily scan


def years_required(text):
    best = None
    snippet = ""
    for m in CONTEXT.finditer(text or ""):
        nums = [word_to_int(g) for g in m.groups() if g]
        nums = [n for n in nums if n is not None]
        if not nums:
            continue
        top = max(nums)
        if best is None or top > best:
            best = top
            i = max(0, m.start() - 60)
            snippet = text[i:m.end() + 60].strip()
    return best, snippet


def bucket(y):
    if y is None:
        return "no stated bar"
    if y <= 2:
        return "actually junior (0-2y)"
    if y <= 5:
        return "junior badge, mid-level bar (3-5y)"
    return "not junior in any sense (6y+)"


def main():
    boards = provider_boards()
    print("scanning %d boards (greenhouse/ashby/lever/workable)..." % len(boards))
    rows = []
    dead = 0
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = {ex.submit(fetch_board, p, s): (p, s) for p, s in boards}
        done = 0
        for f in as_completed(futs):
            p, s = futs[f]
            res = f.result()
            done += 1
            if res is None:
                dead += 1
                continue
            for title, url, posted, desc in res:
                y, snip = years_required(desc)
                rows.append({
                    "title": title, "company": s, "provider": p, "url": url,
                    "posted": posted, "years_required": "" if y is None else y,
                    "bucket": bucket(y), "requirement_snippet": snip[:220],
                })
            if done % 100 == 0:
                print("  %d/%d boards, %d junior ads so far" % (done, len(boards), len(rows)))

    print("done: %d boards dead/failed quietly, %d junior-titled ads collected" % (dead, len(rows)))
    if not rows:
        print("no junior ads found; nothing to report")
        return

    counts = {}
    for r in rows:
        counts[r["bucket"]] = counts.get(r["bucket"], 0) + 1
    total = len(rows)
    order = ["no stated bar", "actually junior (0-2y)",
             "junior badge, mid-level bar (3-5y)", "not junior in any sense (6y+)"]
    print("\n== the junior reality check ==")
    for k in order:
        n = counts.get(k, 0)
        print("  %-38s %4d  (%.1f%%)" % (k, n, 100.0 * n / total))

    stated = [int(r["years_required"]) for r in rows if r["years_required"] != ""]
    hostile = counts.get("junior badge, mid-level bar (3-5y)", 0) + counts.get("not junior in any sense (6y+)", 0)
    print("\n  ads that name a bar of 3+ years: %d of %d (%.1f%%)" % (hostile, total, 100.0 * hostile / total))
    if stated:
        stated.sort()
        print("  median stated bar: %d years | max: %d years" % (
            stated[len(stated) // 2], stated[-1]))

    print("\n== worst offenders (junior title, biggest demand) ==")
    bad = sorted((r for r in rows if r["years_required"] != "" and int(r["years_required"]) >= 6),
                 key=lambda r: -int(r["years_required"]))
    for r in bad[:15]:
        print("  %2dy  %-46s @ %s" % (int(r["years_required"]), r["title"][:46], r["company"]))
    if not bad:
        print("  none found this sweep")

    out = os.path.join(DATA, "junior_ads_%s.csv" % date.today().isoformat())
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("\nwrote %s" % out)


if __name__ == "__main__":
    main()
