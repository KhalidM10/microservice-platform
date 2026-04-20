import logging
import re
from typing import List
from src.core.config import settings
from src.schemas.document import SummarizeResponse, SemanticSearchResult

logger = logging.getLogger(__name__)

_redis_client = None


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
    for sentence in sentences[:3]:
        words = sentence.split()
        if word_count + len(words) > max_words:
            break
        summary_sentences.append(sentence)
        word_count += len(words)
    return " ".join(summary_sentences) if summary_sentences else content[:500]


async def summarize_document(document, max_length: int) -> SummarizeResponse:
    cache_key = f"summary:{document.id}:{max_length}"
    redis = _get_redis()

    if redis:
        try:
            cached = redis.get(cache_key)
            if cached:
                import json
                return SummarizeResponse(**json.loads(cached))
        except Exception:
            pass

    original_length = len(document.content.split())
    summary = ""
    model_used = "extractive-fallback"

    if settings.OPENAI_API_KEY:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            response = await client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{
                    "role": "user",
                    "content": f"Summarize in {max_length} words:\n\n{document.content}",
                }],
                max_tokens=max_length * 2,
            )
            summary = response.choices[0].message.content.strip()
            model_used = "gpt-3.5-turbo"
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
            import json
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
