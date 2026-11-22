"""Pay transparency across the employer boards: who tells you the money?

Scans the public ATS boards from the remote-job-engine watchlist and asks one
question of every posting: does the advert state actual pay, before you apply?

Three signals, counted separately:

1. STRUCTURED: Ashby exposes a compensation object when the employer filled it
   (Greenhouse's list endpoint carries no compensation at all; Lever and
   Workable showed none on the watchlisted boards).
2. TEXT: the description contains a money figure big enough to be a salary
   (10,000+ or the 50k form), in any of the common European and US formats,
   including German "50.000 - 60.000 EUR" style.
3. DODGE: the advert uses a phrase that names pay without stating it
   ("competitive salary", "market rate", "DOE", and friends).

An ad "discloses" if either structured or text fires. The rest split into
dodge-only and nothing-at-all. Junior and senior cuts use the same title
rules as junior_report.py, so the series stays comparable.

Run: python pay_report.py            (takes a few minutes, 16 workers)
Output: a report plus data/pay_transparency_YYYY-MM-DD.csv
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
SENIOR_RE = re.compile(r"senior|\bsr\.?\b|lead|principal|staff|head of|director|\bvp\b|chief", re.I)

DODGE_PATTERNS = {
    "competitive salary": r"competitive (?:salary|compensation|pay)",
    "market rate": r"market[ -]?(?:rate|competitive|leading)",
    "negotiable": r"salary (?:is )?negotiable|negotiable salary",
    "DOE": r"\bdoe\b|depending on experience",
    "commensurate": r"commensurate (?:with|upon)",
    "attractive salary": r"attractive (?:salary|compensation)",
}
DODGES = {name: re.compile(pat, re.I) for name, pat in DODGE_PATTERNS.items()}

# money figures: currency-symbol amounts >= 10,000, k-forms, German dot format
MONEY = re.compile(
    r"[$€£]\s?\d{2,3}[,.]\s?\d{3}(?:\s?[-–—to]+\s?[$€£]?\s?\d{2,3}[,.]\s?\d{3})?"
    r"|\d{2,3}[,.]\d{3}\s?(?:€|eur|euros?|£|gbp|usd|dollars?)"
    r"|[$€£]\s?\d{2,3}k(?:\s?[-–—to]+\s?[$€£]?\s?\d{2,3}k)?"
    r"|\d{2}\.000(?:\s?[-–—bis]+\s?\d{2}\.000)?\s?(?:€|eur|euro)",
    re.I,
)


def amount_ok(m):
    """True if the matched figure is big enough to plausibly be a salary."""
    nums = [int(n.replace(".", "").replace(",", "")) for n in re.findall(r"\d{2,3}", m)]
    ks = re.findall(r"\d{2,3}(?=k)", m, re.I)
    return any(n >= 10000 for n in nums) or any(int(k) * 1000 >= 10000 for k in ks)


def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</li>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = htmllib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def get_json(url, timeout=30, tries=5):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            last = e
            time.sleep(3)
    raise last


def provider_boards():
    data = get_json(BOARDS_URL)
    pairs = []
    for prov in ("greenhouse", "ashby", "lever", "workable"):
        for slug in data.get(prov, []):
            pairs.append((prov, slug))
    return pairs


def ashby_comp_string(comp):
    if not isinstance(comp, dict):
        return ""
    for key in ("scrapeableCompensationSalarySummary", "compensationTierSummary"):
        v = comp.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    tiers = comp.get("compensationTiers") or []
    if isinstance(tiers, list) and tiers:
        first = tiers[0]
        s = first.get("tierSummary") or ""
        if s:
            return s.strip()
    return ""


def fetch_board(prov, slug):
    """Return [(title, url, posted, description, structured)] or None on failure."""
    try:
        if prov == "greenhouse":
            data = get_json("https://boards-api.greenhouse.io/v1/boards/%s/jobs?content=true" % slug)
            return [(j.get("title") or "", j.get("absolute_url") or "",
                     str(j.get("updated_at") or "")[:10], strip_html(j.get("content") or ""), "")
                    for j in data.get("jobs", [])]
        if prov == "ashby":
            data = get_json("https://api.ashbyhq.com/posting-api/job-board/%s?includeCompensation=true" % slug)
            return [(j.get("title") or "", j.get("jobUrl") or "",
                     str(j.get("publishedAt") or "")[:10], strip_html(j.get("descriptionPlain") or ""),
                     ashby_comp_string(j.get("compensation")))
                    for j in data.get("jobs", [])]
        if prov == "lever":
            data = get_json("https://api.lever.co/v0/postings/%s?mode=json" % slug)
            out = []
            for j in (data if isinstance(data, list) else []):
                created = j.get("createdAt")
                posted = ""
                if created:
                    try:
                        posted = time.strftime("%Y-%m-%d", time.gmtime(int(created) / 1000))
                    except Exception:
                        pass
                out.append((j.get("text") or "", j.get("hostedUrl") or "",
                            posted, strip_html(j.get("descriptionPlain") or j.get("description") or ""), ""))
            return out
        data = get_json("https://apply.workable.com/api/v1/widget/accounts/%s?details=true" % slug)
        return [(j.get("title") or "", j.get("url") or "",
                 str(j.get("published_on") or "")[:10], strip_html(j.get("description") or ""), "")
                for j in data.get("jobs", [])]
    except Exception:
        return None


def bucket(has_struct, pay_texts, dodges):
    if has_struct or pay_texts:
        return "pay disclosed"
    if dodges:
        return "dodge only"
    return "no pay signal"


def main():
    boards = provider_boards()
    print("scanning %d boards for pay signals..." % len(boards))
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
            for title, url, posted, desc, structured in res:
                pay_texts = [m for m in MONEY.findall(desc or "") if amount_ok(m)]
                dodges = sorted(name for name, rx in DODGES.items() if rx.search(desc or ""))
                rows.append({
                    "title": title, "company": s, "provider": p, "url": url, "posted": posted,
                    "junior": 1 if JUNIOR_RE.search(title or "") else 0,
                    "senior": 1 if SENIOR_RE.search(title or "") else 0,
                    "structured_pay": structured[:120],
                    "pay_texts": "|".join(pay_texts)[:200],
                    "dodge_phrases": "|".join(dodges),
                    "bucket": bucket(structured, pay_texts, dodges),
                })
            if done % 100 == 0:
                print("  %d/%d boards, %d ads" % (done, len(boards), len(rows)))

    print("done: %d boards dead/failed quietly, %d ads collected" % (dead, len(rows)))
    if not rows:
        print("nothing to report")
        return

    total = len(rows)

    def pct(n):
        return 100.0 * n / total

    def report_line(label, subset):
        n = len(subset)
        if not n:
            print("  %-28s no ads" % label)
            return
        d = sum(1 for r in subset if r["bucket"] == "pay disclosed")
        g = sum(1 for r in subset if r["bucket"] == "dodge only")
        z = n - d - g
        print("  %-28s %5d ads | disclosed %5.1f%% | dodge-only %5.1f%% | nothing %5.1f%%" % (
            label, n, 100.0 * d / n, 100.0 * g / n, 100.0 * z / n))

    print("\n== pay transparency by group ==")
    report_line("all ads", rows)
    report_line("junior-titled", [r for r in rows if r["junior"]])
    report_line("senior-titled", [r for r in rows if r["senior"]])
    print("\n== by provider ==")
    for prov in ("greenhouse", "ashby", "lever", "workable"):
        report_line(prov, [r for r in rows if r["provider"] == prov])

    structured_n = sum(1 for r in rows if r["structured_pay"])
    print("\n== the structured signal ==")
    print("  ads with employer-filled structured pay: %d of %d (%.1f%%)" % (structured_n, total, pct(structured_n)))
    ash = [r for r in rows if r["provider"] == "ashby"]
    if ash:
        a = sum(1 for r in ash if r["structured_pay"])
        print("  ashby only: %d of %d (%.1f%%)" % (a, len(ash), 100.0 * a / len(ash)))

    cur = {"EUR": 0, "USD": 0, "GBP": 0}
    for r in rows:
        blob = (r["structured_pay"] + " " + r["pay_texts"]).lower()
        if "€" in blob or "eur" in blob:
            cur["EUR"] += 1
        if "$" in blob or "usd" in blob:
            cur["USD"] += 1
        if "£" in blob or "gbp" in blob:
            cur["GBP"] += 1
    disclosed = sum(1 for r in rows if r["bucket"] == "pay disclosed")
    print("\n== currencies among disclosed ads ==")
    for k, n in sorted(cur.items(), key=lambda x: -x[1]):
        if n:
            print("  %s: %d ads" % (k, n))

    print("\n== dodge phrases, all ads ==")
    for name, rx in DODGES.items():
        n = sum(1 for r in rows if name in r["dodge_phrases"])
        if n:
            print("  %-22s %4d ads (%.1f%%)" % (name, n, pct(n)))

    print("\n== sample disclosures ==")
    for r in [r for r in rows if r["bucket"] == "pay disclosed"][:6]:
        ev = r["structured_pay"] or r["pay_texts"]
        print("  %-46s @ %-14s %s" % (r["title"][:46], r["company"][:14], ev[:70]))

    out = os.path.join(DATA, "pay_transparency_%s.csv" % date.today().isoformat())
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("\nwrote %s" % out)


if __name__ == "__main__":
    main()
