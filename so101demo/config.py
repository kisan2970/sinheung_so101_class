"""Config loading: config/demo.yaml (defaults) deep-merged with config/local.yaml (site-specific)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

DEMO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = DEMO_ROOT / "config"
DEFAULT_PATH = CONFIG_DIR / "demo.yaml"
LOCAL_PATH = CONFIG_DIR / "local.yaml"
LOG_DIR = DEMO_ROOT / "logs"


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config() -> dict[str, Any]:
    with open(DEFAULT_PATH, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if LOCAL_PATH.exists():
        with open(LOCAL_PATH, encoding="utf-8") as f:
            cfg = _merge(cfg, yaml.safe_load(f) or {})
    return cfg


def update_local(patch: dict[str, Any]) -> None:
    """Merge `patch` into config/local.yaml (created if missing)."""
    local = {}
    if LOCAL_PATH.exists():
        with open(LOCAL_PATH, encoding="utf-8") as f:
            local = yaml.safe_load(f) or {}
    local = _merge(local, patch)
    with open(LOCAL_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(local, f, allow_unicode=True, sort_keys=False)
