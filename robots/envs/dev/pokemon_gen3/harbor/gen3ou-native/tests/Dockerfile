FROM node:22.14.0-bookworm@sha256:e5ddf893cc6aeab0e5126e4edae35aa43893e2836d1d246140167ccc2616f5d7

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      build-essential \
      git \
      python3 \
      python3-jsonschema \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
RUN git init pokemon-showdown \
    && cd pokemon-showdown \
    && git remote add origin https://github.com/smogon/pokemon-showdown.git \
    && git fetch --depth=1 origin 6e71625b9e6cffeda268b548ae7f43a7643fc3f0 \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "6e71625b9e6cffeda268b548ae7f43a7643fc3f0" \
    && test "$(sha256sum package.json | awk '{print $1}')" = \
      "7124aad8913672f0a4264e74e2036f33fc51dad2c12e3f520e7e668cd7ed5120" \
    && test "$(sha256sum package-lock.json | awk '{print $1}')" = \
      "ed45c185e5287cd10aa9ddb2603f3e03f7628f6a3639d11502e52ecc516a49ef" \
    && printf '%s\n' "6e71625b9e6cffeda268b548ae7f43a7643fc3f0" > .harbor-oracle-revision

COPY oracle-observer.patch /opt/oracle-observer.patch
# esbuild's platform binary is an optional dependency. Keep lockfile-resolved
# optionals; omitting them makes arm64 verifier builds impossible.
RUN test "$(sha256sum /opt/oracle-observer.patch | awk '{print $1}')" = \
      "d24bb9b50f52983858db21ab886d2e66c4db231394dec8c014a64bde4349e058" \
    && cd /opt/pokemon-showdown \
    && git apply --check /opt/oracle-observer.patch \
    && git apply /opt/oracle-observer.patch \
    && git apply --reverse --check /opt/oracle-observer.patch \
    && npm ci --ignore-scripts \
    && node build \
    && rm -rf .git /root/.npm

COPY oracle_smoke.js /opt/oracle_smoke.js
COPY oracle-smoke.sha256 /opt/oracle-smoke.sha256
RUN test "$(sha256sum /opt/oracle_smoke.js | awk '{print $1}')" = \
      "b8664ae406a9471f6912b3076b74897e52cff12ea6e996bb055ac03b0cde1bf5" \
    && test "$(PS_GEN3_VERIFY_TRACE=1 node /opt/oracle_smoke.js | sha256sum | awk '{print $1}')" = \
      "$(cat /opt/oracle-smoke.sha256)"

# Separate verifier mode does not inject the task's tests directory.  Bake the
# verifier entry point and its public contract into the image explicitly.
COPY test.sh validate_manifest.py validate_case.py native_boundary_driver.c \
  native_boundary_smoke.sh native-boundary-smoke.sha256 \
  compare_boundaries.py oracle_boundary_driver.js shared_case.js \
  normalize_case.js NATIVE_BOUNDARY_DRIVER.md /tests/
COPY contracts /tests/contracts
COPY cases /tests/cases
RUN chmod 0555 /tests/test.sh /tests/validate_manifest.py /tests/validate_case.py \
      /tests/native_boundary_smoke.sh /tests/compare_boundaries.py \
    && test "$(sha256sum /tests/contracts/case.schema.json | awk '{print $1}')" = \
      "d124f8e57c706105c1246c90bf2bc1eec797617b339c2e97d3b7343b7723fcf6" \
    && test "$(sha256sum /tests/contracts/feature-map.schema.json | awk '{print $1}')" = \
      "93e60559089ddf750dd5b6c3e3f9de83e79d6f4530e4040b2ac1e2a075aefb85" \
    && test "$(sha256sum /tests/contracts/supported-features.json | awk '{print $1}')" = \
      "cb8572b17af016fe0a200028c7dc98070202be1f6ffced7673205e6cb119fe94" \
    && test "$(sha256sum /tests/cases/seed42-battle04.case | awk '{print $1}')" = \
      "0e2493737497b7575a8dcca7ed9949675fb133f43a3c5a1f0287aa09f81ceed0" \
    && mkdir -p /opt/gen3-cases \
    && python3 /tests/validate_case.py /tests/contracts/case.schema.json \
      /tests/cases/seed42-battle04.case /tests/contracts/supported-features.json \
    && POKEMON_SHOWDOWN_DIR=/opt/pokemon-showdown node /tests/normalize_case.js \
      /tests/cases/seed42-battle04.case \
      /opt/gen3-cases/seed42-battle04.init \
    && test "$(wc -c </opt/gen3-cases/seed42-battle04.init)" = 608

# Harbor re-materializes the submitted artifact at its original /app path
# before invoking /tests/test.sh. Runtime network is disabled by task.toml; all
# network use above occurs while building this image.
WORKDIR /app
