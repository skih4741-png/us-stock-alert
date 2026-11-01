// Apps Script 없이 모델 접근 실패·한도 제한·모델 설정을 검증합니다.
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const source = fs.readFileSync('apps_script/Code.gs', 'utf8');
const part = source.slice(source.indexOf('var AI_PROVIDERS ='), source.indexOf('// 공급자 키가 하나라도'));
function run(props, codes) {
  const calls = [];
  const c = {PropertiesService:{getScriptProperties:()=>({getProperties:()=>props})},
    UrlFetchApp:{fetch:(url, req)=>{
      const model = JSON.parse(req.payload).model; calls.push(model);
      const code=codes.shift() || 200;
      return {getResponseCode:()=>code,getContentText:()=>JSON.stringify({choices:[{message:{content:'{"answer":"ok"}'}}]})};
    }}};
  vm.createContext(c);vm.runInContext(part,c);
  return {calls,result:c.aiCall_('test','test')};
}
let r=run({GROQ_API_KEY:'test'},[404,200]);
assert.deepEqual(r.calls,['openai/gpt-oss-20b','llama-3.1-8b-instant']);assert.equal(r.result.ok,true);
r=run({GROQ_API_KEY:'test',OPENROUTER_API_KEY:'test'},[429,200]);
assert.equal(r.calls.length,2);assert.equal(r.result.provider,'openrouter');
r=run({GROQ_API_KEY:'test',GROQ_MODEL:'custom-model'},[200]);assert.equal(r.calls[0],'custom-model');
assert.equal(run({},[]).result.ok,false);
console.log('PASS: Apps Script 모델 404 대체, 429 공급자 전환, 모델 속성, 키 누락');
