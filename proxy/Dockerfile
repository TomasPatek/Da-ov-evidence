# Caddy with a DNS provider plugin, needed for Let's Encrypt DNS validation
# of a domain that is only reachable on the local network.
ARG CADDY_VERSION=2.8.4
FROM caddy:${CADDY_VERSION}-builder AS builder
ARG DNS_PROVIDER=cloudflare
RUN xcaddy build --with github.com/caddy-dns/${DNS_PROVIDER}

FROM caddy:${CADDY_VERSION}
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
