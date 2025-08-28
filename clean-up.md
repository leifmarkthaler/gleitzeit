# Gleitzeit 0.0.6 Directory Cleanup Recommendations

## Overview
This document provides recommendations for cleaning up and organizing the Gleitzeit 0.0.6 project directory to improve maintainability and reduce clutter.

## Critical Issues to Address

### 1. Log Files (HIGH PRIORITY)
**Files to remove:** All `.log` files in root directory
- `server.log`, `server2.log`, `server3.log`
- `server_batch_*.log`, `server_hybrid_*.log`
- `server_sql_*.log`, `server_fixed.log`
- `test_parallel.log`, `ui_hybrid_test.log`
- Total: ~15 log files

**Action:** These are already in `.gitignore` but exist in the directory. Remove immediately.

### 2. Database Files (HIGH PRIORITY)
**Files to remove:**
- `gleitzeit.db`
- `gleitzeit_test.db`

**Action:** These are test databases that should not be in version control. Already in `.gitignore`.

### 3. Test Output Files (MEDIUM PRIORITY)
**Files to remove:**
- `fail_test.txt`
- `hybrid_test_*.txt` (3 files)
- `sql_test_*.txt` (2 files)
- `test_batch_file.txt`
- `test_file_*.txt` (3 files)

**Action:** Remove these test-generated files.

### 4. Backup Files (MEDIUM PRIORITY)
**Files to remove:**
- `__init__.py.bak`

**Action:** Remove backup files.

## Organizational Improvements

### 1. Archive Directory
**Current state:** Contains 10 audit/report markdown files
**Recommendation:** Good practice - keep historical documentation archived

### 2. Documentation Structure
**Current issues:**
- Documentation spread across root (`*.md` files) and `docs/` directory
- Some docs in root should be in `docs/`:
  - `auth-migration-guide.md`
  - `client-restructure.md`
  - `current-state-of-gleitzeit.md`
  - `scaling-pathway.md`

**Recommendation:** Move technical documentation to `docs/` directory, keep only README, LICENSE, CHANGELOG in root.

### 3. Test Files Organization
**Current issues:**
- 30+ test files in root directory (`test_*.py`)
- Test shell script (`test_cli_commands.sh`)
- Test workflows (`test_*.yaml`)

**Recommendation:** Move all test files to appropriate subdirectories in `tests/`:
- `tests/integration/` for integration tests
- `tests/scripts/` for test scripts
- `tests/workflows/` for test workflow files

### 4. Example Workflows
**Current state:** `examples/` directory well-organized with 40+ example files
**Recommendation:** Keep as is - good reference material

### 5. Build Artifacts
**Current issues:**
- `src/gleitzeit.egg-info/` should not be tracked

**Recommendation:** This is already in `.gitignore` pattern (`*.egg-info/`) but exists. Remove it.

### 6. Experimental Directory
**Current state:** Contains RAG system and agent system experiments
**Recommendation:** Consider moving stable features to main codebase or clearly marking as experimental

## Cleanup Script

```bash
#!/bin/bash
# cleanup.sh - Run from project root

# Remove log files
rm -f *.log

# Remove database files
rm -f *.db

# Remove test output files
rm -f fail_test.txt
rm -f hybrid_test_*.txt
rm -f sql_test_*.txt
rm -f test_batch_file.txt
rm -f test_file_*.txt

# Remove backup files
rm -f *.bak

# Remove build artifacts
rm -rf src/gleitzeit.egg-info/

# Create directories if needed
mkdir -p tests/integration
mkdir -p tests/scripts
mkdir -p tests/workflows

# Move test files to tests directory (optional - review before running)
# mv test_*.py tests/integration/ 2>/dev/null
# mv test_*.yaml tests/workflows/ 2>/dev/null
# mv test_*.sh tests/scripts/ 2>/dev/null

echo "Cleanup complete!"
```

## Summary Statistics

- **Files to remove immediately:** ~35 files (logs, databases, test outputs)
- **Files to reorganize:** ~35 test files in root
- **Documentation to consolidate:** 4 root-level docs → `docs/`
- **Estimated space savings:** Several MB from logs and databases

## Priority Actions

1. **Immediate:** Remove all `.log` and `.db` files
2. **High:** Remove test output files and backup files
3. **Medium:** Reorganize test files into `tests/` subdirectories
4. **Low:** Consolidate documentation into `docs/`

## Next Steps

1. Run the cleanup script (review commands first)
2. Update `.gitignore` if any patterns are missing
3. Consider adding a `make clean` target or cleanup script to project
4. Document file organization standards in contributing guidelines