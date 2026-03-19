"""
Test data factories for a0_memory plugin tests.

Provides builder functions for Document, metadata, and memory search
result fixtures. Uses plain Python — no external faker dependency.
"""
import sys
import uuid
from datetime import datetime
from typing import Any

# Document is the real stub class installed in root conftest
Document = sys.modules['langchain_core.documents'].Document


# ── ID Generators ──────────────────────────────────────────────────────────────

def make_doc_id(prefix: str = '') -> str:
    """Generate a 10-char random ID like guids.generate_id() does."""
    return (prefix + uuid.uuid4().hex[:10])[:10]


def make_timestamp(dt: datetime = None) -> str:
    """Return a Memory-formatted timestamp string."""
    return (dt or datetime(2026, 1, 15, 10, 30, 0)).strftime("%Y-%m-%d %H:%M:%S")


# ── Document Factories ─────────────────────────────────────────────────────────

def make_document(
    content: str = 'Test memory content',
    area: str = 'main',
    doc_id: str = None,
    timestamp: str = None,
    **extra_metadata: Any,
) -> 'Document':
    """
    Build a Document with standard a0_memory metadata.

    Args:
        content: Page content of the document.
        area: Memory area ('main', 'fragments', 'solutions', 'instruments').
        doc_id: Document ID. Auto-generated if None.
        timestamp: Timestamp string. Defaults to 2026-01-15 10:30:00.
        **extra_metadata: Additional metadata key-value pairs.

    Returns:
        Document instance with complete metadata.
    """
    return Document(
        page_content=content,
        metadata={
            'id': doc_id or make_doc_id(),
            'area': area,
            'timestamp': timestamp or make_timestamp(),
            **extra_metadata,
        },
    )


def make_main_memory(
    content: str = 'Agent Zero remembered this fact.',
    doc_id: str = None,
    **kwargs,
) -> 'Document':
    """Build a 'main' area memory document."""
    return make_document(content=content, area='main', doc_id=doc_id, **kwargs)


def make_fragment_memory(
    content: str = 'Fragment of a conversation.',
    doc_id: str = None,
    **kwargs,
) -> 'Document':
    """Build a 'fragments' area memory document."""
    return make_document(content=content, area='fragments', doc_id=doc_id, **kwargs)


def make_solution_memory(
    content: str = 'Solution to problem XYZ: use approach ABC.',
    doc_id: str = None,
    **kwargs,
) -> 'Document':
    """Build a 'solutions' area memory document."""
    return make_document(content=content, area='solutions', doc_id=doc_id, **kwargs)


def make_knowledge_document(
    content: str = 'Knowledge base entry.',
    source_file: str = '/knowledge/default/facts.md',
    doc_id: str = None,
    **kwargs,
) -> 'Document':
    """Build a knowledge-source document (from file ingestion)."""
    return make_document(
        content=content,
        area='main',
        doc_id=doc_id,
        knowledge_source=True,
        source_file=source_file,
        file_type='md',
        **kwargs,
    )


def make_document_batch(
    count: int = 5,
    area: str = 'main',
    content_prefix: str = 'Memory entry',
) -> list:
    """
    Build a list of `count` documents.

    Useful for bulk insert / delete integration tests.
    """
    return [
        make_document(
            content=f'{content_prefix} {i+1}',
            area=area,
            doc_id=make_doc_id(f'{i:04d}'),
        )
        for i in range(count)
    ]


# ── Memory Filter Factories ────────────────────────────────────────────────────

def make_area_filter(area: str) -> str:
    """Build a safe area filter expression for _get_comparator."""
    return f"area == '{area}'"


def make_timestamp_filter(before: str) -> str:
    """Build a safe timestamp filter (before a given date string)."""
    return f"timestamp < '{before}'"


# ── Dashboard Payload Factories ────────────────────────────────────────────────

def make_search_input(
    memory_subdir: str = 'default',
    search: str = 'test query',
    area: str = '',
    limit: int = 10,
    threshold: float = 0.6,
) -> dict:
    """Build a search action payload for MemoryDashboard.process()."""
    return {
        'action': 'search',
        'memory_subdir': memory_subdir,
        'search': search,
        'area': area,
        'limit': limit,
        'threshold': threshold,
    }


def make_delete_input(memory_id: str, memory_subdir: str = 'default') -> dict:
    """Build a delete action payload."""
    return {
        'action': 'delete',
        'memory_id': memory_id,
        'memory_subdir': memory_subdir,
    }


def make_bulk_delete_input(memory_ids: list, memory_subdir: str = 'default') -> dict:
    """Build a bulk_delete action payload."""
    return {
        'action': 'bulk_delete',
        'memory_ids': memory_ids,
        'memory_subdir': memory_subdir,
    }


def make_update_input(
    original: dict,
    edited: dict,
    memory_subdir: str = 'default',
) -> dict:
    """Build an update action payload."""
    return {
        'action': 'update',
        'memory_subdir': memory_subdir,
        'original': original,
        'edited': edited,
    }
