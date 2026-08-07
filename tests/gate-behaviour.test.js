// Verifies the gate's reload behaviour. Run against a locally served build:
//
//   CS_GATE_PW=gate-test-pw CS_ACCESS_API_URL=https://api.example.test python3 build.py
//   (cd site && python3 -m http.server 8795 &)
//   NODE_PATH=$(npm root -g) GATE_URL=http://localhost:8795/healthcare/ \
//     GATE_SECRET=gate-test-pw node tests/gate-behaviour.test.js
//
// Checks:
//   - after unlocking once, a reload shows the GATE again (never auto-enters)
//   - the last-used email is prefilled
//   - clicking the CTA (or pressing Enter) unlocks immediately
//   - the email stays editable and a different address still works
const { chromium } = require('playwright');
const SECRET = process.env.GATE_SECRET || 'gate-test-pw';
const URL_ = process.env.GATE_URL || 'http://localhost:8795/healthcare/';

let failures = 0;
function check(name, cond, extra) {
  if (cond) console.log(`  PASS  ${name}`);
  else { failures++; console.log(`  FAIL  ${name}${extra !== undefined ? ' -> ' + JSON.stringify(extra) : ''}`); }
}

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const ctx = await browser.newContext({ viewport: { width: 900, height: 900 } });
  const page = await ctx.newPage();

  // Worker stand-in: "known@acme.com" is already approved, anyone else is new.
  const approved = new Set(['known@acme.com']);
  let requestAccessCalls = [], checkEmailCalls = 0;
  await page.route('**/check-email*', (route) => {
    checkEmailCalls++;
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'none' }) });
  });
  await page.route('**/request-access', async (route) => {
    const email = JSON.parse(route.request().postData()).email;
    requestAccessCalls.push(email);
    const body = approved.has(email)
      ? { status: 'approved', secret: SECRET }
      : { status: 'pending', requestId: 'req-new' };
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  });
  await page.route('**/check-access*', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'pending' }) }));

  const gateVisible = () => page.evaluate(() => !!document.getElementById('pm-cs-gate'));
  const contentShown = () => page.evaluate(() => !!document.querySelector('#pm-cs-doc h1'));
  const emailValue = () => page.inputValue('#pm-cs-access-form input[type=email]');

  console.log('\n== first visit: gate up, nothing prefilled ==');
  await page.goto(URL_, { waitUntil: 'networkidle' });
  check('gate is showing', await gateVisible());
  check('case study hidden', !(await contentShown()));
  check('email box empty', (await emailValue()) === '', await emailValue());

  console.log('\n== enter an approved address -> unlocks ==');
  await page.fill('#pm-cs-access-form input[type=email]', 'known@acme.com');
  await page.click('#pm-cs-access-form button');
  await page.waitForSelector('#pm-cs-doc h1', { timeout: 8000 });
  check('case study revealed', await contentShown());
  check('gate removed', !(await gateVisible()));

  console.log('\n== THE ASK: reload -> gate again, email prefilled, no auto-entry ==');
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(1200); // give any stray auto-unlock a chance to fire
  check('gate is showing again', await gateVisible());
  check('did NOT auto-enter the case study', !(await contentShown()));
  check('email prefilled from last time', (await emailValue()) === 'known@acme.com', await emailValue());
  check('no background check-email call', checkEmailCalls === 0, checkEmailCalls);
  check('no request fired on load', requestAccessCalls.length === 1, requestAccessCalls);

  console.log('\n== clicking the CTA lets me straight back in ==');
  const t0 = Date.now();
  await page.click('#pm-cs-access-form button');
  await page.waitForSelector('#pm-cs-doc h1', { timeout: 8000 });
  check(`unlocked on click (${Date.now() - t0}ms)`, await contentShown());

  console.log('\n== pressing Enter in the field works too ==');
  await page.reload({ waitUntil: 'networkidle' });
  check('gate back after reload', await gateVisible());
  await page.click('#pm-cs-access-form input[type=email]');
  await page.keyboard.press('Enter');
  await page.waitForSelector('#pm-cs-doc h1', { timeout: 8000 });
  check('Enter key unlocked it', await contentShown());

  console.log('\n== the address is editable: a new one goes through request flow ==');
  await page.reload({ waitUntil: 'networkidle' });
  await page.fill('#pm-cs-access-form input[type=email]', 'stranger@else.com');
  check('field accepted a new address', (await emailValue()) === 'stranger@else.com');
  await page.click('#pm-cs-access-form button');
  await page.waitForFunction(() => {
    const el = document.getElementById('pm-cs-access-status');
    return el && !el.hidden && /waiting for approval/i.test(el.textContent);
  }, { timeout: 8000 });
  check('new address -> waiting for approval', true);
  check('still gated for unapproved address', !(await contentShown()));
  check('request used the edited address', requestAccessCalls[requestAccessCalls.length - 1] === 'stranger@else.com',
    requestAccessCalls);

  console.log('\n== reload while a request is pending: gate + resumes waiting ==');
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(600);
  check('gate showing', await gateVisible());
  check('prefilled with the pending address', (await emailValue()) === 'stranger@else.com', await emailValue());
  check('button still usable to change address', !(await page.isDisabled('#pm-cs-access-form button')));

  console.log(failures === 0 ? '\nALL PASSED\n' : `\n${failures} FAILURE(S)\n`);
  await browser.close();
  process.exit(failures === 0 ? 0 : 1);
})();
