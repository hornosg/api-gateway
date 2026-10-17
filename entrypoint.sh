#!/bin/bash
set -e

# Validate required environment variables
required_vars=("AI_GATEWAY_API_KEY" "MARKETPLACE_ADMIN_API_KEY" "CORS_ORIGINS" "JWT_PUBLIC_KEY" "SALES_SERVICE_API_KEY" "CATALOG_BFF_API_KEY" "ONBOARDING_SERVICE_API_KEY" "PIM_S2S_API_KEY" "PIM_CATALOG_S2S_API_KEY")
for var in "${required_vars[@]}"; do
  if [ -z "${!var}" ]; then
    echo "SECURITY ERROR: Required environment variable $var is not set"
    exit 1
  fi
done

# ACC-E03 T5: JWT_PUBLIC_KEY es la pública RS256 de account-service (PEM). En .env va en una
# línea con \n literales; acá se normaliza a líneas reales. Sólo material público: una
# privada en esta variable es un incidente L4 y el gateway no arranca.
JWT_PUBLIC_KEY_PEM=$(printf '%b' "$JWT_PUBLIC_KEY")
if echo "$JWT_PUBLIC_KEY_PEM" | grep -q 'PRIVATE KEY'; then
  echo "SECURITY ERROR: JWT_PUBLIC_KEY contains a PRIVATE KEY — only the public key goes to Kong"
  exit 1
fi
if ! echo "$JWT_PUBLIC_KEY_PEM" | grep -q -- '-----BEGIN PUBLIC KEY-----'; then
  echo "SECURITY ERROR: JWT_PUBLIC_KEY is not a PEM public key (-----BEGIN PUBLIC KEY-----)"
  exit 1
fi

# Step 1: Replace API key placeholders
sed "s|\${AI_GATEWAY_API_KEY}|${AI_GATEWAY_API_KEY}|g; s|\${MARKETPLACE_ADMIN_API_KEY}|${MARKETPLACE_ADMIN_API_KEY}|g; s|\${SALES_SERVICE_API_KEY}|${SALES_SERVICE_API_KEY}|g; s|\${CATALOG_BFF_API_KEY}|${CATALOG_BFF_API_KEY}|g; s|\${ONBOARDING_SERVICE_API_KEY}|${ONBOARDING_SERVICE_API_KEY}|g; s|\${PIM_S2S_API_KEY}|${PIM_S2S_API_KEY}|g; s|\${PIM_CATALOG_S2S_API_KEY}|${PIM_CATALOG_S2S_API_KEY}|g" \
  /opt/kong/kong.yml.template > /tmp/kong_intermediate.yml

# Step 2: Expand the RS256 public key block and the CORS origins list
while IFS= read -r line; do
  if [[ "$line" == *'${JWT_PUBLIC_KEY}'* ]]; then
    indent="${line%%\$\{JWT_PUBLIC_KEY\}*}"
    while IFS= read -r pem_line; do
      if [ -n "$pem_line" ]; then echo "${indent}${pem_line}"; fi
    done <<< "$JWT_PUBLIC_KEY_PEM"
  elif echo "$line" | grep -q '__CORS_ORIGINS_PLACEHOLDER__'; then
    IFS=',' read -ra ORIGINS <<< "$CORS_ORIGINS"
    for origin in "${ORIGINS[@]}"; do
      origin=$(echo "$origin" | tr -d ' ')
      echo "        - \"${origin}\""
    done
  else
    echo "$line"
  fi
done < /tmp/kong_intermediate.yml > /tmp/kong.yml

rm -f /tmp/kong_intermediate.yml

export KONG_DECLARATIVE_CONFIG=/tmp/kong.yml

echo "Kong configuration generated successfully"
echo "  CORS origins: $CORS_ORIGINS"
echo "  API keys: [REDACTED]"

exec /docker-entrypoint.sh kong docker-start
