# Enhanced Agent Progress & Findings Schema

## Improved Progress JSONL Format

### Every 30-60 seconds, agents should log:

```jsonl
{"timestamp": "2025-09-09T00:05:30Z", "agent_id": "db_specialist-123", "action": "analyzing_connection_pools", "sub_task": "Database Connection Analysis", "sub_progress": 60, "overall_progress": 25, "status": "working", "context": "Found max_connections=20, analyzing utilization patterns", "eta_subtask": "90s", "eta_overall": "4m"}

{"timestamp": "2025-09-09T00:06:00Z", "agent_id": "db_specialist-123", "action": "running_explain_queries", "sub_task": "Query Performance Analysis", "sub_progress": 15, "overall_progress": 35, "status": "working", "context": "Analyzing login query execution plan", "finding_preview": "Missing index detected on users.email", "eta_subtask": "120s", "eta_overall": "3m"}

{"timestamp": "2025-09-09T00:06:30Z", "agent_id": "db_specialist-123", "action": "documenting_critical_issue", "sub_task": "Query Performance Analysis", "sub_progress": 80, "overall_progress": 45, "status": "critical_finding", "context": "Confirmed missing index causing 3-4s delays", "eta_subtask": "30s", "eta_overall": "2.5m"}
```

## Enhanced Findings JSONL Format (Real-time Discoveries)

### Instead of single JSON file, append findings as discovered:

```jsonl
{"timestamp": "2025-09-09T00:05:45Z", "agent_id": "db_specialist-123", "type": "finding", "severity": "HIGH", "category": "performance", "issue": "Missing index on users.email column", "impact": "3-4 second delay per login query", "confidence": "confirmed", "evidence": "EXPLAIN shows seq scan on 50k records", "fix": "CREATE INDEX idx_users_email ON users(email);"}

{"timestamp": "2025-09-09T00:07:12Z", "agent_id": "db_specialist-123", "type": "finding", "severity": "HIGH", "category": "performance", "issue": "N+1 query in user permissions loading", "impact": "15+ queries per login instead of 2", "confidence": "confirmed", "evidence": "Query log shows repeated SELECT from roles table", "fix": "Add eager loading for user.roles relationship"}

{"timestamp": "2025-09-09T00:08:30Z", "agent_id": "db_specialist-123", "type": "finding", "severity": "MEDIUM", "category": "capacity", "issue": "Connection pool exhaustion", "impact": "Connections waiting up to 2 seconds", "confidence": "likely", "evidence": "Pool utilization at 95%+ during peak", "fix": "Increase max_connections from 20 to 100"}
```

## Progress Status Values
- `starting` - Agent initializing
- `working` - Actively analyzing/investigating  
- `blocked` - Waiting for resource/dependency
- `critical_finding` - Found major issue, documenting
- `completing` - Finalizing analysis
- `completed` - Task finished

## Action Categories
- `analyzing_*` - Investigating specific component
- `running_*` - Executing tests/queries/scans
- `documenting_*` - Writing findings/reports  
- `synthesizing_*` - Combining/analyzing results
- `waiting_*` - Blocked on external dependency

## Key Improvements
1. **Frequent Updates**: Every 30-60s instead of major milestones only
2. **Real-time Context**: What agent is actually doing right now
3. **Progress Granularity**: Both sub-task and overall percentages  
4. **Time Estimates**: ETA for current work and total completion
5. **Incremental Findings**: Discoveries logged as they happen
6. **Status Tracking**: Clear indication of agent state
7. **Evidence Collection**: Findings include supporting evidence