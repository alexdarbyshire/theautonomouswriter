const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../site/content/suggest.md'), 'utf8');
const script = source.match(/<script>([\s\S]*?)<\/script>/)[1];
const draftKey = 'autonomous-writer-suggestion-draft';
const settle = () => new Promise(resolve => setImmediate(resolve));

function loadPage({ storage = new Map(), authenticated = false, submit } = {}) {
  const ids = [...source.matchAll(/id="([^"]+)"/g)].map(match => match[1]);
  const elements = Object.fromEntries(ids.map(id => [id, {
    value: '', textContent: '', innerHTML: '', disabled: id === 'submit-btn',
    style: {}, listeners: {},
    addEventListener(event, listener) { this.listeners[event] = listener; },
  }]));
  const requests = [];
  const sessionStorage = {
    getItem(key) { return storage.get(key) ?? null; },
    setItem(key, value) { storage.set(key, value); },
    removeItem(key) { storage.delete(key); },
  };
  vm.runInNewContext(script, {
    document: { getElementById: id => elements[id] }, sessionStorage,
    fetch(url, options) {
      requests.push({ url, options });
      if (url === '/.auth/me') {
        return Promise.resolve({ json: () => Promise.resolve({ clientPrincipal: authenticated ? {} : null }) });
      }
      return submit ? submit() : Promise.resolve({ status: 200, json: () => Promise.resolve({ ok: true, message: 'Received' }) });
    },
  });
  return {
    elements, requests, storage,
    input(value) {
      elements['suggestion-text'].value = value;
      elements['suggestion-text'].listeners.input();
    },
    click() { elements['submit-btn'].listeners.click(); },
  };
}

test('draft survives sign-in return without automatic submission', async () => {
  const first = loadPage();
  first.input('Dreams and the clues they leave behind');
  first.click();
  assert.equal(first.elements['auth-nudge'].style.display, 'block');
  const returned = loadPage({ storage: first.storage, authenticated: true });
  await settle();
  assert.equal(returned.elements['suggestion-text'].value, 'Dreams and the clues they leave behind');
  assert.equal(returned.elements['char-count'].textContent, '38 / 300');
  assert.equal(returned.elements['submit-btn'].disabled, false);
  assert.equal(returned.requests.filter(request => request.url === '/api/suggest').length, 0);
});

test('successful submission clears the draft from the page and storage', async () => {
  const page = loadPage({ authenticated: true });
  await settle();
  page.input('Dreams and the clues they leave behind');
  page.click();
  await settle();
  assert.equal(page.elements['suggestion-text'].value, '');
  assert.equal(page.elements['char-count'].textContent, '0 / 300');
  assert.equal(page.elements['submit-btn'].disabled, true);
  assert.equal(page.storage.has(draftKey), false);
});

test('blocked storage warns before sign-in and does not break the form', async () => {
  const storage = { get() { throw Error('blocked'); }, set() { throw Error('blocked'); }, delete() { throw Error('blocked'); } };
  const page = loadPage({ storage });
  page.input('A suggestion worth keeping');
  assert.equal(page.elements['submit-btn'].disabled, false);
  page.click();
  assert.equal(page.elements['draft-warning'].style.display, 'block');
  assert.equal(page.elements['auth-nudge'].style.display, 'block');
});

test('a later edit survives an earlier submission succeeding', async () => {
  let complete;
  const page = loadPage({ authenticated: true, submit: () => new Promise(resolve => { complete = resolve; }) });
  await settle();
  page.input('The first suggestion');
  page.click();
  page.input('The next suggestion');
  assert.equal(page.elements['submit-btn'].disabled, true);
  complete({ status: 200, json: () => Promise.resolve({ ok: true, message: 'Received' }) });
  await settle();
  assert.equal(page.elements['suggestion-text'].value, 'The next suggestion');
  assert.equal(page.storage.get(draftKey), 'The next suggestion');
  assert.equal(page.elements['submit-btn'].disabled, false);
});

test('reload and cancelled sign-in keep the draft available', () => {
  const page = loadPage();
  page.input('A draft before cancelled sign-in');
  page.click();
  const returned = loadPage({ storage: page.storage });
  assert.equal(returned.elements['suggestion-text'].value, 'A draft before cancelled sign-in');
  returned.click();
  assert.equal(returned.elements['auth-nudge'].style.display, 'block');
});

test('deleting the text removes the saved draft and disables submission', () => {
  const page = loadPage();
  page.input('A draft to discard');
  page.input('');
  assert.equal(page.storage.has(draftKey), false);
  assert.equal(page.elements['char-count'].textContent, '0 / 300');
  assert.equal(page.elements['submit-btn'].disabled, true);
});

for (const [name, submit] of [
  ['API rejection', () => Promise.resolve({ status: 429, json: () => Promise.resolve({ ok: false, message: 'Try later' }) })],
  ['network failure', () => Promise.reject(Error('offline'))],
  ['expired sign-in returning HTML', () => Promise.resolve({ status: 200, json: () => Promise.reject(Error('HTML response')) })],
]) {
  test(`${name} preserves the draft for retry`, async () => {
    const page = loadPage({ authenticated: true, submit });
    await settle();
    page.input('A draft to retry later');
    page.click();
    await settle();
    assert.equal(page.elements['suggestion-text'].value, 'A draft to retry later');
    assert.equal(page.storage.get(draftKey), 'A draft to retry later');
    assert.equal(page.elements['submit-btn'].disabled, false);
  });
}

test('storage failure does not prevent an authenticated submission', async () => {
  const storage = { get() { throw Error('blocked'); }, set() { throw Error('blocked'); }, delete() { throw Error('blocked'); } };
  const page = loadPage({ storage, authenticated: true });
  await settle();
  page.input('A suggestion without storage');
  page.click();
  await settle();
  assert.equal(page.elements['suggestion-text'].value, '');
  assert.equal(page.elements['submit-btn'].disabled, true);
  assert.equal(page.requests.filter(request => request.url === '/api/suggest').length, 1);
});
