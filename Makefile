# a0_memory Plugin — Test Makefile
# Python: /opt/venv/bin/python3
# pytest: 9.0.2

PYTHON := python3
PYTEST := $(PYTHON) -m pytest
TEST_DIR := tests

.PHONY: test test-unit test-integration test-api test-coverage test-fast help

## Default: run full suite
test:
	$(PYTEST) $(TEST_DIR)/ -v --tb=short

## Unit tests only (fastest — pure logic, no async)
test-unit:
	$(PYTEST) $(TEST_DIR)/unit/ -v --tb=short -m unit

## Integration tests (async Memory CRUD with mocked FAISS)
test-integration:
	$(PYTEST) $(TEST_DIR)/integration/ -v --tb=short -m integration

## API handler tests (MemoryDashboard action routing)
test-api:
	$(PYTEST) $(TEST_DIR)/api/ -v --tb=short -m api

## Run with coverage report
test-coverage:
	$(PYTEST) $(TEST_DIR)/ --tb=short \
		--cov=helpers --cov=api \
		--cov-report=term-missing \
		--cov-report=html:htmlcov

## Fast: stop on first failure, minimal output
test-fast:
	$(PYTEST) $(TEST_DIR)/ -x -q --tb=line

## Security fix tests only (high-priority CI gate)
test-security:
	$(PYTEST) $(TEST_DIR)/unit/test_get_comparator.py \
	          $(TEST_DIR)/unit/test_index_integrity.py \
	          -v --tb=short

## Show available targets
help:
	@grep -E '^[a-zA-Z_-]+:' Makefile | \
	  awk -F':' '{printf "  make %-20s\n", $$1}'
