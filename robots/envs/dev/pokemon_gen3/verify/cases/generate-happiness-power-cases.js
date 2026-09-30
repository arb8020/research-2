#!/usr/bin/env node
'use strict';
const cp=require('child_process'),fs=require('fs'),path=require('path');
const revision='6e71625b9e6cffeda268b548ae7f43a7643fc3f0';const showdownDir=path.resolve(process.argv[2]||'');
if(!process.argv[2])throw new Error('usage: generate-happiness-power-cases.js POKEMON_SHOWDOWN_DIR');
if(cp.execFileSync('git',['-C',showdownDir,'rev-parse','HEAD'],{encoding:'utf8'}).trim()!==revision)throw new Error('wrong Showdown revision');
const {Dex,Teams,TeamValidator}=require(showdownDir);const {normalizeCase}=require('./normalize');const dex=Dex.forGen(3),validator=new TeamValidator('gen3ou'),out=path.join(__dirname,'derived');
function stats(id){const b=dex.species.get(id).baseStats,s=x=>2*b[x]+31;return[s('hp')+110,s('atk')+5,s('def')+5,s('spa')+5,s('spd')+5,s('spe')+5];}
function member(species,ability,move,gender,happiness,writeHappiness=true){return{normalized:{species,level:100,gender,nature:'hardy',ability,item:'',moves:[move],stats:stats(species),status:null,...(happiness===undefined?{}:{happiness})},text:`${dex.species.get(species).name} (${gender})\nAbility: ${dex.abilities.get(ability).name}\nLevel: 100\n${writeHappiness&&happiness!==undefined?`Happiness: ${happiness}\n`:''}EVs: 1 HP / 0 Atk / 0 Def / 0 SpA / 0 SpD / 0 Spe\nHardy Nature\n- ${dex.moves.get(move).name}\n`};}
function emit(id,move,happiness,{writeHappiness=true,normalizedHappiness=happiness}={}){const left=member('snorlax','immunity',move,'M',normalizedHappiness,writeHappiness),right=member('blissey','naturalcure','softboiled','F');for(const [i,m] of [left,right].entries()){const errors=validator.validateTeam(Teams.import(m.text));if(errors)throw new Error(`${id}: ${errors.join('; ')}`);fs.writeFileSync(path.join(out,`${id}-p${i+1}.txt`),m.text);}const value={schema:'pokemon-native-differential-case-v1',id,provenance:{kind:'showdown-derived',source_file:'data/moves.ts',test_name:`${move} happiness power at ${happiness===undefined?'default':happiness}`,oracle_revision:revision},format:'gen3ou',seed:[419,71,29,7],teams:[left,right].map((m,i)=>({source:`${id}-p${i+1}.txt`,normalized:[m.normalized]})),source_choices:[['move 1','move 1']],choices:[['move 1','move 1']],forced_outcomes:[],features:['choice.move','move.happiness-power','state.set-happiness','state.canonical','prng.labeled'],boundaries:['request','choice','queue','handlers','state','events','prng'],limits:{max_boundaries:2,max_actions:2}};fs.writeFileSync(path.join(out,`${id}.json`),`${JSON.stringify(normalizeCase(value),null,2)}\n`);}
emit('happiness-return-default','return',undefined);
emit('happiness-frustration-import-default','frustration',undefined,{writeHappiness:false,normalizedHappiness:0});
emit('happiness-return-zero','return',0);
emit('happiness-frustration-max','frustration',255);
emit('happiness-return-midpoint','return',128);
emit('happiness-frustration-midpoint','frustration',128);
console.log('generated 6 happiness-power cases');
