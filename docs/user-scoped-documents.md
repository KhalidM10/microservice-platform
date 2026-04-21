# User-Scoped Documents

## Overview

Every document is owned by the user who created it. Users can only read, edit,
delete, search, and summarise their own documents — other users' documents are
completely invisible to them.

---

## How It Works

### Ownership assignment

When a document is created, `owner_id` is set from the JWT token's `sub` claim:

```python
# document-service/src/api/routes/documents.py
owner_id = token["sub"]
doc = await document_service.create_document(db, data, owner_id=owner_id)
```

### Scoped queries

Every read and write operation filters by `owner_id`:

| Operation | Enforcement |
|---|---|
| List documents | `WHERE owner_id = :owner_id` |
| Keyword search | `WHERE owner_id = :owner_id AND (title ILIKE … OR content ILIKE …)` |
| Semantic search | Loads only the caller's documents before running TF-IDF |
| Get document | Returns `None` (→ 404) if `doc.owner_id != token["sub"]` |
| Update document | Returns `None` (→ 404) if caller doesn't own the document |
| Delete document | Returns `None` (→ 404) if caller doesn't own the document |
| Summarize | Fetches document with ownership check before calling AI |

### Response for unauthorised access

All ownership violations return **404 Not Found** (not 403), so users cannot
probe the system to discover whether a document ID exists.

---

## Example

```bash
# User A creates a document
TOKEN_A=$(curl -s -X POST http://localhost:8080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com","password":"Password123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

DOC_ID=$(curl -s -X POST http://localhost:8080/api/v1/documents \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"title":"My Private Doc","content":"Secret content"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# User B logs in and tries to access User A's document
TOKEN_B=$(curl -s -X POST http://localhost:8080/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"bob@example.com","password":"Password123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s http://localhost:8080/api/v1/documents/$DOC_ID \
  -H "Authorization: Bearer $TOKEN_B"
# → {"detail":"Document not found"}   ← 404, not 403
```

---

## Service Layer API

```python
# All functions now require owner_id for scoped operations

await document_service.list_documents(db, owner_id=user_id, skip=0, limit=10)
await document_service.get_document(db, doc_id, owner_id=user_id)
await document_service.update_document(db, doc_id, data, owner_id=user_id)
await document_service.soft_delete_document(db, doc_id, owner_id=user_id)
await document_service.search_documents(db, query, owner_id=user_id)
```

Passing `owner_id=None` to `get_document` skips the ownership check (used
internally when admin access is needed in future).

---

## Tests

Cross-user isolation is tested at two levels:

**HTTP level** (7 tests in `document-service/tests/test_documents.py`):
- `test_list_documents_only_own` — user B's docs absent from user A's list
- `test_get_other_users_document_returns_404`
- `test_update_other_users_document_returns_404`
- `test_delete_other_users_document_returns_404`
- `test_search_does_not_return_other_users_docs`
- `test_summarize_other_users_document_returns_404`
- `test_semantic_search_scoped_to_owner`

**Service layer** (5 tests):
- `test_service_get_wrong_owner_returns_none`
- `test_service_update_wrong_owner_returns_none`
- `test_service_soft_delete_wrong_owner_returns_none`
- `test_service_list_documents_scoped`
- `test_service_search_scoped`
