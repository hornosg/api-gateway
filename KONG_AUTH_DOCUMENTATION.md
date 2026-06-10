# Kong API Gateway - Documentación de Autenticación

## 📋 Resumen Ejecutivo

Este documento describe el sistema de autenticación dual implementado en Kong Gateway para diferenciar entre:
- **Operaciones Administrativas Globales** (Marketplace Admin)
- **Operaciones de Tenant** (Backoffice/Sellers)

## 🔐 Tipos de Autenticación

### 1. Autenticación para Marketplace Admin (Operaciones Globales)

Las operaciones administrativas que afectan al sistema completo (curación de productos, gestión de catálogo global, validación de marcas) usan **API Key**.

#### Headers Requeridos:
```http
X-API-Key: marketplace-admin-key-2025
X-User-Role: marketplace_admin
Content-Type: application/json
```

#### Ejemplo de Request (Curación de Producto):
```bash
curl -X POST http://localhost:8001/ai/products/curate \
  -H "Content-Type: application/json" \
  -H "X-API-Key: marketplace-admin-key-2025" \
  -H "X-User-Role: marketplace_admin" \
  -d '{
    "product": {
      "id": "product-id-123",
      "name": "Producto a Curar",
      "brand": "Marca X",
      "category": "Categoría Y",
      "price": 100.50,
      "currency": "ARS"
    },
    "use_ai_extraction": true,
    "validate_brand": true
  }'
```

#### Ejemplo de Request (Listar Productos Scrapeados):
```bash
curl -X GET "http://localhost:8001/scraper/api/v1/marketplace/products?page_size=10" \
  -H "X-API-Key: marketplace-admin-key-2025" \
  -H "X-User-Role: marketplace_admin"
```

### 2. Autenticación para Backoffice/Sellers (Operaciones de Tenant)

Las operaciones específicas de un tenant (gestión de productos propios, ventas, inventario) usan **JWT Token**.

#### Headers Requeridos:
```http
Authorization: Bearer <jwt_token>
X-Tenant-ID: <tenant_uuid>
Content-Type: application/json
```

#### Ejemplo de Request (Categorizar Producto del Tenant):
```bash
curl -X POST http://localhost:8001/ai/products/categorize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "X-Tenant-ID: 550e8400-e29b-41d4-a716-446655440001" \
  -d '{
    "product_name": "Laptop Gaming",
    "description": "Laptop para juegos con RTX 4060"
  }'
```

#### Ejemplo de Request (Chat con Documentos del Tenant):
```bash
curl -X POST http://localhost:8001/ai/documents/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." \
  -H "X-Tenant-ID: 550e8400-e29b-41d4-a716-446655440001" \
  -d '{
    "document_id": "doc-456",
    "question": "¿Cuáles son las cláusulas de penalización?"
  }'
```

## 🎯 Endpoints por Tipo de Usuario

### Endpoints Exclusivos para Marketplace Admin

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/scraper/api/v1/marketplace/products` | GET | Listar productos scrapeados |
| `/scraper/api/v1/marketplace/products/{id}/curation-status` | PATCH | Actualizar estado de curación |
| `/ai/products/curate` | POST | Curar producto con AI |
| `/ai/products/bulk-curate` | POST | Curación masiva |
| `/ai/marketplace/brands/validate` | POST | Validar marcas globales |
| `/ai/catalog/generate-template` | POST | Generar templates globales |
| `/pim/api/v1/marketplace/brands` | GET/POST | Gestión de marcas del marketplace |
| `/pim/api/v1/marketplace/categories` | GET/POST | Gestión de categorías globales |

### Endpoints Exclusivos para Tenants (Backoffice)

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/ai/onboarding/analyze-business` | POST | Análisis del negocio del tenant |
| `/ai/products/categorize` | POST | Categorización de productos propios |
| `/ai/documents/chat` | POST | Chat con documentos del tenant |
| `/ai/voice/transcribe` | POST | Transcripción de ventas |
| `/pim/api/v1/products` | GET/POST | Gestión de productos del tenant |
| `/stock/api/v1/inventory` | GET/POST | Gestión de inventario del tenant |
| `/iam/api/v1/users` | GET/POST | Gestión de usuarios del tenant |

## 🔄 Flujo de Autenticación en Kong

### Para Requests de Admin:

```mermaid
graph LR
    A[Frontend Admin] -->|X-API-Key| B[Kong Gateway]
    B -->|Valida API Key| C{¿Key Válida?}
    C -->|Sí| D[Agrega Headers]
    D -->|X-User-Role: marketplace_admin| E[Backend Service]
    C -->|No| F[403 Forbidden]
```

### Para Requests de Tenant:

```mermaid
graph LR
    A[Frontend Backoffice] -->|JWT Token| B[Kong Gateway]
    B -->|Valida JWT| C{¿Token Válido?}
    C -->|Sí| D[Extrae tenant_id del JWT]
    D -->|X-Tenant-ID| E[Backend Service]
    C -->|No| F[401 Unauthorized]
```

## 🔧 Configuración en Kong

### Consumers Configurados

```yaml
consumers:
  # Para usuarios autenticados con JWT
  - username: iam-service-consumer
    jwt_secrets:
      - key: "iam-service"
        algorithm: "HS256"
        secret: "${JWT_SECRET}"
    acls:
      - group: "authenticated"

  # Consumer anónimo para rutas públicas
  - username: anonymous-consumer
    acls:
      - group: "public-routes"

  # Para AI Gateway (comunicación interna y ACL)
  - username: ai-gateway-consumer
    custom_id: ai-gateway
    keyauth_credentials:
      - key: "ai-gateway-secret-key-2025"
    acls:
      - group: "ai-gateway-access"
      - group: "authenticated"
  
  # Para operaciones administrativas globales
  - username: marketplace-admin-consumer
    keyauth_credentials:
      - key: "marketplace-admin-key-2025"
    acls:
      - group: "marketplace-admin"
      - group: "authenticated"
```

> ⚠️ **IMPORTANTE**: Cada consumer debe tener una API Key única. La duplicación de keys causará que Kong falle al iniciar con el error "uniqueness violation".

### Services y Routes

```yaml
services:
  # Scraper Service (solo admin)
  - name: scraper-service
    url: http://mc-scraper:8086
    routes:
      - paths: [/scraper/]
        strip_path: true

  # AI Gateway (autenticación flexible)
  - name: ai-gateway-service
    url: http://ai-gateway:8050
    routes:
      - paths: [/ai/, /ai-gateway/]
        strip_path: true
        
  # PIM Service (ambos tipos de auth)
  - name: pim-service
    url: http://pim-service:8080
    routes:
      - paths: [/pim/]
        strip_path: true
```

## 🛡️ Seguridad

### API Keys
- Deben rotarse mensualmente
- Almacenar en variables de entorno, nunca en código
- Usar diferentes keys para cada ambiente (dev, staging, prod)

### JWT Tokens
- Expiración máxima: 24 horas
- Refresh token: 7 días
- Incluir claims mínimos necesarios

### Headers Sensibles
- Kong puede ocultar headers sensibles con `hide_credentials: true`
- Los logs no deben incluir tokens completos

## 📊 Monitoreo y Auditoría

### Logs de Acceso Admin
Todas las operaciones administrativas generan logs con:
- Usuario/API Key utilizada
- Operación realizada
- Timestamp
- IP de origen
- Resultado (éxito/error)

### Métricas por Tipo de Auth
Kong genera métricas separadas para:
- Requests con API Key
- Requests con JWT
- Tasa de errores por tipo
- Latencia por endpoint

## 🚨 Troubleshooting

### Error: "Kong en estado Restarting"
**Causa**: Error en la configuración de `kong.yml`, típicamente claves duplicadas
**Síntomas**: 
```bash
docker ps | grep kong
# Muestra: Restarting (1) X seconds ago
```

**Diagnóstico**:
```bash
# Ver logs de Kong
docker logs tv-kong --tail 50

# Buscar errores de "uniqueness violation"
docker logs tv-kong 2>&1 | grep "uniqueness violation"
```

**Solución**:
1. Identificar la clave duplicada en los logs
2. Editar `services/saas-mt-api-gateway/kong.yml`
3. Asegurar que cada `keyauth_credentials.key` sea única en todos los consumers
4. Reiniciar Kong: `docker restart tv-kong`
5. Verificar: `docker ps | grep kong` debe mostrar "Up X seconds (healthy)"

**Ejemplo de error común**:
```yaml
# ❌ INCORRECTO - Key duplicada
consumers:
  - username: consumer-1
    keyauth_credentials:
      - key: "same-key-2025"
  - username: consumer-2
    keyauth_credentials:
      - key: "same-key-2025"  # ❌ DUPLICADA

# ✅ CORRECTO - Keys únicas
consumers:
  - username: consumer-1
    keyauth_credentials:
      - key: "consumer-1-key-2025"
  - username: consumer-2
    keyauth_credentials:
      - key: "consumer-2-key-2025"
```

### Error: "X-Tenant-ID header required"
**Causa**: Request de tenant sin el header X-Tenant-ID
**Solución**: Asegurar que el JWT contenga el tenant_id o agregarlo manualmente

### Error: "Invalid API Key"
**Causa**: API Key incorrecta o expirada
**Solución**: Verificar la key en Kong consumers, rotar si es necesario

### Error: "403 Forbidden"
**Causa**: Usuario/API Key sin permisos para el recurso
**Solución**: Verificar ACLs en Kong, agregar al grupo correcto

### Error: "Invalid X-Tenant-ID format"
**Causa**: El tenant ID no es un UUID válido
**Solución**: Usar formato UUID v4: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

## 📝 Mejores Prácticas

1. **Nunca mezclar tipos de autenticación** en una misma request
2. **Usar el tipo correcto** según el contexto (admin vs tenant)
3. **Validar siempre** en el backend aunque Kong valide primero
4. **Logs detallados** para operaciones administrativas
5. **Rate limiting diferenciado** por tipo de usuario
6. **Cache de validaciones** para mejorar performance

## 🔄 Migración de Sistema Anterior

Si estás migrando de acceso directo a servicios:

### Antes (Incorrecto ❌):
```javascript
// Acceso directo al backend
fetch('http://localhost:8086/api/v1/marketplace/products')
```

### Después (Correcto ✅):
```javascript
// A través de Kong con autenticación
fetch('http://localhost:8001/scraper/api/v1/marketplace/products', {
  headers: {
    'X-API-Key': 'marketplace-admin-key-2025',
    'X-User-Role': 'marketplace_admin'
  }
})
```

## 📚 Referencias

- [Kong Authentication Plugins](https://docs.konghq.com/hub/#authentication)
- [JWT Plugin Documentation](https://docs.konghq.com/hub/kong-inc/jwt/)
- [Key Auth Plugin Documentation](https://docs.konghq.com/hub/kong-inc/key-auth/)
- [ACL Plugin Documentation](https://docs.konghq.com/hub/kong-inc/acl/)

---

**Última actualización**: 21 de Noviembre 2025
**Versión**: 1.1.0
**Mantenido por**: Equipo DevOps - Mercado Cercano

## 🔄 Historial de Cambios

### v1.1.0 - 21 de Noviembre 2025
- ✅ Corregido problema de claves duplicadas en consumers
- ✅ Consolidados consumers de AI Gateway (eliminado `ai-gateway-internal` duplicado)
- ✅ Agregados ACLs adicionales a consumers principales
- ✅ Agregada sección de troubleshooting para errores de configuración
- ✅ Documentado proceso de diagnóstico para Kong en estado "Restarting"

### v1.0.0 - 16 de Agosto 2025
- 🎉 Versión inicial de la documentación de autenticación
- Configuración de autenticación dual (JWT + API Key)
- Documentación de consumers y rutas
- Ejemplos de uso para marketplace admin y tenants