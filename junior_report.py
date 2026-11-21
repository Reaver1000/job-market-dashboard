"""Junior-titled ads versus the experience and technology they demand.

Scans the public ATS boards from the remote-job-engine watchlist (Greenhouse,
Ashby, Lever, Workable; no keys required) and parses every posting for
years-of-experience bars and technology mentions. Junior-titled ads are kept in
full; senior-titled and all other ads are counted for comparison so the numbers
answer the real question: are juniors being asked for more than seniors?

Extraction rules, deliberately conservative:

YEARS
- Only "X years" mentions tied to experience count: "5+ years of experience",
  "experience: 3 years", "minimum of 4 years", "at least two years".
- Ranges count at their top end ("3-5 years" scores 5).
- When several requirements are stated, the MAXIMUM wins.
- Numbers written as words (one..twelve) are understood.

TECHNOLOGY
- Mentions, not requirements: a technology named anywhere in the ad counts.
  The same rule is applied to juniors and seniors, so comparisons are fair.
- The lexicon is public below, best-effort word-boundary matching. Two famously
  ambiguous languages (bare C, bare R) are skipped rather than miscounted;
  "Go" only counts as golang or "with/in/using Go".

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
SENIOR_RE = re.compile(r"senior|\bsr\.?\b|lead|principal|staff|head of|director|\bvp\b|chief", re.I)

# ---------------- technology lexicon ----------------
SKILL_PATTERNS = {
    "python": r"\bpython\b",
    "java": r"\bjava\b(?!script)",
    "javascript": r"\bjavascript\b|\bjs\b(?![a-z])",
    "typescript": r"\btypescript\b",
    "go": r"golang|(?:with|in|using)\s+go\b",
    "rust": r"\brust\b",
    "c++": r"\bc\+\+\b",
    "c#": r"\bc#\b|c sharp|csharp",
    "php": r"\bphp\b",
    "ruby": r"\bruby\b|\brails\b",
    "swift": r"\bswift\b(?!ware)",
    "kotlin": r"\bkotlin\b",
    "scala": r"\bscala\b",
    "matlab": r"\bmatlab\b",
    "bash/shell": r"\bbash\b|shell scripting|shell scripts?\b",
    "powershell": r"powershell",
    "sql": r"\bsql\b|t-sql|pl/sql",
    "html": r"\bhtml5?\b",
    "css": r"\bcss3?\b",
    "react": r"\breact\b|react\.?js",
    "react native": r"react native",
    "angular": r"\bangular(?:\.?js)?\b",
    "vue": r"\bvue(?:\.?js)?\b",
    "next.js": r"next\.?js",
    "node.js": r"node\.?js|\bnode\b(?=[ ,.])",
    "flutter": r"\bflutter\b",
    "android": r"\bandroid\b",
    "ios": r"\bios\b(?! )|\bios development\b",
    "tailwind": r"\btailwind\b",
    "wordpress": r"\bwordpress\b",
    "aws": r"\baws\b|amazon web services",
    "azure": r"\bazure\b",
    "gcp": r"\bgcp\b|google cloud",
    "kubernetes": r"kubernetes|\bk8s\b",
    "docker": r"\bdocker\b",
    "terraform": r"\bterraform\b",
    "ansible": r"\bansible\b",
    "helm": r"\bhelm\b",
    "jenkins": r"\bjenkins\b",
    "ci/cd": r"ci/cd|\bcicd\b|continuous integration|continuous delivery",
    "github actions": r"github actions",
    "git": r"\bgit\b",
    "github": r"\bgithub\b",
    "gitlab": r"\bgitlab\b",
    "prometheus": r"\bprometheus\b",
    "grafana": r"\bgrafana\b",
    "datadog": r"\bdatadog\b",
    "splunk": r"\bsplunk\b",
    "elasticsearch": r"elasticsearch|\bopensearch\b",
    "nginx": r"\bnginx\b",
    "redis": r"\bredis\b",
    "kafka": r"\bkafka\b",
    "rabbitmq": r"rabbitmq",
    "microservices": r"micro-?services",
    "serverless": r"serverless",
    "linux": r"\blinux\b|unix",
    "mysql": r"\bmysql\b",
    "postgresql": r"postgres(?:ql)?",
    "mongodb": r"\bmongo(?:db)?\b",
    "sqlite": r"\bsqlite\b",
    "oracle db": r"\boracle\b",
    "dynamodb": r"dynamo ?db",
    "snowflake": r"\bsnowflake\b",
    "bigquery": r"bigquery|big query",
    "redshift": r"\bredshift\b",
    "databricks": r"databricks",
    "cassandra": r"\bcassandra\b",
    "neo4j": r"neo4j",
    "pandas": r"\bpandas\b",
    "numpy": r"\bnumpy\b",
    "spark": r"\bspark\b(?![a-z])|pyspark",
    "airflow": r"\bairflow\b",
    "dbt": r"\bdbt\b",
    "hadoop": r"\bhadoop\b",
    "tableau": r"\btableau\b",
    "power bi": r"power ?bi",
    "looker": r"\blooker\b",
    "excel": r"\bexcel\b",
    "airbyte": r"\bairbyte\b",
    "fivetran": r"\bfivetran\b",
    "prefect": r"\bprefect\b",
    "pytorch": r"pytorch|\btorch\b",
    "tensorflow": r"tensorflow",
    "scikit-learn": r"scikit-?learn|sklearn",
    "keras": r"\bkeras\b",
    "xgboost": r"xgboost",
    "hugging face": r"hugging ?face|transformers library",
    "llms": r"\bllms?\b|large language models",
    "nlp": r"\bnlp\b|natural language processing",
    "computer vision": r"computer vision|opencv",
    "rest api": r"rest(?:ful)? api",
    "graphql": r"graphql",
    "grpc": r"\bgrpc\b",
    "postman": r"\bpostman\b",
    "openapi/swagger": r"\bopenapi\b|swagger",
    "jira": r"\bjira\b",
    "confluence/atlassian": r"confluence|atlassian",
    "figma": r"\bfigma\b",
    "salesforce": r"salesforce",
    "sap": r"\bsap\b(?![a-z])",
    "hubspot": r"hubspot",
    "zendesk": r"zendesk",
    "servicenow": r"servicenow",
    "sharepoint": r"sharepoint",
    "selenium": r"selenium",
    "playwright": r"playwright",
    "cypress": r"\bcypress\b",
    "pytest": r"\bpytest\b|unit ?tests?\b",
    "agile": r"\bagile\b|scrum|kanban",
}
SKILLS = {name: re.compile(pat, re.I) for name, pat in SKILL_PATTERNS.items()}

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


def fetch_board(prov, slug):
    """Return a list of (title, url, posted, description) for ALL jobs, or None on failure."""
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
                            posted, j.get("descriptionPlain") or j.get("description") or ""))
            raw = out
        else:  # workable
            data = get_json("https://apply.workable.com/api/v1/widget/accounts/%s?details=true" % slug)
            raw = [(j.get("title") or "", j.get("url") or "",
                    str(j.get("published_on") or "")[:10], j.get("description") or "")
                   for j in data.get("jobs", [])]

        return [(t, u, p, strip_html(d)) for t, u, p, d in raw]
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


def skills_in(text):
    return sorted(name for name, rx in SKILLS.items() if rx.search(text or ""))


def bucket(y):
    if y is None:
        return "no stated bar"
    if y <= 2:
        return "actually junior (0-2y)"
    if y <= 5:
        return "junior badge, mid-level bar (3-5y)"
    return "not junior in any sense (6y+)"


def dist_summary(counts):
    if not counts:
        return "n/a"
    s = sorted(counts)
    return "median %d | mean %.1f | p90 %d" % (
        s[len(s) // 2], sum(s) / len(s), s[int(len(s) * 0.9)])


def main():
    boards = provider_boards()
    print("scanning %d boards (greenhouse/ashby/lever/workable)..." % len(boards))
    rows = []
    dead = 0
    all_counts, senior_counts = [], []
    junior_skill_share = {}
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
                sk = skills_in(desc)
                is_jr = bool(JUNIOR_RE.search(title))
                is_sr = bool(SENIOR_RE.search(title))
                all_counts.append(len(sk))
                if is_sr:
                    senior_counts.append(len(sk))
                if is_jr:
                    for name in sk:
                        junior_skill_share[name] = junior_skill_share.get(name, 0) + 1
                    y, snip = years_required(desc)
                    rows.append({
                        "title": title, "company": s, "provider": p, "url": url,
                        "posted": posted, "years_required": "" if y is None else y,
                        "bucket": bucket(y), "requirement_snippet": snip[:220],
                        "skills_count": len(sk),
                        "skills": "|".join(sk),
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
    print("\n== the junior reality check (years) ==")
    for k in order:
        n = counts.get(k, 0)
        print("  %-38s %4d  (%.1f%%)" % (k, n, 100.0 * n / total))
    stated = [int(r["years_required"]) for r in rows if r["years_required"] != ""]
    if stated:
        stated.sort()
        print("  median stated bar: %d years | max: %d years" % (stated[len(stated) // 2], stated[-1]))

    jr_counts = [r["skills_count"] for r in rows]
    print("\n== the technology pile-on ==")
    print("  junior-titled ads : %s" % dist_summary(jr_counts))
    print("  senior-titled ads : %s" % dist_summary(senior_counts))
    print("  all ads          : %s" % dist_summary(all_counts))
    for cut in (6, 10, 15):
        n = sum(1 for c in jr_counts if c >= cut)
        print("  junior ads mentioning %d+ technologies: %d of %d (%.1f%%)" % (cut, n, total, 100.0 * n / total))
    n_agile = sum(1 for r in rows if "agile" in r["skills"])
    print("  junior ads mentioning agile/scrum/kanban: %d (%.1f%%)" % (n_agile, 100.0 * n_agile / total))

    WORKPLACE_TOOLS = ("jira", "confluence/atlassian", "salesforce", "sap",
                       "hubspot", "zendesk", "servicenow", "sharepoint")
    print("\n== workplace tools demanded of graduates ==")
    print("  (tools you cannot have 'experience with' before your first job)")
    any_tool = [r for r in rows if any(t in r["skills"] for t in WORKPLACE_TOOLS)]
    print("  junior ads naming at least one: %d of %d (%.1f%%)" % (
        len(any_tool), total, 100.0 * len(any_tool) / total))
    for t in WORKPLACE_TOOLS:
        n = junior_skill_share.get(t, 0)
        if n:
            print("  %-22s %3d junior ads (%.1f%%)" % (t, n, 100.0 * n / total))
    worst_tools = sorted(any_tool, key=lambda r: -r["skills_count"])[:5]
    for r in worst_tools:
        named = [t for t in WORKPLACE_TOOLS if t in r["skills"]]
        print("  %-46s @ %-18s -> %s" % (r["title"][:46], r["company"][:18], ", ".join(named)))

    print("\n== most-demanded technologies in junior ads ==")
    for name, n in sorted(junior_skill_share.items(), key=lambda x: -x[1])[:15]:
        print("  %-18s %3d junior ads (%.1f%%)" % (name, n, 100.0 * n / total))

    print("\n== worst technology pile-ons, junior titles ==")
    worst = sorted(rows, key=lambda r: -r["skills_count"])[:8]
    for r in worst:
        print("  %2d skills | %-44s @ %s" % (r["skills_count"], r["title"][:44], r["company"]))
        print("             %s" % r["skills"][:150])

    out = os.path.join(DATA, "junior_ads_%s.csv" % date.today().isoformat())
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("\nwrote %s" % out)


if __name__ == "__main__":
    main()
