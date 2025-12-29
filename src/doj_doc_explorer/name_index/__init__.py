from .config import NameIndexRunConfig

__all__ = ["NameIndexRunConfig"]


def __getattr__(name: str):
    if name in {"run_name_index", "run_name_index_and_save"}:
        from .runner import run_name_index, run_name_index_and_save

        return {"run_name_index": run_name_index, "run_name_index_and_save": run_name_index_and_save}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
