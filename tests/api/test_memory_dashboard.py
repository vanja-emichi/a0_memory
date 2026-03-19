"""
API handler tests for MemoryDashboard.

Tests exercise MemoryDashboard.process() action routing and all sub-handlers:
  - search (with query, without query, with area filter)
  - delete (success, missing ID, not found)
  - bulk_delete (success, partial, empty list, invalid type)
  - update (success, missing params)
  - get_memory_subdirs
  - get_current_memory_subdir (with/without context_id)
  - unknown_action fallback
  - exception propagation → success: False response

Memory is patched at the plugin module path by api/conftest.py fixtures.
"""
import pytest
from unittest.mock import MagicMock


# ── Search action ──────────────────────────────────────────────────────────────

@pytest.mark.api
class TestSearchAction:
    """MemoryDashboard._search_memories via process(action='search')."""

    async def test_search_with_query_returns_success(self, dashboard):
        """Search with query returns success=True and memories list."""
        result = await dashboard.process(
            {'action': 'search', 'search': 'remember', 'memory_subdir': 'default'},
            request=None
        )
        assert result['success'] is True
        assert 'memories' in result

    async def test_search_with_query_returns_matching_docs(self, dashboard):
        """Search returns only documents matching the query."""
        result = await dashboard.process(
            {'action': 'search', 'search': 'remember', 'memory_subdir': 'default'},
            request=None
        )
        assert len(result['memories']) >= 1
        assert any('remember' in m['content_full'].lower() for m in result['memories'])

    async def test_search_without_query_returns_all_docs(self, dashboard):
        """Search without query returns all documents in store."""
        result = await dashboard.process(
            {'action': 'search', 'search': '', 'memory_subdir': 'default'},
            request=None
        )
        assert result['success'] is True
        assert result['total_count'] == 3  # 3 sample docs from fixture

    async def test_search_returns_formatted_memory_fields(self, dashboard):
        """Each memory in result has required dashboard fields."""
        result = await dashboard.process(
            {'action': 'search', 'search': '', 'memory_subdir': 'default'},
            request=None
        )
        required_fields = [
            'id', 'area', 'timestamp', 'content_full',
            'knowledge_source', 'source_file', 'file_type',
            'consolidation_action', 'tags', 'metadata'
        ]
        for mem in result['memories']:
            for field in required_fields:
                assert field in mem, f'Missing field: {field}'

    async def test_search_returns_statistics(self, dashboard):
        """Search response includes total_count, knowledge_count, conversation_count."""
        result = await dashboard.process(
            {'action': 'search', 'search': '', 'memory_subdir': 'default'},
            request=None
        )
        assert 'total_count' in result
        assert 'knowledge_count' in result
        assert 'conversation_count' in result
        # 1 of 3 sample docs is a knowledge source
        assert result['knowledge_count'] == 1
        assert result['conversation_count'] == 2

    async def test_search_no_results_returns_empty_list(self, empty_dashboard):
        """Search on empty store returns empty memories list."""
        result = await empty_dashboard.process(
            {'action': 'search', 'search': 'anything', 'memory_subdir': 'default'},
            request=None
        )
        assert result['success'] is True
        assert result['memories'] == []
        assert result['total_count'] == 0

    async def test_search_with_area_filter_applied(self, dashboard):
        """Area filter is passed in query; only matching area docs returned."""
        result = await dashboard.process(
            {
                'action': 'search',
                'search': '',
                'area': 'solutions',
                'memory_subdir': 'default',
            },
            request=None
        )
        assert result['success'] is True
        for mem in result['memories']:
            assert mem['area'] == 'solutions'

    async def test_search_includes_memory_subdir_in_response(self, dashboard):
        """Response includes the queried memory_subdir."""
        result = await dashboard.process(
            {'action': 'search', 'search': '', 'memory_subdir': 'projects/test'},
            request=None
        )
        assert result['memory_subdir'] == 'projects/test'


# ── Delete action ──────────────────────────────────────────────────────────────

@pytest.mark.api
class TestDeleteAction:
    """MemoryDashboard._delete_memory via process(action='delete')."""

    async def test_delete_existing_memory_returns_success(self, dashboard):
        """Deleting a known memory ID returns success=True."""
        result = await dashboard.process(
            {'action': 'delete', 'memory_id': 'testdoc001', 'memory_subdir': 'default'},
            request=None
        )
        assert result['success'] is True
        assert 'testdoc001' in result.get('message', '')

    async def test_delete_missing_memory_id_returns_error(self, dashboard):
        """Missing memory_id in payload returns success=False with error message."""
        result = await dashboard.process(
            {'action': 'delete', 'memory_subdir': 'default'},
            request=None
        )
        assert result['success'] is False
        assert 'error' in result
        assert 'required' in result['error'].lower() or 'id' in result['error'].lower()

    async def test_delete_nonexistent_memory_returns_error(self, dashboard):
        """Deleting a memory ID that doesn't exist returns success=False."""
        result = await dashboard.process(
            {'action': 'delete', 'memory_id': 'does-not-exist-xyz', 'memory_subdir': 'default'},
            request=None
        )
        assert result['success'] is False
        assert 'error' in result


# ── Bulk delete action ────────────────────────────────────────────────────────

@pytest.mark.api
class TestBulkDeleteAction:
    """MemoryDashboard._bulk_delete_memories via process(action='bulk_delete')."""

    async def test_bulk_delete_all_known_ids_returns_success(self, dashboard):
        """Deleting all 3 known IDs returns success=True."""
        result = await dashboard.process(
            {
                'action': 'bulk_delete',
                'memory_ids': ['testdoc001', 'testdoc002', 'testdoc003'],
                'memory_subdir': 'default',
            },
            request=None
        )
        assert result['success'] is True
        assert '3' in result.get('message', '')

    async def test_bulk_delete_empty_list_returns_error(self, dashboard):
        """Empty memory_ids list returns success=False."""
        result = await dashboard.process(
            {'action': 'bulk_delete', 'memory_ids': [], 'memory_subdir': 'default'},
            request=None
        )
        assert result['success'] is False
        assert 'error' in result

    async def test_bulk_delete_wrong_type_returns_error(self, dashboard):
        """memory_ids as string (not list) returns success=False."""
        result = await dashboard.process(
            {'action': 'bulk_delete', 'memory_ids': 'testdoc001', 'memory_subdir': 'default'},
            request=None
        )
        assert result['success'] is False
        assert 'error' in result

    async def test_bulk_delete_partial_match_returns_partial_success(self, dashboard):
        """Deleting mix of known and unknown IDs returns partial success."""
        result = await dashboard.process(
            {
                'action': 'bulk_delete',
                'memory_ids': ['testdoc001', 'nonexistent-xyz'],
                'memory_subdir': 'default',
            },
            request=None
        )
        # At least 1 deleted → success=True with partial message
        assert result['success'] is True


# ── Update action ─────────────────────────────────────────────────────────────

@pytest.mark.api
class TestUpdateAction:
    """MemoryDashboard._update_memory via process(action='update')."""

    async def test_update_returns_success_with_updated_memory(self, dashboard):
        """Successful update returns success=True and updated memory dict."""
        original = {
            'id': 'testdoc001',
            'content_full': 'Original content',
            'metadata': {
                'id': 'testdoc001',
                'area': 'main',
                'timestamp': '2026-01-15 10:30:00',
            }
        }
        edited = {
            'content_full': 'Updated content from dashboard',
            'metadata': {
                'id': 'testdoc001',
                'area': 'main',
                'timestamp': '2026-01-15 10:30:00',
            }
        }
        result = await dashboard.process(
            {
                'action': 'update',
                'memory_subdir': 'default',
                'original': original,
                'edited': edited,
            },
            request=None
        )
        assert result['success'] is True
        assert 'memory' in result

    async def test_update_missing_params_returns_error(self, dashboard):
        """Missing original/edited/memory_subdir returns success=False."""
        result = await dashboard.process(
            {'action': 'update', 'memory_subdir': 'default'},
            request=None
        )
        assert result['success'] is False
        assert 'error' in result


# ── Get memory subdirs action ─────────────────────────────────────────────────

@pytest.mark.api
class TestGetMemorySubdirsAction:
    """MemoryDashboard._get_memory_subdirs via process(action='get_memory_subdirs')."""

    async def test_returns_success_with_subdirs_list(self, dashboard):
        """Returns success=True with list of memory subdirectories."""
        result = await dashboard.process(
            {'action': 'get_memory_subdirs'},
            request=None
        )
        assert result['success'] is True
        assert 'subdirs' in result
        assert isinstance(result['subdirs'], list)
        assert 'default' in result['subdirs']


# ── Get current memory subdir action ─────────────────────────────────────────

@pytest.mark.api
class TestGetCurrentMemorySubdirAction:
    """MemoryDashboard._get_current_memory_subdir via process(action='get_current_memory_subdir')."""

    async def test_without_context_id_returns_default(self, dashboard):
        """No context_id in payload returns 'default' memory_subdir."""
        result = await dashboard.process(
            {'action': 'get_current_memory_subdir'},
            request=None
        )
        assert result['success'] is True
        assert result['memory_subdir'] == 'default'

    async def test_with_unknown_context_id_returns_default(self, dashboard):
        """Unknown context_id (AgentContext.use returns None) falls back to 'default'."""
        result = await dashboard.process(
            {'action': 'get_current_memory_subdir', 'context_id': 'unknown-ctx-id'},
            request=None
        )
        assert result['success'] is True
        assert result['memory_subdir'] == 'default'


# ── Unknown action fallback ───────────────────────────────────────────────────

@pytest.mark.api
class TestUnknownAction:
    """MemoryDashboard process() unknown action fallback."""

    async def test_unknown_action_returns_failure(self, dashboard):
        """Unknown action string returns success=False with error message."""
        result = await dashboard.process(
            {'action': 'nonexistent_action_xyz'},
            request=None
        )
        assert result['success'] is False
        assert 'error' in result
        assert 'Unknown action' in result['error']

    async def test_missing_action_defaults_to_search(self, dashboard):
        """Missing action key defaults to 'search' (default value in process())."""
        result = await dashboard.process(
            {'memory_subdir': 'default', 'search': ''},
            request=None
        )
        # Default action is 'search' — should return success=True
        assert result['success'] is True
        assert 'memories' in result


# ── Exception handling ────────────────────────────────────────────────────────

@pytest.mark.api
class TestExceptionHandling:
    """MemoryDashboard.process() outer try/except swallows exceptions."""

    async def test_exception_in_handler_returns_error_response(self, dashboard, monkeypatch):
        """If a sub-handler raises, process() returns success=False without re-raising."""
        from unittest.mock import AsyncMock
        import api.memory_dashboard as _dashboard_module

        # Patch Memory.get_by_subdir on the module-level binding
        # (api/conftest already imported the module — must patch its bound name)
        raising_mock = AsyncMock(side_effect=RuntimeError('Simulated FAISS failure'))
        original_memory = _dashboard_module.Memory
        mock_memory_cls = MagicMock()
        mock_memory_cls.get_by_subdir = raising_mock
        _dashboard_module.Memory = mock_memory_cls

        try:
            result = await dashboard.process(
                {'action': 'search', 'search': 'test', 'memory_subdir': 'default'},
                request=None
            )
        finally:
            _dashboard_module.Memory = original_memory  # restore

        assert result['success'] is False
        assert 'error' in result
        assert 'Simulated FAISS failure' in result['error']
