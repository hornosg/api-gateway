#!/usr/bin/env python3
# PLAT-E39 · T8c1 · D7 — Tests de config del route `catalog-public-categories-list` en
# kong.yml.template. Espejo de D3.3 de T6d2 (patrón de `catalog-public-service-config.py`
# y `catalog-flip-config.py` de T8a).
#
# Verifica, SIN levantar Kong (parsea el template), las propiedades estructurales que el DoD
# de T8c1 exige para el endpoint público de categorías:
#   1. Existe un route `catalog-public-categories-list` dentro del `catalog-public-service`
#      existente — NO crea service nuevo (D7).
#   2. El path es el regex anclado `~/api/v1/public/marketplace/categories$` (no un prefijo
#      wildcard `categories*`): `POST`/`PATCH`/`DELETE` ni matchean, y `/categories/<id>` no
#      matchea (no hay detalle público: T7 no relevó consumidor).
#   3. `methods: ["GET"]` únicamente.
#   4. `strip_path: false` (el upstream ve el path original — el handler público lo monta en
#      `/api/v1/public/marketplace/categories`).
#   5. El route NO declara plugins jwt/acl propios: la seguridad anónima la hereda del
#      `catalog-public-service` (sin jwt/ACL/consumer, D3.3 punto 1). Un plugin route-level
#      de jwt/acl sobre la route pública contradiría "anónimo por diseño".
#   6. El service admin `catalog-service` sigue con jwt+acl (la pública NO relaja al admin).
#   7. Ningún otro service declara un path que contenga `/public/marketplace/categories` (no
#      hay un service duplicado compitiendo por el mismo path público).
#
# Uso: python3 tests/catalog-public-categories-config.py [ruta/a/kong.yml.template]
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

EXPECTED_PATH = "~/api/v1/public/marketplace/categories$"
EXPECTED_ROUTE = "catalog-public-categories-list"
EXPECTED_SERVICE = "catalog-public-service"

# 1. El route vive en el catalog-public-service existente.
check(EXPECTED_SERVICE in services,
      f"no existe `{EXPECTED_SERVICE}` (T8c1 reusa el service público de T6d2, no crea otro)")
pub = services.get(EXPECTED_SERVICE)
routes = {r.get("name"): r for r in (pub.get("routes", []) if pub else [])}
check(EXPECTED_ROUTE in routes,
      f"no existe el route `{EXPECTED_ROUTE}` en `{EXPECTED_SERVICE}`")

route = routes.get(EXPECTED_ROUTE)

# 2. Path regex anclado con `$`, no prefijo wildcard.
if route:
    paths = route.get("paths", [])
    check(len(paths) == 1, f"el route debe tener un único path, tiene {len(paths)}: {paths!r}")
    check(EXPECTED_PATH in paths,
          f"el path debe ser {EXPECTED_PATH!r}, es {paths!r}")
    for p in paths:
        check(isinstance(p, str) and p.startswith("~/") and p.endswith("$"),
              f"el path debe ser regex con ~/ y anclaje $: {p!r}")
        check("categories" in p and "*" not in p,
              f"el path no debe ser un wildcard `categories*` (D3.3 anclado): {p!r}")

# 3. GET-only.
if route:
    methods = route.get("methods", [])
    check(methods == ["GET"],
          f"el route debe tener methods: ['GET'], tiene {methods!r}")

# 4. strip_path false (upstream ve el path original).
if route:
    check(route.get("strip_path") is False,
          f"strip_path debe ser false (el handler público monta /api/v1/public/marketplace/categories), es {route.get('strip_path')!r}")

# 5. Sin plugins jwt/acl route-level sobre la route pública (anónimo por diseño).
if route:
    route_plugins = [p for p in plugins if p.get("route") == EXPECTED_ROUTE]
    route_plugin_names = [p.get("name") for p in route_plugins]
    check("jwt" not in route_plugin_names,
          f"la route pública NO debe tener plugin jwt route-level (anónimo, D3.3): {route_plugin_names!r}")
    check("acl" not in route_plugin_names,
          f"la route pública NO debe tener plugin acl route-level (anónimo, D3.3): {route_plugin_names!r}")

# 6. El service admin conserva jwt+acl (la pública NO relaja la postura del admin).
admin_plugin_names = [p.get("name") for p in plugins if p.get("service") == "catalog-service"]
check("jwt" in admin_plugin_names, "el service admin `catalog-service` debe conservar jwt")
check("acl" in admin_plugin_names, "el service admin `catalog-service` debe conservar acl")

# 7. Ningún OTRO service declara un path que contenga el substring público de categorías
#    (no hay un service duplicado compitiendo por el mismo path público).
owners = []
for sname, s in services.items():
    for r in s.get("routes", []):
        for p in r.get("paths", []) or []:
            if isinstance(p, str) and "/public/marketplace/categories" in p:
                owners.append((sname, r.get("name")))
check(len(owners) == 1 and owners[0][0] == EXPECTED_SERVICE,
      f"el path público de categories debe vivir sólo en `{EXPECTED_SERVICE}`, aparece en: {owners!r}")

if failures:
    print("FAIL: tests de config de catalog-public-categories (T8c1/D7)")
    for f in failures:
        print("  -", f)
    sys.exit(1)

print(f"PASS: {EXPECTED_ROUTE} cumple D7/D3.3 (route en catalog-public-service existente, regex anclado GET, sin jwt/acl route-level, admin conserva jwt+acl)")