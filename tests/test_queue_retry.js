const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('static/app.js', 'utf8');
function harness(responses) {
  const state = { user: {}, current: 'p' };
  let calls = 0;
  const delays = [];
  const context = vm.createContext({ state, Math, Error, Number, Promise,
    setJudgeStatus() {},
    setTimeout: (resolve, ms) => { delays.push(ms); resolve(); },
    apiPostForm: async () => { calls++; const x = responses.shift(); if (x instanceof Error) throw x; return x; },
  });
  const start = source.indexOf('async function submitWithQueueRetry(');
  vm.runInContext(source.slice(start, source.indexOf('/* Several views', start)), context);
  return { context, state, delays, calls: () => calls };
}
function full() { return Object.assign(new Error('full'), { status: 503, admission: 'rejected-queue-full', retryAfter: '30' }); }
test('confirmed queue rejection waits then admits exactly once', async () => {
  const h = harness([full(), {job_id:'one'}]);
  assert.equal((await h.context.submitWithQueueRetry({}, 'p')).job_id, 'one');
  assert.equal(h.calls(), 2); assert.ok(h.delays[0] >= 30000);
});
test('ambiguous network error and unclassified 503 never replay a POST', async () => {
  for (const err of [new Error('network'), Object.assign(new Error('outage'), {status:503})]) {
    const h = harness([err]); await assert.rejects(h.context.submitWithQueueRetry({},'p'));
    assert.equal(h.calls(),1); assert.equal(h.delays.length,0);
  }
});
test('bounded retries eventually stop', async () => {
  const h = harness(Array.from({length:6},full)); await assert.rejects(h.context.submitWithQueueRetry({},'p'));
  assert.equal(h.calls(),6); assert.equal(h.delays.length,5);
});
test('changing account cancels pending submission', async () => {
  const h = harness([]); h.state.user=null;
  await assert.rejects(h.context.submitWithQueueRetry({},'p')); assert.equal(h.calls(),0);
});
