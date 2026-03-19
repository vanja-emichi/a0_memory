"""
Integration test fixtures for a0_memory plugin.

Provides async Memory instances with fully mocked FAISS/embedder backends.
Tests in this layer exercise real Memory business logic (insert, search, delete,
update) without requiring the A0 runtime or live vector databases.

Fixture hierarchy:
  mock_db_store   — shared in-memory document store (dict)
  mock_faiss_db   — MyFaiss mock with in-memory docstore behaviour
  memory_instance — Memory() wired to mock_faiss_db with _save_db patched
"""
import sys
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Root conftest has already stubbed sys.modules — safe to import Memory here
from helpers.memory import Memory, MyFaiss

# Pull in Document from the stub installed by root conftest
Document = sys.modules['langchain_core.documents'].Document


# ── Shared in-memory document store ───────────────────────────────────────────

@pytest.fixture
def mock_db_store():
    """Plain dict acting as FAISS docstore._dict."""
    return {}


# ── MyFaiss mock with dict-backed docstore ─────────────────────────────────────

@pytest.fixture
def mock_faiss_db(mock_db_store):
    """
    MagicMock mimicking MyFaiss with a real dict-backed docstore.

    Implements the subset of FAISS API that Memory's business logic calls:
      - docstore._dict (for get_all_docs)
      - aadd_documents — async, adds to dict
      - adelete — async, removes from dict
      - asearch — async, returns filtered docs
      - asimilarity_search_with_relevance_scores — async
      - aget_by_ids — async, returns docs by id
      - get_by_ids — sync, returns docs by id
      - save_local — no-op (patched at Memory level)
    """
    db = MagicMock()
    db.docstore = MagicMock()
    db.docstore._dict = mock_db_store

    # get_all_docs — returns the whole store
    db.get_all_docs = lambda: mock_db_store

    # get_by_ids — sync lookup
    def _get_by_ids(ids):
        if isinstance(ids, str):
            ids = [ids]
        return [mock_db_store[i] for i in ids if i in mock_db_store]
    db.get_by_ids = _get_by_ids

    # aget_by_ids — async version
    async def _aget_by_ids(ids):
        return _get_by_ids(ids)
    db.aget_by_ids = _aget_by_ids

    # aadd_documents — stores docs by their metadata id
    async def _aadd_documents(documents, ids):
        for doc, doc_id in zip(documents, ids):
            mock_db_store[doc_id] = doc
        return ids
    db.aadd_documents = _aadd_documents

    # adelete — removes ids from store
    async def _adelete(ids):
        for doc_id in ids:
            mock_db_store.pop(doc_id, None)
    db.adelete = _adelete

    # asearch — simple text substring match (no embeddings)
    async def _asearch(query, search_type=None, k=10, score_threshold=0.0, filter=None, **kwargs):
        results = []
        for doc in mock_db_store.values():
            if query.lower() in doc.page_content.lower():
                if filter is None or filter(doc.metadata):
                    results.append(doc)
        return results[:k]
    db.asearch = _asearch

    # asimilarity_search_with_relevance_scores — returns (doc, 0.9) pairs
    async def _asimilarity_with_scores(query, k=10, score_threshold=0.0, filter=None, fetch_k=40, **kwargs):
        results = []
        for doc in mock_db_store.values():
            if query.lower() in doc.page_content.lower():
                if filter is None or filter(doc.metadata):
                    results.append((doc, 0.9))
        return results[:k]
    db.asimilarity_search_with_relevance_scores = _asimilarity_with_scores

    # save_local — no-op (we patch _save_db_file at Memory level)
    db.save_local = MagicMock()

    return db


# ── Memory instance fixture ────────────────────────────────────────────────────

@pytest.fixture
def memory_instance(mock_faiss_db):
    """
    Memory() wired to mock_faiss_db with I/O side-effects patched away.

    Patches:
      - Memory._save_db_file → no-op (prevents file system writes)
      - helpers.guids.generate_id → deterministic uuid hex
      - helpers.print_style.PrintStyle → no-op (suppresses console output)
    """
    # Patch guids.generate_id to return deterministic IDs
    sys.modules['helpers.guids'].generate_id = lambda n=10: uuid.uuid4().hex[:n]

    # Patch PrintStyle to suppress output
    _ps = MagicMock()
    _ps.return_value = MagicMock()  # instance
    _ps.standard = MagicMock()
    _ps.error = MagicMock()
    sys.modules['helpers.print_style'].PrintStyle = _ps

    with patch.object(Memory, '_save_db_file', staticmethod(lambda db, subdir: None)):
        mem = Memory(db=mock_faiss_db, memory_subdir='test')
        yield mem


# ── Convenience: pre-populated memory instance ─────────────────────────────────

@pytest.fixture
async def populated_memory(memory_instance):
    """
    memory_instance with 3 documents pre-inserted.

    Returns (memory_instance, inserted_ids).
    """
    ids = []
    ids.append(await memory_instance.insert_text(
        'Agent Zero can use tools to complete tasks', {'area': 'main'}
    ))
    ids.append(await memory_instance.insert_text(
        'Python is a programming language', {'area': 'main'}
    ))
    ids.append(await memory_instance.insert_text(
        'Solution to recursive problem: use memoization', {'area': 'solutions'}
    ))
    return memory_instance, ids
