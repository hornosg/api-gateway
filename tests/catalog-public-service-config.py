#!/usr/bin/env python3
# PLAT-E39 · T6d · D3.3 — Tests de config del `catalog-public-service` en kong.yml.template.
#
# Verifica, SIN levantar Kong (parsea el template), las propiedades estructurales que el DoD
# de T6d exige para la superficie pública de catálogo:
#   1. Existe un `catalog-public-service` SEPARADO del admin, mismo upstream (mc-catalog-service:8160).
#   2. NO lleva plugin `jwt` ni `acl` (anónimo, sin consumer) — a diferencia del service admin.
#   3. Tiene siete routes: dos de global-catalog de T6d2, `catalog-public-global-brands-list`
#      de T11-R.2/T6d6, `catalog-public-categories-list` de T8c1/D7 y tres de
#      business-types/templates de T6d4/D11, todos con paths regex ANCLADOS (...$) y
#      `methods: ["GET"]`.
#   4. No matchean POST/PATCH/DELETE ni rutas tenant/S2S (los regex son específicos de la
#      superficie pública `/api/v1/public/...`).
#   5. Tiene plugin `rate-limiting` con `policy: redis` y `limit_by: ip` (no `local`).
#   6. Ningún consumer referencia al service público (no hay fallback anónimo compartido).
#   7. El service admin `catalog-service` conserva jwt+acl (la pública NO relaja al admin).
#
# Uso: python3 tests/catalog-public-service-config.py [ruta/a/kong.yml.template]
# Sale con código != 0 si alguna aserción falla (apta para CI).
import sys
import os

try:
    import yaml
except ImportError:
    print("FAIL: se requiere PyYAML (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)

TEMPLATE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "..", "kong.yml.template"
)

failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


with open(TEMPLATE) as fh:
    doc = yaml.safe_load(fh)

services = {s["name"]: s for s in doc.get("services", [])}
plugins = doc.get("plugins", [])
consumers = doc.get("consumers", [])

# 1. Service separado, mismo upstream.
check("catalog-public-service" in services,
      "no existe `catalog-public-service`")
pub = services.get("catalog-public-service")
admin = services.get("catalog-service")
if pub:
    check(pub.get("url") == "http://mc-catalog-service:8160",
          f"upstream del public service debe ser mc-catalog-service:8160, es {pub.get('url')!r}")
    check(admin is not None, "el service admin `catalog-service` debe seguir existiendo")
    if admin:
        check(pub is not admin and pub["name"] != admin["name"],
              "public y admin son el mismo service — deben ser separados")

# 2. Sin jwt/ACL en el service público.
pub_plugin_names = [p.get("name") for p in plugins if p.get("service") == "catalog-public-service"]
check("jwt" not in pub_plugin_names, "el service público NO debe tener plugin jwt (D3.3)")
check("acl" not in pub_plugin_names, "el service público NO debe tener plugin acl (D3.3)")

# 3 y 4. Routes regex anclados y GET-only. T6d2 (D3.3) agregó los dos de global-catalog;
# T11-R.2/T6d6 (D3.3+D15) agregó `catalog-public-global-brands-list`; T8c1 (D7) agregó
# `catalog-public-categories-list`; T6d4 (D11) agregó los tres de business-types/templates —
# todos al mismo service público, no crean service nuevo. Todas las routes del service público
# comparten las mismas garantías (regex anclado con `$`, `methods:[GET]`): POST/PATCH/DELETE
# ni matchean.
if pub:
    routes = pub.get("routes", [])
    # 7 → 8 el 2026-08-06: T6d8 agregó la ruta template-aware
    # (`/public/global-catalog/templates/<id>/products`). El test quedó stale y FALLABA —
    # detectado por `@dev-security` en el gate L4 de T17. Al sumar una ruta pública hay que
    # actualizar este conteo Y `expected_paths`: el conteo solo no alcanza (dos rutas mal
    # escritas darían 8 igual), y el set solo tampoco (no detecta rutas de más).
    check(len(routes) == 8, f"debe haber EXACTAMENTE ocho routes públicos, hay {len(routes)}")
    expected_paths = {
        "~/api/v1/public/global-catalog/products$",
        "~/api/v1/public/global-catalog/products/[^/]+$",
        "~/api/v1/public/global-catalog/brands$",
        "~/api/v1/public/marketplace/categories$",
        "~/api/v1/public/business-types$",
        "~/api/v1/public/business-type-templates$",
        "~/api/v1/public/business-type-templates/[^/]+$",
        "~/api/v1/public/global-catalog/templates/[^/]+/products$",
    }
    actual_paths = set()
    for r in routes:
        paths = r.get("paths", [])
        methods = r.get("methods", [])
        # Anclado al final con $ (Kong 3.4 exige `~/`, no `~^` — sin start-anchor posible).
        # El aislamiento D3.3 lo da `$` + `[^/]+` + methods:[GET], ver comentario en el template.
        for p in paths:
            check(isinstance(p, str) and p.startswith("~/") and p.endswith("$"),
                  f"path del route {r.get('name')} debe ser regex con ~/ y anclaje $: {p!r}")
        check(methods == ["GET"],
              f"route {r.get('name')} debe tener methods: ['GET'], tiene {methods!r}")
        actual_paths.update(paths)
    check(actual_paths == expected_paths,
          f"los paths públicos no coinciden con los esperados. actual={actual_paths} esperado={expected_paths}")

# 5. Rate-limiting redis por IP.
rl = [p for p in plugins if p.get("service") == "catalog-public-service" and p.get("name") == "rate-limiting"]
check(len(rl) == 1, f"debe haber un plugin rate-limiting en el service público, hay {len(rl)}")
if rl:
    cfg = rl[0].get("config", {})
    check(cfg.get("policy") == "redis",
          f"rate-limit público debe usar policy: redis, usa {cfg.get('policy')!r}")
    check(cfg.get("limit_by") == "ip",
          f"rate-limit público debe limit_by: ip, usa {cfg.get('limit_by')!r}")
    check(cfg.get("redis_host") == "lab-redis",
          f"rate-limit público policy:redis requiere redis_host=lab-redis, tiene {cfg.get('redis_host')!r}")
    check(cfg.get("redis_port") == 6379,
          f"rate-limit público requiere redis_port=6379, tiene {cfg.get('redis_port')!r}")

# 6. Ningún consumer referencia al service público (no hay consumer/ACL público compartido).
#    Consumers no "referencian" services en Kong declarativo, pero un ACL público se reflejaría
#    como un consumer con group "public-routes" usado por el service. Verificamos que el
#    service público NO declara ACL (ya hecho en punto 2) y que ningún consumer fue creado
#    específicamente para catálogo público (no existe catalog-public-consumer).
consumer_names = [c.get("username") for c in consumers]
check("catalog-public-consumer" not in consumer_names,
      "no debe existir `catalog-public-consumer` (D3.3: sin consumer público dedicado ni anónimo)")

# 7. El service admin conserva jwt+acl (la pública NO relaja la postura del admin).
admin_plugin_names = [p.get("name") for p in plugins if p.get("service") == "catalog-service"]
check("jwt" in admin_plugin_names, "el service admin `catalog-service` debe conservar jwt")
check("acl" in admin_plugin_names, "el service admin `catalog-service` debe conservar acl")

if failures:
    print("FAIL: tests de config de catalog-public-service")
    for f in failures:
        print("  -", f)
    sys.exit(1)

print("PASS: catalog-public-service cumple D3.3 (service separado sin jwt/ACL, ocho regex GET anclados [global-catalog list/detail + brands T11-R.2 + categories T8c1 + business-types/templates T6d4 + template-products T6d8], rate-limit redis por IP, admin conserva jwt+acl)")