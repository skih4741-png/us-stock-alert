const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const src=fs.readFileSync('docs/app.js','utf8');
const weekly=src.slice(src.indexOf('  function weeklyOperations('),src.indexOf('  function viewOperations('));
const api=src.slice(src.indexOf('  async function api('),src.indexOf('  /* ---------- 도구'));
const c={Date,Number,CFG:{API_URL:'https://example.invalid'},S:{},deviceId:()=>'',deviceLabel:()=>'',
  AbortController,setTimeout:(fn,ms)=>ms===800?setTimeout(fn,0):setTimeout(fn,ms),clearTimeout,clearAll:()=>{},go:()=>{}};
vm.createContext(c);vm.runInContext(weekly+api,c);
const at=new Date().toISOString();
const m=c.weeklyOperations([{kind:'daily',at,ok:true,took:20},{kind:'daily',at,ok:'skip',took:1}]);
assert.equal(m.total,1);assert.equal(m.rate,100);assert.equal(m.average,20);
(async()=>{
  let calls=0;c.fetch=async()=>{calls++;throw Error('network');};
  await assert.rejects(c.api('paperAdd',{}));assert.equal(calls,1,'do not replay a write after an uncertain response');
  calls=0;await assert.rejects(c.api('data',{}));assert.equal(calls,2);
  c.fetch=async()=>({ok:true,json:async()=>({ok:true,serverVersion:'2.25.1'})});
  await c.api('status');assert.equal(c.S.serverVersion,'2.25.1');
  console.log('PASS: skipped-run metrics, bounded read retries, no blind write replay, backend version');
})().catch(e=>{console.error(e);process.exitCode=1;});
