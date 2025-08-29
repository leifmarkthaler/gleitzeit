# Documentation Cleanup Recommendations

## Files to Remove

### 1. Event Persistence Documentation (Redundant/Outdated)
These files document features that were never fully integrated and reference deleted code:

- **EVENT-PERSISTENCE-STATUS.md** - References deleted redis_backend.py and reverted implementation
- **EVENT-PERSISTENCE-IMPLEMENTATION.md** - Implementation guide for feature that was reverted
- **EVENT-PERSISTENCE-COMPLETED.md** - Claims completion but feature was actually reverted
- **CURRENT-EVENT-IMPLEMENTATION.md** - Duplicate analysis of existing event system
- **event-engine-draft.md** - Draft/planning document, superseded by actual implementation

**Reason**: These 5 files document a feature that was attempted but reverted. The infrastructure exists but isn't integrated. Multiple overlapping documents about the same unfinished feature.

### 2. Execution Engine Documentation (References Deleted Files)
- **EXECUTION-ENGINE-ARCHITECTURE.md** - References deleted execution_engine_backup.py and execution_engine_refactored.py
- **docs/execution-engine-refactoring.md** - Old refactoring plan, already completed

**Reason**: References deleted backup files and completed refactoring work.

### 3. CLI/API Documentation (Outdated)
- **archive/CLI_API_MISALIGNMENT_REPORT.md** - References deleted gleitzeit_cli.py and api_commands.py

**Reason**: Analyzes misalignment in deleted CLI components.

### 4. Experimental/Draft Documentation
- **experimental/agentsystem/WORKFLOW_EXECUTION_GUIDE.md** - References deleted client_legacy.py
- **docs/tutorial-quick-ref.md** - May reference old APIs (needs verification)

**Reason**: References deleted legacy components.

## Files to Keep but Update

### 1. Core Documentation
- **current-state-of-gleitzeit.md** - Needs update to remove references to deleted files
- **STREAMLINE.md** - Active tracking document for cleanup efforts
- **archive/auth-implementation-summary.md** - Historical record, already in archive

### 2. Architecture Documentation
These should be reviewed and updated to reflect current state:
- **docs/architecture.md**
- **docs/providers.md** 
- **docs/cli.md** (if it references old CLI)

## Summary

**Recommended for Deletion: 10 files**
1. EVENT-PERSISTENCE-STATUS.md
2. EVENT-PERSISTENCE-IMPLEMENTATION.md
3. EVENT-PERSISTENCE-COMPLETED.md
4. CURRENT-EVENT-IMPLEMENTATION.md
5. event-engine-draft.md
6. EXECUTION-ENGINE-ARCHITECTURE.md
7. docs/execution-engine-refactoring.md
8. archive/CLI_API_MISALIGNMENT_REPORT.md
9. experimental/agentsystem/WORKFLOW_EXECUTION_GUIDE.md
10. docs/tutorial-quick-ref.md (verify first)

**Estimated Cleanup Impact:**
- Removes ~1,500+ lines of outdated documentation
- Eliminates confusion from multiple overlapping event persistence docs
- Removes references to 8 deleted source files
- Consolidates documentation to reflect current architecture

## Verification Commands

Before deletion, verify no critical information would be lost:
```bash
# Check if any remaining code references these docs
grep -r "EVENT-PERSISTENCE" src/ --include="*.py"
grep -r "EXECUTION-ENGINE" src/ --include="*.py"

# Archive instead of delete if unsure
mkdir -p archive/old-docs
mv EVENT-PERSISTENCE-*.md archive/old-docs/
mv event-engine-draft.md archive/old-docs/
```

## Next Steps

1. **Phase 1**: Delete event persistence documentation (5 files)
2. **Phase 2**: Delete execution engine docs (2 files)
3. **Phase 3**: Archive or delete experimental/outdated docs (3 files)
4. **Phase 4**: Update remaining docs to remove stale references