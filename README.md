# a0_memory — Enhanced Memory Plugin for Agent Zero

A drop-in enhancement of the official built-in Agent Zero `_memory` plugin with improved recall quality, production hardening, security fixes, and a full test suite.

> **Parent:** Official Agent Zero built-in `_memory` plugin — `a0_memory` forks and extends the official memory system shipped with Agent Zero.

---

## What's Different from the Official Plugin

The official `_memory` plugin provides the core memory foundation. `a0_memory` keeps every feature of the original and adds the following improvements:

### 1. Multi-Query Recall with Pure-Python NLP

**Problem:** The original plugin uses a single embedding query to search memories. Short or ambiguous user messages often miss relevant stored memories because the query vector doesn't cover all relevant concepts.

**Fix:** The recall extension now performs keyword extraction using a fast pure-Python NLP pipeline (no LLM call, no external library — runs in microseconds):

- Tokenises the user instruction with a regex
- Filters stopwords from a curated 80-word list
- Extracts up to 4 meaningful keyword terms
- Runs a separate FAISS search for each keyword alongside the main semantic query
- Deduplicates results by document metadata `id` (fallback: content hash)
- Allocates search limits proportionally across queries

**Result:** Significantly higher recall coverage for technical queries, named entities, and multi-concept instructions — without any latency overhead from an LLM call.

**Files changed:** `extensions/python/message_loop_prompts_after/_50_recall_memories.py`

---

### 2. FAISS Index Integrity Verification

**Problem:** `FAISS.load_local()` requires `allow_dangerous_deserialization=True` because FAISS stores indexes as Python pickle files. A tampered `index.faiss` file placed by an attacker could execute arbitrary Python code on load.

**Fix:** A SHA-256 sidecar file (`index.faiss.sha256`) is written alongside `index.faiss` every time the database is saved. On every load, the sidecar is verified before `load_local()` is called:

- Hash matches → normal load
- Hash mismatch → index rebuild (tamper detected, warning logged)
- No sidecar found → fail-open for legacy installs (sidecar written on next save)

**Files changed:** `helpers/memory.py` — `_write_index_hash()`, `_verify_index_hash()`

---

### 3. Memory Filter Injection Hardening

**Problem:** The `memory_load` tool accepts user-supplied filter strings (e.g. `area=='main'`) which are evaluated by `simpleeval`. Without validation, crafted strings could probe the evaluator or invoke built-in callables.

**Fix:** `_get_comparator()` now applies three layers of defence before any evaluation:

1. **Character allowlist regex** — permits only alphanumerics, space, tab, and safe punctuation. Newlines, semicolons, backticks, and shell meta-characters are rejected.
2. **Length cap** — filters longer than 512 characters are rejected.
3. **`functions={}`** — explicitly blocks all callables inside `simpleeval`.

All existing valid filter patterns continue to work unchanged:

```
area=='main'
area == 'fragments' or area == 'solutions'
area=='main' and timestamp<'2024-01-01 00:00:00'
timestamp.startswith('2022-01-01')
```

**Files changed:** `helpers/memory.py` — `_get_comparator()`

---

### 4. Context Truncation Fix (BadRequestError Prevention)

**Problem:** The original `_50_memorize_fragments.py` and `_51_memorize_solutions.py` pass the full conversation history to the utility LLM. In long sessions this exceeds the model's context window and throws a `BadRequestError`, silently failing to memorize anything.

**Fix:** Both extensions truncate `msgs_text` to the last 80,000 characters (~20K tokens) before any LLM call. Memorization only needs recent context — the tail of the conversation is always the most relevant.

**Files changed:**
- `extensions/python/monologue_end/_50_memorize_fragments.py`
- `extensions/python/monologue_end/_51_memorize_solutions.py`

---

### 5. Similarity Search with Scores API

**Problem:** The original `search_similarity_threshold()` returns `Document` objects only — the relevance score is discarded. The memory dashboard and advanced filtering cannot rank or display confidence levels.

**Fix:** New method `search_similarity_threshold_with_scores()` returns `list[tuple[Document, float]]` — the same search with relevance scores preserved and sorted descending.

**Files changed:** `helpers/memory.py` — `search_similarity_threshold_with_scores()`

---

### 6. Plugin-Isolated Configuration Loader

**Problem:** The original plugin directly accesses `agent.config.embeddings_model`, tightly coupling to the Agent Zero core config structure.

**Fix:** `a0_memory` resolves the embedding model through `plugins.get_plugin_config()`, making it configurable per-project and per-agent independently of the core agent config.

**Files changed:** `helpers/memory.py` — `_get_embedding_config()`

---

### 7. Default Configuration Changes

| Setting | Official `_memory` | `a0_memory` | Reason |
|---------|:-----------------:|:-----------:|--------|
| `memory_recall_delayed` | `false` | `true` | Avoids blocking the first message turn; improves response latency |
| `memory_memorize_consolidation` | `true` | `false` | Consolidation uses extra LLM calls per monologue; disabled by default to reduce cost. Enable for long-running agents where deduplication matters. |

---

## Feature Comparison

| Feature | Official `_memory` | `a0_memory` |
|---------|:-----------------:|:-----------:|
| FAISS vector store | Yes | Yes |
| Auto-recall on message | Yes | Yes |
| Auto-memorize fragments | Yes | Yes |
| Auto-memorize solutions | Yes | Yes |
| Memory dashboard UI | Yes | Yes |
| Knowledge import | Yes | Yes |
| Memory consolidation | Yes | Yes |
| Behaviour adjustment | Yes | Yes |
| Multi-query NLP recall | No | Yes |
| FAISS index integrity | No | Yes |
| Filter injection hardening | No | Yes |
| Context truncation fix | No | Yes |
| Search with scores API | No | Yes |
| Plugin-isolated config | No | Yes |
| Test suite (114 tests) | No | Yes |

---

## Installation

```bash
git clone https://github.com/vanja-emichi/a0_memory.git /path/to/agent-zero/usr/plugins/a0_memory
```

Then enable it from the Agent Zero Plugins UI. The official `_memory` plugin should be **disabled** to avoid conflicts — `a0_memory` is a full replacement.

---

## Running Tests

```bash
make test              # full suite
make test-unit         # 65 tests — security fixes, normalizers (pure logic)
make test-integration  # 27 tests — async CRUD with mocked FAISS
make test-api          # 23 tests — memory dashboard action routing
make test-security     # security fixes only — use as CI gate
make test-coverage     # + HTML coverage report at htmlcov/
```

The test suite uses a custom stub layer (`tests/conftest.py`) to isolate `faiss`, `langchain_community`, and `numpy` — no full Agent Zero runtime needed for unit or API tests.

---

## Configuration

All settings from the official plugin are supported. Changed defaults:

```yaml
memory_recall_delayed: true           # non-blocking recall (recommended)
memory_memorize_consolidation: false  # disable LLM consolidation by default
```

Configure per-project or per-agent from the Agent Zero Settings > Memory tab.

---

## Security

- **FAISS integrity**: Index files are SHA-256 verified on every load. Tampered indexes are rejected and rebuilt. Existing installations without sidecars are accepted on first load (fail-open); the sidecar is written on the next save.
- **Filter validation**: All `memory_load` filter strings are validated against a strict character allowlist before evaluation. Injection attempts are rejected and logged.

