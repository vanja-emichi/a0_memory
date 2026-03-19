"""
API test fixtures for MemoryDashboard handler tests.

MemoryDashboard is tested by patching the Memory class at the module
level (plugins._memory.helpers.memory) with an AsyncMock that returns
predictable data.

Fixture hierarchy:
  mock_memory_cls  — class-level AsyncMock for Memory
  dashboard        — MemoryDashboard() instance ready to call .process()
"""
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Document stub is already installed in root conftest
Document = sys.modules['langchain_core.documents'].Document


# ── Sample document fixtures ───────────────────────────────────────────────────

@pytest.fixture
def sample_doc():
    """A single Document with standard a0_memory metadata."""
    return Document(
        page_content='Agent Zero can remember things persistently.',
        metadata={
            'id': 'testdoc001',
            'area': 'main',
            'timestamp': '2026-01-15 10:30:00',
            'knowledge_source': False,
            'source_file': '',
            'file_type': '',
            'consolidation_action': '',
            'tags': [],
        },
    )


@pytest.fixture
def sample_docs(sample_doc):
    """Three documents across two areas."""
    return [
        sample_doc,
        Document(
            page_content='Python is great for AI development.',
            metadata={
                'id': 'testdoc002',
                'area': 'main',
                'timestamp': '2026-01-15 11:00:00',
                'knowledge_source': False,
                'source_file': '',
                'file_type': '',
                'consolidation_action': '',
                'tags': [],
            },
        ),
        Document(
            page_content='Use memoization to speed up recursive algorithms.',
            metadata={
                'id': 'testdoc003',
                'area': 'solutions',
                'timestamp': '2026-01-15 12:00:00',
                'knowledge_source': True,
                'source_file': '/knowledge/solutions/tips.md',
                'file_type': 'md',
                'consolidation_action': '',
                'tags': ['algorithms'],
            },
        ),
    ]


# ── Mock Memory class factory ──────────────────────────────────────────────────

def make_mock_memory(docs=None):
    """
    Build a mock Memory instance compatible with MemoryDashboard method calls.

    Args:
        docs: list of Documents the mock FAISS db returns.
    """
    docs = docs or []
    doc_dict = {doc.metadata['id']: doc for doc in docs}

    mock_mem = MagicMock()

    # db.get_all_docs() — returns dict of all docs
    mock_mem.db = MagicMock()
    mock_mem.db.get_all_docs = lambda: doc_dict

    # search_similarity_threshold — returns matching docs
    async def _search(query, limit=10, threshold=0.6, filter=''):
        return [d for d in docs if query.lower() in d.page_content.lower()]
    mock_mem.search_similarity_threshold = _search

    # delete_documents_by_ids — removes and returns removed docs
    async def _delete(ids):
        removed = []
        for doc_id in ids:
            if doc_id in doc_dict:
                removed.append(doc_dict.pop(doc_id))
        return removed
    mock_mem.delete_documents_by_ids = _delete

    # update_documents — replaces doc in dict
    async def _update(doc_list):
        ids = []
        for doc in doc_list:
            doc_id = doc.metadata['id']
            doc_dict[doc_id] = doc
            ids.append(doc_id)
        return ids
    mock_mem.update_documents = _update

    # get_document_by_id — direct lookup
    mock_mem.get_document_by_id = lambda doc_id: doc_dict.get(doc_id)

    return mock_mem


# ── Dashboard fixture ──────────────────────────────────────────────────────────
# CRITICAL: memory_dashboard.py binds Memory/get_existing_memory_subdirs/get_context_memory_subdir
# at MODULE IMPORT TIME via `from plugins._memory.helpers.memory import ...`.
# Patching sys.modules after import does NOT update the already-bound names.
# Fix: import the module first, then patch its module-level names directly each test.
import api.memory_dashboard as _dashboard_module
from api.memory_dashboard import MemoryDashboard


@pytest.fixture
def dashboard(sample_docs):
    """
    MemoryDashboard instance with Memory patched at module level.

    Patches _dashboard_module.Memory directly so each test gets a fresh
    mock_mem_instance regardless of import caching.
    """
    mock_mem_instance = make_mock_memory(sample_docs)
    mock_memory_cls = MagicMock()
    mock_memory_cls.get_by_subdir = AsyncMock(return_value=mock_mem_instance)
    mock_get_subdirs = MagicMock(return_value=['default', 'projects/test'])
    mock_get_context_subdir = MagicMock(return_value='default')
    mock_agent_ctx = MagicMock()
    mock_agent_ctx.use = MagicMock(return_value=None)

    # Patch module-level names directly — this is what process() calls at runtime
    _dashboard_module.Memory = mock_memory_cls
    _dashboard_module.get_existing_memory_subdirs = mock_get_subdirs
    _dashboard_module.get_context_memory_subdir = mock_get_context_subdir
    _dashboard_module.AgentContext = mock_agent_ctx
    sys.modules['agent'].AgentContext = mock_agent_ctx

    return MemoryDashboard()


@pytest.fixture
def empty_dashboard():
    """MemoryDashboard with empty Memory store."""
    mock_mem_instance = make_mock_memory([])
    mock_memory_cls = MagicMock()
    mock_memory_cls.get_by_subdir = AsyncMock(return_value=mock_mem_instance)
    mock_get_subdirs = MagicMock(return_value=['default'])
    mock_get_context_subdir = MagicMock(return_value='default')
    mock_agent_ctx = MagicMock()
    mock_agent_ctx.use = MagicMock(return_value=None)

    _dashboard_module.Memory = mock_memory_cls
    _dashboard_module.get_existing_memory_subdirs = mock_get_subdirs
    _dashboard_module.get_context_memory_subdir = mock_get_context_subdir
    _dashboard_module.AgentContext = mock_agent_ctx
    sys.modules['agent'].AgentContext = mock_agent_ctx

    return MemoryDashboard()
