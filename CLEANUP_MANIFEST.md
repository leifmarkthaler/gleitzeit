# Cleanup Manifest - Files to be Deleted vs Moved

## Files That Will Be DELETED (Data Loss - Backup First!)

### Log Files (will be deleted)
- `server.log`
- `server2.log`
- `server3.log`
- `server_batch_final.log`
- `server_batch_final2.log`
- `server_batch_test.log`
- `server_fixed.log`
- `server_hybrid_final.log`
- `server_hybrid_test.log`
- `server_hybrid_test2.log`
- `server_hybrid_test3.log`
- `server_param_debug.log`
- `server_sql_batch.log`
- `server_sql_batch2.log`
- `server_sql_fixed.log`
- `test_parallel.log`
- `ui_hybrid_test.log`

### Database Files (will be deleted)
- `gleitzeit.db`
- `gleitzeit_test.db`

### Test Output Files (will be deleted)
- `fail_test.txt`
- `hybrid_test_1.txt`
- `hybrid_test_2.txt`
- `hybrid_test_3.txt`
- `sql_test_1.txt`
- `sql_test_2.txt`
- `test_batch_file.txt`
- `test_file_1.txt`
- `test_file_2.txt`
- `test_file_3.txt`

### Backup Files (will be deleted)
- `__init__.py.bak`

### Build Artifacts (will be deleted)
- `src/gleitzeit.egg-info/` (entire directory)

### Cache Directories (will be deleted)
- All `__pycache__/` directories throughout the project
- `.pytest_cache/` directory

## Files That Will Be MOVED (No Data Loss)

### Python Test Files → `tests/integration/`
- `test_admin_methods.py`
- `test_api_debug.py`
- `test_api_endpoints.py`
- `test_api_registration.py`
- `test_auth_backends.py`
- `test_auth_implementation.py`
- `test_auth_modes.py`
- `test_client_autostart.py`
- `test_complex_workflow_redis.py`
- `test_delete_all_backends.py`
- `test_delete_methods.py`
- `test_delete_with_example.py`
- `test_duplicate_fix.py`
- `test_event_driven.py`
- `test_fail.py`
- `test_log_output.py`
- `test_log_streaming.py`
- `test_minimal_api.py`
- `test_modular_client.py`
- `test_new_endpoints.py`
- `test_os_import.py`
- `test_persistence.py`
- `test_queue_endpoints.py`
- `test_redis_event_architecture.py`
- `test_redis_events.py`
- `test_sql_architecture.py`
- `test_sql_event_architecture.py`
- `test_sql_retry.py`
- `test_workflow.py`

### YAML Test Files → `tests/workflows/`
- `test_complex_workflow.yaml`
- `test_dependency_workflow.yaml`
- `test_llm_only.yaml`
- `test_shared_engine.yaml`
- `test_ui_message.yaml`

### Shell Scripts → `tests/scripts/`
- `test_cli_commands.sh`

### Example Workflows → `examples/workflows/`
- `workflow1.yaml`
- `workflow2.yaml`

### Test Data → `tests/`
- `test_workflow.json`

## Files That Should Be Moved (Documentation)
**Recommendation: Move these to `docs/` directory**
- `auth-migration-guide.md`
- `client-restructure.md`
- `current-state-of-gleitzeit.md`
- `scaling-pathway.md`

## Scripts Created for Cleanup

1. **`backup_before_cleanup.sh`** - Creates a tarball backup of all files that will be deleted
2. **`cleanup.sh`** - Deletes temporary files, logs, databases, and cache directories
3. **`move_tests.sh`** - Moves test files to organized directories (separate from deletion)

## How to Use

1. **First**: Run `./backup_before_cleanup.sh` to create a safety backup
2. **Second**: Run `./cleanup.sh` to remove temporary and generated files
3. **Optional**: Run `./move_tests.sh` to reorganize test files
4. **Manual**: Move documentation files to `docs/` directory as needed

## Recovery

If you need to restore deleted files:
```bash
tar -xzf cleanup_backup_[timestamp].tar.gz
```

## Impact Summary

- **Files deleted**: ~35 files (logs, databases, test outputs, caches)
- **Files moved**: ~35 test files + 2 workflow files
- **Space recovered**: Several MB from logs and databases
- **No source code affected**: Only temporary, test, and generated files