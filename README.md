# Job Market Dashboard

A BI dashboard over a snapshot of **15,936 live job postings** collected from **81 public
sources** on **2026-11-18** by my own job discovery pipeline
([remote-job-engine](https://github.com/Reaver1000/remote-job-engine)). The sweep runs daily
and `data/latest.csv` is refreshed with it.

Built first in **Tableau Public**, second in **Power BI**, because building the same dashboard
in both tools is the fastest honest way to learn them.

## Live version

Two live builds over the same data:

- Web app, fully client-side (fetches latest.csv, aggregates in your browser):
  https://reaver1000-job-market-dashboard.static.hf.space
  Source in `web/`, deployed as a Hugging Face static Space.
- Daily newsletter built from this data: https://remotenotamerica.substack.com
- Tableau Public workbook (built on the 2026-11-17 snapshot; republish against
  `data/latest.csv` for current numbers):
  https://public.tableau.com/app/profile/david.buchan8163/viz/snapshotofJuniorRemoterolesavailable/Dashboard1

A Streamlit variant (`app.py`) runs locally with `streamlit run app.py`, and behind
the `Dockerfile` if you prefer a container.

## The data

`data/latest.csv` — one flat table, refreshed with each sweep. Dated copies
(`data/jobs_snapshot_YYYY-MM-DD.csv`) are kept for history.

| column | meaning |
|---|---|
| title | posting title |
| company | hiring company or board slug |
| location | posting location text |
| remote | 1 if the location or title signals remote work, else 0 |
| posted | posting date, where the source provided one (about 85% of rows) |
| source | collecting lane: ats_greenhouse, ats_ashby, freehire_personio, linkedin_de, ... |
| url | original posting URL |

Two things worth knowing before charting `posted`. Greenhouse reports a posting's `updated_at`,
not its first-published date, so a handful of dormant postings carry old dates (the oldest in
the current snapshot is 2021-03-16). And rows without a date stay blank rather than being
filled with a fake value.

## Refreshing the snapshot

`build_snapshot.py` reads one day's sweep outputs (the markdown files the
remote-job-engine pipeline writes) and rebuilds the CSV: dedupes by URL, derives the remote
flag from location and title, and carries each source's posting date into `posted`. Run it in
the sweep working directory, then copy the result to `data/latest.csv`, save a dated copy as
`data/jobs_snapshot_YYYY-MM-DD.csv`, and commit.

`python publish_dataset.py` then rebuilds `data/history.csv` from all dated snapshots
(every posting ever observed, deduped by URL, with first_seen and last_seen sweep dates) and
`--push-hf Reaver1000/job-market-daily` publishes the snapshots and the history to the
[Hugging Face dataset](https://huggingface.co/datasets/Reaver1000/job-market-daily) using the
`HF_TOKEN` environment variable. The same data is mirrored on
[Kaggle](https://www.kaggle.com/datasets/davidbuchan1000/job-market-daily).

`python junior_report.py` re-scans the ATS boards for junior-titled ads with full
descriptions (a few minutes) and writes `data/junior_ads_YYYY-MM-DD.csv` with the parsed
experience bar, the technologies named, and the exact requirement sentence. Publish it into
the dataset's `junior/` folder to keep the junior-reality-check series accumulating.

`python pay_report.py` runs the same scan for pay transparency: structured compensation
fields where the platform exposes them, salary figures parsed from descriptions, and the
dodge phrases used instead of numbers. It writes `data/pay_transparency_YYYY-MM-DD.csv` for
the dataset's `pay/` folder.

So the daily flow is: latest.csv always holds the most recent sweep (the dashboard reads it),
dated snapshots accumulate, history.csv is the growing corpus behind it, and the junior scan
tracks what the junior market actually demands.

## Build it in Tableau Public (fast path)

1. Download Tableau Public Desktop, free: https://public.tableau.com
2. Connect to Text File, pick the CSV. One flat table, no joins needed.
3. Set `posted` to the Date type.
4. Create these calculated fields:
   - `Remote Share` = `SUM([remote]) / COUNT([remote])`
   - `Is Junior` = `CONTAINS(LOWER([title]),"junior") OR CONTAINS(LOWER([title]),"graduate") OR CONTAINS(LOWER([title]),"entry")`
5. Build four sheets:
   - roles by source (bar, top 15)
   - top 20 companies (bar)
   - roles over time (line on `posted`)
   - remote share (big number or donut)
6. Assemble one dashboard, add filters for source, remote and date.
7. File, Save to Tableau Public. The workbook publishes and gets a public URL.
8. Put that URL in this README and in the CV.

## Build it in Power BI (secondary)

1. Power BI Desktop, free in the Microsoft Store.
2. Get Data, Text/CSV, load the snapshot.
3. Add the measures from `measures.dax`.
4. Build the same visuals.
5. Publish to My Workspace, then File, Publish to web for a public link.

## Measures

See `measures.dax`:

- Total Roles = COUNTROWS
- Remote Roles = count where remote = 1
- Remote Share % = DIVIDE of the two
- Distinct Companies, Distinct Sources

## Why

The pipeline that finds my shortlist is also my portfolio. This dashboard turns one day's sweep
into evidence of data modelling, measures and dashboard design in two BI tools.

## Licence

MIT for the code. The CSV is a snapshot of public job postings, used for demonstration only.
