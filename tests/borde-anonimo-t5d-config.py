#!/usr/bin/env python3
# ACC-E03 · T5d — Tests de config del acceso anónimo residual (O1 de la revisión de T5c).
#
# Decisión (épica ACC-E03, T5d):
#   - ai-gateway-service: borde estricto conservando el OR «JWT o X-API-Key». jwt y key-auth
#     siguen con `anonymous` (jwt corre antes que key-auth) y un `request-termination`
#     401 scoped a (ai-gateway-service, anonymous-consumer) corta a quien no presentó ninguna
#     credencial válida.
#   - onboarding-service: público explícito — sin `jwt` ni `acl`, conserva rate-limiting.
#
# Verifica SIN levantar Kong, más un auto-test de mutación: se quita cada control en una copia
# del documento y el checker TIENE que fallar.
#
# Uso: python3 tests/borde-anonimo-t5d-config.py [ruta/a/kong.yml.template]
import copy
import os
import re
import sys

import yaml

TEMPLATE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(__file__), "..", "kong.yml.template"
)
AI = "ai-gateway-service"
ONB = "onboarding-service"
AI_PUBLIC = "ai-sales-public-service"
ANON = "anonymous-consumer"


def load():
    src = open(TEMPLATE).read()
    src = re.sub(r"\$\{[A-Z_]+\}", "placeholder", src)
    return yaml.safe_load(src)


def svc_plugins(doc, svc):
    out = [p for p in doc.get("plugins", []) if p.get("service") == svc]
    for s in doc.get("services", []):
        if s["name"] == svc:
            out += s.get("plugins", [])
            for r in s.get("routes", []):
                out += r.get("plugins", [])
    return out


def check(doc):
    errs = []
    ai = svc_plugins(doc, AI)
    by = {}
    for p in ai:
        by.setdefault(p["name"], []).append(p)
    # OR JWT|API-key: ambos con anonymous (sin él, un caller sólo-API-key da 401 en jwt).
    for name in ("jwt", "key-auth"):
        if not any((p.get("config") or {}).get("anonymous") == ANON for p in by.get(name, [])):
            errs.append(f"{AI}: {name} sin anonymous → rompe el OR JWT|X-API-Key")
    rt = [p for p in by.get("request-termination", [])
          if p.get("consumer") == ANON and p.get("service") == AI
          and (p.get("config") or {}).get("status_code") == 401]
    if len(rt) != 1:
        errs.append(f"{AI}: falta request-termination 401 scoped a {ANON}")
    for p in by.get("request-termination", []):
        if p.get("consumer") != ANON:
            errs.append(f"{AI}: request-termination sin consumer anónimo cortaría a todos")
    if not by.get("rate-limiting"):
        errs.append(f"{AI}: sin rate-limiting")
    # El anónimo no puede reaparecer por un plugin route-level que no tenga el corte.
    for s in doc.get("services", []):
        if s["name"] == AI and len(s.get("routes", [])) != 1:
            errs.append(f"{AI}: se esperaba 1 route (la del corte)")
    onb = svc_plugins(doc, ONB)
    names = [p["name"] for p in onb]
    for bad in ("jwt", "acl"):
        if bad in names:
            errs.append(f"{ONB}: {bad} presente — debe ser público explícito")
    if "rate-limiting" not in names:
        errs.append(f"{ONB}: sin rate-limiting (control compensatorio)")
    for p in onb:
        if p["name"] == "rate-limiting":
            c = p.get("config") or {}
            if c.get("limit_by") != "ip" or c.get("policy") != "redis":
                errs.append(f"{ONB}: el rate-limit de la ruta pública debe ser limit_by ip + policy redis")
    # Invariante (review L4 C3): todo service que apunte a commerce-ai es el del corte o está
    # en la allowlist pública con paths anclados; un service nuevo sin corte no pasa.
    for s in doc.get("services", []):
        if "mc-commerce-ai-service" in str(s.get("url", "")) and s["name"] not in (AI, AI_PUBLIC):
            errs.append(f"{s['name']}: apunta a mc-commerce-ai-service sin el corte de {AI}")
    return errs


def main():
    doc = load()
    errs = check(doc)
    for e in errs:
        print("FAIL:", e)
    if errs:
        return 1
    print("OK: config T5d (ai-gateway estricto con OR JWT|API-key; onboarding público explícito)")

    def drop(d, name, svc):
        d["plugins"] = [p for p in d["plugins"] if not (p["name"] == name and p.get("service") == svc)]

    def unanon(d, name):
        for p in d["plugins"]:
            if p["name"] == name and p.get("service") == AI:
                p["config"].pop("anonymous", None)
        for s in d["services"]:
            if s["name"] == AI:
                for r in s["routes"]:
                    for p in r.get("plugins", []):
                        if p["name"] == name:
                            p["config"].pop("anonymous", None)

    def rt_200(d):
        for p in d["plugins"]:
            if p["name"] == "request-termination" and p.get("service") == AI:
                p["config"]["status_code"] = 200

    def rt_noconsumer(d):
        for p in d["plugins"]:
            if p["name"] == "request-termination" and p.get("service") == AI:
                p.pop("consumer")

    def onb_jwt(d):
        d["plugins"].append({"name": "jwt", "service": ONB, "config": {"anonymous": ANON}})

    def onb_local(d):
        for p in d["plugins"]:
            if p["name"] == "rate-limiting" and p.get("service") == ONB:
                p["config"]["limit_by"] = "consumer"

    def ai_bypass(d):
        d["services"].append({"name": "otro-ai", "url": "http://mc-commerce-ai-service:8200",
                              "routes": [{"name": "otro-ai-route", "paths": ["/otro-ai"]}]})

    muts = {
        "sin request-termination": lambda d: drop(d, "request-termination", AI),
        "request-termination 200": rt_200,
        "request-termination sin consumer": rt_noconsumer,
        "key-auth sin anonymous": lambda d: unanon(d, "key-auth"),
        "jwt sin anonymous": lambda d: unanon(d, "jwt"),
        "onboarding con jwt anónimo": onb_jwt,
        "onboarding sin rate-limit": lambda d: drop(d, "rate-limiting", ONB),
        "onboarding rate-limit por consumer": onb_local,
        "service nuevo hacia commerce-ai sin corte": ai_bypass,
    }
    bad = 0
    for label, m in muts.items():
        d = copy.deepcopy(doc)
        m(d)
        if not check(d):
            print("FAIL: mutación no detectada:", label)
            bad += 1
    if bad:
        return 1
    print(f"OK: {len(muts)}/{len(muts)} mutaciones detectadas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
