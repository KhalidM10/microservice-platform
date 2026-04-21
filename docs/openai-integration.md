# OpenAI Integration

## Overview

The document service integrates with OpenAI to provide two AI-powered features:

| Feature | Endpoint | Model |
|---|---|---|
| Document summarisation | `POST /api/v1/documents/{id}/summarize` | gpt-4o-mini → gpt-3.5-turbo fallback |
| Tag suggestion | `POST /api/v1/documents/{id}/tags/suggest` | gpt-4o-mini → gpt-3.5-turbo fallback |

Both features degrade gracefully: if no API key is configured, summarisation uses an extractive fallback and tag suggestion returns an empty list.

---

## Setup

### 1. Get an API key

Create a key at <https://platform.openai.com/api-keys>.

### 2. Set the environment variable

**Docker Compose (recommended):**

Create a `.env` file in the project root (already gitignored):

```bash
OPENAI_API_KEY=sk-...
```

`docker-compose.yml` forwards it to the document-service automatically:

```yaml
environment:
  OPENAI_API_KEY: ${OPENAI_API_KEY:-}
```

**Local dev:**

Copy and fill in `document-service/.env.example`:

```bash
cp document-service/.env.example document-service/.env
# edit OPENAI_API_KEY=sk-...
```

### 3. Restart the document-service

```bash
docker compose up -d document-service
```

---

## AI Summarisation

### How it works

1. The route handler fetches the document with ownership check.
2. `ai_service.summarize_document()` checks Redis for a cached result (`summary:{id}:{max_length}`, TTL 1 hour).
3. If no cache hit, it calls OpenAI with a structured system prompt:
   - *System:* "You are a precise document summarizer. Return only the summary text — no preamble, no labels, no quotes."
   - *User:* "Summarize the following document in approximately {N} words. Capture the key points…"
4. The response is cached and returned alongside `model_used`, `original_length`, and `summary_length`.

### Request

```bash
curl -X POST http://localhost:8080/api/v1/documents/{id}/summarize \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"max_length": 150}'
```

### Response

```json
{
  "document_id": "abc123",
  "original_length": 842,
  "summary": "This document describes...",
  "summary_length": 147,
  "model_used": "gpt-4o-mini"
}
```

`model_used` is `"gpt-4o-mini"`, `"gpt-3.5-turbo"`, or `"extractive-fallback"`.

---

## AI Tag Suggestion

### How it works

1. The route handler fetches the document (ownership-scoped).
2. `ai_service.suggest_tags()` checks Redis (`tags:{id}`, TTL 1 hour).
3. If no cache hit, it sends the document title + first 2 000 characters to OpenAI with:
   - *System:* "Return a JSON array of 3-6 short, lowercase tag strings. Output only the JSON array."
4. The model's JSON array is parsed and sanitised (stripped, lowercased, capped at 6).

### Request

```bash
curl -X POST http://localhost:8080/api/v1/documents/{id}/tags/suggest \
  -H "Authorization: Bearer $TOKEN"
```

### Response

```json
{
  "suggested_tags": ["machine learning", "python", "tutorial", "data science"],
  "model_used": "gpt-4o-mini"
}
```

### Applying tags (UI)

In the frontend, open any document → click the **AI Tags 🏷** tab → click **Suggest Tags** → click any suggested tag pill to add it to the document immediately.

---

## Model Selection

The service tries `gpt-4o-mini` first (faster, cheaper, stronger than gpt-3.5-turbo for most tasks). If that call fails it retries with `gpt-3.5-turbo`. If both fail it falls back to the extractive summariser (tags return empty).

---

## Caching

All AI results are cached in Redis for **1 hour** keyed by document ID (and `max_length` for summaries). This means:

- Repeated calls within the hour are instant and free.
- If you update a document's content, the old summary/tags remain cached until TTL expires. Delete the Redis key manually if you need fresh results immediately:

```bash
docker exec microservice-platform-redis-1 redis-cli DEL "summary:{id}:150"
docker exec microservice-platform-redis-1 redis-cli DEL "tags:{id}"
```
