"""Job Market Snapshot: a live dashboard over one day's sweep of the remote
job market. Reads data/latest.csv locally, or downloads the published copy.

Run: streamlit run app.py
"""
import os
import sys
import tempfile
import time
import urllib.request

import pandas as pd
import streamlit as st

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAW_URL = "https://raw.githubusercontent.com/Reaver1000/job-market-dashboard/main/data/latest.csv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


@st.cache_data(ttl=3600, show_spinner="loading the latest sweep...")
def load_df():
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "latest.csv")
    if os.path.exists(local):
        path = local
    else:
        path = os.path.join(tempfile.gettempdir(), "job-market-latest.csv")
        for attempt in range(5):
            try:
                req = urllib.request.Request(RAW_URL, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=60) as r:
                    blob = r.read()
                with open(path, "wb") as f:
                    f.write(blob)
                break
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(3)
    df = pd.read_csv(path, dtype=str)
    df["title"] = df["title"].fillna("")
    df["company"] = df["company"].fillna("")
    df["remote"] = pd.to_numeric(df.get("remote"), errors="coerce").fillna(0).astype(int)
    df["posted"] = pd.to_datetime(df.get("posted"), errors="coerce")
    junior = df["title"].str.lower().str.contains("junior|graduate|entry", regex=True, na=False)
    df["junior"] = junior.astype(int)
    return df


st.set_page_config(page_title="Job Market Snapshot", page_icon=":bar_chart:", layout="wide")

df = load_df()
total = len(df)
if total == 0:
    st.error("No data loaded.")
    st.stop()

sweep_day = df["posted"].max()
dated = df[df["posted"].notna()]
coverage = len(dated) / total * 100

st.title("Job Market Snapshot")
st.caption(
    "%s live postings from %s sources, swept by "
    "[remote-job-engine](https://github.com/Reaver1000/remote-job-engine). "
    "Posting date known for %.0f%% of rows; per-day charts use those."
    % ("{:,}".format(total), df["source"].nunique(), coverage)
)

# ---------------- KPI row ----------------
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Postings", "{:,}".format(total))
remote_n = int(df["remote"].sum())
c2.metric("Remote", "{:,}".format(remote_n), "%.1f%%" % (remote_n / total * 100))
junior_n = int(df["junior"].sum())
c3.metric("Junior-titled", "{:,}".format(junior_n), "%.1f%%" % (junior_n / total * 100))
jr_remote = int(((df["junior"] == 1) & (df["remote"] == 1)).sum())
c4.metric("Junior & remote", "{:,}".format(jr_remote))
c5.metric("Companies", "{:,}".format(df["company"].nunique()))

st.divider()

# ---------------- sidebar filters ----------------
st.sidebar.header("Filters")
top_sources = df["source"].value_counts().index.tolist()
picked = st.sidebar.multiselect("Source lanes", top_sources, default=top_sources[:10])
remote_only = st.sidebar.checkbox("Remote roles only")
junior_only = st.sidebar.checkbox("Junior-titled roles only")
search = st.sidebar.text_input("Title contains (e.g. data analyst)")

d = df
if picked:
    d = d[d["source"].isin(picked)]
if remote_only:
    d = d[d["remote"] == 1]
if junior_only:
    d = d[d["junior"] == 1]
if search.strip():
    d = d[d["title"].str.lower().str.contains(search.strip().lower(), na=False)]

if sweep_day is not None and pd.notna(sweep_day):
    default_from = sweep_day - pd.Timedelta(days=29)
    win = st.sidebar.date_input(
        "Trend window (applies to per-day charts)",
        (default_from.date(), sweep_day.date()),
    )
else:
    win = None

st.sidebar.caption(
    "Data: [latest.csv](%s) from "
    "[job-market-dashboard](https://github.com/Reaver1000/job-market-dashboard), "
    "refreshed with each daily sweep." % RAW_URL
)

# ---------------- per-day trend ----------------
st.subheader("Postings per day")
dd = d[d["posted"].notna()].copy()
if win is not None and len(win) == 2:
    dd = dd[(dd["posted"].dt.date >= win[0]) & (dd["posted"].dt.date <= win[1])]
if len(dd):
    per_day = dd.groupby(dd["posted"].dt.date).agg(
        total=("title", "size"), remote=("remote", "sum"), junior=("junior", "sum")
    )
    per_day.index.name = "day"
    st.line_chart(per_day[["total", "remote", "junior"]], height=300)
    with st.expander("Show the per-day numbers"):
        st.dataframe(per_day.assign(
            remote_pct=(per_day["remote"] / per_day["total"] * 100).round(1),
            junior_pct=(per_day["junior"] / per_day["total"] * 100).round(1),
        ))
else:
    st.info("No dated postings in this filter or window.")

left, right = st.columns(2)

with left:
    st.subheader("Top companies")
    comps = d["company"].value_counts().head(15)
    if len(comps):
        st.bar_chart(comps)

with right:
    st.subheader("Roles by source")
    srcs = d["source"].value_counts().head(15)
    if len(srcs):
        st.bar_chart(srcs)

st.subheader("Remote share by source (min 30 postings)")
g = d.groupby("source").agg(total=("title", "size"), remote=("remote", "sum"))
g = g[g["total"] >= 30]
if len(g):
    share = (g["remote"] / g["total"] * 100).sort_values(ascending=False).round(1)
    st.bar_chart(share)

st.divider()
st.caption(
    "Point-in-time capture of public job postings. Aggregates only, nothing personal. "
    "Greenhouse reports a posting's updated date rather than its first-published date, "
    "so a few dormant postings carry old dates."
)
