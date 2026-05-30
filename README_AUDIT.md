# Audit Log System

The PM Validator includes a persistent audit log to track system activity and user actions.

## Logged Events

| Event Type | Triggered When | Details Logged |
| :--- | :--- | :--- |
| `PDF_SUBMITTED` | A new PDF is uploaded for extraction | Filename, Client IP, Job ID |
| `JOB_STARTED` | An extraction worker begins processing | Filename, Job ID |
| `JOB_COMPLETED` | Extraction finishes successfully | Task ID (dir name), Job ID |
| `JOB_FAILED` | Extraction fails with an error | Error message, Job ID |
| `LLM_CALL` | Any request is made to the LLM proxy | Client IP |

## Storage
- **File**: `backend/logs/audit.db` (SQLite)
- **Volume Mount**: The database is persisted in the `logs` volume in Docker.

## Direct Querying
You can query the audit log directly using the `sqlite3` CLI:
```bash
sqlite3 backend/logs/audit.db "SELECT * FROM events ORDER BY timestamp DESC LIMIT 10;"
```

## Privacy & Limitations
- **Passwords**: User passwords are never logged.
- **File Content**: The actual content of PDFs is not stored in the audit log.
- **LLM Prompts**: Full LLM prompts and responses are not logged to the audit DB (though they may appear in `app.log` if debug logging is enabled).
