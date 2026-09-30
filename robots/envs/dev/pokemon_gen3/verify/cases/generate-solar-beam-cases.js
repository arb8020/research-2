#!/usr/bin/env node
'use strict';
const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const names = {owntempo:'Own Tempo', naturalcure:'Natural Cure', cloudnine:'Cloud Nine',
  solarbeam:'Solar Beam', raindance:'Rain Dance', sunnyday:'Sunny Day',
  thunderwave:'Thunder Wave'};
const n = id => names[id] || id[0].toUpperCase()+id.slice(1);
const mon = (species,ability,moves,stats) => ({species,level:100,gender:'M',ability,
  item:'',moves,stats,status:null});
const smeargle = moves => mon('smeargle','owntempo',moves,[251,76,106,76,126,186]);
const blissey = (moves=['splash'],ability='naturalcure') =>
  mon('blissey',ability,moves,[651,56,56,186,306,146]);
function team(file,pokemon) {
  fs.writeFileSync(path.join(out,file),pokemon.map(p =>
    `${n(p.species)} (M)\nAbility: ${n(p.ability)}\nLevel: 100\nHardy Nature\n${p.moves.map(x=>`- ${n(x)}`).join('\n')}\n`).join('\n'));
}
function make(id,p1,p2,choices,seed=[1,2,3,4]) {
  const a=`${id}-p1.txt`,b=`${id}-p2.txt`; team(a,p1); team(b,p2);
  const value={schema:'pokemon-native-differential-case-v1',id,
    provenance:{kind:'showdown-derived',source_file:'data/moves.ts; data/conditions.ts; sim/battle-actions.ts',test_name:id,oracle_revision:revision},
    format:'gen3ou',seed,teams:[{source:a,normalized:p1},{source:b,normalized:p2}],
    source_choices:choices,choices,forced_outcomes:[],
    features:['choice.move','state.canonical','condition.weather'],
    boundaries:['request','choice','queue','handlers','state','events','prng'],
    limits:{max_boundaries:choices.length+1,max_actions:choices.length*2}};
  fs.writeFileSync(path.join(out,`${id}.json`),`${JSON.stringify(value,null,2)}\n`);
}
make('solar-beam-clear-charge-release',[smeargle(['solarbeam','splash'])],[blissey()],
  [['move 1','move 1'],['move 1','move 1']]);
make('solar-beam-sun-immediate',[smeargle(['splash','solarbeam'])],
  [blissey(['sunnyday','splash'])],[['move 1','move 1'],['move 2','move 2']]);
for (const [label,setter] of [['rain','raindance'],['sand','sandstorm'],['hail','hail']])
  make(`solar-beam-${label}-half`,[smeargle(['solarbeam'])],[blissey([setter,'splash'])],
    [['move 1','move 1'],['move 1','move 2']]);
make('solar-beam-clear-to-rain',[smeargle(['solarbeam'])],
  [blissey(['raindance','splash'])],[['move 1','move 1'],['move 1','move 2']]);
make('solar-beam-cloud-nine-sun',[smeargle(['splash','solarbeam'])],
  [blissey(['sunnyday','splash'],'cloudnine')],[['move 1','move 1'],['move 2','move 2']]);
make('solar-beam-release-protect',[smeargle(['solarbeam'])],
  [mon('persian','limber',['splash','protect'],[271,176,156,166,166,266])],
  [['move 1','move 1'],['move 1','move 2']]);
make('solar-beam-release-paralysis',[smeargle(['solarbeam'])],
  [mon('persian','limber',['splash','thunderwave'],[271,176,156,166,166,266])],
  [['move 1','move 1'],['move 1','move 2']],[2,2,3,4]);
