"""Load the YAML files in ``config/``."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"


def load_yaml(path: str | Path) -> dict:
    """Read a YAML file; relative names are looked up in ``config/``."""
    path = Path(path)
    if not path.is_absolute() and not path.exists():
        path = CONFIG_DIR / path
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
