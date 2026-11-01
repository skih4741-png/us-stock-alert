const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const code = fs.readFileSync('apps_script/Code.gs','utf8');
function run(fn, statuses) {
 const calls=[];
 const context={PropertiesService:{getScriptProperties:()=>({getProperties:()=>({GROQ_API_KEY:'test-key',GROQ_MODEL:'custom-model'})})},UrlFetchApp:{fetch:(url,opt)=>{const b=JSON.parse(opt.payload);calls.push(b.model);const status=statuses.shift();return {getResponseCode:()=>status,getContentText:()=>JSON.stringify({choices:[{message:{content:'{"answer":"ok"}'}}]})};}}};
 vm.createContext(context);vm.runInContext(code,context);
 const r=fn==='aiCall_'?context.aiCall_('s','u'):context.aiCallMsgs_([{role:'user',content:'test'}],true,20);
 return {r,calls};
}
for (const fn of ['aiCall_','aiCallMsgs_']) {
 let {r,calls}=run(fn,[404,200]);assert.equal(r.ok,true);assert.equal(r.model,'llama-3.1-8b-instant');assert.deepEqual(calls,['custom-model','llama-3.1-8b-instant']);
 ({r,calls}=run(fn,[401]));assert.equal(r.ok,false);assert.deepEqual(calls,['custom-model']);
 ({r,calls}=run(fn,[404,404]));assert.equal(r.ok,false);assert.equal(calls.length,2);
}
console.log('PASS: both AI paths respect model override, retry 404 once, and skip retry for key errors.');
