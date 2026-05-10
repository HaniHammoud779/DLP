import streamlit as st
from database.db import SessionLocal, FileEvent
from restore import restore_file
import pandas as pd
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QUARANTINE_FOLDER = os.path.join(BASE_DIR, "quarantine")

st.set_page_config(page_title="DLP Dashboard", layout="wide")

st.title("🔐 Data Leakage Prevention Dashboard")

# Refresh button
if st.button("🔄 Refresh Data"):
    st.rerun()

# Load DB data
session = SessionLocal()
events = session.query(FileEvent).order_by(FileEvent.timestamp.desc()).all()
session.close()

data = []
for e in events:
    data.append({
        "File": e.filename,
        "Action": e.action,
        "Label": e.label,
        "Score": e.score,
        "ML Prediction": e.ml_prediction,
        "Confidence": e.ml_confidence,
        "Time": e.timestamp
    })

df = pd.DataFrame(data)

if df.empty:
    st.warning("No activity detected yet...")
    st.stop()

# Metrics
total = len(df)
safe = len(df[df["Label"] == "SAFE"])
medium = len(df[df["Label"] == "MEDIUM"])
sensitive = len(df[df["Label"] == "SENSITIVE"])

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Files", total)
col2.metric("SAFE", safe)
col3.metric("MEDIUM", medium)
col4.metric("SENSITIVE", sensitive)

st.divider()

# FILTER
st.subheader("🔍 Filter Data")
selected_labels = st.multiselect(
    "Select labels to display:",
    options=["SAFE", "MEDIUM", "SENSITIVE"],
    default=["SAFE", "MEDIUM", "SENSITIVE"]
)

filtered_df = df[df["Label"].isin(selected_labels)]

# CHART
st.subheader("📊 Detection Distribution")
st.bar_chart(filtered_df["Label"].value_counts())

# TIMELINE
st.subheader("📈 Activity Over Time")
filtered_df["Time"] = pd.to_datetime(filtered_df["Time"])
timeline = filtered_df.groupby(filtered_df["Time"].dt.floor("min")).size()
st.line_chart(timeline)

st.divider()

# TABLE
st.subheader("📄 Recent Activity")

def color_label(val):
    if val == "SAFE":
        return "color: green; font-weight: bold"
    elif val == "MEDIUM":
        return "color: orange; font-weight: bold"
    elif val == "SENSITIVE":
        return "color: red; font-weight: bold"
    return ""

styled_df = filtered_df.style.applymap(color_label, subset=["Label"])
st.dataframe(styled_df, use_container_width=True)

st.divider()

# 🔥 FIXED RESTORE SECTION (REAL FILES ONLY)
st.subheader("♻️ Restore Files from Quarantine")

try:
    quarantine_files = os.listdir(QUARANTINE_FOLDER)
except:
    quarantine_files = []

if len(quarantine_files) == 0:
    st.info("No files currently in quarantine")
else:
    for file in quarantine_files:
        col1, col2 = st.columns([4,1])

        col1.write(file)

        if col2.button("Restore", key=file):
            success = restore_file(file)

            if success:
                st.success(f"{file} restored successfully")
                st.rerun()
            else:
                st.error(f"Failed to restore {file}")
