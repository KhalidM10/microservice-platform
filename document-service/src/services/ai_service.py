import json
import logging
import re
from typing import List
from src.core.config import settings
from src.schemas.document import SummarizeResponse, SemanticSearchResponse, SemanticSearchResult, TagSuggestResponse

logger = logging.getLogger(__name__)

_redis_client = None
_PREFERRED_MODEL = "gpt-4o-mini"
_FALLBACK_MODEL = "gpt-3.5-turbo"


def _get_redis():
    global _redis_client
    if _redis_client is None:
        try:
            import redis
            _redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        except Exception:
            return None
    return _redis_client


def _extractive_summary(content: str, max_words: int) -> str:
    sentences = re.split(r'(?<=[.!?])\s+', content.strip())
    summary_sentences = []
    word_count = 0
    for sentence in sentences[:5]:
        words = sentence.split()
        if word_count + len(words) > max_words:
            break
        summary_sentences.append(sentence)
        word_count += len(words)
    return " ".join(summary_sentences) if summary_sentences else content[:500]


async def _openai_chat(messages: list, max_tokens: int) -> tuple[str, str]:
    """Call OpenAI, try gpt-4o-mini first then fall back to gpt-3.5-turbo."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    for model in (_PREFERRED_MODEL, _FALLBACK_MODEL):
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.3,
            )
            return response.choices[0].message.content.strip(), model
        except Exception as exc:
            logger.warning("OpenAI model %s failed: %s", model, exc)
    raise RuntimeError("All OpenAI models failed")


async def summarize_document(document, max_length: int) -> SummarizeResponse:
    cache_key = f"summary:{document.id}:{max_length}"
    redis = _get_redis()

    if redis:
        try:
            cached = redis.get(cache_key)
            if cached:
                return SummarizeResponse(**json.loads(cached))
        except Exception:
            pass

    original_length = len(document.content.split())
    summary = ""
    model_used = "extractive-fallback"

    if settings.OPENAI_API_KEY:
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are a precise document summarizer. "
                        "Return only the summary text — no preamble, no labels, no quotes."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Summarize the following document in approximately {max_length} words. "
                        "Capture the key points, main arguments, and any important conclusions.\n\n"
                        f"Title: {document.title}\n\n{document.content}"
                    ),
                },
            ]
            summary, model_used = await _openai_chat(messages, max_tokens=max_length * 2)
        except Exception as exc:
            logger.warning("OpenAI summarization failed, using fallback: %s", exc)
            summary = _extractive_summary(document.content, max_length)
    else:
        summary = _extractive_summary(document.content, max_length)

    result = SummarizeResponse(
        document_id=str(document.id),
        original_length=original_length,
        summary=summary,
        summary_length=len(summary.split()),
        model_used=model_used,
    )

    if redis:
        try:
            redis.setex(cache_key, 3600, json.dumps(result.model_dump()))
        except Exception:
            pass

    return result


async def suggest_tags(document) -> TagSuggestResponse:
    cache_key = f"tags:{document.id}"
    redis = _get_redis()

    if redis:
        try:
            cached = redis.get(cache_key)
            if cached:
                return TagSuggestResponse(**json.loads(cached))
        except Exception:
            pass

    if not settings.OPENAI_API_KEY:
        return TagSuggestResponse(suggested_tags=[], model_used="none")

    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a document tagging assistant. "
                    "Return a JSON array of 3-6 short, lowercase tag strings. "
                    "Output only the JSON array, no other text."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Suggest tags for this document.\n\n"
                    f"Title: {document.title}\n\n"
                    f"{document.content[:2000]}"
                ),
            },
        ]
        raw, model_used = await _openai_chat(messages, max_tokens=80)

        # Parse the JSON array the model returned
        match = re.search(r'\[.*?\]', raw, re.DOTALL)
        tags = json.loads(match.group()) if match else []
        tags = [str(t).strip().lower() for t in tags if t][:6]
    except Exception as exc:
        logger.warning("Tag suggestion failed: %s", exc)
        return TagSuggestResponse(suggested_tags=[], model_used="error")

    result = TagSuggestResponse(suggested_tags=tags, model_used=model_used)

    if redis:
        try:
            redis.setex(cache_key, 3600, json.dumps(result.model_dump()))
        except Exception:
            pass

    return result


async def generate_embedding(text: str) -> list[float] | None:
    """Generate an OpenAI text-embedding-3-small vector for the given text."""
    if not settings.OPENAI_API_KEY:
        return None
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    try:
        resp = await client.embeddings.create(
            model="text-embedding-3-small",
            input=text[:8191],
        )
        return resp.data[0].embedding
    except Exception as exc:
        logger.warning("Embedding generation failed: %s", exc)
        return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    import numpy as np
    va = np.array(a, dtype=float)
    vb = np.array(b, dtype=float)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(np.dot(va, vb) / denom) if denom > 0 else 0.0


def _embedding_search(documents: list, query_embedding: list[float], limit: int) -> list[SemanticSearchResult]:
    scored = []
    for doc in documents:
        if not doc.embedding:
            continue
        try:
            stored = json.loads(doc.embedding) if isinstance(doc.embedding, str) else doc.embedding
            score = _cosine_similarity(query_embedding, stored)
            scored.append((score, doc))
        except Exception:
            continue

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        SemanticSearchResult(
            id=str(doc.id),
            title=doc.title,
            content=doc.content,
            owner_id=doc.owner_id,
            similarity_score=round(score, 4),
            tags=doc.tags,
        )
        for score, doc in scored[:limit]
        if score > 0.05
    ]


def _tfidf_search(documents: list, query: str, limit: int) -> list[SemanticSearchResult]:
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity as sk_cosine
        import numpy as np

        corpus = [f"{doc.title} {doc.content}" for doc in documents]
        vectorizer = TfidfVectorizer(stop_words="english")
        tfidf_matrix = vectorizer.fit_transform(corpus)
        query_vec = vectorizer.transform([query])
        scores = sk_cosine(query_vec, tfidf_matrix).flatten()
        ranked = np.argsort(scores)[::-1][:limit]
        return [
            SemanticSearchResult(
                id=str(documents[i].id),
                title=documents[i].title,
                content=documents[i].content,
                owner_id=documents[i].owner_id,
                similarity_score=round(float(scores[i]), 4),
                tags=documents[i].tags,
            )
            for i in ranked if scores[i] > 0
        ]
    except Exception as exc:
        logger.error("TF-IDF search failed: %s", exc)
        return []


async def semantic_search(
    documents: list, query: str, limit: int
) -> tuple[list[SemanticSearchResult], str]:
    """Return (results, mode) where mode is 'embedding' or 'tfidf'."""
    if not documents:
        return [], "embedding"

    if settings.OPENAI_API_KEY:
        query_embedding = await generate_embedding(query)
        if query_embedding:
            results = _embedding_search(documents, query_embedding, limit)
            if results:
                return results, "embedding"

    return _tfidf_search(documents, query, limit), "tfidf"
