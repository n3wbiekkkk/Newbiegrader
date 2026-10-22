/* Editor line-number gutter: the numbers must always match the code, because a
 * student who trusts them will look at line 12 for a bug that is on line 9.
 * Synthetic DOM only — no browser, no network. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8");
const html = fs.readFileSync(path.join(__dirname, "../static/index.html"), "utf8");

function harness() {
  const elements = new Map();
  const element = (id) => {
    if (!elements.has(id)) {
      elements.set(id, {
        id, value: "", textContent: "", innerHTML: "",
        selectionStart: 0, selectionEnd: 0, scrollTop: 0, dataset: {},
        classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
        addEventListener() {}, removeEventListener() {},
        setAttribute() {}, getAttribute: () => null, hasAttribute: () => false,
        removeAttribute() {}, querySelectorAll: () => [], querySelector: () => null,
        focus() {}, scrollIntoView() {},
      });
    }
    return elements.get(id);
  };
  const context = vm.createContext({
    document: { getElementById: element },
    $: element,
    state: { lang: "python" },
    saveDraft() {},
    setTimeout: () => 0,
    clearTimeout() {},
  });
  vm.runInContext(source.slice(source.indexOf("/* ---------------- editor keys"),
    source.indexOf("/* ---------------- task tabs")), context);
  return { context, element };
}

test("the gutter numbers every line of the editor", () => {
  const h = harness();
  h.context.setEditorValue("a\nb\nc\nd");
  assert.equal(h.element("editor-gutter").textContent, "1\n2\n3\n4");
});

test("an empty editor still shows line 1", () => {
  const h = harness();
  h.context.setEditorValue("");
  assert.equal(h.element("editor-gutter").textContent, "1");
});

test("a trailing newline does not invent an empty line number", () => {
  const h = harness();
  h.context.setEditorValue("a\n");
  assert.equal(h.element("editor-gutter").textContent, "1\n2");
});

test("the gutter scrolls with the editor", () => {
  const h = harness();
  h.context.setEditorValue("x\ny\nz");
  h.element("editor").scrollTop = 42;
  h.context.syncEditorGutter();
  assert.equal(h.element("editor-gutter").scrollTop, 42);
});

test("Tab indents without changing the line count", () => {
  const h = harness();
  const ed = h.element("editor");
  h.context.setEditorValue("a\nb");
  ed.selectionStart = ed.selectionEnd = 1;
  h.context.applyIndent(ed, false);
  assert.equal(ed.value, "a    \nb");
  assert.equal(h.element("editor-gutter").textContent, "1\n2");
});

test("Shift+Tab outdents and keeps the numbers", () => {
  const h = harness();
  const ed = h.element("editor");
  h.context.setEditorValue("    a\nb");
  ed.selectionStart = ed.selectionEnd = 4;
  h.context.applyIndent(ed, true);
  assert.equal(ed.value, "a\nb");
  assert.equal(h.element("editor-gutter").textContent, "1\n2");
});

test("Enter adds a line and the gutter grows with it", () => {
  const h = harness();
  const ed = h.element("editor");
  h.context.setEditorValue("a\nb");
  ed.selectionStart = ed.selectionEnd = 1;      // end of the first line
  h.context.newlineIndent(ed);
  assert.equal(ed.value, "a\n\nb");
  assert.equal(h.element("editor-gutter").textContent, "1\n2\n3");
});

test("Enter after a block opener indents the new line", () => {
  const h = harness();
  const ed = h.element("editor");
  h.context.setEditorValue("if x:");
  ed.selectionStart = ed.selectionEnd = 5;
  h.context.newlineIndent(ed);
  assert.equal(ed.value, "if x:\n    ");
  assert.equal(h.element("editor-gutter").textContent, "1\n2");
});

test("every write to the editor goes through setEditorValue", () => {
  // A programmatic write does not fire `input`, so a direct `editor.value = ...`
  // anywhere would leave the gutter stale.
  const direct = source.match(/\$\("editor"\)\.value\s*=/g) || [];
  assert.deepEqual(direct, [], "write the editor through setEditorValue() instead");
  assert.equal((source.match(/ed\.value\s*=/g) || []).length, 0,
    "write the editor through setEditorValue() instead");
});

test("the gutter is in the markup, beside the textarea and decorative", () => {
  assert.match(html, /id="editor-gutter"[^>]*aria-hidden="true"/);
  const gutter = html.indexOf('id="editor-gutter"');
  const editor = html.indexOf('id="editor"');
  assert.ok(gutter > -1 && editor > -1);
  assert.ok(gutter < editor, "the gutter sits before the textarea");
});
