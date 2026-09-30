#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const out = path.resolve(__dirname, 'derived');

const sets = {
  compound: {species:'smeargle', level:100, gender:'M', ability:'compoundeyes', item:'', moves:['supersonic','raindance','thunder','splash'], stats:[251,76,106,76,126,186], status:null},
  huge: {species:'smeargle', level:100, gender:'M', ability:'hugepower', item:'', moves:['strength'], stats:[251,76,106,76,126,186], status:null},
  hustle: {species:'smeargle', level:100, gender:'M', ability:'hustle', item:'silkscarf', moves:['strength','toxic','thunder'], stats:[251,76,106,76,126,186], status:null},
  pure: {species:'smeargle', level:100, gender:'M', ability:'purepower', item:'', moves:['strength'], stats:[251,76,106,76,126,186], status:null},
  gutspsn: {species:'machop', level:100, gender:'M', ability:'guts', item:'', moves:['strength'], stats:[281,196,136,106,106,106], status:'psn'},
  gutstox: {species:'machop', level:100, gender:'M', ability:'guts', item:'', moves:['strength'], stats:[281,196,136,106,106,106], status:'tox'},
  marowak: {species:'marowak', level:100, gender:'M', ability:'rockhead', item:'thickclub', moves:['strength'], stats:[261,196,256,136,196,126], status:null},
  cubone: {species:'cubone', level:100, gender:'M', ability:'rockhead', item:'thickclub', moves:['strength'], stats:[241,136,226,116,136,106], status:null},
  foe: {species:'blissey', level:100, gender:'F', ability:'naturalcure', item:'', moves:['sandattack','splash'], stats:[651,56,56,186,306,146], status:null},
};

function display(id) { return id.replace(/(^|[^a-z])([a-z])/g, (_,a,b)=>a+b.toUpperCase()); }
function writeSet(name, set) {
  const file = `scalar-${name}.txt`;
  const lines = [`${display(set.species)} (${set.gender})`, `Ability: ${display(set.ability)}`];
  if (set.item) lines[0] += ` @ ${display(set.item)}`;
  lines.push(`Level: ${set.level}`, 'Hardy Nature', ...set.moves.map(m => `- ${display(m)}`), '');
  fs.writeFileSync(path.join(out, file), lines.join('\n'));
  return {source:file, normalized:[set]};
}
const team = Object.fromEntries(Object.entries(sets).map(([id,set])=>[id,writeSet(id,set)]));
function emit(id, left, choices, test) {
  const value = {
    schema:'pokemon-native-differential-case-v1', id:`scalar-${id}`,
    provenance:{kind:'showdown-derived', source_file:'data/abilities.ts; data/mods/gen3/abilities.ts; data/mods/gen4/abilities.ts; data/mods/gen4/items.ts', test_name:test, oracle_revision:revision},
    format:'gen3ou', seed:[1,2,3,4], teams:[team[left],team.foe],
    source_choices:choices, choices, forced_outcomes:[],
    features:['damage.gen3','handler.modify-attack','hit.accuracy','prng.labeled','state.canonical'],
    boundaries:['request','choice','queue','handlers','state','events','prng','terminal'],
    limits:{max_boundaries:choices.length+1,max_actions:choices.length*2},
  };
  fs.writeFileSync(path.join(out, `${value.id}.json`), `${JSON.stringify(value,null,2)}\n`);
}
emit('compound-integral','compound',[['move 1','move 2']], 'Compound Eyes integral accuracy relay');
emit('compound-fractional','compound',[['move 4','move 1'],['move 1','move 2']], 'Compound Eyes preserves fractional staged accuracy relay');
emit('compound-always-hit','compound',[['move 2','move 2'],['move 3','move 2']], 'Compound Eyes observes boolean rain Thunder without a draw');
emit('huge-power','huge',[['move 1','move 2']], 'Huge Power chained Attack relay');
emit('pure-power','pure',[['move 1','move 2']], 'Pure Power chained Attack relay');
emit('hustle','hustle',[['move 1','move 2'],['move 2','move 2'],['move 3','move 2']], 'Hustle direct Attack rounding and physical-type accuracy predicate');
emit('guts-poison','gutspsn',[['move 1','move 2']], 'Guts any-status predicate with poison');
emit('thick-club-marowak','marowak',[['move 1','move 2']], 'Thick Club Marowak species predicate');
emit('thick-club-cubone','cubone',[['move 1','move 2']], 'Thick Club Cubone species predicate');
