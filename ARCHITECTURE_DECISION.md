# Architecture Decision Record: ExecutionEngine Refactoring

**Date:** 2025-08-31  
**Decision:** Option B - Incremental Refactoring of ExecutionEngine  
**Status:** Approved and In Progress

## Context

After conducting an architecture audit, we identified that:
1. ExecutionEngine is overloaded with 1,708 lines and 20+ responsibilities
2. An orchestration layer was attempted but lacks critical features (parameter substitution, retry logic, provider execution, timeouts, result storage)
3. We now have two incomplete systems instead of one working system
4. Technical debt has increased rather than decreased

## Decision

**We will pursue Option B: Incremental refactoring of the existing ExecutionEngine**

## Rationale

### Why Option B over Option A (Complete Orchestration)

1. **Lower Risk**
   - Working with proven, production-tested code
   - No feature regression during migration
   - Incremental changes can be validated at each step

2. **Faster Time to Value**
   - 3-4 weeks vs 6+ weeks for feature parity
   - Immediate improvements to existing system
   - No parallel system maintenance

3. **Pragmatic Approach**
   - Achieves same architectural goals without full rewrite
   - Lessons learned from orchestration attempt inform refactoring
   - Shared services benefit entire codebase

4. **Clear Migration Path**
   - Extract services that can be reused
   - Gradually reduce ExecutionEngine responsibilities
   - No "big bang" deployment required

## Implementation Plan

### Phase 1: Extract Shared Services (Week 1-2)
- [x] Document architecture decision
- [ ] Extract ParameterResolver from ExecutionEngine
- [ ] Create UnifiedDependencyManager
- [ ] Update ExecutionEngine to use new services
- [ ] Archive orchestration attempt

### Phase 2: Core Refactoring (Week 3-4)
- [ ] Extract WorkflowManager from ExecutionEngine
- [ ] Extract TaskExecutor from ExecutionEngine
- [ ] Create lightweight TaskOrchestrator
- [ ] Reduce ExecutionEngine to <500 lines

### Phase 3: Event Simplification (Week 5-6)
- [ ] Implement EventCoordinator
- [ ] Reduce event chains from 8+ to 3-4 hops
- [ ] Remove circular dependencies

## Success Criteria

1. **Code Quality**
   - ExecutionEngine reduced from 1,708 to <500 lines
   - No component exceeds 500 lines
   - Clear separation of concerns

2. **Functionality**
   - All existing features preserved
   - No breaking changes to API
   - Improved testability

3. **Performance**
   - No performance regression
   - Reduced event latency
   - Lower memory footprint

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing workflows | High | Comprehensive test suite, gradual rollout |
| Performance regression | Medium | Benchmark before/after each change |
| Scope creep | Medium | Strict adherence to phases, no new features |

## Alternative Considered

**Option A: Complete the Orchestration Layer**
- Rejected due to high effort (6+ weeks) and risk of reimplementing bugs
- Would require maintaining two systems during extended migration
- No clear advantage over incremental refactoring

## Review and Approval

- **Proposed by:** Architecture Audit Team
- **Reviewed by:** Development Team
- **Approved by:** Project Lead
- **Review Date:** 2025-08-31

## References

- [ARCHITECTURE-AUDIT.md](./ARCHITECTURE-AUDIT.md)
- Original ExecutionEngine: `src/gleitzeit/core/execution_engine.py`
- Orchestration attempt: `src/gleitzeit/orchestration/`

---

*This decision will be reviewed after Phase 1 completion to validate approach*