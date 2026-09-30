'use strict';

// This is verifier code. It asks the pinned Showdown revision to import the
// team exports and calculate every derived Gen 3 set value, then writes the
// exact little-endian Gen3BattleInit byte layout consumed by the native ABI.
const fs = require('fs');
const {loadCase} = require('./shared_case');

const showdownDir = process.env.POKEMON_SHOWDOWN_DIR || '/opt/pokemon-showdown';
const common = require(`${showdownDir}/test/common`).gen(3);
const {Teams} = require(showdownDir);
const casePath = process.argv[2];
const outputPath = process.argv[3];
if (!casePath || !outputPath) throw new Error('usage: normalize_case.js CASE OUTPUT');

const fixture = loadCase(casePath);
const teams = fixture.teams.map(teamPath => {
	const imported = Teams.import(fs.readFileSync(teamPath, 'utf8'));
	if (!imported || imported.length !== 6) throw new Error(`invalid six-Pokemon team: ${teamPath}`);
	return imported;
});
const battle = common.createBattle({formatid: fixture.format, seed: fixture.seed}, teams);

const ABI_VERSION = 12;
const SET_SIZE = 48;
const TEAM_SIZE = 296;
const INIT_SIZE = 608;
const bytes = Buffer.alloc(INIT_SIZE);
bytes.writeUInt32LE(ABI_VERSION, 0);
bytes.writeUInt32LE(INIT_SIZE, 4);
for (let side = 0; side < 2; side++) {
	const teamOffset = 8 + side * TEAM_SIZE;
	bytes.writeUInt32LE(ABI_VERSION, teamOffset);
	bytes.writeUInt32LE(TEAM_SIZE, teamOffset + 4);
	for (let slot = 0; slot < 6; slot++) {
		const pokemon = battle.sides[side].pokemon[slot];
		const offset = teamOffset + 8 + slot * SET_SIZE;
		bytes.writeUInt32LE(ABI_VERSION, offset);
		bytes.writeUInt32LE(SET_SIZE, offset + 4);
		bytes.writeUInt16LE(pokemon.species.num, offset + 8);
		bytes.writeUInt16LE(pokemon.getItem().num, offset + 10);
		bytes.writeUInt16LE(pokemon.getAbility().num, offset + 12);
		for (let move = 0; move < 4; move++) {
			const moveSlot = pokemon.moveSlots[move];
			bytes.writeUInt16LE(battle.dex.moves.get(moveSlot.id).num, offset + 14 + move * 2);
			bytes.writeUInt16LE(moveSlot.maxpp, offset + 34 + move * 2);
		}
		const stats = [pokemon.maxhp, pokemon.storedStats.atk, pokemon.storedStats.def,
			pokemon.storedStats.spa, pokemon.storedStats.spd, pokemon.storedStats.spe];
		stats.forEach((stat, index) => bytes.writeUInt16LE(stat, offset + 22 + index * 2));
		bytes.writeUInt8(pokemon.level, offset + 42);
		bytes.writeUInt8(pokemon.gender === 'M' ? 1 : pokemon.gender === 'F' ? 2 : 0, offset + 43);
		bytes.writeUInt8(pokemon.happiness, offset + 44);
		bytes.writeUInt8(pokemon.set.shiny ? 1 : 0, offset + 45);
	}
}
fixture.seed.forEach((word, index) => bytes.writeUInt16LE(word, 600 + index * 2));
fs.writeFileSync(outputPath, bytes);
