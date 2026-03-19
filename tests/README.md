# a0_memory Plugin — Test Suite

## Quick Start

~~~bash
# Run full suite
make test

# Unit tests only (fastest — no async, pure logic)
make test-unit

# Integration tests only
make test-integration

# API handler tests only
make test-api

# Run with coverage
make test-coverage
~~~

---

## Setup

### Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.13+ | `/opt/venv/bin/python3` |
| pytest | 9.0.2 | Already in `/opt/venv` |
| pytest-asyncio | 1.3.0 | Required for async Memory tests |
| simpleeval | 1.0.4 | Required for `_get_comparator` tests |
| faiss / langchain | — | **NOT required** — stubbed in `conftest.py` |

### Why no faiss/langchain in tests?

`helpers/memory.py` imports `faiss`, `langchain_community`, and `numpy` at module
top-level. These are A0 runtime dependencies not present in `/opt/venv`.

The root `conftest.py` installs `sys.modules` stubs for all heavy runtime deps
**before** any test module is imported. This allows testing all business logic
(insert, delete, search, CRUD, security fixes) without the A0 runtime.

---

## Running Tests

~~~bash
# All tests
python3 -m pytest tests/

# By marker
python3 -m pytest tests/ -m unit
python3 -m pytest tests/ -m integration
python3 -m pytest tests/ -m api

# Verbose output
python3 -m pytest tests/ -v

# Stop on first failure
python3 -m pytest tests/ -x

# Run specific file
python3 -m pytest tests/unit/test_get_comparator.py

# Run specific test
python3 -m pytest tests/unit/test_index_integrity.py::TestVerifyIndexHash::test_returns_false_when_index_tampered

# With short traceback (default in pytest.ini)
python3 -m pytest tests/ --tb=short
~~~

---

## Test Architecture

~~~
tests/
├── conftest.py              # ROOT: sys.modules stubs — MUST run first
│                            # Installs: faiss, langchain, numpy, agent, models,
│                            # helpers.*, plugins.* stubs before any import
├── factories/
│   └── memory_factory.py   # Document builders, metadata factories,
│                            # dashboard payload factories
├── unit/                    # Pure logic — no async, no I/O, no stubs needed beyond conftest
│   ├── test_get_comparator.py     # Security Fix #2: simpleeval filter hardening
│   ├── test_index_integrity.py   # Security Fix #1: FAISS SHA-256 hash sidecar
│   └── test_normalizers.py       # _cosine_normalizer, _score_normalizer
├── integration/             # Async Memory CRUD with mocked FAISS dict-backend
│   ├── conftest.py          # mock_faiss_db, memory_instance, populated_memory fixtures
│   └── test_memory_crud.py  # insert, delete, search, update, format_docs_plain
└── api/                     # MemoryDashboard handler action routing
    ├── conftest.py           # dashboard fixture with module-level Memory patch
    └── test_memory_dashboard.py  # search, delete, bulk_delete, update, subdirs, exceptions
~~~

### Fixture Hierarchy

~~~
conftest.py (root)
  └── sys.modules stubs (session-scoped side-effect)

integration/conftest.py
  ├── mock_db_store (function)    — fresh {} per test
  ├── mock_faiss_db (function)    — MagicMock with dict-backed async FAISS API
  ├── memory_instance (function)  — Memory() with patched _save_db_file + guids
  └── populated_memory (function) — memory_instance + 3 pre-inserted docs

api/conftest.py
  ├── sample_doc (function)       — single Document fixture
  ├── sample_docs (function)      — 3 Documents (2 main, 1 solutions)
  ├── make_mock_memory (helper)   — builds mock Memory instance
  ├── dashboard (function)        — MemoryDashboard with module-level patched Memory
  └── empty_dashboard (function)  — MemoryDashboard with empty store
~~~

### Key Design Decisions

**1. sys.modules stub order matters**  
Stubs must be installed in dependency order. `helpers.knowledge_import` must be
stubbed before `helpers.memory` is imported (relative import chain). See the
commented ordering in `tests/conftest.py`.

**2. Module-level import binding**  
`api/memory_dashboard.py` binds `Memory` at import time:
```python
from plugins._memory.helpers.memory import Memory, ...
```
Patching `sys.modules` after import does NOT update this binding. API test
fixtures patch `api.memory_dashboard.Memory` directly on the module object.

**3. get_document_by_id raises on missing ID**  
The source code does `return self.db.get_by_ids(id)[0]` which raises `IndexError`
when the ID is not found. Tests verify deletion via `db.get_all_docs()` dict checks
rather than calling `get_document_by_id` on deleted IDs.

**4. numpy.bool_ must be a real Python type**  
pytest's `pytest.approx` internally calls `isinstance(val, np.bool_)`. If
`np.bool_` is a `MagicMock`, `isinstance()` raises `TypeError`. The numpy stub
assigns `bool_` → `bool` to prevent this.

---

## Security Fix Coverage

### Fix 1 — FAISS Index Integrity (`test_index_integrity.py`)

| Test | Scenario | Risk |
|------|----------|------|
| `test_creates_sha256_sidecar_file` | Sidecar file created on write | HIGH |
| `test_sidecar_contains_correct_sha256` | Hash matches actual file | HIGH |
| `test_overwrites_existing_sidecar` | Re-write updates hash | HIGH |
| `test_returns_false_when_index_tampered` | Tampered index detected | HIGH |
| `test_fail_open_when_no_sidecar` | Legacy install: no sidecar → trust | MEDIUM |
| `test_fail_open_when_sidecar_unreadable` | Read error → trust (fail-open) | MEDIUM |
| `test_returns_false_when_sidecar_corrupted` | Wrong hash → reject | HIGH |
| `test_hash_write_then_verify_roundtrip` | Full write→tamper→verify cycle | HIGH |
| `test_large_index_hashed_correctly` | Chunked hashing >65536 bytes | MEDIUM |

⚠️ **Production gap**: `.a0proj/memory/default/` has no `index.faiss.sha256` sidecar
as of 2026-03-19. The `default` memory subdir is still in fail-open mode. The fix
will be applied on next `_save_db_file` call for that subdir.

### Fix 2 — simpleeval Filter Hardening (`test_get_comparator.py`)

| Category | Tests | Coverage |
|----------|-------|----------|
| Allowlist (valid filters) | 10 | Passes regex, evaluates correctly |
| Blocklist (18 attack patterns) | 17 pass + 1 xfail | Shell, import, exec, SQLi, injection |
| Length cap boundary | 3 | 512 chars pass, 513 reject |
| functions={} enforcement | 2 | len() blocked, comparisons work |
| Error handling | 3 | Undefined vars, malformed, empty metadata |

⚠️ **Known gap (xfail)**: `\n` in filter string passes the `\s` class in
`_FILTER_SAFE` regex. `simpleeval` evaluates only the first expression silently.
Recommend: replace `\s` with `[ \t]` or add explicit `\n` rejection.

---

## Best Practices

### Test naming convention
Test names follow: `test_{subject}_{condition}_{expected_result}`

~~~python
def test_area_equals_main_matches(self, sample_metadata):        # ✅
def test_it(self):                                                # ❌
~~~

### Test isolation
- Each test gets a fresh `mock_db_store = {}` — no shared state
- `Memory.index` class-level cache is never modified (we instantiate `Memory()` directly)
- `_save_db_file` is patched to no-op — no filesystem side effects in integration tests

### Async test pattern
~~~python
@pytest.mark.integration
class TestInsertText:
    async def test_insert_text_returns_id(self, memory_instance):
        doc_id = await memory_instance.insert_text('content')
        assert isinstance(doc_id, str)
~~~
`asyncio_mode = auto` in `pytest.ini` — no `@pytest.mark.asyncio` needed.

### Adding new unit tests
1. Import `Memory` from `helpers.memory` — stubs are already in `tests/conftest.py`
2. Test only static/class methods with pure inputs — no fixtures required
3. Mark with `@pytest.mark.unit`

### Adding new integration tests
1. Use `memory_instance` or `populated_memory` fixtures from `integration/conftest.py`
2. Verify state via `mem.db.get_all_docs()` dict — do NOT call `get_document_by_id` on potentially missing IDs
3. Mark with `@pytest.mark.integration`

---

## CI Integration Notes

### GitHub Actions (recommended)
~~~yaml
- name: Run tests
  run: python3 -m pytest tests/ -v --tb=short
  working-directory: /a0/usr/projects/a0_memory
~~~

### Quality gates
| Gate | Threshold | Rationale |
|------|-----------|----------|
| Unit tests (security fixes) | 100% pass | Zero tolerance for security regressions |
| Integration tests | 100% pass | Core CRUD must never regress |
| API handler tests | 100% pass | Dashboard actions are user-facing |
| xfail tests | Must XFAIL | If xfail passes unexpectedly → investigate |

### Known limitations
- `test_fail_open_when_sidecar_unreadable` is **skipped when running as root** (Docker)
  because `chmod 0o000` is ignored by root. This test is valid in non-root CI environments.
- Tests do not run against a live FAISS index — integration coverage is at the Memory
  business logic layer only. Vector similarity correctness requires a full A0 runtime test.

---

## Current Test Results

```
113 passed, 1 skipped, 1 xfailed in 0.53s

Unit:        65 tests  (37 _get_comparator, 14 index_integrity, 16 normalizers)
Integration: 27 tests  (insert, delete, search, update, format)
API:         23 tests  (search, delete, bulk_delete, update, subdirs, exceptions)

Skipped:  1  (chmod 0o000 ignored as root)
XFailed:  1  (newline injection — known \\s regex gap)
```
