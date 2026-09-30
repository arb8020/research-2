#!/usr/bin/env node
'use strict';
const fs = require('fs'); const path = require('path'); const cp = require('child_process');
const showdownDir = process.argv[2];
if (!showdownDir) throw new Error('usage: generate-kings-rock-cases.js POKEMON_SHOWDOWN_DIR');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
if (cp.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding:'utf8'}).trim() !== revision) throw new Error('wrong Showdown revision');
const {TeamValidator, Teams} = require(path.resolve(showdownDir));
const validator = new TeamValidator('gen3ou'); const out = path.resolve(__dirname, 'derived');
const catalog = {
  smeargle: {name:'Smeargle', gender:'M', ability:'Own Tempo', stats:[251,76,106,76,126,186]},
  blissey: {name:'Blissey', gender:'F', ability:'Natural Cure', stats:[651,56,56,186,306,146]},
  dustox: {name:'Dustox', gender:'M', ability:'Shield Dust', stats:[261,136,176,136,216,166]},
  jirachi: {name:'Jirachi', gender:'N', ability:'Serene Grace', stats:[341,236,236,236,236,236]},
};
const names = {tackle:'Tackle', armthrust:'Arm Thrust', aerialace:'Aerial Ace', splash:'Splash', softboiled:'Soft-Boiled', moonlight:'Moonlight'};
function member(species, moves, item='') { const e=catalog[species]; return {
  export:`${e.name}${e.gender!=='N'?` (${e.gender})`:''}${item?` @ ${item}`:''}\nAbility: ${e.ability}\nLevel: 100\nEVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n${moves.map(m=>`- ${names[m]}`).join('\n')}\n`,
  normalized:{species,level:100,gender:e.gender,nature:'hardy',ability:e.ability.toLowerCase().replace(/ /g,''),item:item.toLowerCase().replace(/[ ']/g,''),moves,stats:e.stats,status:null}}; }
function team(id, side, members) { const source=`${id}-p${side+1}.txt`; const text=members.map(x=>x.export).join('\n'); const problems=validator.validateTeam(Teams.import(text)); if(problems)throw new Error(problems.join('; ')); fs.writeFileSync(path.join(out,source),text); return {source,normalized:members.map(x=>x.normalized)}; }
function emit(id, move, target, seed, forced, testName, attacker='smeargle') { const choices=[['move 1','move 1']]; const targetMove=target==='blissey'?'softboiled':'moonlight'; const fixture={schema:'pokemon-native-differential-case-v1',id,provenance:{kind:'showdown-derived',source_file:'data/mods/gen3/items.ts',test_name:testName,oracle_revision:revision},format:'gen3ou',seed,teams:[team(id,0,[member(attacker,[move],"King's Rock")]),team(id,1,[member(target,[targetMove])])],source_choices:choices,choices,forced_outcomes:forced,features:['choice.move','item.kings-rock','handler.modify-move','effect.secondary','condition.volatile','prng.labeled','state.canonical'],boundaries:['request','choice','queue','handlers','state','events','prng'],limits:{max_boundaries:2,max_actions:2}}; fs.writeFileSync(path.join(out,`${id}.json`),`${JSON.stringify(fixture,null,2)}\n`); }
emit('kings-rock-tackle-success','tackle','blissey',[313,197,83,14],[{label:'move.secondary',occurrence:1,range:100,result:1}],'eligible single hit appends a successful flinch secondary');
emit('kings-rock-tackle-failure','tackle','blissey',[313,197,83,1],[{label:'move.secondary',occurrence:1,range:100,result:21}],'eligible single hit owns a failed secondary draw');
emit('kings-rock-shield-dust','tackle','dustox',[313,197,83,14],[],'Shield Dust filters the appended secondary before its draw');
emit('kings-rock-arm-thrust-per-hit','armthrust','blissey',[313,197,83,1],[
  {label:'move.multihit_count',occurrence:1,range:8,result:3},
  {label:'move.secondary',occurrence:1,range:100,result:30},
  {label:'move.secondary',occurrence:2,range:100,result:28},
  {label:'move.secondary',occurrence:3,range:100,result:8},
],'eligible multihit rolls the appended secondary once per connected hit');
emit('kings-rock-serene-grace-order','aerialace','blissey',[313,197,83,4],
  [{label:'move.secondary',occurrence:1,range:100,result:18}],
  'King\'s Rock appends before lower-priority Serene Grace doubles the chance','jirachi');
console.log('generated 5 King\'s Rock cases');
