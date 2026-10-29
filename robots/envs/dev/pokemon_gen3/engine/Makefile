CC ?= cc
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -pedantic -O2

.PHONY: all test clean

all: libpokemon_gen3.so

libpokemon_gen3.so: gen3_abi.c gen3_move_hit.c gen3_move_program.c gen3_move_preflight.c gen3_move_hit.h gen3_move_program.h gen3_move_preflight.h gen3_abi.h data_gen3.h
	$(CC) $(CFLAGS) -fPIC -shared gen3_abi.c gen3_move_hit.c gen3_move_program.c gen3_move_preflight.c -o $@

test_gen3_abi: test_gen3_abi.c gen3_abi.c gen3_abi.h data_gen3.h
	$(CC) $(CFLAGS) test_gen3_abi.c gen3_abi.c -o $@

test_ocean: test_ocean.c gen3_abi.c gen3_abi.h data_gen3.h ../ocean/pokemon_gen3.h
	$(CC) $(CFLAGS) -I../tests/puffer_stub test_ocean.c gen3_abi.c -o $@

test_scheduler: test_scheduler.c gen3_abi.c gen3_abi.h data_gen3.h
	$(CC) $(CFLAGS) test_scheduler.c -o $@

test_effect_runtime: test_effect_runtime.c gen3_abi.c gen3_abi.h data_gen3.h
	$(CC) $(CFLAGS) test_effect_runtime.c -o $@

test_move_hit: test_move_hit.c gen3_move_hit.c gen3_move_hit.h gen3_abi.h data_gen3.h
	$(CC) $(CFLAGS) test_move_hit.c gen3_move_hit.c -o $@

test_move_program: test_move_program.c gen3_move_program.c gen3_move_program.h data_gen3.h
	$(CC) $(CFLAGS) test_move_program.c gen3_move_program.c -o $@

test_move_preflight: test_move_preflight.c gen3_move_preflight.c gen3_move_preflight.h gen3_move_program.h gen3_abi.c gen3_abi.h data_gen3.h
	$(CC) $(CFLAGS) test_move_preflight.c gen3_move_preflight.c gen3_abi.c -o $@

test_verify_trace: test_verify_trace.c gen3_abi.c gen3_abi.h gen3_verify_trace.h data_gen3.h
	$(CC) $(CFLAGS) -DGEN3_VERIFY_TRACE test_verify_trace.c -o $@

test: test_gen3_abi test_ocean test_scheduler test_effect_runtime test_move_hit test_move_program test_move_preflight test_verify_trace
	./test_gen3_abi
	./test_ocean
	./test_scheduler
	./test_effect_runtime
	./test_move_hit
	./test_move_program
	./test_move_preflight
	./test_verify_trace

clean:
	rm -f libpokemon_gen3.so test_gen3_abi test_ocean test_scheduler \
		test_effect_runtime check_puffer5
	rm -f test_move_hit test_move_program test_move_preflight test_verify_trace

# Compile the adapter against a real pinned PufferLib source checkout:
# make check-puffer5 PUFFERLIB_SRC=/path/to/PufferLib/src
.PHONY: check-puffer5
check-puffer5:
	test -n "$(PUFFERLIB_SRC)"
	$(CC) $(CFLAGS) -Wno-unused-parameter -Wno-unused-function \
		-I$(PUFFERLIB_SRC) -I../tests/puffer_stub \
		check_puffer5.c gen3_abi.c -o check_puffer5
	./check_puffer5
