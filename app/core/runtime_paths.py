from pathlib import Path

RUNTIME_DIR = Path("app/data/runtime")
RUNTIME_LOOKUP_DIR = RUNTIME_DIR / "lookup"
RUNTIME_RAG_DIR = RUNTIME_DIR / "rag"

FAQ_INDEX_PATH = RUNTIME_LOOKUP_DIR / "faq_index.json"
TESTS_PRICE_INDEX_PATH = RUNTIME_LOOKUP_DIR / "tests_price_index.json"

TESTS_CHUNKS_PATH = RUNTIME_RAG_DIR / "tests_chunks.jsonl"
PACKAGES_CHUNKS_PATH = RUNTIME_RAG_DIR / "packages_chunks_v2.jsonl"
BRANCHES_CHUNKS_PATH = RUNTIME_RAG_DIR / "branches_chunks.jsonl"
PRICES_CHUNKS_PATH = RUNTIME_RAG_DIR / "prices_chunks.jsonl"

SITE_KNOWLEDGE_CHUNKS_PATH = Path("app/data/sources/web/site_knowledge_chunks_hard.jsonl")


def path_exists(p: Path) -> bool:
    return p.exists()
