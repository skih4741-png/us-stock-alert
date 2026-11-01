const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const sheets={};
class Sheet {
 constructor(){this.rows=[];}
 getLastRow(){return this.rows.length;}
 getLastColumn(){return Math.max(0,...this.rows.map(r=>r.length));}
 getRange(r,c,n=1,m=1){const self=this;return {setNumberFormat(){return this;},setValues(vals){for(let i=0;i<n;i++){const row=self.rows[r-1+i] ||= [];for(let j=0;j<m;j++)row[c-1+j]=vals[i][j];}return this;},getDisplayValues(){return Array.from({length:n},(_,i)=>Array.from({length:m},(_,j)=>String(self.rows[r-1+i]?.[c-1+j] ?? '')));}};}
 getDataRange(){return this.getRange(1,1,this.getLastRow(),this.getLastColumn());}
}
const ss={getSheetByName:n=>sheets[n],insertSheet:n=>(sheets[n]=new Sheet())};
const c={console,PropertiesService:{getScriptProperties:()=>({getProperty:()=>null})},SpreadsheetApp:{getActiveSpreadsheet:()=>ss}};
vm.createContext(c);vm.runInContext(fs.readFileSync('apps_script/Code.gs','utf8'),c);
vm.runInContext('full_ = () => true;',c);
const call=(action,req)=>{c.req=req;return vm.runInContext('ACTIONS.'+action+'(req)',c);};
// 기존 11열 장부를 그대로 읽고 13열에 요청 ID/진입 근거만 추가.
sheets['모의 거래']=new Sheet();sheets['모의 거래'].rows=[Array(11).fill('old header'),['1','2026-10-01','OLD','1','10','','','','','','old note']];
const req={t:'TEST',qty:2,price:10,date:'2026-10-30',stop:9,target:12,requestId:'a-valid-request-0001',entry_context:{t:'TEST',reason:'연습 근거',price:10,team:{views:[]}}};
assert.equal(call('paperAdd',{...req,qty:1.5}).ok,false);
assert.equal(call('paperAdd',{...req,qty:1000}).ok,false);
assert.equal(call('paperAdd',{...req,entry_context:{}}).ok,false);
assert.equal(call('paperAdd',req).ok,true);
assert.equal(call('paperAdd',req).ok,true);assert.equal(sheets['모의 거래'].rows.length,3);
assert.equal(sheets['모의 거래'].rows[1][10],'old note');
assert.equal(sheets['모의 거래'].rows[2][11],req.requestId);
const saved=call('deskSave',{note:{t:'TEST',reason:'기다리는 이유',waitBelow:9,invalidBelow:8,status:'유지',snapshot:req.entry_context}});
assert.equal(saved.ok,true);assert.equal(saved.deskNotes[0].waitBelow,9);
assert.throws(()=>call('deskSave',{note:{t:'TEST',waitBelow:-1}}),/가격 조건/);
vm.runInContext('full_ = () => false;',c);
assert.equal(call('deskSave',{note:{t:'TEST'}}).auth,true);
assert.equal(call('paperAdd',req).auth,true);
console.log('PASS: paper request idempotency, integer/cash validation, legacy columns, persistent notes, authentication');
