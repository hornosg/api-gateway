#!/usr/bin/env python3
# ACC-E03 · T5c — Tests de config del borde estricto en kong.yml.template.
#
# Contrato (épica ACC-E03, T5c): en las rutas sin acceso público el plugin `jwt` NO lleva
# `anonymous` (o el `acl` exige sólo `authenticated`) para que un JWT inválido dé 401 en Kong
# sin llegar al upstream; las rutas públicas inventariadas siguen respondiendo sin token.
#
# Verifica, SIN levantar Kong (parsea el template):
#   1. Los 13 services estrictos (los 12 del inventario + catalog-service) tienen `jwt`
#      service-level SIN `anonymous` y `acl` con allow == ["authenticated"].
#   2. Lista blanca cerrada: los ÚNICOS `jwt` con `anonymous` (service- o route-level) son
#      onboarding-service y ai-gateway-service (inventario de la épica). Uno nuevo falla.
#   3. Ninguna route de un service estricto re-abre el fallback con un `jwt`/`acl` propio.
#   4. `catalog-bff-public-service`: upstream del BFF, 1 route GET-only, sin jwt/acl, regex
#      anclado que matchea SÓLO `/catalog/api/v1/marketplace/categories[/tree]`, uri
#      reescrito al capture y rate-limiting.
#   5. CASO NEGATIVO (auto-test de mutación): se re-introduce cada control ausente en una
#      copia del documento (anonymous en pim, public-routes en iam, regex sin `$`, POST en el
#      service público, jwt anónimo en una route de tenant) y el checker TIENE que fallar.
#      Si una mutación pasa, el test no está mirando el control y sale != 0.
#
# Uso: python3 tests/borde-estricto-config.py [ruta/a/kong.yml.template]
# Sale con código != 0 si alguna aserción falla (apta para CI).
import copy
import os
import re
import sys

try:
    import yaml
except ImportError:
    print("FAIL: se requiere PyYAML (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)

TEMPLATE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "..", "kong.yml.template"
)

# Inventario de la épica (criterio d): borde estricto.
STRICT = [
    "iam-service", "pim-service", "stock-service", "catalog-bff-service", "sales-service",
    "customer-service", "ledger-service", "payment-method-service", "marketplace-service",
    "webdata-service", "notification-service", "tenant-service",
    # Ya estricto antes de T5c (PLAT-E39); no debe regresionar.
    "catalog-service",
]
# Inventario de la épica: conservan `anonymous` con justificación escrita.
ANONYMOUS_ALLOWED = {"onboarding-service", "ai-gateway-service"}

PUBLIC_SVC = "catalog-bff-public-service"
PUBLIC_OK = [
    "/catalog/api/v1/marketplace/categories",
    "/catalog/api/v1/marketplace/categories/tree",
]
PUBLIC_MUST_NOT_MATCH = [
    "/catalog/api/v1/marketplace/categories/",
    "/catalog/api/v1/marketplace/categories/123",
    "/catalog/api/v1/marketplace/categories/tree/x",
    "/catalog/api/v1/marketplace/categories/tree/",
    "/catalog/api/v1/marketplace/categoriesX",
    "/catalog/api/v1/marketplace/categories?x=1/admin",
    "/catalog/api/v1/products",
    "/catalog/api/v1/marketplace/brands",
    "/admin/api/v1/marketplace/categories",
    "/admin/api/v1/marketplace/categories/tree",
    "/x/catalog/api/v1/marketplace/categories",
    "/catalog/api/v1/marketplace/categories%2F..%2Fadmin",
]


def load():
    with open(TEMPLATE) as f:
        src = f.read()
    src = re.sub(r"\$\{[A-Z_]+\}", "placeholder", src)
    src = re.sub(r"__[A-Z_]+__", "placeholder", src)
    return yaml.safe_load(src)


def kong_regex_match(pattern, path):
    # Kong (router traditional_compatible) ancla el regex al inicio del path; `re.match`
    # reproduce ese anclaje. El fin lo tiene que anclar el propio patrón con `$`.
    return re.match(pattern, path) is not None


def check(doc):
    failures = []
    services = {s["name"]: s for s in doc.get("services", [])}
    plugins = doc.get("plugins", [])

    def svc_plugin(name, svc):
        return [p for p in plugins if p["name"] == name and p.get("service") == svc]

    # 1. Services estrictos.
    for svc in STRICT:
        if svc not in services:
            failures.append(f"{svc}: service ausente del template")
            continue
        jwts = svc_plugin("jwt", svc)
        if len(jwts) != 1:
            failures.append(f"{svc}: esperaba 1 plugin jwt service-level, hay {len(jwts)}")
        for p in jwts:
            if "anonymous" in (p.get("config") or {}):
                failures.append(f"{svc}: jwt conserva anonymous="
                                f"{p['config']['anonymous']!r} — un JWT inválido llega al upstream")
        acls = svc_plugin("acl", svc)
        if len(acls) != 1:
            failures.append(f"{svc}: esperaba 1 plugin acl service-level, hay {len(acls)}")
        for p in acls:
            allow = (p.get("config") or {}).get("allow")
            if allow != ["authenticated"]:
                failures.append(f"{svc}: acl allow={allow!r}, esperado ['authenticated']")

    # 2. Lista blanca cerrada de `anonymous` (global, service- y route-level).
    with_anon = set()
    for p in plugins:
        if p["name"] == "jwt" and "anonymous" in (p.get("config") or {}):
            with_anon.add(p.get("service") or p.get("route") or "<global>")
    for s in services.values():
        for p in s.get("plugins", []) or []:
            if p["name"] == "jwt" and "anonymous" in (p.get("config") or {}):
                with_anon.add(s["name"])
        for r in s.get("routes", []) or []:
            for p in r.get("plugins", []) or []:
                if p["name"] == "jwt" and "anonymous" in (p.get("config") or {}):
                    with_anon.add(f"{s['name']}/{r.get('name')}")
    extra = with_anon - ANONYMOUS_ALLOWED
    if extra:
        failures.append(f"jwt con anonymous fuera del inventario: {sorted(extra)}")

    # 3. Ninguna route de un service estricto re-abre el fallback.
    for svc in STRICT:
        for r in (services.get(svc) or {}).get("routes", []) or []:
            for p in r.get("plugins", []) or []:
                cfg = p.get("config") or {}
                if p["name"] == "jwt" and "anonymous" in cfg:
                    failures.append(f"{svc}/{r.get('name')}: jwt route-level con anonymous")
                if p["name"] == "acl" and "public-routes" in (cfg.get("allow") or []):
                    failures.append(f"{svc}/{r.get('name')}: acl route-level admite public-routes")

    # 4. Service público del BFF.
    pub = services.get(PUBLIC_SVC)
    if pub is None:
        failures.append(f"{PUBLIC_SVC}: service ausente — las categorías públicas darían 401")
        return failures
    if pub.get("url") != "http://mc-catalog-bff-service:8085":
        failures.append(f"{PUBLIC_SVC}: url={pub.get('url')!r}, esperado el BFF :8085")
    if svc_plugin("jwt", PUBLIC_SVC) or svc_plugin("acl", PUBLIC_SVC):
        failures.append(f"{PUBLIC_SVC}: no debe llevar jwt/acl (es público)")
    routes = pub.get("routes", []) or []
    if len(routes) != 1:
        failures.append(f"{PUBLIC_SVC}: esperaba 1 route, hay {len(routes)}")
        return failures
    r = routes[0]
    if r.get("methods") != ["GET"]:
        failures.append(f"{PUBLIC_SVC}: methods={r.get('methods')!r}, debe ser ['GET']")
    paths = r.get("paths") or []
    if len(paths) != 1 or not paths[0].startswith("~"):
        failures.append(f"{PUBLIC_SVC}: esperaba 1 path regex (~...), hay {paths!r}")
        return failures
    pattern = paths[0][1:]
    if not pattern.endswith("$"):
        failures.append(f"{PUBLIC_SVC}: regex {pattern!r} no anclado con $")
    for path in PUBLIC_OK:
        if not kong_regex_match(pattern, path):
            failures.append(f"{PUBLIC_SVC}: regex no matchea la ruta pública {path}")
    for path in PUBLIC_MUST_NOT_MATCH:
        if kong_regex_match(pattern, path):
            failures.append(f"{PUBLIC_SVC}: regex matchea {path} — amplía el acceso anónimo")
    pl = {p["name"]: p.get("config") or {} for p in r.get("plugins", []) or []}
    if "jwt" in pl or "acl" in pl:
        failures.append(f"{PUBLIC_SVC}: route no debe llevar jwt/acl")
    uri = ((pl.get("request-transformer") or {}).get("replace") or {}).get("uri")
    if uri != "$(uri_captures[1])":
        failures.append(f"{PUBLIC_SVC}: request-transformer uri={uri!r}, "
                        "esperado $(uri_captures[1])")
    for path in PUBLIC_OK:
        m = re.match(pattern, path)
        if m and m.group(1) != path[len("/catalog"):]:
            failures.append(f"{PUBLIC_SVC}: capture de {path} = {m.group(1)!r}, "
                            f"esperado {path[len('/catalog'):]!r}")
    if "rate-limiting" not in pl:
        failures.append(f"{PUBLIC_SVC}: falta rate-limiting en la ruta anónima")
    return failures


def mutations(doc):
    def jwt_of(d, svc):
        return next(p for p in d["plugins"] if p["name"] == "jwt" and p.get("service") == svc)

    def acl_of(d, svc):
        return next(p for p in d["plugins"] if p["name"] == "acl" and p.get("service") == svc)

    def pub_route(d):
        return next(s for s in d["services"] if s["name"] == PUBLIC_SVC)["routes"][0]

    def m_anon_pim(d):
        jwt_of(d, "pim-service")["config"]["anonymous"] = "anonymous-consumer"

    def m_public_routes_iam(d):
        acl_of(d, "iam-service")["config"]["allow"].append("public-routes")

    def m_regex_sin_ancla(d):
        r = pub_route(d)
        r["paths"] = [r["paths"][0].rstrip("$")]

    def m_post_publico(d):
        pub_route(d)["methods"] = ["GET", "POST"]

    def m_route_anon_tenant(d):
        tenant = next(s for s in d["services"] if s["name"] == "tenant-service")
        tenant["routes"][0].setdefault("plugins", []).append(
            {"name": "jwt", "config": {"anonymous": "anonymous-consumer"}})

    def m_sin_service_publico(d):
        d["services"] = [s for s in d["services"] if s["name"] != PUBLIC_SVC]

    def m_anon_nuevo_global(d):
        d["plugins"].append({"name": "jwt", "service": "crm-frontend",
                             "config": {"anonymous": "anonymous-consumer"}})

    return [m_anon_pim, m_public_routes_iam, m_regex_sin_ancla, m_post_publico,
            m_route_anon_tenant, m_sin_service_publico, m_anon_nuevo_global]


def main():
    doc = load()
    failures = check(doc)

    # 5. Caso negativo: cada mutación que reabre el borde TIENE que ser detectada.
    for m in mutations(doc):
        d = copy.deepcopy(doc)
        try:
            m(d)
        except (StopIteration, KeyError, IndexError) as e:
            failures.append(f"mutación {m.__name__}: no aplicable ({e!r}) — revisar el test")
            continue
        if not check(d):
            failures.append(f"mutación {m.__name__}: el checker NO la detectó — "
                            "el test no está mirando ese control")

    if failures:
        print(f"FAIL ({len(failures)}) — {TEMPLATE}")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print(f"OK — borde estricto: {len(STRICT)} services sin anonymous, "
          f"anonymous sólo en {sorted(ANONYMOUS_ALLOWED)}, {PUBLIC_SVC} acotado, "
          f"{len(mutations(doc))} mutaciones negativas detectadas")


if __name__ == "__main__":
    main()
