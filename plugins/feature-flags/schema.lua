local typedefs = require "kong.db.schema.typedefs"

return {
  name = "feature-flags",
  fields = {
    { protocols = typedefs.protocols_http },
    { config = {
        type = "record",
        fields = {
          { enabled = { type = "boolean", default = true } },
          { default_friends_family = { type = "boolean", default = false } },
          { default_premium_analytics = { type = "boolean", default = false } }
        }
      }
    }
  }
} 