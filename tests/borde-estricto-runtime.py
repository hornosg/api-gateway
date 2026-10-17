#!/usr/bin/env python3
# ACC-E03 · T5c — Test runtime del borde estricto contra `lab-kong` vivo.
#
# Criterios "Hecho cuando" de T5c (épica ACC-E03):
#   (a) `alg:none` y un RS256 firmado con OTRA clave a una ruta gateada → 401 SIN
#       `X-Kong-Upstream-Latency` (rechazo en el borde, el upstream no se entera). Se prueba en
#       una ruta por service estricto, y además sin token y con basura en el header.
#   (b) Las rutas públicas inventariadas siguen en 200 sin token (y llegan al upstream).
#   (c) Login vivo + endpoint gateado → 200.
#   Negativo extra: el service público del BFF NO amplía el acceso anónimo (POST, `/<id>`,
#   `/tree/x`, `/admin/...` sin token → 401 en el borde).
#
# Los tokens forjados copian iss/kid del firmador real (`iam-service`, kid del login vivo)
# para que el rechazo dependa SÓLO de la firma/alg, no de un iss desconocido.
#
# Uso: python3 tests/borde-estricto-runtime.py
#   KONG_URL (default http://localhost:8000), LOGIN_EMAIL, LOGIN_PASSWORD (seed de iam).
# Requiere: PyJWT + cryptography. Sale != 0 si alguna aserción falla.
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request

try:
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
except ImportError:
    print("FAIL: se requiere PyJWT y cryptography", file=sys.stderr)
    sys.exit(2)

KONG = os.environ.get("KONG_URL", "http://localhost:8000").rstrip("/")
EMAIL = os.environ.get("LOGIN_EMAIL", "admin@saasadmin.com")
PASSWORD = os.environ.get("LOGIN_PASSWORD", "123456")
UPSTREAM_HDR = "X-Kong-Upstream-Latency"

# Una ruta por service estricto (inventario de la épica) + catalog-service y un flip.
GATED = [
    ("iam-service", "GET", "/iam/api/v1/roles"),
    ("pim-service", "GET", "/pim/api/v1/categories"),
    ("pim-service (health)", "GET", "/pim/api/v1/health"),
    ("stock-service", "GET", "/stock/api/v1/stock"),
    ("catalog-bff-service", "GET", "/catalog/api/v1/products"),
    ("catalog-bff-service (/admin)", "GET", "/admin/api/v1/marketplace/categories"),
    ("sales-service", "GET", "/sales/api/v1/sales"),
    ("customer-service", "GET", "/customers/api/v1/customers"),
    ("ledger-service", "GET", "/ledger/api/v1/accounts"),
    ("payment-method-service", "GET", "/payment-methods/api/v1/payment-methods"),
    ("marketplace-service", "GET", "/marketplace/products"),
    ("webdata-service", "GET", "/webdata/api/v1/sites"),
    ("notification-service", "GET", "/notification/api/v1/notifications"),
    ("tenant-service", "GET", "/tenant/api/v1/tenant"),
    ("catalog-service", "GET", "/catalog-service/api/v1/brands"),
    ("catalog-flip-brands", "GET", "/pim/api/v1/marketplace-brands"),
]

# Inventario de rutas públicas (criterio d) → 200 sin token, llegando al upstream.
PUBLIC_200 = [
    ("GET", "/catalog/api/v1/marketplace/categories", None),
    ("GET", "/catalog/api/v1/marketplace/categories/tree", None),
    ("GET", "/onboarding/api/v1/steps", None),
    ("GET", "/api/v1/public/marketplace/categories", None),
]
# Públicas que no dan 200 sin body válido, pero NO deben cortarse en el borde.
PUBLIC_REACH_UPSTREAM = [
    ("POST", "/iam/api/v1/auth/refresh", {}),
]

# El service público del BFF no amplía el acceso anónimo.
NOT_WIDENED = [
    ("POST", "/catalog/api/v1/marketplace/categories"),
    ("GET", "/catalog/api/v1/marketplace/categories/123"),
    ("GET", "/catalog/api/v1/marketplace/categories/tree/x"),
    ("GET", "/admin/api/v1/marketplace/categories/tree"),
]

failures = []


def call(method, path, token=None, body=None, raw_auth=None):
    data = json.dumps(body).encode() if body is not None else (b"{}" if method != "GET" else None)
    req = urllib.request.Request(KONG + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if raw_auth is not None:
        req.add_header("Authorization", raw_auth)
    elif token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def has_upstream(headers):
    return any(k.lower() == UPSTREAM_HDR.lower() for k in headers)


def b64url(obj):
    return base64.urlsafe_b64encode(json.dumps(obj, separators=(",", ":")).encode()) \
        .rstrip(b"=").decode()


def login():
    st, _, body = call("POST", "/iam/api/v1/auth/login",
                       body={"email": EMAIL, "password": PASSWORD, "provider": "LOCAL"})
    if st != 200:
        return None, f"login → {st} {body[:200]!r}"
    payload = json.loads(body)
    data = payload.get("data", payload)
    tok = data.get("access_token") or data.get("accessToken") or data.get("token")
    if not tok:
        return None, f"login 200 sin access_token: claves={sorted(data)}"
    return tok, None


def main():
    # (c) login vivo — también da el kid/iss real para que la forja sea plausible.
    token, err = login()
    kid, iss = "acc-69a4a91f940a", "iam-service"
    if err:
        failures.append(f"(c) {err}")
    else:
        hdr = jwt.get_unverified_header(token)
        claims = jwt.decode(token, options={"verify_signature": False})
        kid, iss = hdr.get("kid", kid), claims.get("iss", iss)
        if hdr.get("alg") != "RS256":
            failures.append(f"(c) el login emite alg={hdr.get('alg')!r}, esperado RS256")
        st, h, _ = call("GET", "/iam/api/v1/roles", token=token)
        if st != 200:
            failures.append(f"(c) login vivo + GET /iam/api/v1/roles → {st}, esperado 200")

    now = int(time.time())
    claims = {"iss": iss, "sub": "forged", "exp": now + 600, "iat": now,
              "tenant_id": "00000000-0000-0000-0000-000000000000", "roles": ["SUPER_ADMIN"]}
    alg_none = f"{b64url({'alg': 'none', 'typ': 'JWT', 'kid': kid})}.{b64url(claims)}."
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    foreign = jwt.encode(claims, other_key, algorithm="RS256", headers={"kid": kid})

    # (a) rechazo en el borde.
    variants = [("alg:none", {"token": alg_none}),
                ("RS256 otra clave", {"token": foreign}),
                ("sin token", {}),
                ("Bearer basura", {"raw_auth": "Bearer not.a.jwt"})]
    for svc, method, path in GATED:
        for label, kw in variants:
            st, h, body = call(method, path, **kw)
            if st != 401:
                failures.append(f"(a) {svc} {method} {path} [{label}] → {st}, esperado 401")
            elif has_upstream(h):
                failures.append(f"(a) {svc} {method} {path} [{label}] → 401 DEL UPSTREAM "
                                f"({UPSTREAM_HDR} presente): el borde dejó pasar el token")

    # (b) públicas: 200 sin token y llegando al upstream.
    for method, path, body in PUBLIC_200:
        st, h, _ = call(method, path, body=body)
        if st != 200:
            failures.append(f"(b) pública {method} {path} sin token → {st}, esperado 200")
        elif not has_upstream(h):
            failures.append(f"(b) pública {method} {path} → 200 sin {UPSTREAM_HDR}")
    for method, path, body in PUBLIC_REACH_UPSTREAM:
        st, h, _ = call(method, path, body=body)
        if not has_upstream(h):
            failures.append(f"(b) pública {method} {path} → {st} cortada en el borde")

    # Negativo: el carve-out público del BFF no se extiende.
    for method, path in NOT_WIDENED:
        st, h, _ = call(method, path)
        if st != 401 or has_upstream(h):
            failures.append(f"ampliación: {method} {path} sin token → {st} "
                            f"(upstream={has_upstream(h)}), esperado 401 en el borde")

    if failures:
        print(f"FAIL ({len(failures)}) — {KONG}")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print(f"OK — {len(GATED)} rutas gateadas × {len(variants)} variantes → 401 en el borde; "
          f"{len(PUBLIC_200)} públicas 200; login → 200; {len(NOT_WIDENED)} sin ampliación")


if __name__ == "__main__":
    main()
