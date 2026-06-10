local jwt_decoder = require "kong.plugins.jwt.jwt_parser"

local FeatureFlagsHandler = {}

FeatureFlagsHandler.PRIORITY = 900
FeatureFlagsHandler.VERSION = "1.0.0"

function FeatureFlagsHandler:access(conf)
  local headers = kong.request.get_headers()
  local authorization = headers["authorization"]
  
  if not authorization then
    return
  end
  
  -- Extraer token JWT
  local token = authorization:match("Bearer%s+(.+)")
  if not token then
    return
  end
  
  -- Decodificar JWT
  local jwt, err = jwt_decoder:new(token)
  if err then
    kong.log.err("Error decoding JWT: ", err)
    return
  end
  
  -- Extraer claims
  local claims = jwt.claims
  if not claims or not claims.features then
    -- Si no hay features, usar valores por defecto
    kong.service.request.set_header("X-Features-Friends-Family", "false")
    kong.service.request.set_header("X-Features-Premium-Analytics", "false")
    return
  end
  
  -- Configurar headers basados en feature flags
  local features = claims.features
  kong.service.request.set_header("X-Features-Friends-Family", tostring(features.friends_family or false))
  kong.service.request.set_header("X-Features-Premium-Analytics", tostring(features.premium_analytics or false))
  kong.service.request.set_header("X-Tenant-ID", tostring(claims.tenant_id or ""))
  kong.service.request.set_header("X-User-ID", tostring(claims.user_id or ""))
  
  -- Logging para debugging
  kong.log.info("Features extracted - Friends Family: ", 
                features.friends_family, 
                ", Premium Analytics: ", 
                features.premium_analytics)
end

return FeatureFlagsHandler 