from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class InventoryConfig:
    """Runtime configuration for the audio inventory pipeline."""

    model_size: str = "base"
    device: str = "cpu"
    diarize: bool = False
    hf_token: Optional[str] = None
    overwrite: bool = False
    max_files: Optional[int] = None
    log_level: str = "INFO"
    keywords: Dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Optional[Path]) -> "InventoryConfig":
        if path is None:
            return cls()
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        if path.suffix.lower() in {".yaml", ".yml"}:
            return cls._load_yaml(path)
        if path.suffix.lower() == ".json":
            return cls._load_json(path)
        raise ValueError("Config must be .json or .yaml/.yml")

    @classmethod
    def _load_json(cls, path: Path) -> "InventoryConfig":
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return cls(**payload)

    @classmethod
    def _load_yaml(cls, path: Path) -> "InventoryConfig":
        try:
            import yaml  # type: ignore
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
            raise ModuleNotFoundError(
                "PyYAML is required to load YAML configs. Install pyyaml or use JSON."
            ) from exc
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
        return cls(**payload)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_size": self.model_size,
            "device": self.device,
            "diarize": self.diarize,
            "hf_token": self.hf_token,
            "overwrite": self.overwrite,
            "max_files": self.max_files,
            "log_level": self.log_level,
            "keywords": self.keywords,
        }

