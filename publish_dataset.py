"""Accumulate the daily snapshots into a history dataset.

Usage:
  python publish_dataset.py                     # rebuild data/history.csv
  python publish_dataset.py --push-hf REPO_ID   # rebuild, then upload snapshots
                                                # and history to a HF dataset repo
                                                # (requires HF_TOKEN env var)

Each day's sweep is data/jobs_snapshot_YYYY-MM-DD.csv; data/latest.csv is always
the most recent one. History is deduped by URL: first_seen and last_seen record
which sweeps a posting appeared in, and field values come from the latest sweep
that contained it. The 2026-11-17 snapshot predates the exporter fix that carried
posting dates, so its posted column is empty and stays empty.
"""
import argparse
import csv
import glob
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FIELDS = ["title", "company", "location", "remote", "posted", "source", "url",
          "first_seen", "last_seen"]
DATE_RE = re.compile(r"jobs_snapshot_(\d{4}-\d{2}-\d{2})\.csv$")


def norm_url(u):
    return re.sub(r"[?#].*$", "", (u or "")).rstrip("/").lower()


def remote_flag(title, location):
    blob = "%s %s" % (title or "", location or "")
    return 1 if re.search(r"remote|home ?office|anywhere", blob, re.I) else 0


def rebuild(data_dir="data"):
    snaps = []
    for p in sorted(glob.glob(os.path.join(data_dir, "jobs_snapshot_*.csv"))):
        m = DATE_RE.search(p)
        if m:
            snaps.append((m.group(1), p))
    if not snaps:
        raise SystemExit("no dated snapshots found in %s" % data_dir)

    hist = {}
    for day, path in snaps:
        with open(path, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                url = norm_url(r.get("url", ""))
                if not url or not (r.get("title") or "").strip():
                    continue
                key = url
                if key not in hist:
                    hist[key] = {
                        "title": r.get("title", ""),
                        "company": r.get("company", ""),
                        "location": r.get("location", ""),
                        "remote": r.get("remote") or remote_flag(r.get("title"), r.get("location")),
                        "posted": (r.get("posted") or "").strip()[:10],
                        "source": r.get("source", ""),
                        "url": url,
                        "first_seen": day,
                        "last_seen": day,
                    }
                else:
                    row = hist[key]
                    row["last_seen"] = day
                    # latest sweep wins for field values
                    row.update({
                        "title": r.get("title") or row["title"],
                        "company": r.get("company") or row["company"],
                        "location": r.get("location") or row["location"],
                        "remote": r.get("remote") or remote_flag(r.get("title"), r.get("location")),
                        "posted": (r.get("posted") or "").strip()[:10] or row["posted"],
                        "source": r.get("source") or row["source"],
                    })

    out = os.path.join(data_dir, "history.csv")
    rows = sorted(hist.values(), key=lambda x: (x["first_seen"], x["url"]))
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    print("snapshots: %d (%s .. %s)" % (len(snaps), snaps[0][0], snaps[-1][0]))
    print("unique postings: %d" % len(rows))
    fresh = sum(1 for r in rows if r["last_seen"] == snaps[-1][0])
    print("present in latest sweep: %d" % fresh)
    print("gone from latest sweep: %d" % (len(rows) - fresh))
    print("wrote %s" % out)
    return out, snaps


def push_hf(repo_id, data_dir, snaps):
    from huggingface_hub import HfApi

    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN not set")
    api = HfApi(token=token)
    api.create_repo(repo_id=repo_id, repo_type="dataset", private=False, exist_ok=True)
    for day, path in snaps:
        api.upload_file(path_or_fileobj=path,
                        path_in_repo="snapshots/%s" % os.path.basename(path),
                        repo_id=repo_id, repo_type="dataset")
        print("uploaded snapshot %s" % day)
    api.upload_file(path_or_fileobj=os.path.join(data_dir, "history.csv"),
                    path_in_repo="history.csv", repo_id=repo_id, repo_type="dataset")
    print("uploaded history.csv")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--push-hf", metavar="REPO_ID", default=None,
                    help="e.g. Reaver1000/job-market-daily")
    args = ap.parse_args()
    out, snaps = rebuild()
    if args.push_hf:
        push_hf(args.push_hf, "data", snaps)
