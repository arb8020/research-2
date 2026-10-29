#!/usr/bin/env node
'use strict';

const cp = require('child_process');
const fs = require('fs');
const path = require('path');
const REVISION = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const showdownDir = path.resolve(process.argv[2] || '');
if (!process.argv[2]) throw new Error('usage: generate-fake-out-cases.js POKEMON_SHOWDOWN_DIR');
if (cp.execFileSync('git', ['-C', showdownDir, 'rev-parse', 'HEAD'], {encoding: 'utf8'}).trim() !== REVISION) throw new Error('wrong Showdown revision');
const {Dex, Teams, TeamValidator} = require(showdownDir);
const {normalizeCase} = require('./normalize');
const dex = Dex.forGen(3); const validator = new TeamValidator('gen3ou');
const out = path.join(__dirname, 'derived');
function stats(id, level=100) { const b=dex.species.get(id).baseStats; const s=x=>Math.floor((2*b[x]+31)*level/100); return [s('hp')+level+10,s('atk')+5,s('def')+5,s('spa')+5,s('spd')+5,s('spe')+5]; }
function member(species,ability,moves,gender='M'){return{species,level:100,gender,nature:'hardy',ability,item:'',moves,stats:stats(species),status:null};}
function text(team){return team.map(x=>`${dex.species.get(x.species).name}${x.gender==='N'?'':` (${x.gender})`}\nAbility: ${dex.abilities.get(x.ability).name}\nLevel: 100\nEVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n${x.moves.map(m=>`- ${dex.moves.get(m).name}`).join('\n')}\n`).join('\n');}
function emit(s){const files=[`${s.id}-p1.txt`,`${s.id}-p2.txt`];for(let i=0;i<2;i++){const t=text(s.teams[i]);const errors=validator.validateTeam(Teams.import(t));if(errors)throw new Error(`${s.id} p${i+1}: ${errors.join('; ')}`);fs.writeFileSync(path.join(out,files[i]),t);}const value={schema:'pokemon-native-differential-case-v1',id:s.id,provenance:{kind:'showdown-derived',source_file:'data/moves.ts; sim/battle-actions.ts',test_name:s.description,oracle_revision:REVISION},format:'gen3ou',seed:s.seed||[419,71,29,7],teams:s.teams.map((t,i)=>({source:files[i],normalized:t})),source_choices:s.choices,choices:s.nativeChoices||s.choices,forced_outcomes:[],features:['choice.move','move.fake-out','handler.try','state.active-move-actions','state.canonical','prng.labeled',...(s.features||[])],boundaries:['request','choice','queue','handlers','state','events','prng'],limits:{max_boundaries:s.choices.length+1,max_actions:s.choices.length*2}};fs.writeFileSync(path.join(out,`${s.id}.json`),`${JSON.stringify(normalizeCase(value),null,2)}\n`);}
emit({id:'fake-out-pressure-ghost-repeat',description:'failed first hit still consumes Fake Out eligibility and Pressure PP',teams:[[member('smeargle','owntempo',['fakeout'])],[member('dusclops','pressure',['nightshade'])]],choices:[['move 1','move 1'],['move 1','move 1']],features:['ability.pressure','hit.type-immunity']});
emit({id:'fake-out-flinched-action-counts',description:'a selected move canceled by BeforeMove still consumes first-action eligibility',teams:[[member('smeargle','owntempo',['fakeout'])],[member('persian','limber',['fakeout','protect'],'F')]],choices:[['move 1','move 1'],['move 1','move 2']],features:['volatile.flinch','handler.before-move']});
emit({id:'fake-out-switch-reset',description:'switch re-entry resets selected move action eligibility',teams:[[member('smeargle','owntempo',['fakeout']),member('tyrogue','guts',['tackle'])],[member('blissey','naturalcure',['softboiled'],'F')]],choices:[['move 1','move 1'],['switch 2','move 1'],['switch 2','move 1'],['move 1','move 1']],nativeChoices:[['move 1','move 1'],['switch 2','move 1'],['switch 1','move 1'],['move 1','move 1']],features:['choice.switch']});
console.log('generated 3 Fake Out cases');
