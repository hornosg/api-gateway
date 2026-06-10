# 🌐 SaaS MT API Gateway

API Gateway implementado con Kong que actúa como punto de entrada unificado para todos los microservicios del sistema SaaS Multi-tenant.

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
Frontend Apps → Kong Gateway (8001) → Backend Services
                     ↓
              [Auth, Rate Limit, CORS, Metrics]
```

## 🚀 Configuración y Uso

### Desarrollo Local

El gateway se ejecuta como parte de la infraestructura principal:

```bash
# Iniciar con docker-compose
docker-compose -f docker-compose.infra.yml up kong

# Verificar estado
curl http://localhost:8001/status

# Ver servicios configurados
curl http://localhost:8444/services
```

### Puertos

- **8001**: Kong Proxy (punto de entrada para APIs)
- **8444**: Kong Admin API (configuración y monitoreo)

## 📁 Estructura del Proyecto

```
saas-mt-api-gateway/
├── kong.yml                    # Configuración declarativa de Kong
├── Dockerfile                  # Imagen Docker (no usado actualmente)
├── plugins/
│   └── feature-flags/         # Plugin personalizado (pendiente de activación)
│       ├── handler.lua        
│       └── schema.lua         
├── documentation/
│   ├── ARCHITECTURE_PATTERNS.md  # Patrones arquitectónicos
│   └── KONG_SETUP.md             # Guía de configuración detallada
└── CLAUDE.md                     # Guía para desarrollo con IA
```

## 🔧 Servicios Configurados

### Backend Services
- **IAM Service**: `/iam/` → `http://iam-service:8080`
- **PIM Service**: `/pim/` → `http://pim-service:8080`
- **Stock Service**: `/stock/` → `http://stock-service:8080`
- **AI Gateway**: `/ai-gateway/` → `http://ai-gateway:8000`
- **Chat Service**: `/chat/` → `http://chat-service:8000`

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
curl http://localhost:8001/metrics

# Verificar servicios upstream
curl http://localhost:8444/upstreams
```

### Logs
```bash
# Ver logs del contenedor
docker logs tv-kong

# Seguir logs en tiempo real
docker logs -f tv-kong
```

## 🛠️ Desarrollo

### Testing de Endpoints

```bash
# Test sin autenticación (endpoint público)
curl http://localhost:8001/iam/api/v1/health

# Test con autenticación
curl http://localhost:8001/pim/api/v1/products \
  -H "Authorization: Bearer ${JWT_TOKEN}" \
  -H "X-Tenant-ID: ${TENANT_ID}"
```

### Agregar Nuevo Servicio

1. Editar `kong.yml`
2. Agregar configuración del servicio y rutas
3. Reiniciar Kong: `docker-compose -f docker-compose.infra.yml restart kong`

## ⚠️ Notas Importantes

### Estado del Plugin Feature-Flags
El plugin personalizado `feature-flags` está desarrollado pero **NO está activo** en la configuración actual. Para activarlo:
1. Modificar `docker-compose.infra.yml` para usar el Dockerfile personalizado
2. Agregar `feature-flags` a la variable `KONG_PLUGINS`
3. Reconstruir la imagen con el plugin incluido

### Configuración Actual
Kong se ejecuta actualmente con la imagen estándar `kong:3.4.0` desde `docker-compose.infra.yml`. El Dockerfile personalizado en este directorio no se está utilizando.

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