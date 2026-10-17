#!/usr/bin/env python3
# ACC-E03 · T5d — Test runtime del acceso anónimo residual contra `lab-kong` vivo.
#
# Criterio "Hecho cuando" de T5d: `alg:none` a las rutas de ai-gateway da 401 en el borde
# (sin `X-Kong-Upstream-Latency`) SIN romper al caller por API key ni al de JWT válido.
#   - ai-gateway (`/ai/`, `/ai-gateway/`): sin token, basura, `alg:none`, RS256 de otra clave
#     y X-API-Key inválida → 401 sin upstream. X-API-Key válida (AI_GATEWAY_API_KEY) y JWT del
#     login vivo → NO 401/403 (pasan el borde; commerce-ai apagado → 503 del balancer).
#   - onboarding (público explícito): sin token → 200 con upstream.
#
# Reusa login/forja/call de borde-estricto-runtime.py (T5c).
# Uso: python3 tests/borde-anonimo-t5d-runtime.py  (AI_GATEWAY_API_KEY o infra/api-gateway/.env)
import importlib.util
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("t5c", os.path.join(HERE, "borde-estricto-runtime.py"))
t5c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t5c)
jwt, rsa = t5c.jwt, t5c.rsa


def api_key():
    if os.environ.get("AI_GATEWAY_API_KEY"):
        return os.environ["AI_GATEWAY_API_KEY"]
    with open(os.path.join(HERE, "..", ".env")) as f:
        for line in f:
            if line.startswith("AI_GATEWAY_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    return None


def main():
    fails = []
    token, err = t5c.login()
    if err:
        print("FAIL: login:", err)
        return 1
    kid = jwt.get_unverified_header(token).get("kid")
    iss = jwt.decode(token, options={"verify_signature": False}).get("iss")
    now = int(time.time())
    claims = {"iss": iss, "sub": "forged", "exp": now + 600, "iat": now,
              "tenant_id": "00000000-0000-0000-0000-000000000000", "roles": ["SUPER_ADMIN"]}
    alg_none = f"{t5c.b64url({'alg': 'none', 'typ': 'JWT', 'kid': kid})}.{t5c.b64url(claims)}."
    foreign = jwt.encode(claims, rsa.generate_private_key(public_exponent=65537, key_size=2048),
                         algorithm="RS256", headers={"kid": kid})
    key = api_key()
    if not key:
        print("FAIL: no encuentro AI_GATEWAY_API_KEY")
        return 1

    for path in ("/ai/health", "/ai-gateway/ai/dev-metrics", "/ai/ai/generate-template"):
        rejects = {
            "sin token": {},
            "basura": {"raw_auth": "Bearer x.y.z"},
            "alg:none": {"token": alg_none},
            "otra clave": {"token": foreign},
        }
        for label, kw in rejects.items():
            st, h, _ = t5c.call("GET", path, **kw)
            if st != 401 or t5c.has_upstream(h):
                fails.append(f"{path} {label} → {st} upstream={t5c.has_upstream(h)}, esperado 401 en el borde")
        # API key inválida (y alg:none + API key inválida): tampoco pasa.
        for label, extra in (("api-key inválida", {}), ("alg:none + api-key inválida", {"token": alg_none})):
            st, h, _ = t5c.call("GET", path, headers={"X-API-Key": "no-es-una-key"}, **extra)
            if st != 401 or t5c.has_upstream(h):
                fails.append(f"{path} {label} → {st} upstream={t5c.has_upstream(h)}, esperado 401 en el borde")
        # Callers legítimos: pasan el borde (llegan al upstream).
        for label, kw in (("X-API-Key válida", {"headers": {"X-API-Key": key}}),
                          ("JWT login vivo", {"token": token})):
            st, h, _ = t5c.call("GET", path, **kw)
            # commerce-ai apagado: Kong pasa auth y falla en el balancer (503 «name resolution
            # failed», sin X-Kong-Upstream-Latency). Pasar el borde = cualquier cosa ≠ 401/403.
            if st in (401, 403):
                fails.append(f"{path} {label} → {st} upstream={t5c.has_upstream(h)}, esperado pasar el borde")
            else:
                print(f"  ok {path} {label} → {st} (pasó el borde)")

    # Variantes de path (review L4 C3): no matchean ninguna ruta o quedan gateadas; nunca 2xx del upstream.
    for path in ("/AI/health", "/Ai-gateway/ai/dev-metrics", "/ai"):
        st, h, _ = t5c.call("GET", path)
        if st != 404 or t5c.has_upstream(h):
            fails.append(f"{path} → {st} upstream={t5c.has_upstream(h)}, esperado 404 sin upstream")
    for path in ("/ai/sales/chat%2F..%2Fingest", "/ai/sales/chat/../ingest"):
        st, h, _ = t5c.call("GET", path)
        if 200 <= st < 300:
            fails.append(f"{path} → {st}, un anónimo no puede obtener 2xx")
    st, h, _ = t5c.call("GET", "/onboarding/api/v1/steps")
    if st != 200 or not t5c.has_upstream(h):
        fails.append(f"onboarding sin token → {st} upstream={t5c.has_upstream(h)}, esperado 200")
    for f in fails:
        print("FAIL:", f)
    if fails:
        return 1
    print("OK: ai-gateway rechaza en el borde sin credencial válida; API key y JWT pasan; onboarding público")
    return 0


if __name__ == "__main__":
    sys.exit(main())
