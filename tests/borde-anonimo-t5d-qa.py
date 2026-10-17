#!/usr/bin/env python3
# ACC-E03 · T5d — Tests de QA (fase TEST, independientes de la implementación).
#
# Complementan a borde-anonimo-t5d-config.py y borde-anonimo-t5d-runtime.py con lo que el
# contrato de T5d exige y esos dos no traban:
#
#   Offline (sin Kong):
#     Q1  el corte `request-termination` del anónimo existe SÓLO en ai-gateway-service: un corte
#         global o en otro service tumbaría las rutas públicas que todavía usan el anónimo
#         (ai-sales-public, catalog-public, …). Con auto-test de mutación.
#     Q2  la decisión queda registrada en la épica (Hecho cuando: «decisión registrada en la
#         épica con el inventario de callers»): bloque T5d con inventario de callers, decisión
#         para ai-gateway y para onboarding, y control compensatorio. Con auto-test de mutación.
#
#   Runtime (contra lab-kong vivo; se salta con --offline):
#     R1  la ruta pública hermana /ai/sales/* (mismo upstream commerce-ai) NO queda cortada.
#     R2  /ai-gateway/pim/ (key-auth estricto, sin anónimo) sigue en 401 sin key / con alg:none.
#     R3  el método no es un bypass: POST con alg:none / sin token a ai-gateway → 401 en el borde.
#     R4  canales de API key: el header alternativo `apiKey` con key válida pasa; con key inválida
#         → 401. La key en query string NO abre el borde (key_in_query: false).
#     R5  firma manipulada: token real del login con el payload alterado → 401 en el borde.
#     R6  preflight CORS a ai-gateway no queda cortado por el 401 (callers web de mc_admin).
#     R7  onboarding público explícito: con un `alg:none` forjado sigue respondiendo 200 (Kong no
#         lo parsea) y el control compensatorio está vivo (X-RateLimit-Limit-Minute: 100).
#
# Uso: python3 tests/borde-anonimo-t5d-qa.py [--offline]
import copy
import importlib.util
import json
import os
import re
import sys
import time

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "..", "kong.yml.template")
EPICA = os.path.join(
    os.environ.get("DEVY_PATH", os.path.expanduser("~/Projects")),
    "management", "projects", "account-service", "epicas", "ACC-E03-firma-asimetrica-jwks.md",
)
AI = "ai-gateway-service"
ANON = "anonymous-consumer"


# ─── Offline ────────────────────────────────────────────────────────────────────────────────

def load_template():
    src = open(TEMPLATE).read()
    src = re.sub(r"\$\{[A-Z_]+\}", "placeholder", src)
    return yaml.safe_load(src)


def all_plugins(doc):
    """(scope_service, plugin) para globales, service-level y route-level."""
    out = [(p.get("service"), p) for p in doc.get("plugins", [])]
    for s in doc.get("services", []):
        for p in s.get("plugins", []):
            out.append((s["name"], p))
        for r in s.get("routes", []):
            for p in r.get("plugins", []):
                out.append((s["name"], p))
    return out


def check_q1(doc):
    errs = []
    cuts = [(svc, p) for svc, p in all_plugins(doc) if p["name"] == "request-termination"]
    for svc, p in cuts:
        if p.get("consumer") == ANON and svc != AI:
            errs.append(f"Q1: request-termination del anónimo fuera de {AI} (scope={svc or 'GLOBAL'})")
        if svc is None and p.get("route") is None:
            errs.append("Q1: request-termination GLOBAL — corta toda la flota")
    if not any(svc == AI and p.get("consumer") == ANON for svc, p in cuts):
        errs.append(f"Q1: no hay corte del anónimo en {AI}")
    return errs


def t5d_block(text):
    m = re.search(r"^- \[[ x~]\] \*\*T5d\b.*?(?=^- \[[ x~]\] \*\*T\d)", text, re.S | re.M)
    return m.group(0) if m else ""


def check_q2(text):
    errs = []
    block = t5d_block(text)
    if not block:
        return ["Q2: no encuentro el bloque T5d en la épica"]
    required = {
        "inventario de callers": r"Inventario de callers",
        "decisión": r"\*\*Decisión:?\*\*",
        "ai-gateway en la decisión": r"Decisión.*ai-gateway",
        "onboarding en la decisión": r"Decisión.*onboarding",
        "callers sólo-API-key declarados": r"[Cc]allers sólo-`?X-API-Key`?",
        "control compensatorio de onboarding": r"[Cc]ontrol compensatorio",
    }
    for label, rx in required.items():
        if not re.search(rx, block, re.S):
            errs.append(f"Q2: falta en la épica — {label}")
    return errs


def offline():
    fails = []
    doc = load_template()
    errs = check_q1(doc)
    fails += errs
    if not errs:
        print("  ok Q1 corte del anónimo sólo en ai-gateway-service")
        muts = {
            "corte global del anónimo": lambda d: d["plugins"].append(
                {"name": "request-termination", "consumer": ANON, "config": {"status_code": 401}}),
            "corte del anónimo en ai-sales-public": lambda d: d["plugins"].append(
                {"name": "request-termination", "service": "ai-sales-public-service",
                 "consumer": ANON, "config": {"status_code": 401}}),
            "corte route-level en catalog-public": lambda d: [
                s.setdefault("plugins", []).append(
                    {"name": "request-termination", "consumer": ANON, "config": {"status_code": 401}})
                for s in d["services"] if s["name"] == "catalog-public-service"],
            "sin corte en ai-gateway": lambda d: d.__setitem__("plugins", [
                p for p in d["plugins"]
                if not (p["name"] == "request-termination" and p.get("service") == AI)]),
        }
        for label, m in muts.items():
            d = copy.deepcopy(doc)
            m(d)
            if not check_q1(d):
                fails.append(f"Q1: mutación no detectada — {label}")
        print(f"  ok Q1 mutaciones: {len(muts)} evaluadas")

    if not os.path.exists(EPICA):
        fails.append(f"Q2: no existe la épica en {EPICA}")
    else:
        text = open(EPICA).read()
        errs = check_q2(text)
        fails += errs
        if not errs:
            print("  ok Q2 decisión + inventario de callers registrados en la épica")
            block = t5d_block(text)
            for label, needle in (("sin inventario", "Inventario de callers"),
                                  ("sin decisión", "**Decisión:**")):
                if not check_q2(text.replace(block, block.replace(needle, "XXX"))):
                    fails.append(f"Q2: mutación no detectada — {label}")
    return fails


# ─── Runtime ────────────────────────────────────────────────────────────────────────────────

def runtime():
    spec = importlib.util.spec_from_file_location("t5c", os.path.join(HERE, "borde-estricto-runtime.py"))
    t5c = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(t5c)
    spec2 = importlib.util.spec_from_file_location("t5d", os.path.join(HERE, "borde-anonimo-t5d-runtime.py"))
    t5d = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(t5d)
    jwt = t5c.jwt
    fails = []

    def edge_401(label, st, h):
        if st != 401 or t5c.has_upstream(h):
            fails.append(f"{label} → {st} upstream={t5c.has_upstream(h)}, esperado 401 en el borde")
        else:
            print(f"  ok {label} → 401 en el borde")

    def passes(label, st, h):
        if st in (401, 403):
            fails.append(f"{label} → {st}, esperado pasar el borde")
        else:
            print(f"  ok {label} → {st} (pasó el borde)")

    token, err = t5c.login()
    if err:
        return [f"login: {err}"]
    key = t5d.api_key()
    if not key:
        return ["no encuentro AI_GATEWAY_API_KEY"]
    kid = jwt.get_unverified_header(token).get("kid")
    iss = jwt.decode(token, options={"verify_signature": False}).get("iss")
    now = int(time.time())
    claims = {"iss": iss, "sub": "forged", "exp": now + 600, "iat": now,
              "tenant_id": "00000000-0000-0000-0000-000000000000", "roles": ["SUPER_ADMIN"]}
    alg_none = f"{t5c.b64url({'alg': 'none', 'typ': 'JWT', 'kid': kid})}.{t5c.b64url(claims)}."

    # R1: la ruta pública hermana sobre el mismo upstream no queda cortada.
    for path in ("/ai/sales/health",):
        st, h, _ = t5c.call("GET", path)
        passes(f"R1 {path} sin token (pública)", st, h)

    # R2: /ai-gateway/pim/ sigue estricto (no se amplió por el reordenamiento).
    for label, kw in (("sin key", {}), ("alg:none", {"token": alg_none})):
        st, h, _ = t5c.call("GET", "/ai-gateway/pim/api/v1/products", **kw)
        edge_401(f"R2 /ai-gateway/pim/ {label}", st, h)

    # R3: el método no es un bypass.
    for label, kw in (("sin token", {}), ("alg:none", {"token": alg_none})):
        st, h, _ = t5c.call("POST", "/ai/ai/generate-template", body={"x": 1}, **kw)
        edge_401(f"R3 POST /ai/ai/generate-template {label}", st, h)

    # R4: canales de API key.
    path = "/ai-gateway/ai/dev-metrics"
    st, h, _ = t5c.call("GET", path, headers={"apiKey": key})
    passes(f"R4 {path} header apiKey válida", st, h)
    st, h, _ = t5c.call("GET", path, headers={"apiKey": "no-es-una-key"})
    edge_401(f"R4 {path} header apiKey inválida", st, h)
    st, h, _ = t5c.call("GET", f"{path}?apiKey={key}")
    edge_401(f"R4 {path} key válida en query (key_in_query: false)", st, h)

    # R5: firma manipulada — payload alterado conservando header y firma del login real.
    hdr_b64, _, sig = token.split(".")
    real = jwt.decode(token, options={"verify_signature": False})
    real["roles"] = ["SUPER_ADMIN"]
    real["tenant_id"] = "00000000-0000-0000-0000-000000000000"
    tampered = f"{hdr_b64}.{t5c.b64url(real)}.{sig}"
    st, h, _ = t5c.call("GET", path, token=tampered)
    edge_401(f"R5 {path} token del login con payload alterado", st, h)

    # R6: preflight CORS no queda cortado (cors corre antes que la auth).
    st, h, _ = t5c.call("OPTIONS", path, headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "Authorization",
    })
    if st in (401, 403) or "access-control-allow-origin" not in {k.lower() for k in h}:
        fails.append(f"R6 preflight {path} → {st}, esperado respuesta CORS (sin 401/403)")
    else:
        print(f"  ok R6 preflight {path} → {st} con Access-Control-Allow-Origin")

    # R7: onboarding público explícito + control compensatorio vivo.
    for label, kw in (("sin token", {}), ("alg:none forjado", {"token": alg_none})):
        st, h, _ = t5c.call("GET", "/onboarding/api/v1/steps", **kw)
        low = {k.lower(): v for k, v in h.items()}
        if st != 200 or not t5c.has_upstream(h):
            fails.append(f"R7 onboarding {label} → {st} upstream={t5c.has_upstream(h)}, esperado 200")
        elif low.get("x-ratelimit-limit-minute") != "100":
            fails.append(f"R7 onboarding {label}: X-RateLimit-Limit-Minute="
                         f"{low.get('x-ratelimit-limit-minute')!r}, esperado '100' (control compensatorio)")
        else:
            print(f"  ok R7 onboarding {label} → 200 con rate-limit 100/min")
    return fails


def main():
    fails = offline()
    if "--offline" not in sys.argv:
        fails += runtime()
    for f in fails:
        print("FAIL:", f)
    if fails:
        return 1
    print("OK: QA T5d")
    return 0


if __name__ == "__main__":
    sys.exit(main())
