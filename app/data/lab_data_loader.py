"""
Lab data loader for the Lab RAG v2 pipeline.

Loads the 6 sheets of ``tests_REBUILT.xlsx`` (plus ``packages.xlsx``) into
pandas DataFrames and exposes simple test-lookup helpers. All reads are done
once and cached on the instance; the engine warms this up at startup.

The master sheet uses two header rows (row 1 = Arabic labels, row 2 = English
keys), so it is read with ``header=1`` and data therefore starts at Excel row 3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

# Project root: app/data/lab_data_loader.py -> parents[2] == repo root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXCEL = PROJECT_ROOT / "app" / "data" / "sources" / "excel" / "tests_REBUILT.xlsx"
DEFAULT_PACKAGES = PROJECT_ROOT / "app" / "data" / "sources" / "excel" / "packages.xlsx"

# Sheet names (exact, from the rebuilt workbook)
SHEET_MASTER = "التحاليل الكاملة"
SHEET_SYNONYMS = "الكلمات المرادفة"
SHEET_SYMPTOMS = "الأعراض والتحاليل"
SHEET_DISAMBIG = "التحاليل المتشابهة"

# Canonical master column keys (row-2 English/Arabic keys)
COL_ID = "test_id"
COL_NAME_AR = "اسم التحليل بالعربية"
COL_NAME_EN = "names"


class LabDataLoader:
    """Loads and caches the rebuilt lab workbook sheets."""

    def __init__(self, excel_path: str | Path = DEFAULT_EXCEL,
                 packages_path: str | Path = DEFAULT_PACKAGES) -> None:
        self.excel_path = Path(excel_path)
        self.packages_path = Path(packages_path)
        self._master: Optional[pd.DataFrame] = None
        self._synonyms: Optional[pd.DataFrame] = None
        self._symptoms: Optional[pd.DataFrame] = None
        self._disambig: Optional[pd.DataFrame] = None
        self._packages: Optional[pd.DataFrame] = None
        self._by_id: dict[str, dict] = {}

    # ------------------------------------------------------------------ loaders
    def load_master(self) -> pd.DataFrame:
        """Load the master sheet (one row per test), indexed by ``test_id``."""
        if self._master is None:
            df = pd.read_excel(self.excel_path, sheet_name=SHEET_MASTER, header=1, dtype=str).fillna("")
            df = df[df[COL_ID].astype(str).str.strip() != ""]
            self._master = df.reset_index(drop=True)
            self._by_id = {str(r[COL_ID]).strip(): r.to_dict() for _, r in self._master.iterrows()}
        return self._master

    def load_synonym_index(self) -> pd.DataFrame:
        """Load the flat synonym index (search_term | test_id | name_ar | name_en | match_type)."""
        if self._synonyms is None:
            self._synonyms = pd.read_excel(self.excel_path, sheet_name=SHEET_SYNONYMS, dtype=str).fillna("")
        return self._synonyms

    def load_symptoms_map(self) -> pd.DataFrame:
        """Load the symptom -> test_ids/package_ids mapping."""
        if self._symptoms is None:
            self._symptoms = pd.read_excel(self.excel_path, sheet_name=SHEET_SYMPTOMS, dtype=str).fillna("")
        return self._symptoms

    def load_disambiguation(self) -> pd.DataFrame:
        """Load the disambiguation-groups sheet."""
        if self._disambig is None:
            self._disambig = pd.read_excel(self.excel_path, sheet_name=SHEET_DISAMBIG, dtype=str).fillna("")
        return self._disambig

    def load_packages(self) -> pd.DataFrame:
        """Load the standalone packages workbook (best-effort; empty DF on failure)."""
        if self._packages is None:
            try:
                self._packages = pd.read_excel(self.packages_path, dtype=str).fillna("")
            except Exception:
                self._packages = pd.DataFrame()
        return self._packages

    def load_all(self) -> None:
        """Eagerly load every sheet (used by warm_up)."""
        self.load_master()
        self.load_synonym_index()
        self.load_symptoms_map()
        self.load_disambiguation()
        self.load_packages()

    # ------------------------------------------------------------------ lookups
    def get_test_by_id(self, test_id: str) -> dict:
        """Return the master row for a test_id as a dict ({} if not found)."""
        if self._master is None:
            self.load_master()
        return self._by_id.get(str(test_id).strip(), {})

    def get_tests_by_ids(self, ids: list[str]) -> list[dict]:
        """Return master rows for a list of test_ids (preserving order, skipping misses)."""
        if self._master is None:
            self.load_master()
        out: list[dict] = []
        seen: set[str] = set()
        for tid in ids or []:
            t = str(tid).strip()
            if t and t not in seen and t in self._by_id:
                seen.add(t)
                out.append(self._by_id[t])
        return out
