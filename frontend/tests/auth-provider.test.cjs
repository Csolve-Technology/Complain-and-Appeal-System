const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const vm = require('node:vm');
const source = ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/components/ChiroAuthProvider.tsx'),'utf8'), {
  compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020,jsx:ts.JsxEmit.ReactJSX}
}).outputText;
function render({ready=true, authorized=true, pathname='/login', mode='keycloak', role='Citizen'}={}) {
  const values=[[],ready,mode,true,authorized,role,null]; let index=0;
  const effects=[], redirects=[];
  const module={exports:{}};
  const jsx=(type,props)=>({type,props});
  vm.runInNewContext(source, {module,exports:module.exports,require:name=>{
    if(name==='react') return {createContext:()=>({Provider:'SessionProvider'}),useState:()=>[values[index++],()=>{}],useEffect:callback=>effects.push(callback)};
    if(name==='react/jsx-runtime') return {jsx,jsxs:jsx};
    if(name==='next/navigation') return {usePathname:()=>pathname,useRouter:()=>({replace:url=>redirects.push(url)})};
    if(name==='@/lib/role') return {defaultRouteForRole:role=>role==='Citizen'?'/cases':'/dashboard'};
    return {};
  }});
  const tree=module.exports.ChiroAuthProvider({children:'LOGIN_FORM'});
  effects[1]();
  return {tree,redirects};
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
test('signed-out users see login after checking and protected pages wait for redirect',()=>{
  assert.equal(render({authorized:false}).tree.type,'SessionProvider');
  const {tree,redirects}=render({authorized:false,pathname:'/cases'});
  assert.equal(tree.props.role,'status');assert.deepEqual(redirects,['/auth/sign-in']);
});
test('authenticated app pages render without an extra sign-in redirect',()=>{
  const {tree,redirects}=render({pathname:'/cases'});
  assert.equal(tree.type,'SessionProvider');assert.deepEqual(redirects,[]);
});
test('local authenticated login also waits for navigation to the staff dashboard',()=>{
  const {tree,redirects}=render({mode:'local',role:'Admin'});
  assert.equal(tree.props.role,'status');assert.deepEqual(redirects,['/dashboard']);
});
