FROM gcc:14-bookworm

# starter.tar is a content-addressed snapshot produced by package-starter.sh.
# It deliberately excludes build products, caches, node_modules, and reference
# checkouts.  The task therefore has no network or language-runtime dependency.
COPY starter.tar /tmp/gen3ou-starter.tar
COPY starter.sha256 /tmp/starter.sha256
RUN sed 's|  starter.tar$|  /tmp/gen3ou-starter.tar|' /tmp/starter.sha256 \
      | sha256sum -c - \
    && mkdir -p /app \
    && tar -xf /tmp/gen3ou-starter.tar -C /app \
    && rm /tmp/gen3ou-starter.tar

WORKDIR /app/robots/envs/dev/pokemon_gen3
