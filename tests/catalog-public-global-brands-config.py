#!/usr/bin/env python3
# PLAT-E39 · T11-R.2 / T6d6 · D3.3 + D15 — Tests de config de la route
# `catalog-public-global-brands-list` en kong.yml.template. Espejo de D3.3 de T6d2/T8c1/T6d4
# (patrón de `catalog-public-business-types-config.py`).
#
# Verifica, SIN levantar Kong (parsea el template), las propiedades estructurales que el DoD
# de T6d6 exige para el endpoint público de marcas por categoría:
#   1. Existe el route `catalog-public-global-brands-list` dentro del `catalog-public-service`
#      existente — NO crea service nuevo (reusa el de T6d2).
#   2. El path es regex anclado con `$`, no wildcard: `~/api/v1/public/global-catalog/brands$`.
#      `POST`/`PATCH`/`DELETE` ni matchean; `/brands/<id>` no matchea (no hay detalle público).
#   3. `methods: ["GET"]` únicamente.
#   4. `strip_path: false` (el upstream ve el path original — el handler lo monta en
#      `/api/v1/public/global-catalog/brands`).
#   5. Ningún plugin jwt/acl route-level sobre la route pública (anónimo por diseño, D3.3).
#   6. El service admin `catalog-service` sigue con jwt+acl (la pública NO relaja al admin).
#   7. Ningún otro service declara un path que contenga el substring público de brands (no hay
#      service duplicado compitiendo).
#
# Uso: python3 tests/catalog-public-global-brands-config.py [ruta/a/kong.yml.template]
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
ROUTE_NAME = "catalog-public-global-brands-list"
EXPECTED_PATH = "~/api/v1/public/global-catalog/brands$"

# 1. El route vive en el catalog-public-service existente (no crea service nuevo).
check(EXPECTED_SERVICE in services,
      f"no existe `{EXPECTED_SERVICE}` (T6d6 reusa el service público de T6d2, no crea otro)")
pub = services.get(EXPECTED_SERVICE)
routes = {r.get("name"): r for r in (pub.get("routes", []) if pub else [])}

check(ROUTE_NAME in routes,
      f"no existe el route `{ROUTE_NAME}` en `{EXPECTED_SERVICE}`")
route = routes.get(ROUTE_NAME)

# 2. Path regex anclado con `$`, no prefijo wildcard.
if route:
    paths = route.get("paths", [])
    check(len(paths) == 1, f"`{ROUTE_NAME}` debe tener un único path, tiene {len(paths)}: {paths!r}")
    check(EXPECTED_PATH in paths,
          f"`{ROUTE_NAME}` path debe ser {EXPECTED_PATH!r}, es {paths!r}")
    for p in paths:
        check(isinstance(p, str) and p.startswith("~/") and p.endswith("$"),
              f"`{ROUTE_NAME}` path debe ser regex con ~/ y anclaje $: {p!r}")
        check("*" not in p,
              f"`{ROUTE_NAME}` path no debe ser wildcard (D3.3 anclado): {p!r}")

# 3. GET-only.
if route:
    methods = route.get("methods", [])
    check(methods == ["GET"],
          f"`{ROUTE_NAME}` debe tener methods: ['GET'], tiene {methods!r}")

# 4. strip_path false (upstream ve el path original).
if route:
    check(route.get("strip_path") is False,
          f"`{ROUTE_NAME}` strip_path debe ser false (handler monta /api/v1/public/...), es {route.get('strip_path')!r}")

# 5. Sin plugins jwt/acl route-level sobre la route pública (anónimo por diseño).
if route:
    route_plugins = [p for p in plugins if p.get("route") == ROUTE_NAME]
    route_plugin_names = [p.get("name") for p in route_plugins]
    check("jwt" not in route_plugin_names,
          f"`{ROUTE_NAME}` route pública NO debe tener plugin jwt route-level (anónimo): {route_plugin_names!r}")
    check("acl" not in route_plugin_names,
          f"`{ROUTE_NAME}` route pública NO debe tener plugin acl route-level (anónimo): {route_plugin_names!r}")

# 6. El service admin conserva jwt+acl (la pública NO relaja la postura del admin).
admin_plugin_names = [p.get("name") for p in plugins if p.get("service") == "catalog-service"]
check("jwt" in admin_plugin_names, "el service admin `catalog-service` debe conservar jwt")
check("acl" in admin_plugin_names, "el service admin `catalog-service` debe conservar acl")

# 7. Ningún OTRO service declara un path que contenga el substring público de brands (no hay
#    service duplicado).
PUBLIC_SUBSTRING = "/public/global-catalog/brands"
owners = []
for sname, s in services.items():
    for r in s.get("routes", []):
        for p in r.get("paths", []) or []:
            if isinstance(p, str) and PUBLIC_SUBSTRING in p:
                owners.append((sname, r.get("name")))
check(len(owners) == 1 and owners[0][0] == EXPECTED_SERVICE,
      f"el path público de brands debe vivir sólo en `{EXPECTED_SERVICE}` (1 route), aparece en: {owners!r}")

if failures:
    print("FAIL: tests de config de catalog-public-global-brands (T11-R.2/T6d6/D3.3+D15)")
    for f in failures:
        print("  -", f)
    sys.exit(1)

print(f"PASS: route `{ROUTE_NAME}` en `{EXPECTED_SERVICE}` cumple D3.3+D15 "
      "(regex anclado GET, sin jwt/acl route-level, admin conserva jwt+acl, sin service duplicado)")