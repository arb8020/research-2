#!/usr/bin/env node
'use strict';
const fs = require('fs');
const path = require('path');
const out = path.resolve(__dirname, 'derived');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const names = {owntempo: 'Own Tempo', naturalcure: 'Natural Cure', cloudnine: 'Cloud Nine',
  clearbody: 'Clear Body', raindance: 'Rain Dance', sunnyday: 'Sunny Day'};
const mon = (species, ability, moves, stats) => ({species, level: 100, gender: 'M',
  ability, item: '', moves, stats, status: null});
const smeargle = moves => mon('smeargle', 'owntempo', moves, [251,76,106,76,126,186]);
const blissey = (moves=['splash'], ability='naturalcure') =>
  mon('blissey', ability, moves, [651,56,56,186,306,146]);
function n(id) { return names[id] || id[0].toUpperCase()+id.slice(1); }
function team(file,p) { fs.writeFileSync(path.join(out,file),
  `${n(p.species)} (M)\nAbility: ${n(p.ability)}\nLevel: 100\nHardy Nature\n${p.moves.map(x=>`- ${n(x)}`).join('\n')}\n`); }
function make(id,p1,p2,choices,seed=[1,2,3,4],test=id) {
  const a=`${id}-p1.txt`,b=`${id}-p2.txt`; team(a,p1);team(b,p2);
  const x={schema:'pokemon-native-differential-case-v1',id,
    provenance:{kind:'showdown-derived',source_file:'data/moves.ts; data/mods/gen3/scripts.ts; sim/battle-actions.ts',test_name:test,oracle_revision:revision},
    format:'gen3ou',seed,teams:[{source:a,normalized:[p1]},{source:b,normalized:[p2]}],
    source_choices:choices,choices,forced_outcomes:[],
    features:['choice.move','state.canonical','condition.weather'],
    boundaries:['request','choice','queue','handlers','state','events','prng'],
    limits:{max_boundaries:choices.length+1,max_actions:choices.length*2}};
  fs.writeFileSync(path.join(out,`${id}.json`),`${JSON.stringify(x,null,2)}\n`);
}
make('thunder-clear-hit-secondary-success',smeargle(['thunder']),blissey(),
  [['move 1','move 1']],[2,2,3,4]);
make('thunder-clear-miss',smeargle(['thunder']),blissey(),[['move 1','move 1']]);
make('thunder-secondary-failure',smeargle(['thunder']),blissey(),
  [['move 1','move 1']],[3,2,3,4]);
for(const [label,setter] of [['rain','raindance'],['sun','sunnyday'],['sand','sandstorm'],['hail','hail']])
  make(`thunder-${label}`,smeargle(['splash','thunder']),blissey([setter,'splash']),[['move 1','move 1'],['move 2','move 2']]);
make('thunder-cloud-nine',smeargle(['splash','thunder']),
  mon('golduck','cloudnine',['raindance','splash'],[301,200,192,226,196,206]),[['move 1','move 1'],['move 2','move 2']]);
make('thunder-replacement-expiry',smeargle(['splash','thunder']),blissey(['raindance','sunnyday','splash']),
  [['move 1','move 1'],['move 1','move 2'],['move 2','move 3'],['move 1','move 3'],['move 1','move 3'],['move 1','move 3'],['move 1','move 3'],['move 2','move 3']]);
make('thunder-protect',smeargle(['splash','thunder']),
  mon('persian','limber',['raindance','protect'],[271,176,156,166,166,266]),[['move 1','move 1'],['move 2','move 2']]);
make('thunder-substitute',smeargle(['splash','thunder']),
  mon('persian','limber',['raindance','substitute'],[271,176,156,166,166,266]),[['move 1','move 1'],['move 2','move 2']]);
make('thunder-limber-prevention',smeargle(['thunder']),
  mon('persian','limber',['splash'],[271,176,156,166,166,266]),
  [['move 1','move 1']],[2,2,3,4]);
