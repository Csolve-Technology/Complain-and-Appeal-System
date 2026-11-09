const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const vm = require('node:vm');
const source = ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/components/ChiroAuthProvider.tsx'),'utf8'), {
  compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020,jsx:ts.JsxEmit.ReactJSX}
}).outputText;
function render({ready=true, authorized=true, pathname='/login', mode='keycloak', role='Citizen', error=null}={}) {
  const values=[[],ready,mode,true,authorized,role,error]; let index=0;
  const effects=[], redirects=[], initializations=[], logins=[];
  const module={exports:{}};
  const jsx=(type,props)=>({type,props});
  vm.runInNewContext(source, {module,exports:module.exports,process:{env:{NEXT_PUBLIC_API_URL:'http://localhost:8000/api'}},
    fetch:async()=>({ok:true,json:async()=>({mode,url:'https://auth.chirocity.gov.et',realm:'chirocity',clientId:'cas-web'})}),
    window:{location:{pathname},addEventListener(){},removeEventListener(){}},
    require:name=>{
    if(name==='react') return {createContext:()=>({Provider:'SessionProvider'}),useRef:()=>({current:false}),useState:()=>[values[index++],()=>{}],useEffect:callback=>effects.push(callback)};
    if(name==='react/jsx-runtime') return {jsx,jsxs:jsx};
    if(name==='next/navigation') return {usePathname:()=>pathname,useRouter:()=>({replace:url=>redirects.push(url)})};
    if(name==='@/lib/role') return {defaultRouteForRole:role=>role==='Citizen'?'/cases':'/dashboard'};
    if(name==='@/services/auth-session') return {configureAuth(){},initializeSso:async options=>initializations.push(options),getCachedAccessToken:()=>null,signIn:async()=>logins.push('login')};
    if(name==='@/services/auth-http') return {installAxiosAuth(){}};
    return {};
  }});
  const tree=module.exports.ChiroAuthProvider({children:'LOGIN_FORM'});
  effects[1]();
  return {tree,redirects,initializations,logins,repeatNavigation:()=>effects[1](),start:async()=>{effects[0]();await new Promise(resolve=>setImmediate(resolve));}};
}
test('authenticated callbacks never mount the login form before redirect completes',()=>{
  for(const pathname of ['/login','/auth/sign-in','/auth/sign-up','/']){
    const {tree,redirects}=render({pathname});
    assert.equal(tree.props.role,'status');
    assert.equal(tree.props.children,'Opening CAS...');
    assert.deepEqual(redirects,['/cases']);
  }
});
test('pending session checks do not mount login or protected content',()=>{
  for(const pathname of ['/login','/cases']){
    const {tree,redirects}=render({ready:false,authorized:false,pathname});
    assert.equal(tree.props.role,'status');assert.deepEqual(redirects,[]);
  }
});
test('signed-out entry opens Keycloak once without mounting the CAS sign-in screen',()=>{
  for(const pathname of ['/login','/cases']) {
    const view=render({authorized:false,pathname});
    assert.equal(view.tree.props.children,'Opening Chiro Auth...');
    assert.deepEqual(view.logins,['login']);assert.deepEqual(view.redirects,[]);
    view.repeatNavigation();assert.equal(view.logins.length,1);
  }
});

test('authorization errors allow account switching instead of an automatic redirect loop',()=>{
  const view=render({authorized:false,error:'Access not granted'});
  assert.equal(view.tree.type,'SessionProvider');assert.equal(view.logins.length,0);
});
test('authenticated app pages render without an extra sign-in redirect',()=>{
  const {tree,redirects}=render({pathname:'/cases'});
  assert.equal(tree.type,'SessionProvider');assert.deepEqual(redirects,[]);
});
test('local authenticated login also waits for navigation to the staff dashboard',()=>{
  const {tree,redirects}=render({mode:'local',role:'Admin'});
  assert.equal(tree.props.role,'status');assert.deepEqual(redirects,['/dashboard']);
});

test('CAS root, callback and protected pages require login without an intermediate screen',async()=>{
  for(const pathname of ['/','/login','/auth/sign-in','/cases']){
    const view=render({ready:false,authorized:false,pathname});
    await view.start();
    assert.equal(view.initializations.length,1);
    assert.equal(view.initializations[0].requireLogin,true);
    assert.equal(view.tree.props.role,'status');
  }
});

test('applicant signup stays public without a session-check redirect',async()=>{
  const view=render({ready:false,authorized:false,pathname:'/auth/sign-up'});
  await view.start();
  assert.equal(view.initializations[0].requireLogin,false);
  assert.equal(view.initializations[0].skipSessionCheck,true);
});

test('local mode never starts the Keycloak redirect flow',async()=>{
  const view=render({ready:false,authorized:false,mode:'local'});
  await view.start();
  assert.equal(view.initializations.length,0);
});
