#!/usr/bin/env python3
# PLAT-E39 · T6d4 · D11 — Tests de config de las routes `catalog-public-business-types-*`
# en kong.yml.template. Espejo de D3.3 de T6d2/T8c1 (patrón de
# `catalog-public-categories-config.py`).
#
# Verifica, SIN levantar Kong (parsea el template), las propiedades estructurales que el
# DoD de T6d4 exige para los tres endpoints públicos de la taxonomía de plantilla:
#   1. Existen tres routes (`catalog-public-business-types-list`,
#      `catalog-public-business-type-templates-list`,
#      `catalog-public-business-type-template-detail`) dentro del `catalog-public-service`
#      existente — NO crea service nuevo (D11).
#   2. Los paths son regex anclados con `$`, no wildcards: `business-types$`,
#      `business-type-templates$` y `business-type-templates/[^/]+$` (detalle = un solo
#      segmento). `POST`/`PATCH`/`DELETE` ni matchean.
#   3. `methods: ["GET"]` únicamente en los tres.
#   4. `strip_path: false` (el upstream ve el path original — los handlers públicos los
#      montan en `/api/v1/public/...`).
#   5. Ningún route declara plugins jwt/acl propios (anónimo por diseño, D3.3/D11).
#   6. El service admin `catalog-service` sigue con jwt+acl (la pública NO relaja al admin).
#   7. Ningún otro service declara un path que contenga los substrings públicos de
#      business-types/business-type-templates (no hay service duplicado compitiendo).
#
# Uso: python3 tests/catalog-public-business-types-config.py [ruta/a/kong.yml.template]
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

EXPECTED_SERVICE = "catalog-public-service"

ROUTES = [
    ("catalog-public-business-types-list", "~/api/v1/public/business-types$"),
    ("catalog-public-business-type-templates-list", "~/api/v1/public/business-type-templates$"),
    ("catalog-public-business-type-template-detail", "~/api/v1/public/business-type-templates/[^/]+$"),
]

# 1. Los tres routes viven en el catalog-public-service existente (no crea service nuevo).
check(EXPECTED_SERVICE in services,
      f"no existe `{EXPECTED_SERVICE}` (T6d4 reusa el service público de T6d2, no crea otro)")
pub = services.get(EXPECTED_SERVICE)
routes = {r.get("name"): r for r in (pub.get("routes", []) if pub else [])}

for route_name, expected_path in ROUTES:
    check(route_name in routes,
          f"no existe el route `{route_name}` en `{EXPECTED_SERVICE}`")
    route = routes.get(route_name)

    # 2. Path regex anclado con `$`, no prefijo wildcard.
    if route:
        paths = route.get("paths", [])
        check(len(paths) == 1, f"`{route_name}` debe tener un único path, tiene {len(paths)}: {paths!r}")
        check(expected_path in paths,
              f"`{route_name}` path debe ser {expected_path!r}, es {paths!r}")
        for p in paths:
            check(isinstance(p, str) and p.startswith("~/") and p.endswith("$"),
                  f"`{route_name}` path debe ser regex con ~/ y anclaje $: {p!r}")
            check("*" not in p,
                  f"`{route_name}` path no debe ser wildcard (D11 anclado): {p!r}")

    # 3. GET-only.
    if route:
        methods = route.get("methods", [])
        check(methods == ["GET"],
              f"`{route_name}` debe tener methods: ['GET'], tiene {methods!r}")

    # 4. strip_path false (upstream ve el path original).
    if route:
        check(route.get("strip_path") is False,
              f"`{route_name}` strip_path debe ser false (handler monta /api/v1/public/...), es {route.get('strip_path')!r}")

    # 5. Sin plugins jwt/acl route-level sobre la route pública (anónimo por diseño).
    if route:
        route_plugins = [p for p in plugins if p.get("route") == route_name]
        route_plugin_names = [p.get("name") for p in route_plugins]
        check("jwt" not in route_plugin_names,
              f"`{route_name}` route pública NO debe tener plugin jwt route-level (anónimo): {route_plugin_names!r}")
        check("acl" not in route_plugin_names,
              f"`{route_name}` route pública NO debe tener plugin acl route-level (anónimo): {route_plugin_names!r}")

# 6. El service admin conserva jwt+acl (la pública NO relaja la postura del admin).
admin_plugin_names = [p.get("name") for p in plugins if p.get("service") == "catalog-service"]
check("jwt" in admin_plugin_names, "el service admin `catalog-service` debe conservar jwt")
check("acl" in admin_plugin_names, "el service admin `catalog-service` debe conservar acl")

# 7. Ningún OTRO service declara un path que contenga los substrings públicos de
#    business-types/business-type-templates (no hay service duplicado).
PUBLIC_SUBSTRINGS = [
    "/public/business-types",
    "/public/business-type-templates",
]
owners = []
for sname, s in services.items():
    for r in s.get("routes", []):
        for p in r.get("paths", []) or []:
            if isinstance(p, str) and any(sub in p for sub in PUBLIC_SUBSTRINGS):
                owners.append((sname, r.get("name")))
check(len(owners) == 3 and all(o[0] == EXPECTED_SERVICE for o in owners),
      f"los paths públicos de business-types deben vivir sólo en `{EXPECTED_SERVICE}` (3 routes), aparece en: {owners!r}")

if failures:
    print("FAIL: tests de config de catalog-public-business-types (T6d4/D11)")
    for f in failures:
        print("  -", f)
    sys.exit(1)

print(f"PASS: 3 routes de business-types/templates en `{EXPECTED_SERVICE}` cumplen D11/D3.3 "
      "(regex anclado GET, sin jwt/acl route-level, admin conserva jwt+acl, sin service duplicado)")