import sys
from pathlib import Path

import streamlit as st

APP_ROOT = Path(__file__).resolve().parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

st.set_page_config(page_title="DOJ Toolkit", layout="wide")

st.title("DOJ Dataset QA Toolkit")
st.caption("Landing page for inventory and probe review dashboards.")

st.markdown(
    """
    Use the navigation sidebar to open the **Inventory QA**, **Probe QA**, **Probe Run Comparison**,
    **Probe Document Viewer**, or **PDF Labeling** pages.
    These views stay local to your machine and never upload document contents. They help
    non-technical reviewers quickly spot health issues and understand changes between runs
    before deeper processing. The document viewer adds an optional PDF preview so you can
    confirm individual files without leaving the dashboard. The PDF labeling view guides
    reviewers through classifying PDFs and safely saves results to the master labels file.
    """
)

st.info(
    "Need a starting point? Run an inventory with the CLI, then open the Probe QA page to see which PDFs are ready for fast text extraction."
)
