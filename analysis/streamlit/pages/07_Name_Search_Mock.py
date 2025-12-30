import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.doj_doc_explorer.name_index.io import load_latest_name_index  # noqa: E402
from src.streamlit_config import get_output_dir  # noqa: E402

st.set_page_config(page_title="Name Search (Mock)", layout="wide")


@st.cache_data(show_spinner=False)
def _cached_load_latest_name_index(out_dir_str: str) -> Tuple[List[Dict], Dict, Dict]:
    return load_latest_name_index(out_dir_str)


def _mock_name_index() -> List[Dict[str, object]]:
    return [
        {
            "canonical_key": "doe|jane",
            "display_name": "Jane Doe",
            "total_count": 6,
            "variants": ["jane doe", "doe, jane", "doe jane"],
            "internal_docs": [
                {
                    "title": "Email re: scheduling",
                    "doc_id": "doc-001",
                    "rel_path": "emails/2024/meeting_notes.pdf",
                    "doj_url": "https://www.justice.gov/example/email",
                    "doc_type_final": "TEXT_PDF",
                    "content_type": "email",
                    "pages": [
                        {"page_num": 1, "count": 2},
                        {"page_num": 3, "count": 1},
                    ],
                    "total_count": 3,
                },
                {
                    "title": "Witness statement",
                    "doc_id": "doc-014",
                    "rel_path": "statements/witness_jd.pdf",
                    "doj_url": "https://www.justice.gov/example/statement",
                    "doc_type_final": "TEXT_PDF",
                    "content_type": "legal filing",
                    "pages": [
                        {"page_num": 2, "count": 1},
                        {"page_num": 4, "count": 2},
                    ],
                    "total_count": 3,
                },
            ],
        },
        {
            "canonical_key": "smith|alex",
            "display_name": "Alex Smith",
            "total_count": 4,
            "variants": ["alex smith", "smith, alex", "smith alex"],
            "internal_docs": [
                {
                    "title": "Call log summary",
                    "doc_id": "doc-022",
                    "rel_path": "logs/call_log_april.pdf",
                    "doj_url": "https://www.justice.gov/example/call-log",
                    "doc_type_final": "TEXT_PDF",
                    "content_type": "memo",
                    "pages": [
                        {"page_num": 5, "count": 1},
                        {"page_num": 7, "count": 2},
                        {"page_num": 9, "count": 1},
                    ],
                    "total_count": 4,
                }
            ],
        },
    ]


def _summarize_records(records: List[Dict[str, object]]) -> Dict[str, int]:
    name_count = len(records)
    total_mentions = 0
    doc_ids = set()
    for record in records:
        total_mentions += int(record.get("total_count") or 0)
        for doc in record.get("internal_docs", []):
            doc_id = doc.get("doc_id")
            if doc_id:
                doc_ids.add(str(doc_id))
    return {
        "total_names": name_count,
        "total_docs": len(doc_ids),
        "total_mentions": total_mentions,
    }


def _format_pages(pages: List[Dict[str, int]]) -> str:
    if not pages:
        return ""
    parts = [f"p.{item.get('page_num')} ({item.get('count')}×)" for item in pages]
    return ", ".join(parts)


def _flatten_records(records: List[Dict[str, object]]) -> pd.DataFrame:
    rows = []
    for record in records:
        name = record.get("display_name") or "(unknown name)"
        canonical_key = record.get("canonical_key") or ""
        variants = ", ".join(record.get("variants") or [])
        name_total = int(record.get("total_count") or 0)
        for doc in record.get("internal_docs", []):
            rows.append(
                {
                    "Name": name,
                    "Canonical key": canonical_key,
                    "Variants": variants,
                    "Total mentions (name)": name_total,
                    "Document title": doc.get("title") or "(untitled)",
                    "Doc ID": doc.get("doc_id") or "",
                    "Relative path": doc.get("rel_path") or "",
                    "Doc type": doc.get("doc_type_final") or "",
                    "Content type": doc.get("content_type") or "",
                    "Total mentions (doc)": int(doc.get("total_count") or 0),
                    "Pages": _format_pages(doc.get("pages") or []),
                    "DOJ URL": doc.get("doj_url") or "",
                }
            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _matches_query(value: str, query: str) -> bool:
    return query in value.lower()


def _build_name_options(records: List[Dict[str, object]]) -> List[str]:
    names = set()
    for record in records:
        names.add(record.get("display_name") or "(unknown name)")
    return ["All names"] + sorted(names, key=str.casefold)


st.title("Name Search (Mock)")
st.caption("Preview the name-search experience inside Streamlit using safe sample data.")

st.markdown(
    """
    **What this page is for:** a lightweight, local-only preview of the name-search experience. It uses **mock data by default**
    so testers can validate the layout, filters, and export workflow without running the full name-index pipeline.

    **Safety reminder:** this view shows **counts and page numbers only**—no extracted text or snippets—so it stays public-safe.
    """
)

source_choice = st.radio(
    "Data source",
    options=["Mock sample (recommended for testing)", "Latest name_index output"],
    horizontal=True,
)

out_dir = get_output_dir()
if source_choice == "Latest name_index output":
    st.caption("Output folder (from Configuration page)")
    st.code(str(out_dir), language="text")
    st.page_link("pages/00_Configuration.py", label="Update output folder", icon="🧭")

    records, summary, _run_log = _cached_load_latest_name_index(str(out_dir))
    if not records:
        st.warning("No name_index output found yet. Use the mock sample data or run the name_index pipeline first.")
        st.stop()
    data_source_note = "Loaded from outputs/name_index/LATEST.json"
else:
    records = _mock_name_index()
    summary = {}
    data_source_note = "Using mock sample data for layout testing."

st.info(data_source_note)

if not summary:
    summary = _summarize_records(records)

summary_cols = st.columns(3)
summary_cols[0].metric("Names indexed", f"{summary.get('total_names', 0):,}")
summary_cols[1].metric("Documents with mentions", f"{summary.get('total_docs', 0):,}")
summary_cols[2].metric("Total mentions", f"{summary.get('total_mentions', 0):,}")

st.markdown("### Search")
st.caption("Type a name, document title, or path fragment to filter the mock index.")

name_options = _build_name_options(records)
if "name_search_filters" not in st.session_state:
    st.session_state.name_search_filters = {
        "selected_name": "All names",
        "query": "",
        "min_mentions": 1,
    }

saved_filters = st.session_state.name_search_filters
selected_default = saved_filters["selected_name"] if saved_filters["selected_name"] in name_options else "All names"

with st.form("name_search_form"):
    selected_name = st.selectbox(
        "Name dropdown",
        options=name_options,
        index=name_options.index(selected_default),
        help="Choose a single name to focus the results, or leave as All names.",
    )
    query = st.text_input(
        "Search terms",
        placeholder="e.g., Jane Doe or meeting_notes.pdf",
        value=saved_filters["query"],
    )
    min_mentions = st.slider(
        "Minimum total mentions (per name)",
        min_value=1,
        max_value=10,
        value=int(saved_filters["min_mentions"]),
    )
    submitted = st.form_submit_button("Search")

if submitted:
    st.session_state.name_search_filters = {
        "selected_name": selected_name,
        "query": query,
        "min_mentions": min_mentions,
    }

active_filters = st.session_state.name_search_filters
selected_name = active_filters["selected_name"]
query = active_filters["query"]
min_mentions = active_filters["min_mentions"]

index_df = _flatten_records(records)
if index_df.empty:
    st.info("No records are available to display yet.")
    st.stop()

filtered_df = index_df[index_df["Total mentions (name)"] >= min_mentions].copy()
if selected_name != "All names":
    filtered_df = filtered_df[filtered_df["Name"] == selected_name]
if query:
    query_norm = query.lower()
    matches = (
        filtered_df[["Name", "Document title", "Relative path", "Canonical key", "Variants"]]
        .fillna("")
        .apply(lambda row: any(_matches_query(str(val), query_norm) for val in row), axis=1)
    )
    filtered_df = filtered_df[matches]

st.markdown("### Results")
st.caption("Each row represents one document where a name appears, including page counts.")

st.dataframe(filtered_df, use_container_width=True, hide_index=True)

st.download_button(
    "Download results as CSV",
    data=filtered_df.to_csv(index=False).encode("utf-8"),
    file_name="name_search_results_mock.csv",
)

st.divider()
st.markdown(
    """
    **What to test next (plain language)**
    - Confirm the **search box** finds names, document titles, and path fragments.
    - Verify the **minimum mentions slider** hides low-frequency names.
    - Export the table and share it with non-technical reviewers for feedback.
    """
)
