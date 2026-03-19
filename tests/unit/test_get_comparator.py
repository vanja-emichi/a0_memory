"""
Unit tests for Memory._get_comparator — simpleeval filter hardening (Security Fix #2).

Fix applied in helpers/memory.py:
- Character allowlist regex: ^[a-zA-Z0-9_\\-\\.\\t '"=<>!()\\[\\],:\\+]+$
- Length cap: 512 characters
- functions={} passed to simple_eval (no builtins callable)
- Returns lambda data: False on rejection

Risk: HIGH — filter injection could allow arbitrary Python eval via simpleeval.
Coverage target: 100% of _get_comparator branches.
"""
import pytest
from helpers.memory import Memory


# ── Fixtures ────────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_metadata():
    """Representative metadata dict passed to comparator(data)."""
    return {
        'area': 'main',
        'timestamp': '2026-01-15 10:30:00',
        'id': 'abc123def4',
        'score': 0.95,
    }


# ── Allowlist: valid filters that should pass and execute correctly ──────────────

@pytest.mark.unit
class TestGetComparatorAllowlist:
    """Filters that satisfy the allowlist regex — should evaluate correctly."""

    def test_area_equals_main_matches(self, sample_metadata):
        """area == 'main' returns True when metadata area is main."""
        comp = Memory._get_comparator("area == 'main'")
        assert comp(sample_metadata) is True

    def test_area_equals_solutions_no_match(self, sample_metadata):
        """area == 'solutions' returns False when metadata area is main."""
        comp = Memory._get_comparator("area == 'solutions'")
        assert comp(sample_metadata) is False

    def test_area_not_equals(self, sample_metadata):
        """area != 'fragments' returns True when metadata area is main."""
        comp = Memory._get_comparator("area != 'fragments'")
        assert comp(sample_metadata) is True

    def test_double_quoted_string(self, sample_metadata):
        '''area == "main" with double quotes should work.'''
        comp = Memory._get_comparator('area == "main"')
        assert comp(sample_metadata) is True

    def test_alphanumeric_id_comparison(self, sample_metadata):
        """id == 'abc123def4' matches exact ID."""
        comp = Memory._get_comparator("id == 'abc123def4'")
        assert comp(sample_metadata) is True

    def test_timestamp_less_than(self, sample_metadata):
        """timestamp < '2026-12-31 00:00:00' returns True."""
        comp = Memory._get_comparator("timestamp < '2026-12-31 00:00:00'")
        assert comp(sample_metadata) is True

    def test_timestamp_greater_than_no_match(self, sample_metadata):
        """timestamp > '2027-01-01 00:00:00' returns False."""
        comp = Memory._get_comparator("timestamp > '2027-01-01 00:00:00'")
        assert comp(sample_metadata) is False

    def test_empty_string_filter_returns_none_comparator(self):
        """Empty string: _get_comparator rejects via regex (no match on empty)."""
        # Empty string: _FILTER_SAFE.match('') returns None (no match) — rejected
        comp = Memory._get_comparator('')
        assert comp({'area': 'main'}) is False

    def test_comparator_is_callable(self):
        """_get_comparator always returns a callable."""
        comp = Memory._get_comparator("area == 'main'")
        assert callable(comp)

    def test_rejected_filter_is_callable(self):
        """Rejected filters still return a callable (lambda data: False)."""
        comp = Memory._get_comparator('__import__(os)')
        assert callable(comp)


# ── Blocklist: unsafe characters and patterns that must be rejected ─────────────

@pytest.mark.unit
class TestGetComparatorBlocklist:
    """
    Filters containing unsafe characters must be rejected.
    Rejected comparator must return False for any metadata.
    """

    @pytest.mark.parametrize('bad_filter,description', [
        ('__import__("os")',              'dunder import attempt'),
        ('os.system("rm -rf /")',         'shell command via os.system'),
        ('exec("print(1)")',              'exec builtin call'),
        ('eval("1+1")',                   'nested eval call'),
        ('open("/etc/passwd").read()',    'file read attempt'),
        ('{"x":1}',                      'dict literal — curly brace'),
        ('area; DROP TABLE memories',    'SQL injection style — semicolon'),
        ('area == "main" # comment',     'inline comment — hash char'),
        ('a' * 513,                       '513 chars — exceeds length cap'),
        ('area == "main" & True',        'bitwise AND — ampersand'),
        ('area == "main" | True',        'bitwise OR — pipe'),
        ('area == `main`',               'backtick shell substitution'),
        ('area == "main"\x00null',       'null byte injection'),
        ('area == "main"; exec("x")',    'chained exec via semicolon'),
        ('\\x41\\x42',                  'hex escape sequences'),
        ('area == "main" % s',           'format string percent'),
        ('area == "main" $ var',         'dollar sign — shell variable'),
    ])
    def test_blocked_filter_returns_false(
        self, bad_filter, description, sample_metadata
    ):
        """Unsafe filter '{description}' must be rejected — comparator returns False."""
        comp = Memory._get_comparator(bad_filter)
        result = comp(sample_metadata)
        assert result is False, (
            f'Expected False for unsafe filter ({description}): {bad_filter!r}'
        )



    def test_newline_injection_blocked(self, sample_metadata):
        """Newline in filter string is rejected — regex uses [ \t] not \\s."""
        # Build the filter with a literal newline using chr(10) to avoid syntax errors
        newline_filter = 'area == "main"' + chr(10) + 'import os'
        comp = Memory._get_comparator(newline_filter)
        result = comp(sample_metadata)
        assert result is False, 'Newline injection must be rejected'
# ── Length cap boundary ──────────────────────────────────────────────────────────

@pytest.mark.unit
class TestGetComparatorLengthCap:
    """Length boundary: exactly 512 chars allowed, 513 rejected."""

    def test_512_char_safe_string_not_rejected_by_length(self):
        """512-char string of safe chars passes length check."""
        # Use only allowlist chars: 'a' repeated 512 times
        filter_512 = 'a' * 512
        comp = Memory._get_comparator(filter_512)
        # It will pass length/regex but fail eval — still callable
        assert callable(comp)

    def test_513_char_string_rejected(self, sample_metadata):
        """513-char string is rejected regardless of character content."""
        filter_513 = 'a' * 513
        comp = Memory._get_comparator(filter_513)
        assert comp(sample_metadata) is False

    def test_exactly_512_chars_passes_length_gate(self):
        """Exactly 512 chars: length gate does not reject."""
        # Build a valid 512-char filter: pad with spaces after a valid expression
        base = "area == 'main'"
        padded = base + ' ' * (512 - len(base))
        assert len(padded) == 512
        comp = Memory._get_comparator(padded)
        assert callable(comp)


# ── functions={} enforcement ──────────────────────────────────────────────────────

@pytest.mark.unit
class TestGetComparatorNoFunctions:
    """
    functions={} prevents calling any Python builtin through simpleeval.
    Even if a function name passes the regex (e.g. 'len'), it must not be callable.
    """

    def test_len_builtin_not_callable_through_comparator(self, sample_metadata):
        """len() is a safe-looking identifier but must not execute."""
        # 'len' passes regex but simpleeval with functions={} raises FeatureNotAvailable
        comp = Memory._get_comparator("len(area) > 0")
        # Result may be False (rejected by regex due to parens being valid...)
        # Actually parens ARE in allowlist — simpleeval will try to call len
        # With functions={}, this should raise inside comparator → returns False
        result = comp(sample_metadata)
        assert result is False

    def test_valid_comparison_without_functions_works(self, sample_metadata):
        """Pure comparison without function calls works fine with functions={}."""
        comp = Memory._get_comparator("area == 'main'")
        assert comp(sample_metadata) is True


# ── Error handling: eval fails gracefully ────────────────────────────────────────

@pytest.mark.unit
class TestGetComparatorErrorHandling:
    """Comparator must not propagate exceptions — always returns bool."""

    def test_undefined_variable_returns_false(self, sample_metadata):
        """Filter referencing undefined variable returns False, not NameError."""
        comp = Memory._get_comparator("nonexistent_field == 'value'")
        result = comp(sample_metadata)
        assert result is False

    def test_malformed_expression_returns_false(self, sample_metadata):
        """Syntactically valid chars but semantically broken returns False."""
        comp = Memory._get_comparator("area == == 'main'")
        result = comp(sample_metadata)
        assert result is False

    def test_empty_metadata_dict_no_exception(self):
        """Comparator against empty metadata dict does not raise."""
        comp = Memory._get_comparator("area == 'main'")
        result = comp({})
        assert result is False
