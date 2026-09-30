CC ?= cc
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -pedantic -O2

SOURCES = pokemon.c gen3_rules.c gen3_slice_data.c singles2.c
KERNEL_INCLUDES = $(wildcard pokemon_kernel/*.inc pokemon_kernel/*.h)

.PHONY: all test test-sanitize test-long clean regenerate-data regenerate-admission

all: test_pokemon test_random_play test_ocean_slice test_admission test_prng

test_pokemon: test_pokemon.c test_plugin.c test_plugin.h $(SOURCES) $(KERNEL_INCLUDES) pokemon.h gen3_rules.h gen3_slice_data.h singles2.h
	$(CC) $(CFLAGS) test_pokemon.c test_plugin.c $(SOURCES) -o $@

test_random_play: test_random_play.c $(SOURCES) $(KERNEL_INCLUDES) pokemon.h gen3_rules.h gen3_slice_data.h singles2.h
	$(CC) $(CFLAGS) test_random_play.c $(SOURCES) -o $@

test_ocean_slice: test_ocean_slice.c $(SOURCES) $(KERNEL_INCLUDES) pokemon.h gen3_rules.h gen3_slice_data.h singles2.h ../ocean/pokemon_slice.h
	$(CC) $(CFLAGS) -I../tests/puffer_stub test_ocean_slice.c $(SOURCES) -o $@

test_admission: test_admission.c pokemon_admission.c pokemon_admission.h pokemon_acquisition.c pokemon_acquisition.h gen3_admission_data.c gen3_admission_data.h $(SOURCES) $(KERNEL_INCLUDES)
	$(CC) $(CFLAGS) test_admission.c pokemon_admission.c pokemon_acquisition.c gen3_admission_data.c $(SOURCES) -o $@

test_prng: test_prng.c pokemon_kernel/prng.h
	$(CC) $(CFLAGS) test_prng.c -o $@

test: test_pokemon test_random_play test_ocean_slice test_admission test_prng
	./test_pokemon
	./test_random_play
	./test_ocean_slice
	./test_admission
	./test_prng

test-sanitize:
	$(MAKE) clean
	ulimit -s 65520; $(MAKE) test CFLAGS="-std=c11 -Wall -Wextra -Werror -pedantic -O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined"

test-long:
	$(CC) $(CFLAGS) -DPOKEMON_RANDOM_BATTLE_COUNT=10000u \
		test_random_play.c $(SOURCES) -o test_random_play_long
	./test_random_play_long
	rm -f test_random_play_long

regenerate-data:
	node ../tools/generate_slice_data.js "$${POKEMON_SHOWDOWN_DIR}" header > gen3_slice_data.h.tmp
	node ../tools/generate_slice_data.js "$${POKEMON_SHOWDOWN_DIR}" source > gen3_slice_data.c.tmp
	node ../tools/generate_slice_data.js "$${POKEMON_SHOWDOWN_DIR}" id-map > ../verify/cases/native-id-map.json.tmp
	mv gen3_slice_data.h.tmp gen3_slice_data.h
	mv gen3_slice_data.c.tmp gen3_slice_data.c
	mv ../verify/cases/native-id-map.json.tmp ../verify/cases/native-id-map.json

regenerate-admission:
	node ../tools/generate_gen3_admission.js "$${POKEMON_SHOWDOWN_DIR}" header > gen3_admission_data.h
	node ../tools/generate_gen3_admission.js "$${POKEMON_SHOWDOWN_DIR}" source > gen3_admission_data.c

clean:
	rm -f test_pokemon test_random_play test_random_play_long test_ocean_slice test_admission test_prng *.o
	rm -rf test_pokemon.dSYM test_random_play.dSYM test_ocean_slice.dSYM test_admission.dSYM test_prng.dSYM
