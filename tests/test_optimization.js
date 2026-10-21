// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Newbiegrader contributors
/* Actual frontend functions in an isolated VM; synthetic identities only. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
const source = fs.readFileSync('static/app.js', 'utf8');
function slice(a, b) {return source.slice(source.indexOf(a), source.indexOf(b, source.indexOf(a)));}
function cacheHarness() {
  const requests = [], elements = new Map();
  const c = vm.createContext({Date, state: {current:'canary', user:{email:'a@example.invalid'}},
    apiGet: url => new Promise((resolve, reject) => requests.push({url,resolve,reject})),
    $: id => {if (!elements.has(id)) elements.set(id, {value:'', classList:{remove(){}}}); return elements.get(id);},
    skel: () => 'loading', esc: String, historyTable: rows => JSON.stringify(rows), bindViewButtons() {}});
  vm.runInContext('const DETAIL_CACHE_TTL=60000;const _detailInflight=new Map();'
    + 'const _sampleInflight=new Map();const _pdfPrefetched=new Set();', c);
  vm.runInContext(slice('const _getCache =', 'function apiPostJson'), c);
  vm.runInContext(slice('async function loadHistory(', 'async function viewSubmission('), c);
  return {c,requests,elements};
}
test('old identity cleanup cannot erase a new inflight history request', async () => {
  const {c,requests} = cacheHarness();
  const old = c.apiGetCached('/history', 10000); c.clearGetCache();
  const current = c.apiGetCached('/history', 10000);
  requests[0].resolve({submissions:[{name:'old'}]}); await old;
  assert.equal(c.apiGetCached('/history',10000), current);
  requests[1].resolve({submissions:[{name:'new'}]}); await current;
  assert.equal((await c.apiGetCached('/history',10000)).submissions[0].name,'new');
});
test('late personal history cannot paint after logout or account switching', async () => {
  const {c,requests,elements} = cacheHarness();
  const old = c.loadHistory(); c.clearGetCache(); c.state.user={email:'b@example.invalid'};
  requests[0].resolve({configured:true, submissions:[{problem:'secret',name:'old account'}]}); await old;
  assert.equal(elements.get('hist-body').innerHTML, 'loading');
  assert.equal(elements.has('hist-stats'), false);
});
test('manual refresh replaces the cached answer for subsequent visits', async () => {
  const {c,requests} = cacheHarness();
  const path='/api/history?limit=100&mine=1';
  const first=c.apiGetCached(path,10000); requests[0].resolve({configured:false,submissions:[],version:1}); await first;
  const second=c.loadHistory(true); requests[1].resolve({configured:false,submissions:[],version:2}); await second;
  assert.equal((await c.apiGetCached(path,10000)).version,2);
});
test('pending history is never cached and an error can retry', async () => {
  const {c,requests}=cacheHarness();
  let p=c.apiGetCached('/history',10000); requests[0].resolve({submissions:[{status:'running'}]}); await p;
  p=c.apiGetCached('/history',10000); requests[1].reject(new Error('synthetic')); await assert.rejects(p);
  p=c.apiGetCached('/history',10000); requests[2].resolve({submissions:[]}); await p;
  assert.equal(requests.length,3);
});
test('single pass escaping matches the old HTML text and quoted-attribute policy', () => {
  const c=vm.createContext({});vm.runInContext(slice('function esc(', 'function inlineMd('),c);
  const original=s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  for(const value of [null,undefined,0,'ภาษาไทย 🌙',`<img src=x onerror="bad()"> & '`, '&lt;&amp;', '\u0000'])
    assert.equal(c.esc(value),original(value));
});
test('problem index preserves first duplicate, ID types and replacement-array invalidation', () => {
  const c=vm.createContext({});vm.runInContext(slice('const _byPidIndex', 'function problemCell('),c);
  const first={id:'1',title:'old'}, duplicate={id:'1',title:'duplicate'}, numeric={id:1};
  const list=[first,duplicate,numeric];
  assert.equal(c.byPidOf(list,'1'),first);assert.equal(c.byPidOf(list,1),numeric);
  assert.equal(c.byPidOf([{id:'1',title:'new'}],'1').title,'new');
  assert.equal(c.byPidOf([],'1'),null);assert.equal(c.byPidOf(null,'1'),null);
});
test('cached Thai date formatters preserve existing locale/year output', () => {
  const c=vm.createContext({Date,Intl});
  vm.runInContext(slice('const SHORT_TIME_OPTS', 'function historyTable('),c);
  vm.runInContext(slice('const _thaiTimeFmt', 'function contestWindowText('),c);
  for(const iso of ['2020-01-02T03:04:00Z',new Date().toISOString(),'invalid']) {
    const d=new Date(iso);
    const opts={day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'};
    if(d.getFullYear()!==new Date().getFullYear()) opts.year='2-digit';
    assert.equal(c.shortTime(iso),isNaN(d)?iso:d.toLocaleString('th-TH',opts));
    assert.equal(c.thaiTime(iso),isNaN(d)?iso:d.toLocaleString('th-TH',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}));
  }
});

test('history filter races render only the newest response', async () => {
  const {c,requests,elements} = cacheHarness();
  const first=c.loadHistory();elements.get('hist-filter').value='second';
  const second=c.loadHistory();
  requests[1].resolve({configured:true,submissions:[{problem:'second',score:100}]});await second;
  const current=elements.get('hist-body').innerHTML;
  requests[0].resolve({configured:true,submissions:[{problem:'first',score:0}]});await first;
  assert.equal(elements.get('hist-body').innerHTML,current);
});

test('parallel announcements and detail cannot overwrite a newer contest', async () => {
  const requests=[], elements=new Map(), rendered=[];
  const c=vm.createContext({state:{contestCache:{},is_admin:false},
    $: id=>{if(!elements.has(id))elements.set(id,{classList:{add(){},remove(){}}});return elements.get(id);},
    apiGet: url=>new Promise((resolve,reject)=>requests.push({url,resolve,reject})),
    skel:()=> 'loading',setTitle(){},contestWindowText:()=>'',contestStatusBadge:()=>'',
    renderContestJoin:d=>rendered.push(d.id),renderContestProblems(){},renderContestScoreboard(){},startContestTicker(){},
    esc:String,shortTime:String,isUnconfiguredMessage:()=>false});
  vm.runInContext('let _getGen=0;',c);
  vm.runInContext(slice('async function renderContest(cid)', 'function renderContestJoin('),c);
  vm.runInContext(slice('async function renderContestAnnc(', 'function renderContestScoreboard('),c);
  const old=c.renderContest('old'),current=c.renderContest('new');
  assert.equal(requests.length,4,'both requests start before detail resolves');
  requests[3].resolve({id:'new',title:'new'});await current;
  requests[2].resolve({announcements:[{body:'NEW',created_at:''}]});await Promise.resolve();await Promise.resolve();
  requests[1].resolve({id:'old',title:'old'});await old;
  requests[0].resolve({announcements:[{body:'OLD',created_at:''}]});await Promise.resolve();await Promise.resolve();
  assert.equal(elements.get('contest-title').textContent,'new');
  assert.deepEqual(rendered,['new']);
  assert.match(elements.get('contest-annc').innerHTML,/NEW/);
  assert.doesNotMatch(elements.get('contest-annc').innerHTML,/OLD/);
});

test('late admin task data and persistent cache rows are filtered for the current identity', () => {
  const c=vm.createContext({state:{is_admin:false}});
  vm.runInContext(slice('function problemRowsForIdentity(', 'const _byPidIndex'),c);
  const rows=[{id:'public',hidden:false,contest_only:false,config_hidden:false},
    {id:'unpublished',hidden:true},{id:'contest',contest_only:true}];
  const publicRows=c.problemRowsForIdentity(rows);
  assert.equal(publicRows.length,1);assert.equal(publicRows[0].id,'public');
  assert.equal('hidden' in publicRows[0],false);
  c.state.is_admin=true;assert.equal(c.problemRowsForIdentity(rows),rows);
});

test('late identity response cannot restore an account after logout refresh wins', async () => {
  const requests=[];
  const c=vm.createContext({state:{user:{email:'old@example.invalid'},is_admin:true,problems:[]},
    apiGet:()=>new Promise(resolve=>requests.push(resolve)), clearGetCache(){},
    $:()=>({classList:{toggle(){}},textContent:''}),location:{hash:'#/tasks'},setLang(){}});
  vm.runInContext(slice('function problemRowsForIdentity(', 'const _byPidIndex'),c);
  vm.runInContext(slice('async function refreshMe()', '$("login-btn").onclick'),c);
  const old=c.refreshMe(),latest=c.refreshMe();
  requests[1]({user:null,is_admin:false});await latest;
  requests[0]({user:{email:'old@example.invalid'},is_admin:true});await old;
  assert.equal(c.state.user,null);assert.equal(c.state.is_admin,false);
});

test('unknown queue position is not shown as first in line', () => {
  const c=vm.createContext({});
  vm.runInContext(slice('function jobStateText(', 'function waitedText('),c);
  for(const hint of [null,undefined,'invalid'])
    assert.equal(c.jobStateText({status:'queued',queued_ahead:hint}),'อยู่ในคิวตรวจ');
  assert.match(c.jobStateText({status:'queued',queued_ahead:0}),/คนแรก/);
  assert.match(c.jobStateText({status:'queued',queued_ahead:3}),/3 งาน/);
});
