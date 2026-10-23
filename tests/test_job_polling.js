/* Run with node --test tests/test_job_polling.js; no browser or dependency. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { test } = require("node:test");

const app = fs.readFileSync(require("node:path").join(__dirname, "../static/app.js"), "utf8");
const pollingCode = app.slice(app.indexOf("/* ---------------- judging jobs"),
  app.indexOf("function jobStateText"));

function harness(jobs, random = 0.5) {
  let now = 0;
  const waits = [], calls = [], ticks = [], saved = new Map();
  const context = vm.createContext({
    Date: { now: () => now }, Math: Object.assign(Object.create(Math), { random: () => random }),
    performance: { now: () => now },
    setTimeout: (callback, ms) => { waits.push(ms); now += ms; callback(); },
    apiGet: async (path) => {
      calls.push(path);
      const job = jobs[Math.min(calls.length - 1, jobs.length - 1)];
      if (job instanceof Error) throw job;
      return job;
    },
    state: { current: "other", jobResults: {} },
    rememberJob: (pid, jid) => saved.set(pid, jid), forgetJob: (pid) => saved.delete(pid),
    setTaskTab: () => {}, setJudgeStatus: () => {}, renderResults: () => {},
  });
  vm.runInContext(pollingCode, context);
  return { context, waits, calls, ticks, saved,
    poll: (jid = "job/a") => context.pollJob(jid, (job) => ticks.push(job)) };
}

test("unchanged jobs back off, progress resets delay, and terminal jobs stop", async () => {
  const h = harness([
    ...Array(10).fill({ status: "queued", queued_ahead: 8 }),
    { status: "queued", queued_ahead: 2 }, { status: "running" }, { status: "done", result: { score: 100 } },
  ]);
  const result = await h.poll();
  assert.equal(result.result.score, 100);
  assert.ok(h.waits[4] > h.waits[0], "long queues must reduce polling traffic");
  assert.ok(h.waits.every((ms) => ms >= 500 && ms <= 5000));
  assert.ok(h.waits[10] < h.waits[9], "queue progress should restore responsiveness");
  assert.ok(h.waits[11] < h.waits[9], "execution polls faster than a deep queue");
  assert.equal(h.calls.length, 13);
  assert.equal(h.ticks.length, 13);
  assert.equal(h.calls[0], "/api/jobs/job%2Fa");
});

test("jitter spreads clients while staying bounded", async () => {
  const jobs = [...Array(20).fill({ status: "running" }), { status: "done" }];
  const low = harness(jobs, 0), high = harness(jobs, 0.999);
  await Promise.all([low.poll(), high.poll()]);
  assert.notEqual(low.waits[0], high.waits[0]);
  assert.ok([...low.waits, ...high.waits].every((ms) => ms >= 500 && ms <= 5000));
});

test("terminal errors and ownership HTTP failures preserve their original contract", async () => {
  const terminal = { status: "error", error: "judging timed out" };
  const h = harness([terminal]);
  assert.equal(await h.poll(), terminal);
  assert.equal(h.waits.length, 0);
  const forbidden = Object.assign(new Error("not your job"), { status: 403 });
  const denied = harness([forbidden]);
  await assert.rejects(denied.poll(), (error) => error === forbidden);
  assert.equal(denied.calls.length, 1);
});

test("four minute timeout identifies the job and resume retains its stored id", async () => {
  const h = harness([{ status: "queued", queued_ahead: 100 }]);
  await assert.rejects(h.poll(), (error) => error.timeout && error.job_id === "job/a");
  assert.equal(h.waits.reduce((sum, ms) => sum + ms, 0), 240000);
  assert.ok(h.calls.length < 70, "a stuck queue must not poll hundreds of times");
  h.saved.set("thai_time", "job/a");
  await h.context.resumeJob("thai_time", "job/a");
  assert.equal(h.saved.get("thai_time"), "job/a");
});

test("resume records a final result and clears the pending id", async () => {
  const h = harness([{ status: "done", result: { score: 100 } }]);
  h.saved.set("thai_time", "job/a");
  await h.context.resumeJob("thai_time", "job/a");
  assert.equal(h.saved.has("thai_time"), false);
  assert.equal(h.context.state.jobResults.thai_time.result.score, 100);
});

test("network blips retry without forgetting the job", async () => {
  const blip = () => new Error("socket hang up");   // no .status: not an HTTP error
  const h = harness([blip(), blip(), { status: "done", result: { score: 100 } }]);
  const result = await h.poll();
  assert.equal(result.result.score, 100);
  assert.equal(h.calls.length, 3);
});

test("persistent network failure keeps the job id for resume", async () => {
  const h = harness([new Error("network down")]);
  await assert.rejects(h.poll(), (error) => error.keepJob === true && error.job_id === "job/a");
  assert.equal(h.calls.length, 9);   // 1 initial + 8 retries, then give up but keep id
});

test("active jobs expose completion within one polling interval", async () => {
  for (const job of [{ status: "running" }, { status: "queued", queued_ahead: 0 }]) {
    const h = harness([...Array(12).fill(job), { status: "done" }], 0.999);
    await h.poll();
    assert.ok(h.waits.every((ms) => ms <= 1000));
  }
});
