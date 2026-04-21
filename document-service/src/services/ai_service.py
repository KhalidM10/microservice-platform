import json
import logging
import re
from typing import List
from src.core.config import settings
from src.schemas.document import SummarizeResponse, SemanticSearchResult, TagSuggestResponse

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


async def semantic_search(documents: list, query: str, limit: int) -> List[SemanticSearchResult]:
    if not documents:
        return []

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        import numpy as np

        corpus = [f"{doc.title} {doc.content}" for doc in documents]
        vectorizer = TfidfVectorizer(stop_words="english")
        tfidf_matrix = vectorizer.fit_transform(corpus)
        query_vec = vectorizer.transform([query])
        scores = cosine_similarity(query_vec, tfidf_matrix).flatten()

        ranked_indices = np.argsort(scores)[::-1][:limit]
        results = []
        for idx in ranked_indices:
            if scores[idx] > 0:
                doc = documents[idx]
                results.append(SemanticSearchResult(
                    id=str(doc.id),
                    title=doc.title,
                    content=doc.content,
                    owner_id=doc.owner_id,
                    similarity_score=float(scores[idx]),
                    tags=doc.tags,
                ))
        return results
    except Exception as exc:
        logger.error("Semantic search failed: %s", exc)
        return []
