const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function session() {
  const storage = new Map([['token', 'legacy-token'], ['user_groups', 'legacy-user']]);
  const events = new EventTarget();
  const instances = [];
  class Keycloak {
    authenticated = true;
    token = 'memory-only-token';
    calls = [];
    constructor(options) { this.options = options; instances.push(this); }
    async init(options) { this.calls.push(['init', options]); return true; }
    async updateToken(seconds) { this.calls.push(['refresh', seconds]); if (this.failRefresh) throw new Error('Session expired'); return false; }
    async register(options) { this.calls.push(['register', options]); }
    async login(options) { this.calls.push(['login', options]); }
    async logout(options) { this.calls.push(['logout', options]); }
    clearToken() { this.authenticated = false; this.token = undefined; this.onAuthLogout?.(); }
  }
  const module = { exports: {} };
  const source = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src/services/auth-session.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, esModuleInterop: true },
  }).outputText;
  vm.runInNewContext(source, {
    module, exports: module.exports, require: (name) => { assert.equal(name, 'keycloak-js'); return Keycloak; }, Event,
    document: { cookie: "" },
    window: { location: { origin: 'https://cas.chirocity.gov.et' }, dispatchEvent: events.dispatchEvent.bind(events) },
    localStorage: { getItem: k => storage.get(k), removeItem: k => storage.delete(k) },
  });
  return { auth: module.exports, instances, storage, events };
}
const settings = { mode: 'keycloak', url: 'https://auth.chirocity.gov.et', realm: 'chirocity', clientId: 'cas-web' };

test('SSO initialization is shared, requires PKCE and removes legacy persisted credentials', async () => {
  const { auth, instances, storage } = session();
  auth.configureAuth(settings); auth.configureAuth(settings);
  await Promise.all([auth.initializeSso(), auth.initializeSso()]);
  assert.equal(instances.length, 1);
  const calls = instances[0].calls.filter(c => c[0] === 'init');
  assert.equal(calls.length, 1);
  assert.equal(calls[0][1].pkceMethod, 'S256');
  assert.equal(calls[0][1].flow, 'standard');
  assert.equal(calls[0][1].onLoad, 'check-sso');
  assert.equal(storage.size, 0);
});

test('normal app entry requires Keycloak login directly with the same PKCE callback', async () => {
  const {auth,instances}=session();auth.configureAuth(settings);
  await auth.initializeSso({requireLogin:true});
  const options=instances[0].calls.find(c=>c[0]==='init')[1];
  assert.equal(options.onLoad,'login-required');
  assert.equal(options.pkceMethod,'S256');
  assert.equal(options.flow,'standard');
  assert.equal(options.redirectUri,'https://cas.chirocity.gov.et/login');
});

test('a newly registered applicant opens central login with their email and a fresh login prompt', async () => {
  const {auth,instances}=session();auth.configureAuth(settings);
  await auth.signIn({loginHint:'applicant@example.invalid',prompt:'login'});
  const options=instances[0].calls.find(call=>call[0]==='login')[1];
  assert.equal(options.redirectUri,'https://cas.chirocity.gov.et/login');
  assert.equal(options.loginHint,'applicant@example.invalid');
  assert.equal(options.prompt,'login');
});

test('public applicant registration does not redirect its session check to the login callback', async () => {
  const {auth,instances}=session();auth.configureAuth(settings);
  await auth.initializeSso({requireLogin:false,skipSessionCheck:true});
  assert.equal(instances[0].calls.find(c=>c[0]==='init')[1].onLoad,undefined);
  await auth.signUp();
  assert.ok(instances[0].calls.some(c=>c[0]==='register'));
});
test('API requests refresh the in-memory token without persisting it', async () => {
  const { auth, instances, storage } = session(); auth.configureAuth(settings);
  assert.equal(await auth.accessToken(), 'memory-only-token');
  assert.equal(instances[0].calls[0][0], 'refresh');
  assert.equal(instances[0].calls[0][1], 30);
  assert.equal(storage.size, 0);
});
test('expired sessions clear credentials and notify the application', async () => {
  const { auth, instances, storage, events } = session(); auth.configureAuth(settings);
  let ended = false; events.addEventListener('cas:session-ended', () => { ended = true; });
  instances[0].failRefresh = true;
  await assert.rejects(auth.accessToken(), /Session expired/);
  assert.equal(ended, true);
  assert.equal(instances[0].token, undefined);
  assert.equal(await auth.accessToken(), undefined);
  assert.equal(storage.size, 0);
});
test('login and shared logout use the exact configured return URI', async () => {
  const { auth, instances } = session(); auth.configureAuth(settings);
  await auth.signIn(); await auth.signOut();
  for (const [name, options] of instances[0].calls) {
    assert.ok(['login', 'logout'].includes(name));
    assert.equal(options.redirectUri, 'https://cas.chirocity.gov.et/login');
  }
});
test('refresh success notifies the app to re-fetch its roles', async () => {
  const { auth, instances, events } = session(); auth.configureAuth(settings); await auth.initializeSso();
  let refreshed = false; events.addEventListener('cas:token-refreshed', () => { refreshed = true; });
  instances[0].onAuthRefreshSuccess(); assert.equal(refreshed, true);
});
test('local mode retains compatibility and clears credentials on logout', async () => {
  const { auth, storage } = session(); auth.configureAuth({ ...settings, mode: 'local' });
  assert.equal(await auth.accessToken(), 'legacy-token');
  await auth.signOut(); assert.equal(storage.size, 0);
});

test('applicant registration uses the central registration flow and returns to CAS login', async () => {
  const { auth, instances } = session(); auth.configureAuth(settings);
  await auth.signUp();
  assert.equal(instances[0].calls[0][0], 'register');
  assert.equal(instances[0].calls[0][1].redirectUri, 'https://cas.chirocity.gov.et/login');
});
