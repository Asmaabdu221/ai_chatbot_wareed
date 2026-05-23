"""
Hybrid lab-test retrieval engine (Lab RAG v2).

Three retrieval layers:
  1. SynonymRetriever  - exact + fuzzy match over the 35k-row synonym index.
  2. VectorRetriever   - OpenAI-embedding semantic search via ChromaDB
                         (degrades to a no-op when unavailable).
  3. SymptomRouter     - maps symptom phrases to tests.

LabRetrievalEngine orchestrates the three based on the classified intent.
Heavy objects are built once via warm_up() (call at startup).
"""

from __future__ import annotations

import os

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd
from rapidfuzz import fuzz, process

from app.utils.arabic_normalizer import normalize
from app.data.lab_data_loader import (
    LabDataLoader, DEFAULT_EXCEL, COL_ID, COL_NAME_AR, COL_NAME_EN,
)
from app.services.intent_classifier import QueryIntent

PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Persist path is env-overridable so a Render persistent disk can be mounted
# (e.g. CHROMA_PERSIST_PATH=/data/chromadb) without code changes.
_CHROMA_ENV = os.getenv("CHROMA_PERSIST_PATH", "").strip()
CHROMA_DIR = Path(_CHROMA_ENV) if _CHROMA_ENV else PROJECT_ROOT / "app" / "data" / "runtime" / "chroma_lab_v2"
COLLECTION_NAME = "lab_tests_v2"


def build_test_document(row: dict) -> str:
    """Build one rich embedding document per test from the master row."""
    name_en = row.get(COL_NAME_EN) or row.get("اسم التحليل بالإنجليزية") or ""
    parts = [
        ("تحليل", row.get(COL_NAME_AR, "")),
        ("Test", name_en),
        ("الفائدة", row.get("فائدة التحليل", "")),
        ("الأعراض", row.get("symptoms_aliases", "")),
        ("مناسب لـ", row.get("who_needs_it", "")),
        ("أفضل لـ", row.get("best_for", "")),
        ("مقارنة", row.get("test_comparison", "")),
    ]
    return " | ".join(f"{k}: {v}" for k, v in parts if str(v).strip())


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed texts with OpenAI (text-embedding-3-small by default). Raises on failure."""
    from openai import OpenAI
    from app.core.config import settings
    model = getattr(settings, "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    resp = client.embeddings.create(model=model, input=texts)
    return [d.embedding for d in resp.data]


@dataclass
class RetrievalResult:
    """Result of a retrieval call."""
    tests: list[dict] = field(default_factory=list)
    test_ids: list[str] = field(default_factory=list)
    intent: Optional[QueryIntent] = None
    disambiguation: Optional[dict] = None


# ----------------------------------------------------------------- Layer 1
class SynonymRetriever:
    """Exact + fuzzy lookup over the synonym index. Returns test_ids by score."""

    def __init__(self, synonym_df: pd.DataFrame) -> None:
        self.index: dict[str, list[str]] = {}
        for _, row in synonym_df.iterrows():
            term = normalize(row.get("search_term", ""))
            tid = str(row.get("test_id", "")).strip()
            if term and tid:
                self.index.setdefault(term, [])
                if tid not in self.index[term]:
                    self.index[term].append(tid)
        self.terms: list[str] = list(self.index.keys())

    def search(self, query: str, threshold: int = 82, limit: int = 5) -> list[str]:
        """Return test_ids for a query (exact hit first, else fuzzy)."""
        norm_q = normalize(query)
        if not norm_q:
            return []
        if norm_q in self.index:
            return list(self.index[norm_q])
        # token_set_ratio matches names embedded in filler ("كم سعر CBC" -> "cbc").
        matches = process.extract(norm_q, self.terms, scorer=fuzz.token_set_ratio, limit=limit)
        out: list[str] = []
        for term, score, _ in matches:
            if score >= threshold:
                for tid in self.index.get(term, []):
                    if tid not in out:
                        out.append(tid)
        return out


# ----------------------------------------------------------------- Layer 2
class VectorRetriever:
    """ChromaDB + OpenAI-embedding semantic search. No-op if unavailable."""

    def __init__(self) -> None:
        self._collection = None
        self._available = False
        if os.getenv("EMBEDDING_BACKEND", "openai").strip().lower() == "none":
            return  # vector layer disabled -> engine falls back to Layers 1 + 3
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(CHROMA_DIR))
            self._collection = client.get_or_create_collection(
                name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
            )
            self._available = self._collection.count() > 0
        except Exception:
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def search(self, query: str, top_k: int = 3) -> list[str]:
        """Return test_ids for nearest documents (empty if unavailable)."""
        if not self._available or self._collection is None:
            return []
        try:
            emb = embed_texts([query])[0]
            res = self._collection.query(query_embeddings=[emb], n_results=top_k)
            ids = res.get("ids") or [[]]
            return list(ids[0])
        except Exception:
            return []


# ----------------------------------------------------------------- Layer 3
class SymptomRouter:
    """Maps symptom phrases to tests via the symptoms sheet."""

    def __init__(self, symptoms_df: pd.DataFrame) -> None:
        self.rows: list[tuple[str, list[str]]] = []
        for _, r in symptoms_df.iterrows():
            sym = normalize(r.get("symptom_ar", ""))
            ids = [t.strip() for t in str(r.get("test_ids", "")).split(",") if t.strip()]
            if sym and ids:
                self.rows.append((sym, ids))

    def route(self, query: str) -> list[str]:
        """Return test_ids ranked by matched-symptom support."""
        nq = normalize(query)
        if not nq:
            return []
        from collections import Counter
        counter: Counter = Counter()
        q_tokens = {w for w in nq.split() if len(w) >= 3}
        for sym, ids in self.rows:
            s_tokens = {w for w in sym.split() if len(w) >= 3}
            overlap = q_tokens & s_tokens
            if sym in nq or nq in sym or overlap:
                weight = len(overlap) or 1
                for tid in ids:
                    counter[tid] += weight
        return [tid for tid, _ in counter.most_common(8)]


# ----------------------------------------------------------------- Orchestrator
class LabRetrievalEngine:
    """Combines the three retrieval layers behind an intent-aware API."""

    def __init__(self, excel_path=DEFAULT_EXCEL) -> None:
        self.data_loader = LabDataLoader(excel_path)
        self.synonym_retriever: Optional[SynonymRetriever] = None
        self.vector_retriever: Optional[VectorRetriever] = None
        self.symptom_router: Optional[SymptomRouter] = None
        self._disambig: Optional[pd.DataFrame] = None
        self._warm = False

    def warm_up(self) -> None:
        """Load all data and build the in-memory retrievers (idempotent)."""
        if self._warm:
            return
        self.data_loader.load_all()
        self.synonym_retriever = SynonymRetriever(self.data_loader.load_synonym_index())
        self.symptom_router = SymptomRouter(self.data_loader.load_symptoms_map())
        self._disambig = self.data_loader.load_disambiguation()
        self.vector_retriever = VectorRetriever()
        self._warm = True

    def _ensure_warm(self) -> None:
        if not self._warm:
            self.warm_up()

    @staticmethod
    def _strip_al(w: str) -> str:
        return w[2:] if w.startswith("ال") and len(w) > 3 else w

    def resolve_ambiguity(self, query: str) -> tuple[list[str], Optional[dict]]:
        """Find the disambiguation group for an ambiguous query."""
        assert self.synonym_retriever is not None and self._disambig is not None
        # Exact name match -> not actually ambiguous; return it directly.
        exact = self.synonym_retriever.index.get(normalize(query))
        if exact:
            return list(exact), None
        ids = self.synonym_retriever.search(query, threshold=78)
        group = ""
        if ids:
            group = str(self.data_loader.get_test_by_id(ids[0]).get("disambiguation_group", "")).strip()
        if not group:
            nq = normalize(query)
            q_words = {self._strip_al(w) for w in nq.split()}
            for _, row in self._disambig.iterrows():
                core = normalize(str(row.get("group_name", ""))).replace("مجموعه", "").strip()
                core_words = {self._strip_al(w) for w in core.split() if w}
                if core_words & q_words:
                    group = str(row.get("group_name", "")).strip()
                    break
        if group:
            sub = self._disambig[self._disambig["group_name"] == group]
            if len(sub):
                row = sub.iloc[0]
                member_ids = [t.strip() for t in str(row.get("test_ids", "")).split(",") if t.strip()]
                return member_ids, {"group": group, "decision_helper": row.get("decision_helper", "")}
        return ids, None

    def retrieve(self, query: str, intent: QueryIntent) -> RetrievalResult:
        """Retrieve tests for a query given its intent."""
        self._ensure_warm()
        assert self.synonym_retriever is not None
        test_ids: list[str] = []
        disambig: Optional[dict] = None

        if intent in (QueryIntent.TEST_LOOKUP, QueryIntent.FASTING_PREP,
                      QueryIntent.AVAILABILITY, QueryIntent.PACKAGE_INQUIRY):
            test_ids = self.synonym_retriever.search(query)
            if not test_ids and self.vector_retriever is not None:
                test_ids = self.vector_retriever.search(query, top_k=3)
        elif intent == QueryIntent.SYMPTOM_QUERY:
            assert self.symptom_router is not None
            test_ids = self.symptom_router.route(query)
            if not test_ids and self.vector_retriever is not None:
                test_ids = self.vector_retriever.search(query, top_k=5)
        elif intent == QueryIntent.AMBIGUOUS:
            test_ids, disambig = self.resolve_ambiguity(query)
        else:
            test_ids = []

        tests = self.data_loader.get_tests_by_ids(test_ids[:8])
        return RetrievalResult(tests=tests, test_ids=test_ids[:8], intent=intent, disambiguation=disambig)


_engine: Optional[LabRetrievalEngine] = None


def get_lab_retrieval_engine() -> LabRetrievalEngine:
    """Return the process-wide singleton engine (warmed on first use)."""
    global _engine
    if _engine is None:
        _engine = LabRetrievalEngine()
        _engine.warm_up()
    return _engine
