/* Newbiegrader SPA — hash-routed views (home / tasks / task / history), no build step. */
"use strict";

const $ = (id) => document.getElementById(id);

/* Split-deploy support: static host + separate backend.
 * Set window.GRADER_API_BASE in config.js ("" = same origin). */
const API = (window.GRADER_API_BASE || "").replace(/\/$/, "");

const state = {
  problems: [],
  stats: {},
  current: null,
  lang: "cpp",
  taskTab: "statement",
  file: null,
  user: null,
  filter: { q: "", diff: "", tag: "" },
};

/* ---------------- task tabs ---------------- */
function setTaskTab(tab) {
  state.taskTab = tab;
  document.querySelectorAll(".tab-btn").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".tab-pane").forEach((p) =>
    p.classList.toggle("active", p.id === "pane-" + tab));
  if (tab === "subs") loadTaskSubs();
  if (tab === "mine") loadTaskMine();
}
document.querySelectorAll(".tab-btn").forEach((b) => {
  b.onclick = () => setTaskTab(b.dataset.tab);
});

function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function inlineMd(s) {
  s = esc(s);
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  return s;
}

/* Minimal markdown: fences, h1-h3, unordered lists, paragraphs. */
function renderMd(src) {
  const blocks = [];
  src = src.replace(/```(\w*)\n([\s\S]*?)```/g, (_m, _lang, code) => {
    blocks.push(`<pre><code>${esc(code.replace(/\n$/, ""))}</code></pre>`);
    return `\u0000${blocks.length - 1}\u0000`;
  });
  const lines = src.split("\n").map((line) => {
    const ph = line.match(/^\u0000(\d+)\u0000$/);
    if (ph) return blocks[Number(ph[1])] || "";
    if (/^###\s+/.test(line)) return `<h3>${inlineMd(line.replace(/^###\s+/, ""))}</h3>`;
    if (/^##\s+/.test(line)) return `<h2>${inlineMd(line.replace(/^##\s+/, ""))}</h2>`;
    if (/^#\s+/.test(line)) return `<h1>${inlineMd(line.replace(/^#\s+/, ""))}</h1>`;
    if (/^-\s+/.test(line)) return `<li>${inlineMd(line.replace(/^-\s+/, ""))}</li>`;
    if (/^\s*$/.test(line)) return "";
    return `<p>${inlineMd(line)}</p>`;
  });
  return lines.join("\n").replace(/((?:<li>.*<\/li>\n?)+)/g, "<ul>$1</ul>");
}

function badge(text, cls) {
  cls = cls || text;
  return `<span class="badge b-${esc(cls)}">${esc(text)}</span>`;
}

function diffBadge(d) {
  if (!d) return `<span class="dim">—</span>`;
  return `<span class="diff-tag diff-${esc(d)}">${esc(d)}</span>`;
}

/* ---------------- starter templates (all correct) ---------------- */
const TEMPLATES = {
  aplusb: {
    python:
`import sys

def main():
    data = sys.stdin.read().strip().split()
    if not data:
        return
    a, b = int(data[0]), int(data[1])
    print(a + b)

main()
`,
    c:
`#include <stdio.h>

int main(void) {
    long long a, b;
    if (scanf("%lld %lld", &a, &b) != 2) return 0;
    printf("%lld\\n", a + b);
    return 0;
}
`,
    cpp:
`#include <iostream>

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    long long a, b;
    if (!(std::cin >> a >> b)) return 0;
    std::cout << a + b << '\\n';
    return 0;
}
`,
  },
  fizzbuzz: {
    python:
`import sys

def main():
    n = int(sys.stdin.read().strip())
    out = []
    for i in range(1, n + 1):
        if i % 15 == 0:
            out.append("FizzBuzz")
        elif i % 3 == 0:
            out.append("Fizz")
        elif i % 5 == 0:
            out.append("Buzz")
        else:
            out.append(str(i))
    sys.stdout.write("\\n".join(out) + "\\n")

main()
`,
    c:
`#include <stdio.h>

int main(void) {
    int n;
    if (scanf("%d", &n) != 1) return 0;
    for (int i = 1; i <= n; i++) {
        if (i % 15 == 0) printf("FizzBuzz\\n");
        else if (i % 3 == 0) printf("Fizz\\n");
        else if (i % 5 == 0) printf("Buzz\\n");
        else printf("%d\\n", i);
    }
    return 0;
}
`,
    cpp:
`#include <iostream>
#include <string>

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    int n;
    if (!(std::cin >> n)) return 0;
    std::string out;
    out.reserve((size_t)n * 8);
    for (int i = 1; i <= n; i++) {
        if (i % 15 == 0) out += "FizzBuzz\\n";
        else if (i % 3 == 0) out += "Fizz\\n";
        else if (i % 5 == 0) out += "Buzz\\n";
        else { out += std::to_string(i); out += '\\n'; }
    }
    std::cout << out;
    return 0;
}
`,
  },
  palindrome: {
    python:
`import sys

def main():
    data = sys.stdin.read().splitlines()
    s = data[0] if data else ""
    print("YES" if s == s[::-1] else "NO")

main()
`,
    c:
`#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void) {
    char *line = NULL;
    size_t cap = 0;
    if (getline(&line, &cap, stdin) < 0) {
        printf("YES\\n");
        free(line);
        return 0;
    }
    long len = (long)strlen(line);
    while (len > 0 && (line[len - 1] == '\\n' || line[len - 1] == '\\r'))
        line[--len] = '\\0';
    for (long i = 0, j = len - 1; i < j; i++, j--) {
        if (line[i] != line[j]) {
            printf("NO\\n");
            free(line);
            return 0;
        }
    }
    printf("YES\\n");
    free(line);
    return 0;
}
`,
    cpp:
`#include <iostream>
#include <string>

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    std::string s;
    if (!std::getline(std::cin, s)) s = "";
    if (!s.empty() && s.back() == '\\r') s.pop_back();
    std::string r(s.rbegin(), s.rend());
    std::cout << (s == r ? "YES\\n" : "NO\\n");
    return 0;
}
`,
  },
};

/* ---------------- api ---------------- */
async function apiGet(path) {
  const r = await fetch(API + path, { credentials: "include" });
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail || `GET ${path}: ${r.status}`);
  }
  return r.json();
}

async function fetchStats() {
  try {
    const s = await apiGet("/api/stats");
    state.stats = (s && s.configured && s.stats) || {};
  } catch (e) {
    state.stats = {};
  }
}

/* ---------------- router ---------------- */
function show(view) {
  document.querySelectorAll(".view").forEach((v) =>
    v.classList.toggle("active", v.id === "view-" + view));
  document.querySelectorAll(".nav-link").forEach((a) =>
    a.classList.toggle("active",
      a.dataset.route === view || (view === "task" && a.dataset.route === "tasks")));
  window.scrollTo(0, 0);
}

function router() {
  const h = location.hash || "#/";
  if (h.startsWith("#/task/")) {
    const pid = decodeURIComponent(h.slice("#/task/".length));
    if (state.problems.some((p) => p.id === pid)) {
      show("task");
      selectProblem(pid);
    } else {
      location.hash = "#/tasks";
    }
    return;
  }
  if (h === "#/tasks") { show("tasks"); renderTasksTable(); return; }
  if (h === "#/history") { show("history"); loadHistory(); return; }
  show("home");
  renderHome();
}
window.addEventListener("hashchange", router);

/* ---------------- home ---------------- */
function renderHome() {
  $("stat-problems").textContent = state.problems.length;
  let subs = 0, acc = 0;
  Object.values(state.stats).forEach((s) => { subs += s.subs || 0; acc += s.accepted || 0; });
  $("stat-subs").textContent = subs;
  $("stat-accepted").textContent = acc;
}

/* ---------------- tasks table ---------------- */
function filteredProblems() {
  const q = state.filter.q.trim().toLowerCase();
  return state.problems.filter((p) => {
    if (state.filter.diff && (p.difficulty || "") !== state.filter.diff) return false;
    if (state.filter.tag && !(p.tags || []).includes(state.filter.tag)) return false;
    if (q && !(`${p.id} ${p.title}`.toLowerCase().includes(q))) return false;
    return true;
  });
}

function renderTasksTable() {
  const list = filteredProblems();
  $("filter-count").textContent = `${list.length}/${state.problems.length} ข้อ`;
  const tb = $("tasks-body");
  tb.innerHTML = "";
  $("tasks-empty").classList.toggle("hidden", list.length > 0);
  if (!state.problems.length) {
    $("tasks-empty").textContent = "ยังไม่มีโจทย์ — ส่งไฟล์ PDF มาเพื่อสร้างข้อใหม่";
    $("tasks-empty").classList.remove("hidden");
    return;
  }
  list.forEach((p) => {
    const best = (state.stats[p.id] && state.stats[p.id].best != null)
      ? `${state.stats[p.id].best}/100` : "—";
    const tags = (p.tags || []).map((t) => `<span class="tag-chip">${esc(t)}</span>`).join("");
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><strong>${esc(p.id)}</strong></td><td>${esc(p.title)}</td>
      <td>${diffBadge(p.difficulty)}</td><td>${tags || '<span class="dim">—</span>'}</td>
      <td>${p.tests}</td><td>${esc(String(best))}</td>`;
    tr.onclick = () => { location.hash = "#/task/" + encodeURIComponent(p.id); };
    tb.appendChild(tr);
  });
}

/* ---------------- task detail ---------------- */
async function selectProblem(pid) {
  state.current = pid;
  setTaskTab("statement");
  $("task-title").textContent = "Loading...";
  $("task-body").textContent = "Loading problem...";
  $("result-body").innerHTML = `<span class="dim">ส่งโค้ดแล้วผลจะขึ้นตรงนี้</span>`;
  $("score-line").textContent = "";
  $("your-score-num").textContent = "—";
  try {
    const p = await apiGet(`/api/problems/${encodeURIComponent(pid)}`);
    $("task-title").textContent = `${p.id} — ${p.title}`;
    const extra = [p.difficulty, ...((p.tags || []))].filter(Boolean).join(" · ");
    $("task-meta").textContent =
      `TL ${p.time_limit}s | MEM ${p.memory_limit}MB | checker ${p.checker} | ${p.tests} tests` +
      (extra ? ` | ${extra}` : "");
    $("task-body").innerHTML = renderMd(p.statement || "(no statement)");
    const pl = $("pdf-link");
    if (p.has_pdf) {
      pl.classList.remove("hidden");
      $("pdf-anchor").href = `${API}/api/problems/${encodeURIComponent(pid)}/pdf`;
    } else {
      pl.classList.add("hidden");
    }
    refreshYourScore();
  } catch (e) {
    $("task-body").textContent = "โหลดโจทย์ไม่สำเร็จ: " + e.message;
  }
}

async function refreshYourScore() {
  if (!state.current || !state.user) {
    $("your-score-num").textContent = state.user ? "0" : "—";
    return;
  }
  try {
    const h = await apiGet(`/api/history?limit=100&problem=${encodeURIComponent(state.current)}&mine=1`);
    const rows = (h.configured && h.submissions) || [];
    const best = rows.reduce((m, r) => Math.max(m, r.score || 0), 0);
    $("your-score-num").textContent = rows.length ? `${best}/100` : "0";
  } catch (e) {
    $("your-score-num").textContent = "?";
  }
}

async function loadTaskSubs() {
  const body = $("task-all-body");
  if (!state.current) return;
  body.innerHTML = `<span class="dim">กำลังโหลด...</span>`;
  try {
    const h = await apiGet(`/api/history?limit=50&problem=${encodeURIComponent(state.current)}`);
    if (!h.configured) {
      body.innerHTML = `<span class="dim">ยังไม่เปิด submissions (ตั้งค่า Supabase ที่ backend)</span>`;
      return;
    }
    const rows = h.submissions || [];
    if (!rows.length) {
      body.innerHTML = `<span class="dim">ข้อนี้ยังไม่มีใครส่ง — เป็นคนแรกเลย</span>`;
      return;
    }
    body.classList.remove("dim");
    body.innerHTML = historyTable(rows, false);
    bindViewButtons(body);
  } catch (e) {
    body.innerHTML = `<span class="dim">ดูไม่ได้: ${esc(e.message)}</span>`;
  }
}

async function loadTaskMine() {
  const body = $("task-mine-body");
  if (!state.current) return;
  if (!state.user) {
    body.innerHTML = `<span class="dim">login ด้วย Google ก่อนดูของตัวเอง</span>`;
    return;
  }
  body.innerHTML = `<span class="dim">กำลังโหลด...</span>`;
  try {
    const h = await apiGet(`/api/history?limit=100&problem=${encodeURIComponent(state.current)}&mine=1`);
    const rows = (h.configured && h.submissions) || [];
    if (!rows.length) {
      body.innerHTML = `<span class="dim">ยังไม่เคยส่งข้อนี้ — ไปแท็บ Submit เลย</span>`;
      return;
    }
    body.classList.remove("dim");
    body.innerHTML = historyTable(rows, false);
    bindViewButtons(body);
  } catch (e) {
    body.innerHTML = `<span class="dim">ดูไม่ได้: ${esc(e.message)}</span>`;
  }
}

/* ---------------- auth ---------------- */
async function refreshMe() {
  try {
    const me = await apiGet("/api/auth/me");
    state.user = (me && me.user) || null;
  } catch (e) {
    state.user = null;
  }
  $("login-btn").classList.toggle("hidden", !!state.user);
  $("logout-btn").classList.toggle("hidden", !state.user);
  const chip = $("user-chip");
  chip.classList.toggle("hidden", !state.user);
  if (state.user) {
    chip.textContent = state.user.name || state.user.email;
    chip.title = state.user.email || "";
  }
}

$("login-btn").onclick = () => {
  location.href = API + "/api/auth/login";
};

$("logout-btn").onclick = async () => {
  try {
    await fetch(API + "/api/auth/logout", { method: "POST", credentials: "include" });
  } catch (e) { /* ignore */ }
  await refreshMe();
  loadHistory();
};

/* ---------------- language + file ---------------- */
document.querySelectorAll(".lang-btn").forEach((b) => {
  b.onclick = () => {
    state.lang = b.dataset.lang;
    document.querySelectorAll(".lang-btn").forEach((x) =>
      x.classList.toggle("active", x === b)
    );
  };
});

const dz = $("dropzone");
const fi = $("file-input");
dz.onclick = () => fi.click();
["dragover", "dragenter"].forEach((ev) =>
  dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); })
);
["dragleave", "drop"].forEach((ev) =>
  dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); })
);
dz.addEventListener("drop", (e) => {
  if (e.dataTransfer.files.length) setFile(e.dataTransfer.files[0]);
});
fi.onchange = () => { if (fi.files.length) setFile(fi.files[0]); };

function setFile(f) {
  state.file = f;
  $("file-name").textContent = `${f.name} (${f.size} bytes)`;
  $("file-chip").classList.remove("hidden");
}

$("file-clear").onclick = () => {
  state.file = null;
  fi.value = "";
  $("file-chip").classList.add("hidden");
};

$("file-load").onclick = async () => {
  if (!state.file) return;
  $("editor").value = await state.file.text();
  $("submit-status").textContent = "โหลดเนื้อหาไฟล์ลง editor แล้ว";
};

$("template-btn").onclick = () => {
  const t = (TEMPLATES[state.current] || {})[state.lang];
  if (t) {
    $("editor").value = t;
    $("submit-status").textContent = `โหลด template แล้ว (${state.current} / ${state.lang})`;
  } else {
    $("submit-status").textContent = "ข้อนี้ยังไม่มี template";
  }
};

/* ---------------- submit + verdict ---------------- */
$("submit-btn").onclick = async () => {
  if (!state.current) return;
  const btn = $("submit-btn");
  const code = $("editor").value;
  if (!state.user) {
    $("submit-status").textContent = "login ด้วย Google ก่อนส่ง";
    return;
  }
  if (!state.file && !code.trim()) {
    $("submit-status").textContent = "วางโค้ดหรือแนบไฟล์ก่อนส่ง";
    return;
  }
  const fd = new FormData();
  fd.append("problem", state.current);
  fd.append("language", state.lang);
  fd.append("code", code);
  fd.append("name", state.user.name || "");
  if (state.file) fd.append("file", state.file, state.file.name);

  btn.disabled = true;
  $("submit-status").textContent = `กำลังตรวจ ${state.current} (${state.lang})...`;
  $("result-body").innerHTML = `<span class="dim">กำลังรัน — ใช้ limit โหดทุกข้อ...</span>`;
  const t0 = performance.now();
  try {
    const r = await fetch(API + "/api/submit", { method: "POST", body: fd, credentials: "include" });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    renderResults(data, (performance.now() - t0) / 1000);
    $("submit-status").textContent =
      `เสร็จใน ${((performance.now() - t0) / 1000).toFixed(2)}s — ${data.score}/100 คะแนน`;
    await fetchStats();
    renderTasksTable();
    refreshYourScore();
    if (state.taskTab === "subs") loadTaskSubs();
    if (state.taskTab === "mine") loadTaskMine();
    if (document.querySelector("#view-history.active")) loadHistory();
  } catch (e) {
    $("result-body").innerHTML = `<span class="score-big bad">ส่งไม่สำเร็จ</span><pre class="dim">${esc(e.message)}</pre>`;
    $("submit-status").textContent = "error: " + e.message;
  } finally {
    btn.disabled = false;
  }
};

function badgeVerdict(v) {
  return badge(v, v);
}

function renderResults(d, secs) {
  $("score-line").textContent =
    `${d.passed}/${d.total} — ${d.score}/100 — ${secs.toFixed(2)}s`;
  let html = "";
  if (d.verdict === "CE") {
    html += `<div class="score-big bad">COMPILE ERROR</div>`;
    html += `<div class="detail-cell"><pre>${esc(d.compile_error || "(no message)")}</pre></div>`;
  } else {
    const ok = d.accepted;
    html += `<div class="score-big ${ok ? "ok" : "bad"}">${ok ? "ACCEPTED" : "REJECTED"}</div>`;
    if (d.author || d.language) {
      html += `<div class="meta">by ${esc(d.author || "—")} · ${esc(d.language || "")}${d.filename ? ` · ${esc(d.filename)}` : ""}</div>`;
    }
    const counts = Object.entries(d.counts || {})
      .map(([k, n]) => `${esc(k)}:${n}`).join("  ");
    html += `<div class="meta">${esc(counts)} &nbsp;|&nbsp; TL ${esc(String(d.limits.time_s))}s MEM ${esc(String(d.limits.memory_mb))}MB checker ${esc(d.checker)}</div>`;
    if (d.build_warnings) {
      html += `<div class="detail-cell"><p class="dim">build warnings:</p><pre>${esc(d.build_warnings)}</pre></div>`;
    }
    html += `<table class="tests"><thead><tr>
      <th>#</th><th>test</th><th>verdict</th><th>wall</th><th>cpu</th><th>peak</th>
    </tr></thead><tbody>`;
    (d.results || []).forEach((r, i) => {
      html += `<tr class="test-row" data-i="${i}">
        <td>${String(i + 1).padStart(2, "0")}</td><td>${esc(r.test)}</td>
        <td>${badgeVerdict(r.verdict)}</td><td>${r.wall_s}s</td><td>${r.cpu_s}s</td><td>${r.peak_mb}MB</td>
      </tr>`;
      html += `<tr class="detail-row hidden" data-i="${i}"><td colspan="6" class="detail-cell">${detailHtml(r)}</td></tr>`;
    });
    html += `</tbody></table>`;
  }
  if (d.code) {
    html += `<details class="code-view"><summary>ดูโค้ดที่ส่ง (${esc(String(d.code).split("\n").length)} บรรทัด)</summary><pre>${esc(d.code)}</pre></details>`;
  }
  const body = $("result-body");
  body.classList.remove("dim");
  body.innerHTML = html;
  body.querySelectorAll("tr.test-row").forEach((tr) => {
    tr.onclick = () => {
      const det = body.querySelector(`tr.detail-row[data-i="${tr.dataset.i}"]`);
      if (det) det.classList.toggle("hidden");
    };
  });
}

function detailHtml(r) {
  if (r.verdict === "AC") return `<span class="dim">ผ่าน — คลิกแถวเพื่อย่อ</span>`;
  if (r.verdict === "TLE")
    return `<span class="dim">Time Limit Exceeded (wall ${esc(String(r.wall_s))}s). Hint: O(n^2) จะไม่รอด test ใหญ่สุด</span>`;
  if (r.verdict === "MLE")
    return `<pre>${esc(r.detail || "Memory Limit Exceeded")}</pre>`;
  if (r.verdict === "OLE")
    return `<span class="dim">Output Limit Exceeded (${esc(r.detail || "")}) — print loop รึเปล่า?</span>`;
  if (r.verdict === "WA") {
    return `<p><strong>diff (·=space, →=tab):</strong></p><pre>${esc(r.diff || "")}</pre>
      <p><strong>input:</strong></p><pre>${esc(r.input || "")}</pre>
      <p><strong>expected:</strong></p><pre>${esc(r.expected || "")}</pre>
      <p><strong>actual:</strong></p><pre>${esc(r.actual || "")}</pre>`;
  }
  return `<pre>${esc(r.detail || r.verdict)}</pre>`;
}

/* ---------------- history ---------------- */
function historyTable(rows, showProblem) {
  let html = `<table class="tests"><thead><tr>
    <th>เวลา</th>${showProblem ? "<th>ข้อ</th>" : ""}<th>ชื่อ</th><th>ภาษา</th><th>ผล</th><th>คะแนน</th><th></th>
  </tr></thead><tbody>`;
  rows.forEach((r) => {
    const when = new Date(r.created_at).toLocaleString();
    const cls = r.accepted ? "AC" : (r.verdict === "CE" ? "CE" : "WA");
    const label = r.accepted ? "AC" : (r.verdict || "REJECTED");
    html += `<tr>
      <td>${esc(when)}</td>${showProblem ? `<td>${esc(r.problem)}</td>` : ""}<td>${esc(r.name || "—")}</td><td>${esc(r.language)}</td>
      <td>${badge(label, cls)}</td><td>${r.passed}/${r.total} (${r.score})</td>
      <td><button class="ghost-btn" data-view="${esc(r.id)}">ดูผล</button></td>
    </tr>`;
  });
  return html + `</tbody></table>`;
}

function bindViewButtons(root) {
  root.querySelectorAll("button[data-view]").forEach((b) => {
    b.onclick = () => viewSubmission(b.dataset.view);
  });
}

async function loadHistory() {
  const body = $("hist-body");
  const filt = $("hist-filter").value;
  const mine = $("hist-mine").checked;
  if (mine && !state.user) {
    body.innerHTML = `<span class="dim">ติ๊ก "ของฉัน" ต้อง login ก่อน</span>`;
    return;
  }
  try {
    const [h, s] = await Promise.all([
      apiGet(`/api/history?limit=20${filt ? `&problem=${encodeURIComponent(filt)}` : ""}${mine ? "&mine=1" : ""}`),
      apiGet("/api/stats"),
    ]);
    if (!h.configured) {
      body.innerHTML = `<span class="dim">ยังไม่เปิด history — ตั้งค่า SUPABASE_URL / SUPABASE_KEY ที่ backend (schema ใน supabase/schema.sql)</span>`;
      $("hist-stats").textContent = "";
      return;
    }
    const stats = Object.entries(s.stats || {})
      .map(([k, v]) => `${esc(k)}: ส่ง ${v.subs} ครั้ง, ผ่าน ${v.accepted}, ดีสุด ${v.best}`)
      .join(" &nbsp;|&nbsp; ");
    $("hist-stats").innerHTML = stats || "ยังไม่มีข้อมูล";
    const rows = h.submissions || [];
    if (!rows.length) {
      body.innerHTML = `<span class="dim">ยังไม่มีการส่ง</span>`;
      return;
    }
    body.classList.remove("dim");
    body.innerHTML = historyTable(rows, true);
    bindViewButtons(body);
  } catch (e) {
    body.innerHTML = `<span class="dim">ดูประวัติไม่ได้: ${esc(e.message)}</span>`;
  }
}

async function viewSubmission(sid) {
  try {
    const r = await apiGet(`/api/history/${encodeURIComponent(sid)}`);
    if (r.problem !== state.current) {
      location.hash = "#/task/" + encodeURIComponent(r.problem);
      await selectProblem(r.problem);
    }
    show("task");
    setTaskTab("submit");
    renderResults({
      verdict: r.verdict, accepted: r.accepted,
      passed: r.passed, total: r.total, score: r.score,
      counts: r.counts || {}, build_warnings: "",
      compile_error: r.detail || "",
      limits: { time_s: "-", memory_mb: "-" }, checker: "-",
      results: r.results || [],
      code: r.code || "", filename: r.filename || "", language: r.language || "",
      author: r.name || "",
    }, 0);
    document.querySelector("#pane-submit").scrollIntoView({ behavior: "smooth" });
  } catch (e) {
    $("submit-status").textContent = "เปิด submission ไม่ได้: " + e.message;
  }
}

/* ---------------- init ---------------- */
async function init() {
  try {
    const h = await apiGet("/api/health");
    $("health").textContent = `online - ${h.problems.length} ข้อ`;
    $("health").classList.add("ok");
  } catch (e) {
    $("health").textContent = "offline";
    show("home");
    document.querySelector("#view-home .hero .lede").textContent =
      "เชื่อมต่อ server ไม่ได้: " + e.message + " — ตั้งค่า config.js ให้ชี้ไป backend";
    return;
  }
  const data = await apiGet("/api/problems");
  state.problems = data.problems;
  await fetchStats();

  const diffs = [...new Set(state.problems.map((p) => p.difficulty).filter(Boolean))].sort();
  const tags = [...new Set(state.problems.flatMap((p) => p.tags || []))].sort();
  const fd = $("f-diff"), ft = $("f-tag");
  diffs.forEach((d) => {
    const o = document.createElement("option");
    o.value = d; o.textContent = d;
    fd.appendChild(o);
  });
  tags.forEach((t) => {
    const o = document.createElement("option");
    o.value = t; o.textContent = t;
    ft.appendChild(o);
  });
  $("q").oninput = (e) => { state.filter.q = e.target.value; renderTasksTable(); };
  fd.onchange = (e) => { state.filter.diff = e.target.value; renderTasksTable(); };
  ft.onchange = (e) => { state.filter.tag = e.target.value; renderTasksTable(); };

  const hf = $("hist-filter");
  state.problems.forEach((p) => {
    const o = document.createElement("option");
    o.value = p.id;
    o.textContent = `${p.id} — ${p.title}`;
    hf.appendChild(o);
  });
  hf.onchange = loadHistory;
  $("hist-refresh").onclick = loadHistory;
  $("hist-mine").onchange = loadHistory;
  await refreshMe();
  if ((location.hash || "").includes("login=failed")) {
    $("health").textContent = "login failed";
    location.hash = "#/";
  }

  router();
}

init();
