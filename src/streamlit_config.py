from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from src.io_utils import get_default_out_dir, normalize_out_dir


@dataclass
class StreamlitConfig:
    output_dir: Path


CONFIG_STATE_KEY = "doj_streamlit_config"


def _default_config() -> StreamlitConfig:
    return StreamlitConfig(output_dir=get_default_out_dir())


def get_streamlit_config() -> StreamlitConfig:
    if CONFIG_STATE_KEY not in st.session_state:
        st.session_state[CONFIG_STATE_KEY] = _default_config()
    return st.session_state[CONFIG_STATE_KEY]


def set_output_dir(output_dir: str | Path) -> StreamlitConfig:
    config = get_streamlit_config()
    config.output_dir = normalize_out_dir(output_dir)
    st.session_state[CONFIG_STATE_KEY] = config
    return config


def get_output_dir() -> Path:
    return get_streamlit_config().output_dir
