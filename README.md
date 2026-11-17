# Job Market Dashboard

A BI dashboard over a snapshot of **15,516 live job postings** collected from **73 public
sources** on **2026-11-17** by my own job discovery pipeline
([remote-job-engine](https://github.com/Reaver1000/remote-job-engine)).

Built first in **Tableau Public**, second in **Power BI**, because building the same dashboard
in both tools is the fastest honest way to learn them.

## Live version

The Tableau build is published and live

https://public.tableau.com/app/profile/david.buchan8163/viz/snapshotofJuniorRemoterolesavailable/Dashboard1

## The data

`data/jobs_snapshot_2026-11-17.csv` — one flat table.

| column | meaning |
|---|---|
| title | posting title |
| company | hiring company or board slug |
| location | posting location text |
| remote | 1 if the location or title signals remote work, else 0 |
| posted | posting date, where the source provided one |
| source | collecting lane: ats_greenhouse, ats_ashby, freehire_personio, linkedin_de, ... |
| url | original posting URL |

Point-in-time capture of public postings. Aggregates and samples only, nothing personal.

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
