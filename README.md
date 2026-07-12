# 🌐 API Gateway del lab (`~/Projects`)

API Gateway implementado con Kong (`lab-kong`) que actúa como **único punto de entrada** para
todos los microservicios del lab — cross-project, replicable tal cual en prod.

## 📋 Descripción

Este servicio proporciona:
- **Routing centralizado** para todos los microservicios
- **Autenticación JWT** y validación de tokens
- **Rate limiting** para protección contra abuso
- **CORS** configurado para frontends
- **Métricas** con Prometheus
- **Multi-tenancy** con headers automáticos

## 🏗️ Arquitectura

```
Frontend Apps → lab-kong Proxy (8000) → Backend Services
                     ↓
              [Auth, Rate Limit, CORS, Metrics]
```

## 🚀 Configuración y Uso

### Desarrollo Local — este repo es el ÚNICO gateway del lab (`~/Projects`)

Este repo (`infra/api-gateway/` dentro del lab, `hornosg/api-gateway` como git remoto) es la
**única fuente de verdad** de Kong para todo `~/Projects` — cross-project, pensado para ser
replicable tal cual en prod (mismo Dockerfile + template). El directorio `infra/kong/` que existía
antes era un archivo huérfano y peligroso (recargarlo vía Admin API pisaba esta config real); fue
retirado (`MC-E28`, root-cause del incidente del 2026-06-17).

El contenedor `lab-kong` se levanta desde `infra/docker-compose.yml` (raíz del lab), construyendo
la imagen de **este** directorio:

```bash
# Desde ~/Projects (raíz del lab)
docker compose -f infra/docker-compose.yml up -d kong

# Ver estado
curl http://localhost:8001/status

# Ver servicios configurados
curl http://localhost:8001/services
```

### Cómo se genera la config real (`kong.yml.template` → `KONG_DECLARATIVE_CONFIG`)

`kong.yml` **no se edita directo en runtime** — la fuente versionada es `kong.yml.template`, con
placeholders (`${JWT_SECRET}`, `${AI_GATEWAY_API_KEY}`, etc. y `__CORS_ORIGINS_PLACEHOLDER__`).
Al bootear el contenedor, `entrypoint.sh`:
1. Sustituye los placeholders `${...}` con los valores de `infra/api-gateway/.env` (secrets, API keys de consumers).
2. Expande `__CORS_ORIGINS_PLACEHOLDER__` en una lista YAML a partir de `CORS_ORIGINS` (coma-separado) del mismo `.env`.
3. Escribe el resultado en `/tmp/kong.yml` y lo apunta como `KONG_DECLARATIVE_CONFIG`.

**Para aplicar cualquier cambio**: editar `kong.yml.template` y/o `.env`, después **rebuild +
recrear** `lab-kong` — el template se copia a la imagen en el build (`COPY`, no volumen), así que
un `restart` solo reutiliza la imagen vieja sin ver el cambio (verificado 2026-07-09 al agregar
ledger-service: `restart` mantuvo la config anterior, hizo falta rebuild):
```bash
docker compose -f ~/Projects/infra/docker-compose.yml up -d --build kong
```

### Puertos

- **8000**: Kong Proxy (punto de entrada para APIs)
- **8001**: Kong Admin API — expuesto solo en `127.0.0.1` del host (loopback-only, ver ADR-003a), no en la LAN

## 📁 Estructura del Proyecto

```
api-gateway/
├── kong.yml.template            # Fuente de verdad versionada — 24+ servicios, consumers, jwt/acl/rate-limiting
├── entrypoint.sh                # Renderiza el template con .env al boot del contenedor
├── Dockerfile                   # Imagen usada por infra/docker-compose.yml (build context)
├── .env / .env.example          # Secrets/CORS que entrypoint.sh inyecta (NO versionar .env real)
├── plugins/
│   └── feature-flags/          # Plugin personalizado (pendiente de activación)
│       ├── handler.lua        
│       └── schema.lua         
├── documentation/
│   ├── ARCHITECTURE_PATTERNS.md  # Patrones arquitectónicos
│   └── KONG_SETUP.md             # Guía de configuración detallada
└── CLAUDE.md                     # Guía para desarrollo con IA
```

## 🔧 Servicios Configurados

Ver el listado completo y actualizado en `kong.yml.template` (services: / routes:). Incluye,
entre otros: IAM (+ rutas de auth login/refresh públicas con rate-limiting dedicado), PIM,
Stock, Sales, Tenant, Customer, Payment Method, Onboarding, Catalog BFF, Webdata, Notifications,
AI Gateway/Sales Chat, y rutas `internal-*` para tráfico s2s.

### Configuración de Plugins

#### Activos
- **JWT Authentication**: Validación de tokens
- **CORS**: Configurado para localhost:3000, 3004, 3005
- **Rate Limiting**: 60 req/min estándar, 20 req/min para AI
- **Prometheus**: Métricas en `/metrics`

#### Pendientes de Activación
- **Feature Flags Plugin**: Plugin personalizado para manejo de features por tenant (código existe pero no está activado en producción)

## 🔐 Seguridad

### Headers Requeridos
```http
Authorization: Bearer <jwt_token>
X-Tenant-ID: <tenant_uuid>
Content-Type: application/json
```

### Endpoints Públicos (sin autenticación)
- `/iam/api/v1/auth/login`
- `/iam/api/v1/auth/refresh`
- `/*/api/v1/health`

## 📊 Monitoreo

### Health Checks
```bash
# Estado del gateway
curl http://localhost:8001/status

# Métricas Prometheus
curl http://localhost:8000/metrics

# Verificar servicios/rutas configurados
curl http://localhost:8001/services
curl http://localhost:8001/routes
```

### Logs
```bash
# Ver logs del contenedor
docker logs lab-kong

# Seguir logs en tiempo real
docker logs -f lab-kong
```

## 🛠️ Desarrollo

### Testing de Endpoints

```bash
# Test sin autenticación (endpoint público) — vía el PROXY (8000), no el Admin API
curl http://localhost:8000/iam/api/v1/health

# Test con autenticación
curl http://localhost:8000/pim/api/v1/products \
  -H "Authorization: Bearer ${JWT_TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}"
```

### Agregar Nuevo Servicio

1. Editar `kong.yml.template` (agregar el bloque `services:`/`routes:`, y `consumers`/`acls`/`plugins` si requiere auth)
2. Si necesita nuevos secrets, agregarlos como placeholder y documentarlos en `.env.example`
3. Rebuild + recrear Kong: `docker compose -f ~/Projects/infra/docker-compose.yml up -d --build kong` (un `restart` solo no alcanza — el template se copia al build)

## ⚠️ Notas Importantes

### Estado del Plugin Feature-Flags
El plugin personalizado `feature-flags` está desarrollado pero **NO está activo** en la configuración actual. Para activarlo:
1. Agregar `feature-flags` a la variable `KONG_PLUGINS` (Dockerfile o env)
2. Reconstruir la imagen (`docker compose -f ~/Projects/infra/docker-compose.yml build kong`) con el plugin incluido

### Configuración Actual
`lab-kong` se construye **desde el `Dockerfile` de este directorio** (`kong:3.4.0` como base) vía
`infra/docker-compose.yml` (`build: context: ./api-gateway`) — no es la imagen stock sin modificar.
El render de `kong.yml.template` con `.env` ocurre en cada arranque del contenedor (`entrypoint.sh`).

## 📚 Documentación Adicional

- [Autenticación y Seguridad](./KONG_AUTH_DOCUMENTATION.md) - Guía completa de autenticación JWT y API Keys
- [Troubleshooting](./documentation/KONG_TROUBLESHOOTING.md) - Solución de problemas comunes
- [Arquitectura y Patrones](./documentation/ARCHITECTURE_PATTERNS.md)
- [Configuración Detallada de Kong](./documentation/KONG_SETUP.md)
- [Guía para Claude Code](./CLAUDE.md)

## 🤝 Contribución

1. Los cambios de configuración se hacen en `kong.yml`
2. Para cambios en plugins, modificar archivos en `plugins/`
3. Probar localmente antes de hacer push
4. Documentar cambios en este README

## 📝 Licencia

Parte del proyecto SaaS Multi-tenant Platform.