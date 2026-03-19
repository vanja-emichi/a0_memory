"""
Unit tests for FAISS index integrity helpers (Security Fix #1).

Fix applied in helpers/memory.py:
- Memory._write_index_hash(abs_dir): writes SHA-256 of index.faiss → index.faiss.sha256
- Memory._verify_index_hash(abs_dir): verifies hash; fail-open on missing sidecar;
  returns False on mismatch; fail-open on read errors

Risk: HIGH — tampered FAISS index could cause silent corruption or RCE via
malicious pickle deserialization. Hash sidecar detects tampering before load.

Coverage target: 100% of _write_index_hash and _verify_index_hash branches.
"""
import os
import hashlib
import pytest
from helpers.memory import Memory

# Running as root in Docker: chmod 0o000 is ignored by root → skip that test
_running_as_root = os.getuid() == 0


# ── Helpers ────────────────────────────────────────────────────────────────────

def _write_fake_index(directory: str, content: bytes = b'fake faiss index data') -> str:
    """Write a fake index.faiss file and return its path."""
    path = os.path.join(directory, 'index.faiss')
    with open(path, 'wb') as f:
        f.write(content)
    return path


def _sha256_of(data: bytes) -> str:
    """Compute SHA-256 hex digest of bytes."""
    return hashlib.sha256(data).hexdigest()


# ── _write_index_hash ──────────────────────────────────────────────────────────

@pytest.mark.unit
class TestWriteIndexHash:
    """Tests for Memory._write_index_hash(abs_dir)."""

    def test_creates_sha256_sidecar_file(self, tmp_path):
        """_write_index_hash creates index.faiss.sha256 next to index.faiss."""
        _write_fake_index(str(tmp_path))
        Memory._write_index_hash(str(tmp_path))

        sidecar = tmp_path / 'index.faiss.sha256'
        assert sidecar.exists(), 'index.faiss.sha256 must be created'

    def test_sidecar_contains_correct_sha256(self, tmp_path):
        """Sidecar contains the exact SHA-256 hex digest of index.faiss."""
        content = b'deterministic faiss index content'
        _write_fake_index(str(tmp_path), content)
        Memory._write_index_hash(str(tmp_path))

        sidecar = tmp_path / 'index.faiss.sha256'
        stored = sidecar.read_text().strip()
        expected = _sha256_of(content)
        assert stored == expected, f'Stored hash {stored!r} != expected {expected!r}'

    def test_overwrites_existing_sidecar(self, tmp_path):
        """Re-writing after index change updates the sidecar with new hash."""
        index_path = os.path.join(str(tmp_path), 'index.faiss')

        # Write initial index and hash
        with open(index_path, 'wb') as f:
            f.write(b'original index data')
        Memory._write_index_hash(str(tmp_path))

        # Modify index
        with open(index_path, 'wb') as f:
            f.write(b'modified index data')
        Memory._write_index_hash(str(tmp_path))

        sidecar = tmp_path / 'index.faiss.sha256'
        stored = sidecar.read_text().strip()
        expected = _sha256_of(b'modified index data')
        assert stored == expected, 'Sidecar must reflect updated index'

    def test_sidecar_is_64_char_hex(self, tmp_path):
        """SHA-256 hex digest is always exactly 64 hex characters."""
        _write_fake_index(str(tmp_path))
        Memory._write_index_hash(str(tmp_path))

        sidecar = tmp_path / 'index.faiss.sha256'
        stored = sidecar.read_text().strip()
        assert len(stored) == 64
        assert all(c in '0123456789abcdef' for c in stored)

    def test_missing_index_file_does_not_raise(self, tmp_path):
        """If index.faiss doesn't exist, _write_index_hash handles gracefully."""
        # Should not raise — internal try/except catches FileNotFoundError
        try:
            Memory._write_index_hash(str(tmp_path))
        except Exception as e:
            pytest.fail(f'_write_index_hash raised unexpectedly: {e}')

    def test_large_index_hashed_correctly(self, tmp_path):
        """Large file (>65536 bytes) is chunked and hashed correctly."""
        # 65536 is the chunk size in the implementation
        large_content = b'X' * 200_000
        _write_fake_index(str(tmp_path), large_content)
        Memory._write_index_hash(str(tmp_path))

        sidecar = tmp_path / 'index.faiss.sha256'
        stored = sidecar.read_text().strip()
        expected = _sha256_of(large_content)
        assert stored == expected, 'Large file hash must be correct'


# ── _verify_index_hash ─────────────────────────────────────────────────────────

@pytest.mark.unit
class TestVerifyIndexHash:
    """Tests for Memory._verify_index_hash(abs_dir)."""

    def test_returns_true_when_hash_matches(self, tmp_path):
        """Returns True when index.faiss matches its sidecar hash."""
        _write_fake_index(str(tmp_path))
        Memory._write_index_hash(str(tmp_path))

        result = Memory._verify_index_hash(str(tmp_path))
        assert result is True

    def test_returns_false_when_index_tampered(self, tmp_path):
        """Returns False when index.faiss content changes after hash was written."""
        index_path = _write_fake_index(str(tmp_path))
        Memory._write_index_hash(str(tmp_path))

        # Tamper with the index file
        with open(index_path, 'wb') as f:
            f.write(b'TAMPERED CONTENT - attacker modified this')

        result = Memory._verify_index_hash(str(tmp_path))
        assert result is False, 'Tampered index must return False'

    def test_fail_open_when_no_sidecar(self, tmp_path):
        """Returns True (fail-open) when no sidecar exists — legacy install."""
        _write_fake_index(str(tmp_path))
        # Do NOT call _write_index_hash — no sidecar

        result = Memory._verify_index_hash(str(tmp_path))
        assert result is True, 'No sidecar = fail-open (legacy install) must return True'

    @pytest.mark.skipif(_running_as_root, reason='chmod 0o000 is ignored when running as root')
    def test_fail_open_when_sidecar_unreadable(self, tmp_path):
        """Returns True (fail-open) when sidecar file cannot be read."""
        _write_fake_index(str(tmp_path))
        Memory._write_index_hash(str(tmp_path))

        # Make sidecar unreadable
        sidecar_path = os.path.join(str(tmp_path), 'index.faiss.sha256')
        os.chmod(sidecar_path, 0o000)

        try:
            result = Memory._verify_index_hash(str(tmp_path))
            # Fail-open: exception during hash check returns True
            assert result is True, 'Unreadable sidecar must fail-open (return True)'
        finally:
            os.chmod(sidecar_path, 0o644)  # Restore for cleanup

    def test_returns_false_when_sidecar_corrupted(self, tmp_path):
        """Returns False when sidecar contains wrong hash (not a read error)."""
        _write_fake_index(str(tmp_path))
        Memory._write_index_hash(str(tmp_path))

        # Corrupt the sidecar with a wrong (but readable) hash
        sidecar_path = os.path.join(str(tmp_path), 'index.faiss.sha256')
        with open(sidecar_path, 'w') as f:
            f.write('0' * 64)  # Valid-looking hash but wrong

        result = Memory._verify_index_hash(str(tmp_path))
        assert result is False, 'Corrupted sidecar with wrong hash must return False'

    def test_hash_write_then_verify_roundtrip(self, tmp_path):
        """Full roundtrip: write hash → verify → True. Modify → verify → False."""
        index_path = _write_fake_index(str(tmp_path), b'original content')
        Memory._write_index_hash(str(tmp_path))
        assert Memory._verify_index_hash(str(tmp_path)) is True

        # Simulate atomic index update
        with open(index_path, 'wb') as f:
            f.write(b'updated content after reindexing')
        assert Memory._verify_index_hash(str(tmp_path)) is False

        # Hash updated — verify passes again
        Memory._write_index_hash(str(tmp_path))
        assert Memory._verify_index_hash(str(tmp_path)) is True

    def test_empty_index_file_hashed_and_verified(self, tmp_path):
        """Empty index.faiss is a valid edge case — must hash and verify correctly."""
        _write_fake_index(str(tmp_path), b'')
        Memory._write_index_hash(str(tmp_path))

        result = Memory._verify_index_hash(str(tmp_path))
        assert result is True
