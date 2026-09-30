#!/usr/bin/env node
'use strict';
const fs = require('fs'); const path = require('path'); const cp = require('child_process');
const showdownDir = process.argv[2];
if (!showdownDir) throw new Error('usage: generate-shell-bell-cases.js POKEMON_SHOWDOWN_DIR');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
if (cp.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding:'utf8'}).trim() !== revision) throw new Error('wrong Showdown revision');
const {TeamValidator, Teams} = require(path.resolve(showdownDir));
const validator = new TeamValidator('gen3ou'); const out = path.resolve(__dirname, 'derived');
const catalog = {
  smeargle:{name:'Smeargle',gender:'M',ability:'Own Tempo',stats:[251,76,106,76,126,186]},
  blissey:{name:'Blissey',gender:'F',ability:'Natural Cure',stats:[651,56,56,186,306,146]},
  metagross:{name:'Metagross',gender:'N',ability:'Clear Body',stats:[301,306,296,226,216,176]},
  alakazam:{name:'Alakazam',gender:'M',ability:'Synchronize',stats:[251,136,126,306,206,276]},
};
const names={tackle:'Tackle',armthrust:'Arm Thrust',meteormash:'Meteor Mash',recover:'Recover',splash:'Splash',substitute:'Substitute'};
function member(species,moves,item='',initialHP) { const e=catalog[species]; const display=e.gender==='N'?e.name:`${e.name} (${e.gender})`; return {
  export:`${display}${item?` @ ${item}`:''}\nAbility: ${e.ability}\nLevel: 100\nEVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n${moves.map(m=>`- ${names[m]}`).join('\n')}\n`,
  normalized:{species,level:100,gender:e.gender,nature:'hardy',ability:e.ability.toLowerCase().replace(/ /g,''),item:item.toLowerCase().replace(/ /g,''),moves,stats:e.stats,status:null,...(initialHP===undefined?{}:{initial_hp:initialHP})}}; }
function team(id,side,members){const source=`${id}-p${side+1}.txt`;const text=members.map(x=>x.export).join('\n');const problems=validator.validateTeam(Teams.import(text));if(problems)throw new Error(problems.join('; '));fs.writeFileSync(path.join(out,source),text);return{source,normalized:members.map(x=>x.normalized)};}
function emit(id,left,right,choices,testName,seed=[419,71,29,7]){const fixture={schema:'pokemon-native-differential-case-v1',id,provenance:{kind:'showdown-derived',source_file:'data/items.ts',test_name:testName,oracle_revision:revision},format:'gen3ou',seed,teams:[team(id,0,left),team(id,1,right)],source_choices:choices,choices,forced_outcomes:[],features:['choice.move','item.shell-bell','handler.after-move-secondary-self','state.canonical'],boundaries:['request','choice','queue','handlers','state','events','prng'],limits:{max_boundaries:1+choices.length,max_actions:2*choices.length}};fs.writeFileSync(path.join(out,`${id}.json`),`${JSON.stringify(fixture,null,2)}\n`);}
emit('shell-bell-single-hit',[member('smeargle',['tackle'],'Shell Bell',100)],[member('smeargle',['splash'])],[['move 1','move 1']],'single-hit actual damage heals one eighth');
emit('shell-bell-multihit-aggregate',[member('smeargle',['armthrust'],'Shell Bell',100)],[member('smeargle',['splash'])],[['move 1','move 1']],'multihit actual damage aggregates into one heal');
emit('shell-bell-overkill-cap',[member('metagross',['meteormash'],'Shell Bell',100)],[member('alakazam',['recover'],'',17)],[['move 1','move 1']],'overkill uses actual target HP lost rather than calculated damage');
emit('shell-bell-substitute-zero',[member('smeargle',['tackle'],'Shell Bell',100)],[member('alakazam',['substitute'])],[['move 1','move 1']],'Substitute damage is excluded from move total damage');
console.log('generated 4 Shell Bell cases');
