"""Build the job market snapshot CSV from today's sweeps for the BI dashboard."""

import csv
import re

rows = []
seen = set()


def norm_url(u):
    return re.sub(r"[?#].*$", "", (u or "")).rstrip("/").lower()


def add(title, company, location, url, source, posted=""):
    url = norm_url(url)
    if not url or url in seen or not title:
        return
    seen.add(url)
    rows.append(
        {
            "title": re.sub(r"\s+", " ", title).strip(),
            "company": re.sub(r"\s+", " ", company).strip(),
            "location": re.sub(r"\s+", " ", location).strip(),
            "remote": 1 if re.search(r"remote|home ?office|anywhere", ((title or "") + " " + (location or "")), re.I) else 0,
            "posted": (posted or "")[:10],
            "url": url,
            "source": source,
        }
    )


# ATS plugin layer
text = open("ats_jobs.md", encoding="utf-8").read()
for b in re.split(r"\n### ", text)[1:]:
    lines = b.split("\n")
    m = re.match(r"(.*?) @ (.*)$", lines[0].strip())
    if not m:
        continue
    d = {}
    for l in lines[1:]:
        if l.startswith("- "):
            k, _, v = l[2:].partition(": ")
            d[k.strip()] = v.strip()
    src = d.get("src", "ats")
    provider = src.split(":")[1] if src.startswith("ats:") else src
    add(m.group(1), m.group(2), d.get("loc", ""), d.get("url", ""), "ats_" + provider, posted=d.get("posted", ""))

# freehire
text = open("freehire_jobs.md", encoding="utf-8").read()
for b in re.split(r"\n### ", text)[1:]:
    lines = b.split("\n")
    m = re.match(r"(.*?) @ (.*)$", lines[0].strip())
    if not m:
        continue
    d = {}
    for l in lines[1:]:
        if l.startswith("- "):
            k, _, v = l[2:].partition(": ")
            d[k.strip()] = v.strip()
    src = d.get("src", "freehire")
    origin = src.split(":")[1] if ":" in src else src
    add(m.group(1), m.group(2), d.get("loc", ""), d.get("url", ""), "freehire_" + origin, posted=d.get("posted", ""))

# UK linkedin lane
text = open("uk_remote_jobs.md", encoding="utf-8").read()
for b in re.split(r"\n### ", text)[1:]:
    lines = b.split("\n")
    m = re.match(r"(.*?) @ (.*)$", lines[0].strip())
    if not m:
        continue
    d = {}
    for l in lines[1:]:
        if l.startswith("- "):
            k, _, v = l[2:].partition(": ")
            d[k.strip()] = v.strip()
    add(m.group(1), m.group(2), d.get("loc", ""), d.get("url", ""), "linkedin_uk", posted=d.get("posted", ""))

# German linkedin sweep
text = open("linkedin_jobs.md", encoding="utf-8").read()
for b in re.split(r"\n### ", text)[1:]:
    lines = b.split("\n")
    m = re.match(r"(.*?) @ (.*)$", lines[0].strip())
    if not m:
        continue
    d = {}
    for l in lines[1:]:
        if l.startswith("- "):
            k, _, v = l[2:].partition(": ")
            d[k.strip()] = v.strip()
    add(m.group(1), m.group(2), d.get("loc", ""), d.get("url", ""), "linkedin_de", posted=d.get("posted", ""))

out = "data/jobs_snapshot.csv"
import os

os.makedirs("data", exist_ok=True)
with open(out, "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["title", "company", "location", "remote", "posted", "source", "url"])
    w.writeheader()
    for r in rows:
        w.writerow(r)

print(f"{len(rows)} rows written to {out} from {len(set(r['source'] for r in rows))} sources")
