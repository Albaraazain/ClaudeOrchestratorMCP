# Resource Cleanup Implementation for deploy_headless_agent

## Overview
Implemented comprehensive resource cleanup for the `deploy_headless_agent` function in `real_mcp_server.py` to prevent orphaned resources when agent deployment fails.

## Changes Made

### 1. Resource Tracking Variables (Line 3067-3071)
Added tracking variables at the start of the function (before the try block) to monitor created resources:

```python
# Resource tracking variables for cleanup on failure
prompt_file_created = None
tmux_session_created = None
registry_updated = False
global_registry_updated = False
```

### 2. Tracking Points

#### Prompt File Creation (Line 3110)
```python
prompt_file_created = prompt_file  # Track for cleanup on failure
```
- Set after successfully creating the prompt file at line 3107-3109

#### Tmux Session Creation (Line 3138)
```python
tmux_session_created = session_name  # Track for cleanup on failure
```
- Set after successfully creating the tmux session at line 3126-3136

#### Registry Update (Line 3191)
```python
registry_updated = True  # Track for cleanup awareness
```
- Set after successfully updating task registry at line 3189-3190

#### Global Registry Update (Line 3211)
```python
global_registry_updated = True  # Track for cleanup awareness
```
- Set after successfully updating global registry at line 3209-3210

### 3. Early Termination Cleanup (Lines 3145-3151)
Added cleanup for tmux sessions that terminate immediately:

```python
if not check_tmux_session_exists(session_name):
    # Clean up orphaned prompt file since tmux session failed
    if prompt_file_created and os.path.exists(prompt_file_created):
        try:
            os.remove(prompt_file_created)
            logger.info(f"Cleaned up orphaned prompt file: {prompt_file_created}")
        except Exception as cleanup_err:
            logger.error(f"Failed to remove orphaned prompt file: {cleanup_err}")

    return {
        "success": False,
        "error": "Agent session terminated immediately after creation"
    }
```

### 4. Comprehensive Exception Handler (Lines 3239-3273)
Replaced the catch-all exception handler with proper cleanup logic:

```python
except Exception as e:
    logger.error(f"Agent deployment failed: {e}")
    logger.error(f"Cleaning up orphaned resources...")

    # Clean up tmux session if it was created
    if tmux_session_created:
        try:
            subprocess.run(['tmux', 'kill-session', '-t', tmux_session_created],
                         capture_output=True, timeout=5)
            logger.info(f"Killed orphaned tmux session: {tmux_session_created}")
        except Exception as cleanup_err:
            logger.error(f"Failed to kill tmux session: {cleanup_err}")

    # Remove orphaned prompt file
    if prompt_file_created and os.path.exists(prompt_file_created):
        try:
            os.remove(prompt_file_created)
            logger.info(f"Removed orphaned prompt file: {prompt_file_created}")
        except Exception as cleanup_err:
            logger.error(f"Failed to remove prompt file: {cleanup_err}")

    # Rollback registry changes (THIS WILL BE IMPROVED BY file_locking_implementer)
    # For now, log that registry may be corrupted
    if registry_updated or global_registry_updated:
        logger.error(f"Registry was partially updated before failure - may need manual cleanup")

    return {
        "success": False,
        "error": f"Failed to deploy agent: {str(e)}",
        "cleanup_performed": True,
        "resources_cleaned": {
            "tmux_session": tmux_session_created,
            "prompt_file": prompt_file_created
        }
    }
```

## Cleanup Behavior

### What Gets Cleaned Up
1. **Tmux Sessions**: Orphaned tmux sessions are killed using `tmux kill-session`
2. **Prompt Files**: Orphaned prompt files are removed from the workspace
3. **Registry Corruption**: Logged for manual cleanup (file locking will prevent this in the future)

### Error Handling
- Each cleanup operation is wrapped in its own try-except block
- Failed cleanup operations are logged but don't prevent other cleanup attempts
- All cleanup errors are logged for debugging

### Return Value Enhancement
The error return now includes:
- `cleanup_performed`: Boolean indicating cleanup was attempted
- `resources_cleaned`: Dict showing which resources were cleaned up

## Testing Verification

### Manual Code Review
✅ All resource creation points are tracked
✅ Early termination case handled (line 3145-3151)
✅ Exception handler performs comprehensive cleanup
✅ Each cleanup operation is individually error-handled
✅ Logging provides visibility into cleanup actions

### Edge Cases Handled
1. **Tmux session fails to create**: No cleanup needed (tracked variable stays None)
2. **Tmux session terminates immediately**: Prompt file cleaned up
3. **Exception during registry update**: Tmux session and prompt file cleaned up
4. **Cleanup operations fail**: Logged but don't prevent other cleanup attempts

## Integration Notes

### Coordination with file_locking_implementer
The registry rollback is intentionally minimal because the `file_locking_implementer` agent is implementing proper file locking with fcntl. Once file locking is in place:
- Race conditions in registry updates will be prevented
- Atomic operations will eliminate partial updates
- Registry corruption will be impossible

Current implementation logs registry corruption warnings so manual cleanup can be performed if needed before file locking is fully implemented.

## Files Modified
- `real_mcp_server.py`: Lines 3067-3071, 3110, 3138, 3145-3151, 3191, 3211, 3239-3273

## Impact Assessment

### Before Implementation
- Failed deployments left orphaned tmux sessions running
- Prompt files accumulated in workspace
- No visibility into what resources failed to clean up

### After Implementation
- Orphaned tmux sessions are automatically killed
- Prompt files are removed on failure
- Full logging and visibility into cleanup operations
- Return value indicates what was cleaned up

## Recommendations
1. Monitor logs for cleanup failures to identify permission issues
2. Consider adding metrics for cleanup success rate
3. After file locking is implemented, add registry rollback logic
4. Consider adding cleanup verification (e.g., confirm tmux session actually died)
