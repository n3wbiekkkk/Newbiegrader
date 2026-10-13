/* Brutal Grader SPA — vanilla JS, no build step. */
"use strict";

const state = {
  problems: [],
  current: null,
  lang: "python",
  file: null,
};

const $ = (id) => document.getElementById(id);

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

/* ---------------- problems ---------------- */
/* Split-deploy support: static host + separate backend.
 * Set window.GRADER_API_BASE in config.js ("" = same origin). */
const API = (window.GRADER_API_BASE || "").replace(/\/$/, "");

async function apiGet(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(`GET ${path}: ${r.status}`);
  return r.json();
}

async function init() {
  try {
    const h = await apiGet("/api/health");
    $("health").textContent = `online - ${h.problems.length} problems`;
    $("health").classList.add("ok");
  } catch (e) {
    $("health").textContent = "offline";
    $("prob-body").textContent = "Cannot reach server: " + e.message;
    return;
  }
  const data = await apiGet("/api/problems");
  state.problems = data.problems;
  const tabs = $("problem-tabs");
  tabs.innerHTML = "";
  state.problems.forEach((p, i) => {
    const b = document.createElement("button");
    b.className = "tab" + (i === 0 ? " active" : "");
    b.textContent = p.id;
    b.title = p.title;
    b.onclick = () => selectProblem(p.id);
    tabs.appendChild(b);
  });
  if (state.problems.length) selectProblem(state.problems[0].id);
}

async function selectProblem(pid) {
  state.current = pid;
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.textContent === pid)
  );
  $("prob-title").textContent = "Loading...";
  $("prob-body").textContent = "Loading problem...";
  try {
    const p = await apiGet(`/api/problems/${encodeURIComponent(pid)}`);
    $("prob-title").textContent = `${p.id} - ${p.title}`;
    $("prob-meta").textContent =
      `TL ${p.time_limit}s | MEM ${p.memory_limit}MB | checker ${p.checker} | ${p.tests} tests`;
    $("prob-body").innerHTML = renderMd(p.statement || "(no statement)");
  } catch (e) {
    $("prob-body").textContent = "Failed to load problem: " + e.message;
  }
}

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
  $("submit-status").textContent = "file content loaded into editor";
};

$("template-btn").onclick = () => {
  const t = (TEMPLATES[state.current] || {})[state.lang];
  if (t) {
    $("editor").value = t;
    $("submit-status").textContent = `starter template loaded (${state.current} / ${state.lang})`;
  } else {
    $("submit-status").textContent = "no template for this problem/language";
  }
};

/* ---------------- submit + results ---------------- */
$("submit-btn").onclick = async () => {
  if (!state.current) return;
  const btn = $("submit-btn");
  const code = $("editor").value;
  if (!state.file && !code.trim()) {
    $("submit-status").textContent = "paste code or attach a file first";
    return;
  }
  const fd = new FormData();
  fd.append("problem", state.current);
  fd.append("language", state.lang);
  fd.append("code", code);
  if (state.file) fd.append("file", state.file, state.file.name);

  btn.disabled = true;
  $("submit-status").textContent = `judging ${state.current} (${state.lang})...`;
  $("result-body").innerHTML = `<span class="dim">running ${esc(state.current)} — strict limits apply...</span>`;
  const t0 = performance.now();
  try {
    const r = await fetch(API + "/api/submit", { method: "POST", body: fd });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    renderResults(data, (performance.now() - t0) / 1000);
    $("submit-status").textContent =
      `done in ${((performance.now() - t0) / 1000).toFixed(2)}s — score ${data.score}/100`;
  } catch (e) {
    $("result-body").innerHTML = `<span class="score-big bad">SUBMIT FAILED</span><pre class="dim">${esc(e.message)}</pre>`;
    $("submit-status").textContent = "error: " + e.message;
  } finally {
    btn.disabled = false;
  }
};

function badge(v) {
  return `<span class="badge b-${esc(v)}">${esc(v)}</span>`;
}

function renderResults(d, secs) {
  $("score-line").textContent =
    `${d.passed}/${d.total} - score ${d.score}/100 - ${secs.toFixed(2)}s`;
  let html = "";
  if (d.verdict === "CE") {
    html += `<div class="score-big bad">COMPILE ERROR</div>`;
    html += `<div class="detail-cell"><pre>${esc(d.compile_error || "(no message)")}</pre></div>`;
  } else {
    const ok = d.accepted;
    html += `<div class="score-big ${ok ? "ok" : "bad"}">${ok ? "ACCEPTED" : "REJECTED"}</div>`;
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
        <td>${badge(r.verdict)}</td><td>${r.wall_s}s</td><td>${r.cpu_s}s</td><td>${r.peak_mb}MB</td>
      </tr>`;
      html += `<tr class="detail-row hidden" data-i="${i}"><td colspan="6" class="detail-cell">${detailHtml(r)}</td></tr>`;
    });
    html += `</tbody></table>`;
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
  if (r.verdict === "AC") return `<span class="dim">passed — click row to collapse</span>`;
  if (r.verdict === "TLE")
    return `<span class="dim">Time Limit Exceeded (wall ${esc(String(r.wall_s))}s). Hint: O(n^2) will not survive the hidden max test.</span>`;
  if (r.verdict === "MLE")
    return `<pre>${esc(r.detail || "Memory Limit Exceeded")}</pre>`;
  if (r.verdict === "OLE")
    return `<span class="dim">Output Limit Exceeded (${esc(r.detail || "")}). Print loop?</span>`;
  if (r.verdict === "WA") {
    return `<p><strong>diff (·=space, →=tab):</strong></p><pre>${esc(r.diff || "")}</pre>
      <p><strong>input:</strong></p><pre>${esc(r.input || "")}</pre>
      <p><strong>expected:</strong></p><pre>${esc(r.expected || "")}</pre>
      <p><strong>actual:</strong></p><pre>${esc(r.actual || "")}</pre>`;
  }
  return `<pre>${esc(r.detail || r.verdict)}</pre>`;
}

init();
