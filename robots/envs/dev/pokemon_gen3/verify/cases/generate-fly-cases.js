#!/usr/bin/env node
'use strict';
const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const names = {owntempo:'Own Tempo', illuminate:'Illuminate', naturalcure:'Natural Cure', waterabsorb:'Water Absorb',
  fly:'Fly', bounce:'Bounce', dig:'Dig', dive:'Dive', strength:'Strength',
  softboiled:'Soft-Boiled', thunder:'Thunder', protect:'Protect', twister:'Twister',
  gust:'Gust', skyuppercut:'Sky Uppercut', earthquake:'Earthquake', surf:'Surf',
  sandstorm:'Sandstorm', hail:'Hail'};
const n = id => names[id] || id[0].toUpperCase()+id.slice(1);
const mon = (species,ability,moves,stats) => ({species,level:100,gender:'M',ability,
  item:'',moves,stats,status:null});
const smeargle = () => mon('smeargle','owntempo',['fly','splash'],[251,76,106,76,126,186]);
const blissey = moves => mon('blissey','naturalcure',moves,[651,56,56,186,306,146]);
const vaporeon = () => mon('vaporeon','waterabsorb',['splash'],[401,166,156,256,226,166]);
function team(file,pokemon) {
  fs.writeFileSync(path.join(out,file),pokemon.map(p =>
    `${n(p.species)} (M)\nAbility: ${n(p.ability)}\nLevel: 100\nHardy Nature\n${p.moves.map(x=>`- ${n(x)}`).join('\n')}\n`).join('\n'));
}
function make(id,p1,p2,choices,seed=[1,2,3,4]) {
  const a=`${id}-p1.txt`,b=`${id}-p2.txt`; team(a,p1); team(b,p2);
  const value={schema:'pokemon-native-differential-case-v1',id,
    provenance:{kind:'showdown-derived',source_file:'data/moves.ts; data/conditions.ts; sim/battle.ts; sim/battle-actions.ts',test_name:id,oracle_revision:revision},
    format:'gen3ou',seed,teams:[{source:a,normalized:p1},{source:b,normalized:p2}],
    source_choices:choices,choices,forced_outcomes:[],
    features:['choice.move','state.canonical','condition.volatile','hit.accuracy'],
    boundaries:['request','choice','queue','handlers','state','events','prng'],
    limits:{max_boundaries:choices.length+1,max_actions:choices.length*2}};
  fs.writeFileSync(path.join(out,`${id}.json`),`${JSON.stringify(value,null,2)}\n`);
}
make('fly-airborne-miss-release',[smeargle()],[blissey(['strength','softboiled'])],
  [['move 1','move 1'],['move 1','move 2']]);
make('fly-thunder-paralysis-abort',[smeargle()],[blissey(['thunder','softboiled'])],
  [['move 1','move 1'],['move 1','move 2']],[10,2,3,4]);
make('fly-release-protect',[smeargle()],[blissey(['softboiled','protect'])],
  [['move 1','move 1'],['move 1','move 2']]);
make('fly-release-switch',[smeargle()],[blissey(['softboiled']),vaporeon()],
  [['move 1','move 1'],['move 1','switch 2']]);

function hiddenInteraction(id, hiddenMove, attackingMove) {
  const attacker=mon('smeargle','owntempo',['splash',attackingMove],[251,76,106,76,126,186]);
  const charger=blissey([hiddenMove,'softboiled']);
  make(id,[attacker],[charger],[['move 1','move 1'],['move 2','move 1']]);
}
hiddenInteraction('fly-twister-double','fly','twister');
hiddenInteraction('bounce-gust-double','bounce','gust');
hiddenInteraction('bounce-sky-uppercut-bypass','bounce','skyuppercut');
hiddenInteraction('dig-earthquake-double','dig','earthquake');
hiddenInteraction('dive-surf-double','dive','surf');

function hiddenWeather(id, hiddenMove, weatherMove) {
  const setter=mon('smeargle','illuminate',[weatherMove,'splash'],[251,76,106,76,126,186]);
  const charger=blissey([hiddenMove,'softboiled']);
  make(id,[setter],[charger],[['move 1','move 1'],['move 2','move 1']]);
}
hiddenWeather('dig-sandstorm-immunity','dig','sandstorm');
hiddenWeather('dig-hail-immunity','dig','hail');
hiddenWeather('dive-sandstorm-immunity','dive','sandstorm');
hiddenWeather('dive-hail-immunity','dive','hail');
hiddenWeather('fly-sandstorm-not-immune','fly','sandstorm');
