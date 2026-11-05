const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const vm = require('node:vm');
const moduleUnderTest = { exports: {} };
const source = ts.transpileModule(fs.readFileSync(path.join(__dirname, '../src/lib/form-errors.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 }
}).outputText;
vm.runInNewContext(source, {module: moduleUnderTest, exports: moduleUnderTest.exports});
const { parseFormErrors, readFormErrors } = moduleUnderTest.exports;
test('all password validation messages are preserved under the password field', () => {
  const error = parseFormErrors({password:['This password is too common.', 'This password is entirely numeric.']});
  assert.equal(error.fields.password, 'This password is too common. This password is entirely numeric.');
  assert.equal(error.message, 'Please correct the highlighted fields.');
});
test('string email errors and username conflicts are shown at the email input', () => {
  const error = parseFormErrors({email:'Email is required for Chiro Auth accounts.', username:['This username is already taken.']});
  assert.equal(error.fields.email, 'Email is required for Chiro Auth accounts. This username is already taken.');
});
test('general errors remain visible with field validation errors', () => {
  const error = parseFormErrors({detail:'Could not create the account.', password:['Choose another password.']});
  assert.equal(error.message, 'Could not create the account.');
  assert.equal(error.fields.password, 'Choose another password.');
});
test('proxy HTML errors use a readable fallback rather than raw markup', async () => {
  const error = await readFormErrors(new Response('<html>Proxy error</html>', {status:502}));
  assert.equal(error.message, 'Unable to create user (502).');
});
