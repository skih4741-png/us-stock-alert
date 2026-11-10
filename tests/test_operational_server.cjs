const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const code = fs.readFileSync('apps_script/Code.gs', 'utf8');
let waits = 0, releases = 0, failLock = false;
const c = {
  PropertiesService: {getScriptProperties: () => ({getProperty: () => null, getProperties: () => ({})})},
  LockService: {getScriptLock: () => ({waitLock: () => { waits++; if(failLock) throw Error('busy'); }, releaseLock: () => {releases++;}})},
};
vm.createContext(c); vm.runInContext(code, c);
vm.runInContext('out_ = x => x; ACTIONS.quote = () => ({ok:true}); ACTIONS.deskSave = () => {throw Error("write failed")};', c);
const post = r => c.doPost({postData: {contents: JSON.stringify(r)}});
assert.equal(post({action:'quote'}).ok, true);
assert.equal(waits, 0); assert.equal(releases, 0);
vm.runInContext('full_ = () => false;', c);
assert.equal(post({action:'askAI',token:'invalid'}).auth, true);
assert.equal(post({action:'data',token:'invalid'}).auth, true);
assert.equal(waits, 0);
assert.equal(post({action:'deskSave'}).ok, false);
assert.equal(waits, 1); assert.equal(releases, 1);
failLock = true;
post({action:'deskSave'}); assert.equal(waits, 2); assert.equal(releases, 1);
assert.equal(post({action:'toString'}).ok, false);
assert.equal(post(null).ok, false);

// Data reads must not create missing tabs or migrate an existing ledger's headers.
vm.runInContext('READ_ONLY_REQUEST = true', c);
c.SpreadsheetApp = {getActiveSpreadsheet: () => ({getSheetByName: () => null, insertSheet: () => {throw Error('read created a sheet');}})};
assert.equal(c.paperRows_().length, 0);
assert.equal(c.watchList_().length, 0);
assert.equal(c.deskNotes_().length, 0);

const bounded = c.boundedMessages_([{role:'system',content:'rules'}, {role:'user',content:'x'.repeat(20000)+'QUESTION_END'}], 3000);
assert.equal(bounded[0].content,'rules');
assert.ok(bounded[1].content.endsWith('QUESTION_END'));
assert.ok(bounded[1].content.length <= 3000);
for (const remaining of [1, 10, 20, 40]) {
  const result=c.boundedMessages_([{role:'user',content:'x'.repeat(2000)}, {role:'user',content:'y'.repeat(7000-remaining)}],7000);
  assert.ok(result.reduce((n,m)=>n+m.content.length,0)<=7000);
}

// Both on-demand AI paths shrink one oversized request; JSON failure cannot be a success.
let calls = [];
c.PropertiesService.getScriptProperties = () => ({getProperties: () => ({GROQ_API_KEY:'test'})});
c.UrlFetchApp = {fetch: (url, opt) => {
  const body=JSON.parse(opt.payload); calls.push(body);
  return {getResponseCode: () => calls.length === 1 ? 413 : 200,
    getContentText: () => JSON.stringify({choices:[{message:{content:'{"answer":"ok"}'}}]})};
}};
assert.equal(c.aiCall_('rules','x'.repeat(20000)).ok,true);
assert.equal(calls.length,2); assert.ok(calls[1].messages[1].content.length < calls[0].messages[1].content.length);
assert.equal(calls[1].max_tokens,1500);
c.PropertiesService.getScriptProperties = () => ({getProperties: () => ({OPENROUTER_API_KEY:'test',OPENROUTER_MODEL:'paid/model'})});
calls=[];assert.equal(c.aiCall_('rules','data').ok,false);assert.equal(calls.length,0);
console.log('PASS: unlocked reads, retained authentication/write locks, safe missing-sheet reads, bounded prompts and 413 recovery');
