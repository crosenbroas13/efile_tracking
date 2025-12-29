import json
from pathlib import Path

from src.doj_doc_explorer.name_index.config import NameIndexRunConfig
from src.doj_doc_explorer.name_index.io import write_name_index_outputs
from src.doj_doc_explorer.name_index.runner import extract_names_from_text
from src.doj_doc_explorer.name_index.schema import (
    DocMetadata,
    NameIndexAccumulator,
    build_public_records,
    normalize_person_name,
)


def _first_normalized(text: str):
    matches = extract_names_from_text(text)
    assert matches
    return matches[0]


def test_name_normalization_variants():
    assert _first_normalized("John Smith").canonical_key == "smith|john"
    assert _first_normalized("Smith, John").canonical_key == "smith|john"
    assert _first_normalized("SMITH, JOHN").canonical_key == "smith|john"
    assert _first_normalized("O'Neil, Shaun").canonical_key == "o'neil|shaun"
    assert _first_normalized("Anne-Marie Jones").canonical_key == "jones|anne-marie"


def test_variant_generation_includes_orderings():
    normalized = normalize_person_name(first="John", last="Smith")
    assert normalized is not None
    variants = set(normalized.variants)
    assert "john smith" in variants
    assert "smith john" in variants
    assert "smith, john" in variants
    assert normalized.canonical_key == "smith|john"


def test_page_indexing_counts_across_pages():
    normalized = normalize_person_name(first="John", last="Smith")
    assert normalized is not None
    doc = DocMetadata(
        doc_id="doc-1",
        rel_path="folder/file.pdf",
        page_count=2,
        top_level_folder="folder",
        doj_url=None,
        doc_type_final=None,
        content_type=None,
        title="file.pdf",
    )
    accumulator = NameIndexAccumulator()
    accumulator.add(normalized, doc, page_num=1, count=1)
    accumulator.add(normalized, doc, page_num=2, count=2)
    records = accumulator.to_records()
    assert len(records) == 1
    doc_entry = records[0]["docs"][0]
    pages = {page["page_num"]: page["count"] for page in doc_entry["pages"]}
    assert pages[1] == 1
    assert pages[2] == 2
    assert doc_entry["total_count"] == 3


def test_outputs_do_not_store_raw_text(tmp_path: Path):
    outputs_root = tmp_path / "outputs"
    inventory_path = outputs_root / "inventory" / "inv_run" / "inventory.csv"
    inventory_path.parent.mkdir(parents=True)
    inventory_path.write_text("rel_path,abs_path,extension\nfile.pdf,/tmp/file.pdf,pdf\n")
    probe_run_dir = outputs_root / "probes" / "probe_run"
    text_scan_run_dir = outputs_root / "text_scan" / "text_run"
    probe_run_dir.mkdir(parents=True)
    text_scan_run_dir.mkdir(parents=True)

    records = [
        {
            "canonical_key": "smith|john",
            "display_name": "John Smith",
            "variants": ["john smith", "smith john", "smith, john"],
            "total_count": 2,
            "docs": [
                {
                    "doc_id": "doc-1",
                    "rel_path": "folder/file.pdf",
                    "page_count": 2,
                    "top_level_folder": "folder",
                    "doj_url": None,
                    "doc_type_final": None,
                    "content_type": None,
                    "title": "file.pdf",
                    "pages": [{"page_num": 1, "count": 1}, {"page_num": 2, "count": 1}],
                    "total_count": 2,
                }
            ],
        }
    ]
    public_records = build_public_records(records)
    config = NameIndexRunConfig(
        inventory_path=inventory_path,
        probe_run_dir=probe_run_dir,
        text_scan_run_dir=text_scan_run_dir,
        outputs_root=outputs_root,
    )
    run_dir = write_name_index_outputs(records, public_records, config, meta={})

    def assert_no_long_text(value):
        if isinstance(value, dict):
            for item in value.values():
                assert_no_long_text(item)
        elif isinstance(value, list):
            for item in value:
                assert_no_long_text(item)
        elif isinstance(value, str):
            assert len(value) <= 300

    name_index_path = run_dir / "name_index.jsonl"
    for line in name_index_path.read_text().splitlines():
        assert_no_long_text(json.loads(line))
    public_payload = json.loads((run_dir / "public_name_index.json").read_text())
    assert_no_long_text(public_payload)
