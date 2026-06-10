FROM kong:3.4.0

USER root
COPY kong.yml.template /opt/kong/kong.yml.template
COPY entrypoint.sh /opt/kong/entrypoint.sh
RUN chmod +x /opt/kong/entrypoint.sh
USER kong

ENV KONG_DATABASE=off
ENV KONG_PROXY_ACCESS_LOG=/dev/stdout
ENV KONG_ADMIN_ACCESS_LOG=/dev/stdout
ENV KONG_PROXY_ERROR_LOG=/dev/stderr
ENV KONG_ADMIN_ERROR_LOG=/dev/stderr
ENV KONG_ADMIN_LISTEN=0.0.0.0:8001
ENV KONG_ADMIN_GUI_URL=http://localhost:8002

EXPOSE 8000 8443 8001 8444

ENTRYPOINT ["/opt/kong/entrypoint.sh"]
