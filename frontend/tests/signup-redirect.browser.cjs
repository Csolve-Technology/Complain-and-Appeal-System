const { chromium } = require(process.env.PLAYWRIGHT_CORE || 'playwright-core');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const origin = process.env.CAS_TEST_URL || 'http://127.0.0.1:3112';
  let created = 0, loginNavigations = 0;
  try {
    const page = await browser.newPage();
    page.on('framenavigated', frame => {
      if (frame === page.mainFrame() && new URL(frame.url()).pathname === '/auth/sign-in') loginNavigations++;
    });
    await page.route('**/auth/config/', route => route.fulfill({ json: { mode: 'keycloak', url: 'https://auth.chirocity.gov.et', realm: 'cas', clientId: 'cas-web', requireVerifiedEmail: false }, headers: { 'Access-Control-Allow-Origin': origin } }));
    // Registration is mocked: this browser test creates no real account.
    await page.route('**/auth/applicant-registration/', route => {
      const body = route.request().postDataJSON();
      assert.equal(body.email, 'newapplicant@example.invalid');
      assert.equal(body.groups, undefined);
      assert.equal(body.roles, undefined);
      created++;
      return route.fulfill({ status: 201, json: { detail: 'Account created.' }, headers: { 'Access-Control-Allow-Origin': origin } });
    });
    await page.route('https://auth.chirocity.gov.et/**', route => route.fulfill({ contentType: 'text/html', body: route.request().url().includes('3p-cookies') ? '<script>parent.postMessage("supported", "*")</script>' : '<h1>Keycloak login</h1>' }));
    await page.goto(origin + '/auth/sign-up', { waitUntil: 'domcontentloaded' });
    await page.getByRole('heading', { name: 'Create your Citizen account' }).waitFor({ timeout: 60000 });
    for (const [name, value] of Object.entries({ firstName: 'New', lastName: 'Applicant', email: 'newapplicant@example.invalid', phone: '0912345678', password: '123456', confirmPassword: '123456' })) {
      await page.locator(`input[name="${name}"]`).fill(value);
    }
    await page.getByRole('button', { name: 'Create Account', exact: true }).click();
    await page.waitForURL('https://auth.chirocity.gov.et/realms/cas/**', { waitUntil: 'domcontentloaded', timeout: 30000 });
    const url = new URL(page.url());
    assert.equal(url.searchParams.get('client_id'), 'cas-web');
    assert.equal(url.searchParams.get('login_hint'), 'newapplicant@example.invalid');
    assert.equal(url.searchParams.get('prompt'), 'login');
    assert.equal(url.searchParams.get('code_challenge_method'), 'S256');
    assert.equal(url.searchParams.get('redirect_uri'), origin + '/login');
    assert.equal(created, 1);
    assert.equal(loginNavigations, 0);
    console.log('Successful applicant signup opens Keycloak directly with a fresh login prompt; no middle sign-in page.');
    await page.goto(origin + '/auth/sign-up', { waitUntil: 'domcontentloaded' });
    await page.getByRole('link', { name: 'Sign in', exact: true }).click();
    await page.waitForURL('https://auth.chirocity.gov.et/realms/cas/**', { waitUntil: 'domcontentloaded', timeout: 30000 });
    const existingLogin = new URL(page.url());
    assert.equal(existingLogin.searchParams.get('client_id'), 'cas-web');
    assert.equal(existingLogin.searchParams.get('redirect_uri'), origin + '/login');
    assert.equal(existingLogin.searchParams.get('code_challenge_method'), 'S256');
    assert.equal(created, 1);
    assert.equal(loginNavigations, 0);
    console.log('Existing-account Sign in opens Keycloak directly without registering or visiting the middle sign-in page.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
