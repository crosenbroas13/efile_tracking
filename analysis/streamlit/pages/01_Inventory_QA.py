import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent.parent
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app import qa_fileimport as qa_fileimport  # noqa: E402

qa_fileimport.main()
