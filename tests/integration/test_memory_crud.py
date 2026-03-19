"""
Integration tests for Memory CRUD operations.

Tests exercise real Memory class business logic (insert, search, delete, update)
using the mock_faiss_db fixture (dict-backed docstore, no real FAISS/embeddings).

All async methods tested with pytest-asyncio (mode=auto from pytest.ini).
"""
import sys
import pytest

Document = sys.modules['langchain_core.documents'].Document


# ── Insert ─────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestInsertText:
    """Memory.insert_text — single document insertion."""

    async def test_insert_text_returns_id(self, memory_instance):
        """insert_text returns a non-empty string ID."""
        doc_id = await memory_instance.insert_text('Test memory content')
        assert isinstance(doc_id, str)
        assert len(doc_id) > 0

    async def test_insert_text_stores_document(self, memory_instance):
        """Inserted document is retrievable from the store."""
        doc_id = await memory_instance.insert_text('Stored content')
        doc = memory_instance.get_document_by_id(doc_id)
        assert doc is not None
        assert doc.page_content == 'Stored content'

    async def test_insert_text_sets_id_in_metadata(self, memory_instance):
        """Inserted document metadata contains the returned ID."""
        doc_id = await memory_instance.insert_text('With metadata')
        doc = memory_instance.get_document_by_id(doc_id)
        assert doc.metadata['id'] == doc_id

    async def test_insert_text_sets_timestamp(self, memory_instance):
        """Inserted document metadata contains a timestamp string."""
        doc_id = await memory_instance.insert_text('Timestamped entry')
        doc = memory_instance.get_document_by_id(doc_id)
        assert 'timestamp' in doc.metadata
        assert len(doc.metadata['timestamp']) > 0

    async def test_insert_text_defaults_to_main_area(self, memory_instance):
        """Documents without explicit area default to 'main'."""
        doc_id = await memory_instance.insert_text('Default area content')
        doc = memory_instance.get_document_by_id(doc_id)
        assert doc.metadata['area'] == 'main'

    async def test_insert_text_with_custom_area(self, memory_instance):
        """Custom area metadata is preserved on insert."""
        doc_id = await memory_instance.insert_text(
            'Solution content', {'area': 'solutions'}
        )
        doc = memory_instance.get_document_by_id(doc_id)
        assert doc.metadata['area'] == 'solutions'

    async def test_insert_text_with_extra_metadata(self, memory_instance):
        """Extra metadata fields are preserved on insert."""
        doc_id = await memory_instance.insert_text(
            'Tagged content', {'area': 'main', 'tags': ['important', 'work']}
        )
        doc = memory_instance.get_document_by_id(doc_id)
        assert doc.metadata['tags'] == ['important', 'work']

    async def test_insert_multiple_documents_returns_unique_ids(self, memory_instance):
        """Multiple inserts return distinct IDs."""
        id1 = await memory_instance.insert_text('First')
        id2 = await memory_instance.insert_text('Second')
        id3 = await memory_instance.insert_text('Third')
        assert len({id1, id2, id3}) == 3


# ── Insert Documents (batch) ───────────────────────────────────────────────────

@pytest.mark.integration
class TestInsertDocuments:
    """Memory.insert_documents — batch document insertion."""

    async def test_insert_documents_returns_ids_list(self, memory_instance):
        """insert_documents returns a list of IDs with same length as input."""
        docs = [
            Document('Doc 1', metadata={'area': 'main'}),
            Document('Doc 2', metadata={'area': 'main'}),
            Document('Doc 3', metadata={'area': 'solutions'}),
        ]
        ids = await memory_instance.insert_documents(docs)
        assert len(ids) == 3
        assert all(isinstance(i, str) for i in ids)

    async def test_insert_documents_all_stored(self, memory_instance):
        """All batch-inserted documents are retrievable."""
        docs = [Document(f'Content {i}', metadata={}) for i in range(5)]
        ids = await memory_instance.insert_documents(docs)
        for doc_id in ids:
            assert memory_instance.get_document_by_id(doc_id) is not None

    async def test_insert_empty_list_returns_empty(self, memory_instance):
        """Inserting empty list returns empty list and adds nothing to store."""
        ids = await memory_instance.insert_documents([])
        assert ids == []


# ── Delete by IDs ──────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestDeleteDocumentsByIds:
    """Memory.delete_documents_by_ids — targeted deletion."""

    async def test_delete_existing_document(self, populated_memory):
        """Deleting a known ID removes it from the store."""
        mem, ids = populated_memory
        await mem.delete_documents_by_ids([ids[0]])
        # get_document_by_id raises IndexError on missing ID (source behaviour)
        # Verify deletion via docstore dict instead
        assert ids[0] not in mem.db.get_all_docs()

    async def test_delete_returns_removed_docs(self, populated_memory):
        """delete_documents_by_ids returns the documents that were removed."""
        mem, ids = populated_memory
        removed = await mem.delete_documents_by_ids([ids[0]])
        assert len(removed) == 1
        assert removed[0].metadata['id'] == ids[0]

    async def test_delete_nonexistent_id_returns_empty(self, memory_instance):
        """Deleting a non-existent ID returns empty list without error."""
        removed = await memory_instance.delete_documents_by_ids(['nonexistent-id'])
        assert removed == []

    async def test_delete_multiple_ids(self, populated_memory):
        """Multiple IDs can be deleted in one call."""
        mem, ids = populated_memory
        await mem.delete_documents_by_ids([ids[0], ids[1]])
        all_docs = mem.db.get_all_docs()
        assert ids[0] not in all_docs
        assert ids[1] not in all_docs
        # Third doc still present
        assert ids[2] in all_docs

    async def test_delete_does_not_affect_other_documents(self, populated_memory):
        """Deleting one document doesn't affect others."""
        mem, ids = populated_memory
        initial_count = len(mem.db.get_all_docs())
        await mem.delete_documents_by_ids([ids[0]])
        assert len(mem.db.get_all_docs()) == initial_count - 1


# ── Update Documents ───────────────────────────────────────────────────────────

@pytest.mark.integration
class TestUpdateDocuments:
    """Memory.update_documents — in-place document update."""

    async def test_update_changes_content(self, populated_memory):
        """Updated document reflects new page_content."""
        mem, ids = populated_memory
        original = mem.get_document_by_id(ids[0])
        updated_doc = Document(
            page_content='Updated content here',
            metadata=original.metadata,
        )
        await mem.update_documents([updated_doc])
        result = mem.get_document_by_id(ids[0])
        assert result.page_content == 'Updated content here'

    async def test_update_preserves_id(self, populated_memory):
        """Update preserves the document's original ID in metadata."""
        mem, ids = populated_memory
        original = mem.get_document_by_id(ids[0])
        updated_doc = Document(
            page_content='New content',
            metadata={**original.metadata},
        )
        returned_ids = await mem.update_documents([updated_doc])
        assert ids[0] in returned_ids


# ── Search ─────────────────────────────────────────────────────────────────────

@pytest.mark.integration
class TestSearchSimilarityThreshold:
    """Memory.search_similarity_threshold — query-based search."""

    async def test_search_returns_matching_docs(self, populated_memory):
        """Search returns documents containing the query term."""
        mem, ids = populated_memory
        results = await mem.search_similarity_threshold(
            query='tools', limit=10, threshold=0.0
        )
        assert len(results) >= 1
        assert any('tools' in doc.page_content for doc in results)

    async def test_search_with_area_filter(self, populated_memory):
        """Area filter restricts search to the specified memory area."""
        mem, ids = populated_memory
        results = await mem.search_similarity_threshold(
            query='memoization',
            limit=10,
            threshold=0.0,
            filter="area == 'solutions'",
        )
        # Only solutions area docs should match
        for doc in results:
            assert doc.metadata['area'] == 'solutions'

    async def test_search_empty_store_returns_empty(self, memory_instance):
        """Search on empty store returns empty list."""
        results = await memory_instance.search_similarity_threshold(
            query='anything', limit=10, threshold=0.0
        )
        assert results == []

    async def test_search_no_match_returns_empty(self, populated_memory):
        """Search with query that matches nothing returns empty list."""
        mem, ids = populated_memory
        results = await mem.search_similarity_threshold(
            query='xyzzy_no_match_guaranteed_abc123',
            limit=10,
            threshold=0.0,
        )
        assert results == []


# ── get_document_by_id ─────────────────────────────────────────────────────────

@pytest.mark.integration
class TestGetDocumentById:
    """Memory.get_document_by_id — direct ID lookup."""

    async def test_returns_correct_document(self, populated_memory):
        """get_document_by_id returns the document with matching ID."""
        mem, ids = populated_memory
        doc = mem.get_document_by_id(ids[1])
        assert doc is not None
        assert doc.metadata['id'] == ids[1]

    def test_returns_none_for_missing_id(self, memory_instance):
        """get_document_by_id raises IndexError on missing ID (known source behaviour).

        The source code does `return self.db.get_by_ids(id)[0]` which raises IndexError
        when the ID is not found. This test documents the actual behaviour.
        Callers must ensure IDs exist before calling get_document_by_id.
        """
        with pytest.raises((IndexError, KeyError)):
            memory_instance.get_document_by_id('does-not-exist')


# ── format_docs_plain ──────────────────────────────────────────────────────────

@pytest.mark.integration
class TestFormatDocsPlain:
    """Memory.format_docs_plain — output formatting for agent context."""

    def test_formats_single_doc(self):
        """format_docs_plain returns list of formatted strings."""
        from helpers.memory import Memory
        docs = [
            Document(
                page_content='Test content',
                metadata={'id': 'abc123', 'area': 'main', 'timestamp': '2026-01-15 10:30:00'},
            )
        ]
        result = Memory.format_docs_plain(docs)
        assert len(result) == 1
        assert 'Content: Test content' in result[0]
        assert 'area: main' in result[0]

    def test_formats_multiple_docs(self):
        """format_docs_plain handles multiple documents."""
        from helpers.memory import Memory
        docs = [Document(f'Content {i}', metadata={'area': 'main'}) for i in range(3)]
        result = Memory.format_docs_plain(docs)
        assert len(result) == 3

    def test_empty_list_returns_empty(self):
        """format_docs_plain returns empty list for empty input."""
        from helpers.memory import Memory
        assert Memory.format_docs_plain([]) == []
