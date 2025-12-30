from src.doj_doc_explorer.utils.paths import top_level_folder_from_rel_path


def test_top_level_folder_from_rel_path_volume() -> None:
    assert top_level_folder_from_rel_path("VOL00007/file.pdf") == "DataSet 7"
    assert top_level_folder_from_rel_path("prefix/VOL00012/sub/file.pdf") == "DataSet 12"


def test_top_level_folder_from_rel_path_zip() -> None:
    assert top_level_folder_from_rel_path("VOL00003/archive.zip::doc.pdf") == "DataSet 3"


def test_top_level_folder_from_rel_path_fallback() -> None:
    assert top_level_folder_from_rel_path("DataSet 1/file.pdf") == "DataSet 1"
