CC ?= cc
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -pedantic -O2
POKEMON_SHOWDOWN_DIR ?= /private/tmp/pokemon-lockon-clean

.PHONY: test random-test clean

test: native
	POKEMON_SHOWDOWN_DIR="$(POKEMON_SHOWDOWN_DIR)" node oracle.js > oracle.jsonl.tmp
	./native > native.jsonl.tmp
	node compare.js oracle.jsonl.tmp native.jsonl.tmp
	./native > native.replay.jsonl.tmp
	cmp native.jsonl.tmp native.replay.jsonl.tmp
	rm -f oracle.jsonl.tmp native.jsonl.tmp native.replay.jsonl.tmp

random-test:
	node random/test.js
	node random/run.js "$(POKEMON_SHOWDOWN_DIR)"

cases.generated.h: cases.json compile-cases.js
	node compile-cases.js > $@.tmp
	mv $@.tmp $@

NATIVE_SOURCES = ../../native/pokemon.c ../../native/gen3_rules.c ../../native/gen3_slice_data.c ../../native/singles2.c
KERNEL_INCLUDES = $(wildcard ../../native/pokemon_kernel/*.inc)

native: native.c cases.generated.h ../../native/pokemon_admission.c ../../native/pokemon_admission.h ../../native/pokemon_acquisition.c ../../native/pokemon_acquisition.h ../../native/gen3_admission_data.c ../../native/gen3_admission_data.h $(NATIVE_SOURCES) $(KERNEL_INCLUDES)
	$(CC) $(CFLAGS) native.c ../../native/pokemon_admission.c ../../native/pokemon_acquisition.c ../../native/gen3_admission_data.c $(NATIVE_SOURCES) -o $@

clean:
	rm -f native cases.generated.h cases.generated.h.tmp *.jsonl.tmp
