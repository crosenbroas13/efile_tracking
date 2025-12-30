from src.doj_doc_explorer.utils.paths import top_level_folder_from_rel_path


def test_top_level_folder_from_rel_path_volume() -> None:
    assert top_level_folder_from_rel_path("VOL00007/file.pdf") == "VOL00007"
    assert top_level_folder_from_rel_path("prefix/VOL00012/sub/file.pdf") == "VOL00012"


def test_top_level_folder_from_rel_path_zip() -> None:
    assert top_level_folder_from_rel_path("VOL00003/archive.zip::doc.pdf") == "VOL00003"


def test_top_level_folder_from_rel_path_fallback() -> None:
    assert top_level_folder_from_rel_path("DOJ_DataSets_12.23.25/file.pdf") == "DOJ_DataSets_12.23.25"
