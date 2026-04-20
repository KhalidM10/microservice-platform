# AI Features

## Overview

The platform integrates two AI-powered features into the document-service:
AI summarization (backed by OpenAI with an extractive fallback) and
semantic search using TF-IDF cosine similarity.

---

## 1. Document Summarization

### Endpoint

```
POST /api/v1/documents/{id}/summarize
Authorization: Bearer <token>
Content-Type: application/json

{ "max_length": 150 }
```

### Response

```json
{
  "document_id": "5e3b4eb6-31df-42db-acfd-3e94121b4a67",
  "original_length": 320,
  "summary": "Machine learning enables systems to learn from data...",
  "summary_length": 42,
  "model_used": "gpt-3.5-turbo"
}
```

### How it works

```
Request
  │
  ▼
Is OPENAI_API_KEY set?
  ├─ YES → Call GPT-3.5-turbo
  │         "Summarize in {max_length} words:\n\n{content}"
  │         On error → fall back to extractive
  │
  └─ NO  → Extractive fallback
            Split content into sentences
            Return first 3 sentences (up to max_length words)
            model_used: "extractive-fallback"
  │
  ▼
Cache result in Redis (key: summary:{doc_id}:{max_length}, TTL: 1h)
  │
  ▼
Return SummarizeResponse
```

### Caching

Results are cached in Redis for 1 hour per `(document_id, max_length)` pair.
Subsequent identical requests return the cached value without calling OpenAI.

### Configuration

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | No | Leave blank to use extractive fallback |
| `REDIS_URL` | No | Cache disabled gracefully if Redis unavailable |

---

## 2. Semantic Search

### Endpoint

```
POST /api/v1/documents/search/semantic
Authorization: Bearer <token>
Content-Type: application/json

{ "query": "neural networks deep learning", "limit": 10 }
```

### Response

```json
[
  {
    "id": "5e3b4eb6-31df-42db-acfd-3e94121b4a67",
    "title": "Introduction to Machine Learning",
    "content": "Machine learning is a subset...",
    "owner_id": "55379770-...",
    "similarity_score": 0.48,
    "tags": ["ml", "ai"]
  }
]
```

Results are ranked by `similarity_score` (0.0–1.0, higher = more relevant).
Only documents with `similarity_score > 0` are returned.

### How it works

```
Load all non-deleted documents from DB
  │
  ▼
Build corpus: ["{title} {content}" for each doc]
  │
  ▼
TfidfVectorizer (stop_words="english")
  .fit_transform(corpus)        → TF-IDF matrix
  .transform([query])           → query vector
  │
  ▼
cosine_similarity(query_vec, tfidf_matrix)
  │
  ▼
Sort by score descending → return top N
```

No external API call — entirely local computation via scikit-learn.

### Comparison: keyword search vs semantic search

| Feature | `GET /search?q=` | `POST /search/semantic` |
|---|---|---|
| Method | SQL ILIKE | TF-IDF cosine |
| Exact match required | Yes | No |
| Handles synonyms | No | Partial (shared vocabulary) |
| Scales with docs | DB-indexed | In-memory (loads all docs) |
| External API | None | None |

---

## 3. Enabling OpenAI

1. Get an API key from https://platform.openai.com/api-keys
2. Add to your `.env` file:
   ```
   OPENAI_API_KEY=sk-...
   ```
3. Restart the document-service:
   ```bash
   docker-compose restart document-service
   ```

The `model_used` field in the response will change from
`"extractive-fallback"` to `"gpt-3.5-turbo"`.

---

## 4. Extending AI Features

Future improvements planned:
- **Embeddings-based search**: Replace TF-IDF with OpenAI `text-embedding-3-small` for true semantic similarity
- **Auto-tagging**: Suggest tags on document creation using GPT classification
- **Question answering**: `POST /documents/{id}/ask` endpoint for RAG-style Q&A over document content
- **Batch summarization**: Summarize multiple documents in one call
