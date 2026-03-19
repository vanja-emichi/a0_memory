"""
Root conftest.py — sys.modules stub layer for a0_memory plugin tests.

PROBLEM: helpers/memory.py imports faiss, langchain_community, langchain_core,
numpy, agent, models at module top-level. These are A0 runtime deps NOT present
in /opt/venv. Without stubs, every test file would fail on import.

SOLUTION: This conftest runs before any test file is collected. It installs all
missing module stubs into sys.modules BEFORE Python tries to import helpers.memory.

IMPORTANT: Do not reorder stub installation. The ordering matters:
  1. numpy (used in memory.py arithmetic)
  2. faiss (imported directly)
  3. langchain hierarchy (multiple sub-packages)
  4. A0 framework (agent, models, initialize)
  5. helpers sub-modules (must precede helpers.memory import)
  6. plugins hierarchy (memory_dashboard uses plugin-installed path)

Stub strategy:
  - MagicMock() for modules used only as dependencies (calls go to no-op)
  - Real class for Document — needed for test assertions on .page_content / .metadata
  - Real math.exp wired into numpy mock — needed for _score_normalizer
"""
import sys
import math
from unittest.mock import MagicMock

# ── sys.path setup ─────────────────────────────────────────────────────────────
# Project root: helpers/ namespace pkg lives here
sys.path.insert(0, '/a0/usr/projects/a0_memory')
# A0 root: fallback for any transitional absolute imports
sys.path.insert(0, '/a0')

# ── numpy stub ─────────────────────────────────────────────────────────────────
# Memory._score_normalizer calls np.exp(val) — wire to real math.exp
# pytest.approx internally calls isinstance(val, np.bool_) — np.bool_ MUST be
# a real Python type, not a MagicMock, or isinstance() raises TypeError.
_numpy_mock = MagicMock()
_numpy_mock.exp = lambda x: math.exp(float(x))
# Assign real types so isinstance() checks don't break
_numpy_mock.bool_ = bool
_numpy_mock.float32 = float
_numpy_mock.float64 = float
_numpy_mock.int32 = int
_numpy_mock.int64 = int
_numpy_mock.ndarray = list   # minimal stand-in
sys.modules['numpy'] = _numpy_mock
sys.modules['numpy.linalg'] = MagicMock()

# ── faiss stub ──────────────────────────────────────────────────────────────────
sys.modules['faiss'] = MagicMock()

# ── langchain hierarchy stubs ──────────────────────────────────────────────────
for _mod in [
    'langchain',
    'langchain.storage',
    'langchain.embeddings',
    'langchain_community',
    'langchain_community.vectorstores',
    'langchain_community.vectorstores.utils',
    'langchain_community.docstore',
    'langchain_community.docstore.in_memory',
    'langchain_community.document_loaders',
    'langchain_core',
    'langchain_core.embeddings',
    'langchain_core.documents',
    'langchain_core.vectorstores',
    'langchain_core.vectorstores.base',
]:
    sys.modules[_mod] = MagicMock()


# ── Document — real class required for test assertions ──────────────────────────
# memory.py imports Document from langchain_core.documents at module level.
# Tests do assertions on doc.page_content and doc.metadata — needs a real class.
class Document:
    """Minimal stand-in for langchain_core.documents.Document."""

    def __init__(self, page_content: str = '', metadata: dict = None):
        self.page_content = page_content
        self.metadata = metadata if metadata is not None else {}

    def __repr__(self):
        return f'Document(content={self.page_content!r}, metadata={self.metadata})'

    def __eq__(self, other):
        if not isinstance(other, Document):
            return False
        return self.page_content == other.page_content and self.metadata == other.metadata


# Install real Document into the langchain_core.documents stub
sys.modules['langchain_core.documents'].Document = Document

# ── A0 framework stubs ─────────────────────────────────────────────────────────
sys.modules['agent'] = MagicMock()
sys.modules['models'] = MagicMock()
sys.modules['initialize'] = MagicMock()

# ── helpers sub-module stubs ───────────────────────────────────────────────────
# Must be installed BEFORE helpers.memory is imported.
# helpers/ has no __init__.py (namespace pkg) — Python won't auto-create these.
for _mod in [
    'helpers.guids',
    'helpers.log',
    'helpers.print_style',
    'helpers.files',
    'helpers.plugins',
    'helpers.projects',
    'helpers.faiss_monkey_patch',
    'helpers.knowledge_import',
    'helpers.api',
    'helpers.tool',
]:
    sys.modules[_mod] = MagicMock()

# ── Real ApiHandler/Request/Response — MemoryDashboard inherits ApiHandler ─────
# If ApiHandler is a MagicMock attribute, `class MemoryDashboard(ApiHandler)` fails
# at import time with: TypeError: metaclass conflict or similar.
# Solution: install real minimal base classes into helpers.api mock.

class _Request:
    """Minimal stand-in for helpers.api.Request."""
    def __init__(self, data=None):
        self.data = data or {}


class _Response:
    """Minimal stand-in for helpers.api.Response."""
    def __init__(self, data=None, status=200):
        self.data = data or {}
        self.status = status


class _ApiHandler:
    """Minimal stand-in for helpers.api.ApiHandler."""
    async def process(self, input: dict, request) -> dict:
        raise NotImplementedError


sys.modules['helpers.api'].ApiHandler = _ApiHandler
sys.modules['helpers.api'].Request = _Request
sys.modules['helpers.api'].Response = _Response

# ── plugins hierarchy stubs ────────────────────────────────────────────────────
# memory_dashboard.py imports from 'plugins._memory.helpers.memory' (plugin-installed path)
for _mod in [
    'plugins',
    'plugins._memory',
    'plugins._memory.helpers',
    'plugins._memory.helpers.memory',
    'plugins._model_config',
    'plugins._model_config.helpers',
    'plugins._model_config.helpers.model_config',
    'plugins.a0_memory',
    'plugins.a0_memory.helpers',
    'plugins.a0_memory.helpers.memory',
]:
    sys.modules[_mod] = MagicMock()
