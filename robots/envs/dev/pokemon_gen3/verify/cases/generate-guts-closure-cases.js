#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const out = path.join(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const foe = {species:'magikarp',level:100,gender:'M',ability:'swiftswim',item:'',moves:['splash'],stats:[181,56,146,66,76,196],status:null};

function machop(status, moves, item = '') {
  const set = {species:'machop',level:100,gender:'M',ability:'guts',item,moves,stats:[281,196,136,106,106,106],status};
  if (status === 'slp') set.status_state = {kind:'sleep',time:3,skipped_time:0};
  return set;
}
function text(id, set) {
  const file = `guts-closure-${id}.txt`;
  const lines = [`Machop (M)${set.item ? ` @ ${set.item === 'blackbelt' ? 'Black Belt' : set.item}` : ''}`,
    'Ability: Guts','Level: 100','EVs: 1 HP','Hardy Nature',...set.moves.map(move => `- ${move === 'fireblast' ? 'Fire Blast' : move[0].toUpperCase()+move.slice(1)}`),''];
  fs.writeFileSync(path.join(out,file),lines.join('\n'));
  return {source:file,normalized:[set]};
}
const foeFile = 'guts-closure-foe.txt';
fs.writeFileSync(path.join(out,foeFile),'Magikarp (M)\nAbility: Swift Swim\nLevel: 100\nEVs: 1 HP\nHardy Nature\n- Splash\n');
function emit(id, set, seed, test, features) {
  const value = {schema:'pokemon-native-differential-case-v1',id:`guts-closure-${id}`,
    provenance:{kind:'showdown-derived',source_file:'data/abilities.ts; data/mods/gen3/scripts.ts',test_name:test,oracle_revision:revision},
    format:'gen3ou',seed,teams:[text(id,set),{source:foeFile,normalized:[foe]}],
    source_choices:[['move 1','move 1']],choices:[['move 1','move 1']],forced_outcomes:[],
    features:['choice.move','damage.gen3','handler.guts','state.canonical',...features],
    boundaries:['request','choice','queue','handlers','state','events','prng','terminal'],limits:{max_boundaries:2,max_actions:2}};
  fs.writeFileSync(path.join(out,`${value.id}.json`),`${JSON.stringify(value,null,2)}\n`);
}
emit('paralysis-strength',machop('par',['strength']),[17,31,73,107],'Guts modifies Attack when paralysis permits movement',['handler.modify-attack','status.paralysis','prng.status-action']);
emit('sleep-snore',machop('slp',['snore']),[823,17,43,3],'Guts modifies physical Snore while sleep remains',['handler.modify-attack','status.sleep']);
emit('freeze-immobilized',machop('frz',['strength']),[13,29,71,101],'Freeze immobilization prevents reaching ModifyAtk',['status.freeze','prng.status-action']);
emit('special-fire-blast',machop('psn',['fireblast']),[1,2,3,4],'Guts does not modify special-category damage',['handler.modify-special-attack','status.poison']);
emit('poison-black-belt',machop('psn',['brickbreak'],'blackbelt'),[1,2,3,4],'Guts precedes Black Belt for poisoned physical damage',['handler.modify-attack','handler.black-belt','status.poison']);
