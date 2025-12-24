import pandas as pd

from src.doj_doc_explorer.text_scan.categorize import CategoryAccumulator
from src.doj_doc_explorer.text_scan.io import merge_text_scan_signals
from src.doj_doc_explorer.text_scan.quality import TextAccumulator
from src.doj_doc_explorer.text_scan.config import TextQualityConfig


def test_text_quality_empty_label():
    accumulator = TextAccumulator(TextQualityConfig())
    stats = accumulator.finalize(text_pages_scanned=0)
    assert stats.text_quality_label == "EMPTY"


def test_text_quality_low_label_for_gibberish():
    config = TextQualityConfig()
    accumulator = TextAccumulator(config)
    text = ("���� ____ #### %%%% !!!!! ???? " * 5).strip()
    accumulator.update(text)
    stats = accumulator.finalize(text_pages_scanned=1)
    assert stats.text_quality_label == "LOW"


def test_text_quality_good_label_for_email():
    config = TextQualityConfig()
    accumulator = TextAccumulator(config)
    text = (
        "From: analyst@example.com\n"
        "To: reviewer@example.com\n"
        "Subject: Status update\n"
        "Hello team,\n"
        "Here is the weekly status update with action items and next steps.\n"
        "Thanks,\n"
        "Analyst\n"
    )
    accumulator.update(text)
    stats = accumulator.finalize(text_pages_scanned=1)
    assert stats.text_quality_label == "GOOD"


def test_categorize_email_thread():
    accumulator = CategoryAccumulator()
    text = (
        "From: analyst@example.com\n"
        "To: reviewer@example.com\n"
        "Sent: 01/02/2024 9:30 AM\n"
        "Subject: Update\n"
        "-----Original Message-----\n"
        "From: someone@example.com\n"
    )
    accumulator.update(text)
    pred = accumulator.finalize()
    assert pred.content_type_pred == "EMAIL_THREAD"


def test_categorize_legal_proceeding():
    accumulator = CategoryAccumulator()
    text = (
        "IN THE UNITED STATES DISTRICT COURT\n"
        "Case No. 22-CV-1234\n"
        "Plaintiff v. Defendant\n"
        "Motion to Dismiss\n"
    )
    accumulator.update(text)
    pred = accumulator.finalize()
    assert pred.content_type_pred == "LEGAL_PROCEEDING"


def test_merge_text_scan_signals_normalizes_rel_path():
    docs_df = pd.DataFrame(
        {
            "rel_path": ["Folder\\File.pdf", "Other.pdf"],
            "doc_id": ["1", "2"],
        }
    )
    signals_df = pd.DataFrame(
        {
            "rel_path": ["Folder/File.pdf", "Other.pdf"],
            "text_quality_label": ["GOOD", "LOW"],
            "text_quality_score": [0.9, 0.2],
            "content_type_pred": ["EMAIL_THREAD", "FORM_TEMPLATE"],
            "content_type_confidence": [0.8, 0.6],
        }
    )
    merged_df, info = merge_text_scan_signals(docs_df, signals_df)
    assert info["merged"] is True
    assert "text_quality_label" in merged_df.columns
