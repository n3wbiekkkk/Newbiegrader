const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../static/legal.js'), 'utf8');

function page({ saved = null, dark = false, narrow = false, storageBlocked = false, hash = '' } = {}) {
  const events = new Map();
  const buttonEvents = new Map();
  const properties = new Map();
  const questions = new Map([
    ['queue', { tagName: 'DETAILS', open: true }],
    ['account-data', { tagName: 'DETAILS', open: false }],
    ['contact', { tagName: 'SECTION' }],
  ]);
  const attributes = new Map();
  const button = {
    textContent: 'icon content',
    setAttribute: (name, value) => attributes.set(name, value),
    getAttribute: name => attributes.get(name),
    addEventListener: (name, callback) => buttonEvents.set(name, callback),
  };
  const header = { height: 63.2, getBoundingClientRect() { return { height: this.height }; } };
  const contents = { open: true };
  const root = { dataset: {}, style: { setProperty: (name, value) => properties.set(name, value) } };
  const location = { hash };
  let resize;
  let stored = saved;
  const context = {
    matchMedia: query => ({ matches: query.includes('max-width') ? narrow : dark }), location,
    localStorage: {
      getItem() { if (storageBlocked) throw new Error('Unavailable'); return stored; },
      setItem(key, value) { if (storageBlocked) throw new Error('Unavailable'); stored = value; },
    },
    document: {
      documentElement: root,
      getElementById: id => id === 'legal-theme' ? button : questions.get(id),
      querySelector: selector => selector === '.legal-topbar' ? header : contents,
      querySelectorAll: () => [...questions.values()].filter(item => item.tagName === 'DETAILS'),
      addEventListener: (name, callback) => events.set(name, callback),
    },
    window: { addEventListener: (name, callback) => events.set(name, callback) },
    ResizeObserver: class { constructor(callback) { resize = callback; } observe() {} },
  };
  vm.runInNewContext(source, context);
  events.get('DOMContentLoaded')();
  return { root, button, header, contents, properties, questions, location,
    event: name => events.get(name)(), toggle: () => buttonEvents.get('click')(),
    resize: () => resize(), saved: () => stored };
}

test('invalid saved theme falls back to the system preference', () => {
  const p = page({ saved: 'unexpected-value', dark: true });
  assert.equal(p.root.dataset.theme, 'dark');
  assert.equal(p.button.getAttribute('aria-label'), 'ใช้ธีมสว่าง');
  assert.equal(p.button.title, 'ใช้ธีมสว่าง');
  assert.equal(p.button.textContent, 'icon content');
});

test('theme toggling remains usable when browser storage is blocked', () => {
  const p = page({ storageBlocked: true });
  p.toggle();
  assert.equal(p.root.dataset.theme, 'dark');
  assert.equal(p.button.getAttribute('aria-label'), 'ใช้ธีมสว่าง');
  p.toggle();
  assert.equal(p.root.dataset.theme, 'light');
});

test('saved theme is respected and a new selection persists', () => {
  const p = page({ saved: 'light', dark: true });
  assert.equal(p.root.dataset.theme, 'light');
  p.toggle();
  assert.equal(p.saved(), 'dark');
});

test('anchor offset follows a header that wraps to multiple lines', () => {
  const p = page();
  assert.equal(p.properties.get('--legal-header-height'), '64px');
  p.header.height = 132.4;
  p.resize();
  assert.equal(p.properties.get('--legal-header-height'), '133px');
});

test('mobile contents starts collapsed without overriding a later reader choice', () => {
  const mobile = page({ narrow: true });
  assert.equal(mobile.contents.open, false);
  mobile.contents.open = true;
  mobile.resize();
  assert.equal(mobile.contents.open, true);
  assert.equal(page().contents.open, true);
});

test('direct FAQ links and later hash changes reveal the matching answer', () => {
  const p = page({ hash: '#account%2Ddata' });
  assert.equal(p.questions.get('account-data').open, true);
  p.questions.get('queue').open = false;
  p.location.hash = '#queue';
  p.event('hashchange');
  assert.equal(p.questions.get('queue').open, true);
  p.location.hash = '#contact';
  p.event('hashchange');
  assert.equal('open' in p.questions.get('contact'), false);
  p.location.hash = '#%invalid';
  assert.doesNotThrow(() => p.event('hashchange'));
});

test('printing includes closed answers and restores the reader selection', () => {
  const p = page();
  p.event('beforeprint');
  assert.equal(p.questions.get('account-data').open, true);
  p.event('beforeprint');
  p.event('afterprint');
  assert.equal(p.questions.get('queue').open, true);
  assert.equal(p.questions.get('account-data').open, false);
  assert.doesNotThrow(() => p.event('afterprint'));
});
