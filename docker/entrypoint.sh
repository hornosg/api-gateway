#!/bin/bash

# Script de inicialización para Kong con plugins personalizados
# Este script maneja la inicialización de Kong, migraciones y configuración declarativa

set -e

echo "🚀 Iniciando Kong Gateway con plugins personalizados..."

# Esperar a que PostgreSQL esté disponible
echo "⏳ Esperando a que PostgreSQL esté disponible..."
until pg_isready -h ${KONG_PG_HOST:-kong-db} -p ${KONG_PG_PORT:-5432} -U ${KONG_PG_USER:-kong}; do
  echo "   PostgreSQL no está listo, esperando..."
  sleep 2
done

echo "✅ PostgreSQL está disponible"

# Ejecutar migraciones si es necesario
if [ "${KONG_MIGRATE:-false}" = "true" ]; then
  echo "🔄 Ejecutando migraciones de Kong..."
  kong migrations bootstrap || kong migrations up
  echo "✅ Migraciones completadas"
fi

# Aplicar configuración declarativa si existe
if [ -f "/etc/kong/kong.yml" ]; then
  echo "📋 Aplicando configuración declarativa..."
  kong config db_import /etc/kong/kong.yml
  echo "✅ Configuración declarativa aplicada"
fi

# Verificar que el plugin personalizado esté disponible
echo "🔍 Verificando plugins disponibles..."
if kong version | grep -q "Kong"; then
  echo "✅ Kong está correctamente instalado"
  if [ -d "/usr/local/share/lua/5.1/kong/plugins/feature-flags" ]; then
    echo "✅ Plugin feature-flags encontrado"
  else
    echo "⚠️  Plugin feature-flags no encontrado en el directorio esperado"
    ls -la /usr/local/share/lua/5.1/kong/plugins/
  fi
fi

echo "🎯 Iniciando Kong Gateway..."

# Iniciar Kong con logging verbose para debugging
exec kong start --vv 