'use strict';
const fs = require('fs');
const path = require('path');
const showdown = process.env.POKEMON_SHOWDOWN_DIR || process.argv[2];
if (!showdown) throw new Error('POKEMON_SHOWDOWN_DIR or argv[2] must name the pinned clean Showdown checkout');
const childProcess = require('child_process');
const revision = '6e71625b9e6cffeda268b548ae7f43a7643fc3f0';
const actualRevision = childProcess.execFileSync('git', ['rev-parse', 'HEAD'], {
 cwd: showdown, encoding: 'utf8',
}).trim();
if (actualRevision !== revision) throw new Error(`expected Showdown ${revision}, got ${actualRevision}`);
const dirty = childProcess.execFileSync('git', ['status', '--porcelain', '--untracked-files=no'], {
 cwd: showdown, encoding: 'utf8',
}).trim();
if (dirty) throw new Error('condition completeness audit requires a clean pinned Showdown checkout');
const artifactPath = path.join(__dirname, 'gen3ou-inventory.json');
const {Dex, TeamValidator} = require(showdown);
const validator = new TeamValidator('gen3ou');
const dex = validator.dex;
const blank = () => ({hp:1,atk:0,def:0,spa:0,spd:0,spe:0});
const candidate = (s,a,m,i='') => ({name:s.name,species:s.name,item:i,ability:a,moves:[m],nature:'Serious',level:100,evs:blank(),ivs:{hp:31,atk:31,def:31,spa:31,spd:31,spe:31}});
const legalSpecies = dex.species.all().filter(s => {
  if (!s.exists || s.gen > 3) return false;
  const set=candidate(s,s.abilities[0]||'','Splash'); const {tierSpecies}=validator.getValidationSpecies(set);
  return !validator.checkSpecies(set,s,tierSpecies,{});
});
const movePool=dex.moves.all().filter(m=>m.exists&&m.gen<=3);
const moveIDs=new Set(), abilityIDs=new Set(); let seed;
for(const s of legalSpecies) for(const a of new Set(Object.values(s.abilities).filter(Boolean))) for(const m of movePool){
  const set=candidate(s,a,m.name); if(!validator.validateSet(set,{})){moveIDs.add(m.id);abilityIDs.add(dex.abilities.get(a).id);seed||=set;}
}
// Independently reproduce runtime move reachability. A legal submitted
// Metronome can select every effective move admitted by its pinned predicate;
// Struggle is created by the simulator when no move slot is usable.
if (moveIDs.has('metronome')) {
  for (const move of movePool) {
    if ((!move.isNonstandard || move.isNonstandard === 'Unobtainable') && move.flags.metronome) {
      moveIDs.add(move.id);
    }
  }
}
moveIDs.add('struggle');
const itemIDs=new Set(); for(const i of dex.items.all().filter(i=>i.exists&&i.gen<=3)){if(!validator.validateSet({...seed,item:i.name},{}))itemIDs.add(i.id)}
const refs={status:new Set(['slp','frz','brn','par','psn','tox']),volatile:new Set(),side:new Set(),slot:new Set(),weather:new Set(),pseudo_weather:new Set()};
const calls=[], directDeletes=[], unresolved=[];
const apiSpec={
 addVolatile:{kind:'volatile',arg:0},removeVolatile:{kind:'volatile',arg:0},
 addSideCondition:{kind:'side',arg:0},removeSideCondition:{kind:'side',arg:0},
 addSlotCondition:{kind:'slot',arg:1},removeSlotCondition:{kind:'slot',arg:1},
 setWeather:{kind:'weather',arg:0},clearWeather:{kind:null,arg:null},
 addPseudoWeather:{kind:'pseudo_weather',arg:0},removePseudoWeather:{kind:'pseudo_weather',arg:0},
 setStatus:{kind:'status',arg:0},forceStatus:{kind:'status',arg:0},trySetStatus:{kind:'status',arg:0},
 cureStatus:{kind:null,arg:null},clearStatus:{kind:null,arg:null},
};
function splitArgs(src){const out=[];let start=0,depth=0,q='',esc=false;for(let i=0;i<src.length;i++){const c=src[i];if(q){if(esc)esc=false;else if(c==='\\')esc=true;else if(c===q)q='';continue}if(c==='"'||c==="'"||c==='`'){q=c;continue}if('([{'.includes(c))depth++;else if(')]}'.includes(c))depth--;else if(c===','&&depth===0){out.push(src.slice(start,i).trim());start=i+1}}out.push(src.slice(start).trim());return out}
function maskNonCode(src){const out=[...src];let q='',esc=false,line=false,block=false;for(let i=0;i<src.length;i++){const c=src[i],n=src[i+1];if(line){if(c==='\n')line=false;else out[i]=' ';continue}if(block){out[i]=' ';if(c==='*'&&n==='/'){out[++i]=' ';block=false}continue}if(q){out[i]=' ';if(esc)esc=false;else if(c==='\\')esc=true;else if(c===q)q='';continue}if(c==='/'&&n==='/'){out[i]=out[++i]=' ';line=true}else if(c==='/'&&n==='*'){out[i]=out[++i]=' ';block=true}else if(c==='"'||c==="'"||c==='`'){out[i]=' ';q=c}}return out.join('')}
function extractCalls(text){const names=Object.keys(apiSpec);const re=new RegExp('\\b('+names.join('|')+')\\s*\\(','g');const out=[];for(const m of maskNonCode(text).matchAll(re)){let i=m.index+m[0].length,depth=1,q='',esc=false;for(;i<text.length&&depth;i++){const c=text[i];if(q){if(esc)esc=false;else if(c==='\\')esc=true;else if(c===q)q='';continue}if(c==='"'||c==="'"||c==='`'){q=c;continue}if(c==='(')depth++;else if(c===')')depth--}if(depth)throw new Error('unbalanced '+m[1]);const body=text.slice(m.index+m[0].length,i-1);out.push({api:m[1],args:splitArgs(body)})}return out}
function literal(expr){const m=/^(['"])([^'"]+)\1$/.exec(expr||'');return m?Dex.toID(m[2]):null}
const dynamic={
 'ability:effectspore:onDamagingHit:trySetStatus:0':['slp','par','psn'],
 'ability:synchronize:onAfterSetStatus:trySetStatus:0':['brn','par','psn'],
 'move:triattack:secondary.onHit:trySetStatus:0':['brn','par','frz'],
};
for(const id of ['bounce','dig','dive','fly','razorwind','skullbash','skyattack','solarbeam']){
 dynamic[`move:${id}:onTryMove:removeVolatile:0`]=[id];
}
for(const hook of ['onAfterHit','onAfterSubDamage','self.onHit'])dynamic[`move:rapidspin:${hook}:removeSideCondition:0`]=['spikes'];
dynamic['condition:twoturnmove:onStart:addVolatile:0']=['bounce','dig','dive','fly','razorwind','skullbash','skyattack','solarbeam'];
dynamic['condition:twoturnmove:onEnd:removeVolatile:0']=['bounce','dig','dive','fly','razorwind','skullbash','skyattack','solarbeam'];
function add(kind,id){if(id)refs[kind].add(Dex.toID(id))}
function scan(value,owner,path='',seen=new Set()){
 if(!value||(typeof value!=='object'&&typeof value!=='function')||seen.has(value))return;seen.add(value);
 for(const [key,child] of Object.entries(value)){const p=path?path+'.'+key:key;
  if((key==='status'||key==='forceStatus')&&typeof child==='string')add('status',child);
  if(key==='volatileStatus'&&typeof child==='string')add('volatile',child);
  if(key==='sideCondition'&&typeof child==='string')add('side',child);
  if(key==='slotCondition'&&typeof child==='string')add('slot',child);
  if(key==='weather'&&typeof child==='string')add('weather',child);
  if(key==='pseudoWeather'&&typeof child==='string')add('pseudo_weather',child);
  if(typeof child==='function'){const text=Function.prototype.toString.call(child);
   for(const c of extractCalls(text)){const spec=apiSpec[c.api],row={owner,path:p,api:c.api,args:c.args};calls.push(row);
    if(spec.kind){const expr=c.args[spec.arg],lit=literal(expr),dk=`${owner}:${p}:${c.api}:${spec.arg}`;if(lit)add(spec.kind,lit);else if(dynamic[dk])for(const id of dynamic[dk])add(spec.kind,id);else unresolved.push({...row,id_arg:spec.arg,expression:expr});}
    if(c.api==='addVolatile'&&c.args.length>=4&&c.args[3]){const lit=literal(c.args[3]),dk=`${owner}:${p}:${c.api}:3`;if(lit)add('volatile',lit);else if(dynamic[dk])for(const id of dynamic[dk])add('volatile',id);else unresolved.push({...row,id_arg:3,expression:c.args[3],role:'linkedStatus'});}
   }
   for(const m of maskNonCode(text).matchAll(/delete\s+[^;\n]*?\b(volatiles|sideConditions|slotConditions|pseudoWeather)((?:\s*\[[^\]]+\])+)/g)){const original=text.slice(m.index,m.index+m[0].length),accessors=[...original.matchAll(/\[([^\]]+)\]/g)],expression=accessors.at(-1)?.[1].trim(),id=literal(expression);if(!id)unresolved.push({owner,path:p,api:'delete',container:m[1],expression});else directDeletes.push({owner,path:p,container:m[1],id});}
  }
  if(child&&typeof child==='object')scan(child,owner,p,seen);
 }
}
const moves=[...moveIDs].map(id=>dex.moves.get(id)), abilities=[...abilityIDs].map(id=>dex.abilities.get(id)),items=[...itemIDs].map(id=>dex.items.get(id));
for(const x of moves)scan(x,`move:${x.id}`);for(const x of abilities)scan(x,`ability:${x.id}`);for(const x of items)scan(x,`item:${x.id}`);
for(const m of moves)if(m.condition&&!m.sideCondition&&!m.slotCondition&&!m.weather&&!m.pseudoWeather&&!m.status)refs.volatile.add(m.id);
for(const a of abilities)if(a.condition)refs.volatile.add(a.id);for(const i of items)if(i.condition)refs.volatile.add(i.id);
const format=dex.formats.get('gen3ou'),rules=dex.formats.getRuleTable(format),excluded=new Set(['onBegin','onTeamPreview','onBattleStart','onValidateRule','onValidateTeam','onChangeSet','onValidateSet']);
for(const id of rules.keys()){if('+*-!'.includes(id[0]))continue;const r=dex.formats.get(id);if(r.exists&&Object.keys(r).some(k=>k.startsWith('on')&&!excluded.has(k))){refs.pseudo_weather.add(r.id);scan(r,`format:${r.id}`)}}
// Fixed point over every discovered effective Condition.
const scannedConditions=new Set();let changed=true;while(changed){changed=false;for(const id of new Set(Object.values(refs).flatMap(x=>[...x]))){if(scannedConditions.has(id)||!dex.data.Conditions[id])continue;scannedConditions.add(id);scan(dex.data.Conditions[id],`condition:${id}`);changed=true}}
const artifact=JSON.parse(fs.readFileSync(artifactPath,'utf8'));const names={status:'statuses',volatile:'volatiles',side:'side_conditions',slot:'slot_conditions',weather:'weather',pseudo_weather:'pseudo_weather'};
const compare={};for(const[k,a]of Object.entries(names)){const actual=new Set(artifact[a].map(x=>x.id)),expected=refs[k];compare[k]={expected:[...expected].sort(),missing_in_artifact:[...expected].filter(x=>!actual.has(x)).sort(),extra_in_artifact:[...actual].filter(x=>!expected.has(x)).sort()}}
const grouped=Object.entries(calls.reduce((o,c)=>{o[c.api]=(o[c.api]||0)+1;return o},{})).sort().map(([api,count])=>({api,count}));
console.log(JSON.stringify({revision:actualRevision,reachable:{moves:moveIDs.size,abilities:abilityIDs.size,items:itemIDs.size},call_counts:grouped,calls,directDeletes,unresolved,scanned_conditions:[...scannedConditions].sort(),compare},null,2));
