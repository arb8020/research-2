#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const outputDir = path.resolve(__dirname, 'derived');
const persian = moves => ({species: 'persian', level: 100, gender: 'M',
  ability: 'limber', item: '', moves, stats: [271,176,156,166,166,266], status: null});
const machop = {species: 'machop', level: 100, gender: 'M', ability: 'guts', item: '',
  moves: ['megapunch','splash'], stats: [281,196,136,106,106,106], status: null};
const magikarp = {species: 'magikarp', level: 100, gender: 'M', ability: 'swiftswim', item: '',
  moves: ['splash'], stats: [181,56,146,66,76,196], status: null};
const configs = [
  {kind:'flash', edge:'below', seed:179, draws:[55,62], source:'persian-flash-splash-p1.txt',
    user:persian(['flash','splash']), foe:machop, foeSource:'machop-mega-punch-splash-p2.txt', choices:[['move 1','move 2'],['move 2','move 1']]},
  {kind:'flash', edge:'at', seed:275, draws:[36,63], source:'persian-flash-splash-p1.txt',
    user:persian(['flash','splash']), foe:machop, foeSource:'machop-mega-punch-splash-p2.txt', choices:[['move 1','move 2'],['move 2','move 1']]},
  {kind:'sand-attack', edge:'below', seed:179, draws:[55,62], source:'persian-sand-attack-splash-p1.txt',
    user:persian(['sandattack','splash']), foe:machop, foeSource:'machop-mega-punch-splash-p2.txt', choices:[['move 1','move 2'],['move 2','move 1']]},
  {kind:'sand-attack', edge:'at', seed:275, draws:[36,63], source:'persian-sand-attack-splash-p1.txt',
    user:persian(['sandattack','splash']), foe:machop, foeSource:'machop-mega-punch-splash-p2.txt', choices:[['move 1','move 2'],['move 2','move 1']]},
  {kind:'sweet-scent', edge:'below', seed:262, draws:[57,92], source:'persian-sweet-scent-flash-p1.txt',
    user:persian(['sweetscent','flash']), foe:magikarp, foeSource:'magikarp-splash-p2.txt', choices:[['move 1','move 1'],['move 2','move 1']]},
  {kind:'sweet-scent', edge:'at', seed:3, draws:[5,93], source:'persian-sweet-scent-flash-p1.txt',
    user:persian(['sweetscent','flash']), foe:magikarp, foeSource:'magikarp-splash-p2.txt', choices:[['move 1','move 1'],['move 2','move 1']]},
];
for (const config of configs) {
  const id = `boost-accuracy-${config.kind}-${config.edge}`;
  const value = {
    schema:'pokemon-native-differential-case-v1', id,
    provenance:{kind:'showdown-derived',source_file:'sim/battle-actions.ts',
      test_name:`${config.kind} post-boost accuracy ${config.edge} threshold`,oracle_revision:revision},
    format:'gen3ou',seed:[17,31,47,config.seed],
    teams:[{source:config.source,normalized:[config.user]}, {source:config.foeSource,normalized:[config.foe]}],
    source_choices:config.choices,choices:config.choices,
    forced_outcomes:config.draws.map((result,index)=>({label:'move.accuracy',occurrence:index+1,range:100,result})),
    features:['effect.boost','hit.accuracy','prng.labeled','state.canonical'],
    boundaries:['request','choice','queue','state','events','prng'],limits:{max_boundaries:3,max_actions:4},
  };
  fs.writeFileSync(path.join(outputDir, `${id}.json`), `${JSON.stringify(value,null,2)}\n`);
}
