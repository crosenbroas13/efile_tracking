import sys
from pathlib import Path

import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.io_utils import normalize_out_dir  # noqa: E402
from src.streamlit_config import get_output_dir, set_output_dir  # noqa: E402

st.set_page_config(page_title="Configuration", layout="wide")

st.title("Configuration")
st.caption(
    "Set the local file paths once, then every dashboard page will use the same values. "
    "Nothing here uploads data—these paths stay on your computer."
)

st.markdown(
    """
    **Why this matters:** Streamlit pages all need the same output folder for inventories, probes, and labels.
    By setting it here, you only update it once—no more copy/paste mistakes across pages.
    """
)

current_out_dir = get_output_dir()
out_dir_text = st.text_input(
    "Output folder (contains inventory/, probes/, text_scan/, labels/)",
    value=str(current_out_dir),
)

save_cols = st.columns([1, 3])
if save_cols[0].button("Save configuration"):
    updated_config = set_output_dir(out_dir_text)
    st.success(f"Saved. Active output folder: {updated_config.output_dir}")
else:
    st.info(f"Active output folder: {current_out_dir}")

normalized_preview = normalize_out_dir(out_dir_text)
if normalized_preview != current_out_dir:
    st.caption(f"Normalized path preview: {normalized_preview}")
