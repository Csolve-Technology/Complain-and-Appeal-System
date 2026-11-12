const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const ts=require('typescript');
const auth=['src/services/auth-session.ts','src/services/chiroAuth.ts'].find(p=>fs.existsSync(p));
const text=fs.readFileSync(auth,'utf8');
const helper=text.slice(text.indexOf('function configureDashboardBroker('));
assert(helper.startsWith('function configureDashboardBroker('));
function client(search){
 const calls=[];
 const original={login:async function(options){assert.equal(this,original);calls.push(options);},logout:async()=>{},register:async()=>{}};
 const originalLogin=original.login, originalLogout=original.logout, originalRegister=original.register;
 const exports={};
 const code=ts.transpileModule(helper+'\nexport { configureDashboardBroker };',{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
 vm.runInNewContext(code,{exports,window:{location:{search}},URLSearchParams});
 exports.configureDashboardBroker(original);
 return {original,calls,originalLogin,originalLogout,originalRegister};
}
test('ordinary app entry preserves its normal login',async()=>{const c=client('');await c.original.login({redirectUri:'https://app.invalid/login'});assert.equal(c.original.login,c.originalLogin);assert.equal(c.calls[0].idpHint,undefined);});
test('unknown or arbitrary providers cannot be selected through the launch parameter',()=>{for(const search of ['?chiro_idp=evil','?idpHint=evil','?chiro_idp=https://evil.invalid']){const c=client(search);assert.equal(c.original.login,c.originalLogin);}});
test('dashboard entry selects only dashboard-sso and forces fresh target-realm authentication',async()=>{const c=client('?chiro_idp=dashboard-sso');await c.original.login({redirectUri:'https://app.invalid/login',idpHint:'wrong',scope:'openid profile email'});assert.equal(c.calls.length,1);assert.equal(c.calls[0].idpHint,'dashboard-sso');assert.equal(c.calls[0].prompt,'login');assert.equal(c.calls[0].redirectUri,'https://app.invalid/login');assert.equal(c.calls[0].scope,'openid profile email');});
test('dashboard routing leaves registration and logout unchanged',()=>{const c=client('?chiro_idp=dashboard-sso');assert.equal(c.original.logout,c.originalLogout);assert.equal(c.original.register,c.originalRegister);});
test('every new adapter receives the broker hook before initialization',()=>{const constructor=text.indexOf('new Keycloak(');const hook=text.indexOf('configureDashboardBroker(',constructor);const init=text.indexOf('.init(',constructor);assert(constructor>=0&&hook>constructor&&init>hook);});
