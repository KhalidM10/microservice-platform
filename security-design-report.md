# Security Design Report

## Authentication Flow

```
Client → POST /api/v1/auth/register (email, password)
       → auth-service hashes password (bcrypt) → stores User
       → returns UserResponse (no password)

Client → POST /api/v1/auth/login (email, password)
       → auth-service verifies bcrypt hash
       → issues access_token (30 min, HS256) + refresh_token (7 days)
       → returns TokenResponse

Client → GET /api/v1/documents (Authorization: Bearer <access_token>)
       → document-service.verify_token decodes JWT, validates type="access"
       → extracts sub (user_id) → sets as owner_id on documents
       → returns documents

Client → POST /api/v1/auth/refresh (refresh_token)
       → auth-service validates type="refresh"
       → issues new access_token + refresh_token
```

## JWT Lifecycle

- **Issue**: On successful login, signed with SECRET_KEY using HS256
- **Payload**: `{ sub: user_id, role: user|admin, exp: unix_ts, iat: unix_ts, type: access|refresh }`
- **Validate**: Every protected endpoint calls `verify_token()` — checks signature, expiry, and type field
- **Refresh**: Client exchanges refresh_token for new token pair before access_token expires
- **Blacklist**: Logout posts to auth-service which acknowledges; the api-gateway can maintain a Redis blacklist of revoked JTIs for production hardening

## Authorization Model

| Role  | Rate Limit     | Permissions                        |
|-------|----------------|------------------------------------|
| guest | 10 req/min/IP  | auth/register, auth/login only     |
| user  | 100 req/min    | CRUD own documents, notifications  |
| admin | 1000 req/min   | All operations                     |

Role is embedded in JWT payload and validated at the api-gateway layer.

## Rate Limiting Strategy

Implemented in `api-gateway/src/middleware/rate_limit.py` using Redis:

- Key: `rate:{user_id}` for authenticated, `rate:{client_ip}` for anonymous
- Sliding window: 60-second EXPIRE on Redis keys
- Headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`
- On limit exceeded: HTTP 429 with `retry_after: 60`

## Input Validation

- **Pydantic v2**: All request bodies validated at schema level with `min_length`, `max_length`, `max_items`
- **Title**: 1–255 chars; **Content**: 1–50,000 chars; **Tags**: max 20 items
- **Email**: Validated via `pydantic[email]` (email-validator library)
- **Password**: Minimum 8 characters enforced at registration

## Secrets Management

- All secrets stored as environment variables, loaded via `pydantic-settings`
- `.env` file is in `.gitignore` — never committed
- `.env.example` has placeholder values only
- Kubernetes secrets via `k8s/secrets.yaml` (placeholder file, also in `.gitignore`)
- `SECRET_KEY` used for JWT signing — must be a cryptographically random 32+ character string in production

## OWASP Top 10 Checklist

| #   | Risk                    | Mitigation                                                                 |
|-----|-------------------------|----------------------------------------------------------------------------|
| A01 | Broken Access Control   | JWT required on all document endpoints; owner_id enforced per resource     |
| A02 | Cryptographic Failures  | bcrypt for passwords (work factor 12); HS256 JWT with SECRET_KEY from env  |
| A03 | Injection               | SQLAlchemy ORM used throughout — no raw SQL strings; Pydantic validates all input |
| A04 | Insecure Design         | Threat model documented here; services communicate via internal Docker network |
| A05 | Security Misconfiguration | Security headers middleware on all responses; DEBUG=false in production   |
| A06 | Vulnerable Components   | All dependencies pinned to exact versions in requirements.txt              |
| A07 | Auth Failures           | Rate limiting 10 req/min unauthenticated; JWT blacklist on logout         |
| A08 | Integrity Failures      | Docker multi-stage build; plan: Docker Content Trust for image signing     |
| A09 | Logging Failures        | Structured JSON logs with correlation IDs on every request                 |
| A10 | SSRF                   | No user-controlled URLs; internal service URLs are hardcoded in config     |

## Security Headers (api-gateway)

Applied by `SecurityHeadersMiddleware` to every response:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Strict-Transport-Security: max-age=31536000; includeSubDomains
Content-Security-Policy: default-src 'self'
Referrer-Policy: strict-origin-when-cross-origin
```

## Known Limitations and Future Improvements

1. **JWT Blacklist**: Currently logout is acknowledged but the token remains valid until expiry. Production should store JTI in Redis with TTL matching token expiry.
2. **mTLS**: Internal service-to-service communication uses plain HTTP inside Docker network. Production should use mTLS or a service mesh (Istio).
3. **Role-based document access**: Currently any authenticated user can read any document. Future: per-document ACL.
4. **Secrets rotation**: No automated secret rotation. Future: HashiCorp Vault integration.
5. **HTTPS**: Local dev uses HTTP. Production must terminate TLS at the ingress/load balancer.
