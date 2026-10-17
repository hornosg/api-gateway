#!/usr/bin/env python3
# PLAT-E39 · T8a/T17 · D1/D3.3 — Tests de config del flip de Kong en kong.yml.template.
#
# Verifica, SIN levantar Kong (parsea el template), las propiedades estructurales que el
# DoD de T8a/T17 exige para el flip de los paths de plataforma que mc_admin sirve vía `/pim/`:
#   1. Existen 5 services `catalog-flip-*`, cada uno con upstream mc-catalog-service:8160
#      y URL que incluye el handler path `/api/v1/<familia>` (patrón reclassify).
#   2. Cada flip service tiene EXACTAMENTE 1 route, `strip_path: true`, `methods: ["GET"]`
#      (GET-only: catalog-service es read-only para brand/category/business-types/
#      business-type-templates; las mutaciones quedan en pim vía la catch-all `/pim/`).
#   3. Cada route declara `jwt` + `acl` + `rate-limiting` (route-level, autocontenido).
#   4. D1 — la config de jwt+acl+rate-limiting de cada flip es IDÉNTICA a la del service
#      `pim-service` vigente (mismo HS256/iss/exp, mismas ACL groups, mismo rate limit),
#      EXCEPTO (T17 · D3.3): el flip NO usa `anonymous` ni `public-routes` — jamás el
#      `anonymous-consumer` compartido en rutas admin. Sin JWT → 401 en el borde.
#   5. El flip de global-catalog es `/global-catalog/products` (acotado), NO el prefijo
#      `global-catalog` — catalog-service no sirve `/global-catalog/business-types`.
#   6. Sin colisión de prefijos: `/pim/api/v1/business-types` no es prefijo de
#      `/pim/api/v1/business-type-templates` (divergen en `s` vs `-`).
#   7. Los paths de flip son más específicos que la catch-all `/pim/` (ganan el matcheo
#      GET); los method no-GET caen a `/pim/` → pim (mutaciones preservadas).
#
# Uso: python3 tests/catalog-flip-config.py [ruta/a/kong.yml.template]
# Sale con código != 0 si alguna aserción falla (apta para CI).
import sys
import os
import re

try:
    import yaml
except ImportError:
    print("FAIL: se requiere PyYAML (pip install pyyaml)", file=sys.stderr)
    sys.exit(2)

TEMPLATE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "..", "kong.yml.template"
)

failures = []


def load():
    with open(TEMPLATE) as f:
        src = f.read()
    # El template tiene placeholders ${VAR} y __X__ que no son YAML válido para
    # valores secretos; sustituir por string neutro para parsear la estructura.
    src = re.sub(r"\$\{[A-Z_]+\}", "placeholder", src)
    src = re.sub(r"__[A-Z_]+__", "placeholder", src)
    return yaml.safe_load(src)


def plugins_of(route):
    return {p["name"]: p.get("config", {}) for p in route.get("plugins", [])}


def main():
    doc = load()
    services = {s["name"]: s for s in doc.get("services", [])}
    plugins = doc.get("plugins", [])

    # Config vigente de pim-service (fuente de verdad para D1).
    pim_jwt = next(p["config"] for p in plugins
                   if p["name"] == "jwt" and p.get("service") == "pim-service")
    pim_acl = next(p["config"] for p in plugins
                   if p["name"] == "acl" and p.get("service") == "pim-service")
    pim_rl = next(p["config"] for p in plugins
                  if p["name"] == "rate-limiting" and p.get("service") == "pim-service")

    # T17 · D3.3 — el flip NO usa anonymous ni public-routes. La referencia a
    # comparar es la config de pim SIN `anonymous` (jwt) y SIN `public-routes` (acl).
    expected_jwt = {k: v for k, v in pim_jwt.items() if k != "anonymous"}
    expected_acl = {
        "allow": [g for g in pim_acl.get("allow", []) if g != "public-routes"],
        "hide_groups_header": pim_acl.get("hide_groups_header", True),
    }

    expected = {
        "catalog-flip-brands":
            ("/pim/api/v1/marketplace-brands", "/api/v1/marketplace-brands"),
        "catalog-flip-categories":
            ("/pim/api/v1/marketplace/categories", "/api/v1/marketplace/categories"),
        "catalog-flip-business-types":
            ("/pim/api/v1/business-types", "/api/v1/business-types"),
        "catalog-flip-business-type-templates":
            ("/pim/api/v1/business-type-templates", "/api/v1/business-type-templates"),
        "catalog-flip-global-catalog-products":
            ("/pim/api/v1/global-catalog/products", "/api/v1/global-catalog/products"),
    }

    for name, (ext_path, handler_path) in expected.items():
        if name not in services:
            failures.append(f"{name}: service ausente")
            continue
        svc = services[name]
        url = svc.get("url", "")
        if url != f"http://mc-catalog-service:8160{handler_path}":
            failures.append(f"{name}: url={url!r} esperada "
                            f"http://mc-catalog-service:8160{handler_path}")
        routes = svc.get("routes", [])
        if len(routes) != 1:
            failures.append(f"{name}: esperaba 1 route, hay {len(routes)}")
            continue
        r = routes[0]
        if r.get("paths") != [ext_path]:
            failures.append(f"{name}: paths={r.get('paths')!r} esperado [{ext_path!r}]")
        if r.get("strip_path") is not True:
            failures.append(f"{name}: strip_path debe ser true")
        if r.get("methods") != ["GET"]:
            failures.append(f"{name}: methods={r.get('methods')!r} debe ser [GET] "
                            f"(GET-only: las mutaciones quedan en pim)")
        pl = plugins_of(r)
        if set(pl) != {"jwt", "acl", "rate-limiting"}:
            failures.append(f"{name}: plugins={sorted(pl)} esperado "
                            "['acl','jwt','rate-limiting']")
            continue
        # D1 — idéntica a pim-service, salvo anonymous/public-routes (T17 · D3.3).
        if "anonymous" in pl["jwt"]:
            failures.append(f"{name}: jwt NO debe usar anonymous (T17 · D3.3 — "
                            f"jamás el anonymous-consumer compartido en rutas admin)")
        if pl["jwt"] != expected_jwt:
            failures.append(f"{name}: jwt diverge de pim-service (D1 idéntica, "
                            f"sin anonymous). diff={pl['jwt']} vs {expected_jwt}")
        if "public-routes" in pl["acl"].get("allow", []):
            failures.append(f"{name}: acl NO debe permitir public-routes (T17 · D3.3)")
        if pl["acl"] != expected_acl:
            failures.append(f"{name}: acl diverge de pim-service (D1 idéntica, "
                            f"sin public-routes). diff={pl['acl']} vs {expected_acl}")
        if pl["rate-limiting"] != pim_rl:
            failures.append(f"{name}: rate-limiting diverge de pim-service")

    # Aserción 5: global-catalog flip acotado a /products.
    gc = services.get("catalog-flip-global-catalog-products", {})
    gc_path = gc.get("routes", [{}])[0].get("paths", [None])[0]
    if gc_path != "/pim/api/v1/global-catalog/products":
        failures.append(f"global-catalog flip debe ser acotado a /products, no al "
                        f"prefijo global-catalog (catalog-service no sirve "
                        f"/global-catalog/business-types). path={gc_path!r}")

    # Aserción 6: sin colisión business-types vs business-type-templates.
    bt = "/pim/api/v1/business-types"
    btt = "/pim/api/v1/business-type-templates"
    if btt.startswith(bt) or bt.startswith(btt):
        failures.append(f"colisión de prefijos entre {bt} y {btt}")

    # Aserción 7: los flip paths son más específicos que la catch-all /pim/.
    pim_route = services.get("pim-service", {}).get("routes", [{}])[0]
    pim_paths = pim_route.get("paths", [])
    if "/pim/" in pim_paths:
        for name, (ext_path, _) in expected.items():
            # ext_path debe tener más segmentos que /pim/ para ganar el matcheo.
            if ext_path.rstrip("/").count("/") <= "/pim/".count("/"):
                failures.append(f"{name}: {ext_path} no es más específico que /pim/")

    if failures:
        print("FAIL — tests de config del flip de Kong (T8a/T17 · D1/D3.3):")
        for f in failures:
            print(f"  ✗ {f}")
        sys.exit(1)
    print("PASS — 5 flip services con jwt+acl+rate-limiting idénticos a pim-service "
          "(sin anonymous ni public-routes, T17 · D3.3), GET-only, paths acotados, "
          "sin colisión, más específicos que /pim/.")


if __name__ == "__main__":
    main()