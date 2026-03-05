from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.paths import RUNTIME_DIR


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_tests_kb() -> list[dict[str, Any]]:
    return _load_json(RUNTIME_DIR / "tests_kb.json")


def load_packages() -> list[dict[str, Any]]:
    return _load_json(RUNTIME_DIR / "packages.json")


def load_packages_index() -> dict[str, Any]:
    return _load_json(RUNTIME_DIR / "packages_index.json")


def load_faq_index() -> dict[str, Any]:
    return _load_json(RUNTIME_DIR / "faq_index.json")


def load_branches_index() -> dict[str, Any]:
    return _load_json(RUNTIME_DIR / "branches_index.json")

