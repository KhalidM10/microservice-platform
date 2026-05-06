import json
import logging
from src.core.config import settings

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


def extract_basic_metadata(content: str) -> dict:
    """Word count and language — no API needed."""
    word_count = len(content.split()) if content.strip() else 0
    language = None
    try:
        from langdetect import detect
        if len(content.strip()) > 50:
            language = detect(content[:1000])
    except Exception:
        pass
    return {"word_count": word_count, "language": language}


async def extract_ai_metadata(document) -> dict:
    """Extract entities, category, and sentiment via gpt-4o-mini. Cached 24 h."""
    if not settings.OPENAI_API_KEY:
        return {}

    cache_key = f"meta_ai:{document.id}"
    redis = _get_redis()
    if redis:
        try:
            cached = redis.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Analyze the document and return ONLY a valid JSON object with:\n"
                        '- "entities": {"people":[],"organizations":[],"locations":[]}\n'
                        '- "category": one of: report, article, note, email, code, legal, financial, academic, other\n'
                        '- "sentiment": one of: positive, neutral, negative\n'
                        "No explanation, no markdown — raw JSON only."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Title: {document.title}\n\n{document.content[:3000]}",
                },
            ],
            max_tokens=300,
            temperature=0.1,
        )
        raw = response.choices[0].message.content.strip()
        # Strip markdown code fences if the model wraps output
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result = json.loads(raw.strip())

        if redis:
            try:
                redis.setex(cache_key, 86400, json.dumps(result))
            except Exception:
                pass

        return result
    except Exception as exc:
        logger.warning("AI metadata extraction failed: %s", exc)
        return {}
