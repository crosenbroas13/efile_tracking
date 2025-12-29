import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
STREAMLIT_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, STREAMLIT_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import qa_fileimport  # noqa: E402

qa_fileimport.main()
