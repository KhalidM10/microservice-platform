import logging
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, RetryError
from fastapi import Request, Response
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=30.0)
    return _client


async def close_http_client():
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10), reraise=True)
async def _do_request(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> httpx.Response:
    response = await client.request(method, url, **kwargs)
    return response


async def proxy_request(
    request: Request,
    target_url: str,
    service_name: str,
    strip_prefix: str = "",
) -> Response:
    client = get_http_client()

    path = request.url.path
    if strip_prefix and path.startswith(strip_prefix):
        path = path[len(strip_prefix):]

    query = str(request.url.query)
    full_url = f"{target_url}{path}"
    if query:
        full_url = f"{full_url}?{query}"

    headers = dict(request.headers)
    headers.pop("host", None)

    correlation_id = getattr(request.state, "correlation_id", "")
    if correlation_id:
        headers["X-Correlation-ID"] = correlation_id

    body = await request.body()

    try:
        upstream = await _do_request(
            client,
            method=request.method,
            url=full_url,
            headers=headers,
            content=body,
        )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=dict(upstream.headers),
            media_type=upstream.headers.get("content-type"),
        )
    except Exception as exc:
        logger.error("All retries failed for %s: %s", service_name, exc)
        return JSONResponse(
            status_code=503,
            content={"error": "service temporarily unavailable", "service": service_name},
        )
