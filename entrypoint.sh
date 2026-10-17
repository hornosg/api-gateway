#!/bin/bash
set -e

# Validate required environment variables
required_vars=("AI_GATEWAY_API_KEY" "MARKETPLACE_ADMIN_API_KEY" "CORS_ORIGINS" "JWT_SECRET" "SALES_SERVICE_API_KEY" "CATALOG_BFF_API_KEY" "ONBOARDING_SERVICE_API_KEY" "PIM_S2S_API_KEY" "PIM_CATALOG_S2S_API_KEY")
for var in "${required_vars[@]}"; do
  if [ -z "${!var}" ]; then
    echo "SECURITY ERROR: Required environment variable $var is not set"
    exit 1
  fi
done

# Step 1: Replace API key and JWT secret placeholders
sed "s|\${AI_GATEWAY_API_KEY}|${AI_GATEWAY_API_KEY}|g; s|\${MARKETPLACE_ADMIN_API_KEY}|${MARKETPLACE_ADMIN_API_KEY}|g; s|\${JWT_SECRET}|${JWT_SECRET}|g; s|\${SALES_SERVICE_API_KEY}|${SALES_SERVICE_API_KEY}|g; s|\${CATALOG_BFF_API_KEY}|${CATALOG_BFF_API_KEY}|g; s|\${ONBOARDING_SERVICE_API_KEY}|${ONBOARDING_SERVICE_API_KEY}|g; s|\${PIM_S2S_API_KEY}|${PIM_S2S_API_KEY}|g; s|\${PIM_CATALOG_S2S_API_KEY}|${PIM_CATALOG_S2S_API_KEY}|g" \
  /opt/kong/kong.yml.template > /tmp/kong_intermediate.yml

# Step 2: Replace CORS origins placeholder with YAML list from comma-separated env var
while IFS= read -r line; do
  if echo "$line" | grep -q '__CORS_ORIGINS_PLACEHOLDER__'; then
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
