CC ?= cc
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -pedantic -O3

ROOT := ../..
NATIVE := $(ROOT)/native
SOURCES := $(NATIVE)/pokemon.c $(NATIVE)/gen3_rules.c \
	$(NATIVE)/gen3_slice_data.c $(NATIVE)/singles2.c
TARGET := benchmark

.PHONY: all run self-check gate container-gate reference-gate clean

CONTAINER_IMAGE := gcc@sha256:5e927c284bf55a7dc796262e311a0703344f62f41f5621eb56843111b1d37e15

all: $(TARGET)

$(TARGET): benchmark.c $(SOURCES) $(NATIVE)/pokemon.h \
		$(NATIVE)/gen3_rules.h $(NATIVE)/gen3_slice_data.h \
		$(NATIVE)/singles2.h $(ROOT)/ocean/pokemon_slice.h
	$(CC) $(CFLAGS) -I$(ROOT)/tests/puffer_stub benchmark.c \
		$(SOURCES) -o $@

run: $(TARGET)
	./$(TARGET)

self-check: $(TARGET)
	@first=`./$(TARGET) | sed -n 's/.*"deterministic_digest": "\([0-9a-f]*\)".*/\1/p'`; \
	second=`./$(TARGET) | sed -n 's/.*"deterministic_digest": "\([0-9a-f]*\)".*/\1/p'`; \
	test -n "$$first"; test "$$first" = "$$second"; \
	echo "deterministic digest $$first"

gate: $(TARGET)
	@result=$$(mktemp "$${TMPDIR:-/tmp}/pokemon-performance.XXXXXX"); \
	trap 'rm -f "$$result"' EXIT HUP INT TERM; \
	./$(TARGET) > "$$result"; \
	node check.js candidate "$$result" orbstack-gcc14-calibration.json

container-gate:
	@result=$$(mktemp "$${TMPDIR:-/tmp}/pokemon-performance-container.XXXXXX"); \
	trap 'rm -f "$$result"' EXIT HUP INT TERM; \
	docker run --rm -v "$(abspath $(ROOT)):/work" -w /work/verify/performance \
		$(CONTAINER_IMAGE) sh -c 'make clean benchmark >/dev/null && ./benchmark' > "$$result"; \
	node check.js candidate "$$result" orbstack-gcc14-calibration.json

reference-gate: $(TARGET)
	@result=$$(mktemp "$${TMPDIR:-/tmp}/pokemon-performance.XXXXXX"); \
	trap 'rm -f "$$result"' EXIT HUP INT TERM; \
	./$(TARGET) > "$$result"; \
	node check.js reference "$$result" reference-contract.json

clean:
	rm -f $(TARGET)
