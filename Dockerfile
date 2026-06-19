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

# S1 (ADR-003a) — KONG_TRUSTED_IPS se deja DELIBERADAMENTE sin setear (vacío = default).
# Con trusted_ips vacío Kong NO honra X-Forwarded-For y kong.client.get_forwarded_ip()
# devuelve la IP de conexión real → el limit_by:ip del anti-fuerza-bruta (K2) NO es
# evadible por XFF spoofing. NO setear este valor: ponerlo (p.ej. a la red docker)
# habilitaría honrar XFF y volvería el anti-bruteforce trivialmente evadible.
# ASSUMPTION: no hay reverse-proxy delante de Kong (los clientes pegan directo a :8000).
# Si en el futuro se antepone un proxy/LB, RE-EVALUAR esto junto con K2.

EXPOSE 8000 8443 8001 8444

ENTRYPOINT ["/opt/kong/entrypoint.sh"]
