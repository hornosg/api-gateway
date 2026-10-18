#!/usr/bin/env python3
# ACC-E09 T2 · ADR-006 «Exposición del endpoint» — tests de config (sin levantar Kong).
#   1. No existe ninguna ruta ni service de Kong hacia /api/v1/s2s/token (O-1 de la revisión L4 de
#      T2: los emisores van directo por lab-network).
#   2. iam-s2s-block-service: /iam/api/v1/s2s termina en 404 con request-termination; es más
#      específica que el catch-all /iam/ de iam-service.
#   3. Ningún plugin global (sin service/route/consumer) de jwt/acl.
# Uso: python3 tests/s2s-token-config.py [ruta/a/kong.yml.template]
import os
import re
import sys

import yaml

TEMPLATE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "kong.yml.template")
failures = []


def check(cond, msg):
    if not cond:
        failures.append(msg)


def main():
    src = open(TEMPLATE).read()
    src = re.sub(r"\$\{[A-Z_]+\}", "placeholder", src)
    src = re.sub(r"__[A-Z_]+__", "placeholder", src)
    doc = yaml.safe_load(src)
    services = {s["name"]: s for s in doc.get("services", [])}
    top = doc.get("plugins", [])

    # O-1: la emisión no tiene ruta en Kong. Ningún service ni ruta puede tener como upstream el
    # endpoint de emisión ni exponer un path que termine en él (los emisores van directo por lab-network).
    check("iam-s2s-token-service" not in services, "iam-s2s-token-service no debe existir: la emisión es solo directa")
    for name, svc in services.items():
        check("/api/v1/s2s/token" not in str(svc.get("url", "")), f"{name}: el upstream no puede ser el endpoint de emisión")
        for r in svc.get("routes", []):
            for path in r.get("paths", []):
                check(not path.rstrip("/").endswith("/s2s/token"), f"{name}: ruta pública {path} alcanza la emisión")

    blk = services.get("iam-s2s-block-service")
    check(blk is not None, "falta iam-s2s-block-service")
    if blk:
        r = (blk.get("routes") or [{}])[0]
        check(set(r.get("paths", [])) >= {"/iam/api/v1/s2s", "/internal/iam/api/v1/s2s"}, f"paths del bloqueo: {r.get('paths')}")
        check("methods" not in r, "el bloqueo aplica a todos los métodos")
        rp = {p["name"]: p.get("config", {}) for p in r.get("plugins", [])}
        rt = rp.get("request-termination", {})
        check(rt.get("status_code") == 404, f"request-termination debe responder 404: {rt}")
    # C-1 (revisión L4 de T2): todo service cuyo upstream sea la RAÍZ de iam y tenga un prefijo con
    # strip_path alcanzaría /api/v1/s2s/token desde ese prefijo (/iam/, /internal/iam/…). Cada uno
    # necesita un bloqueo más específico <prefijo>api/v1/s2s.
    blocked = set((blk or {}).get("routes", [{}])[0].get("paths", [])) if blk else set()
    for name, svc in services.items():
        if str(svc.get("url", "")).rstrip("/") != "http://mc-iam-service:8080":
            continue
        for r in svc.get("routes", []):
            for path in r.get("paths", []):
                if name == "iam-s2s-block-service":
                    continue
                if not path.endswith("/"):
                    continue
                need = path + "api/v1/s2s"
                check(need in blocked, f"{name}: el prefijo {path} alcanza la emisión; falta el bloqueo {need}")
    iam_paths = [p for r in services.get("iam-service", {}).get("routes", []) for p in r.get("paths", [])]
    check("/iam/" in iam_paths, "el catch-all /iam/ cambió: revisar el bloqueo")

    globales = [p["name"] for p in top if not any(k in p for k in ("service", "route", "consumer"))]
    check("jwt" not in globales and "acl" not in globales, f"plugins globales jwt/acl: {globales}")

    if failures:
        for f in failures:
            print("FAIL:", f)
        sys.exit(1)
    print("OK: s2s-token-config (sin ruta de emisión en Kong; /iam/api/v1/s2s → 404)")


main()
