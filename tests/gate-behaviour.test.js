// Verifies the gate's reload behaviour. Run against a locally served build:
//
//   CS_GATE_PW=gate-test-pw CS_ACCESS_API_URL=https://api.example.test python3 build.py
//   (cd site && python3 -m http.server 8796 &)
//   NODE_PATH=$(npm root -g) GATE_URL=http://localhost:8796/healthcare/ \
//     GATE_SECRET=gate-test-pw node tests/gate-behaviour.test.js
//
// GATE_SECRET must equal the CS_GATE_PW the build was made with.
//
// Checks:
//   - after unlocking once, a reload shows the GATE again (never auto-enters)
//   - the last-used email is prefilled
//   - clicking the CTA (or pressing Enter) unlocks immediately
//   - the email stays editable and a different address still works
const { chromium } = require('playwright');
const SECRET = process.env.GATE_SECRET || 'gate-test-pw';
const URL_ = process.env.GATE_URL || 'http://localhost:8796/healthcare/';

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

  console.log('\n== the first ask is just an email ==');
  {
    const main = await page.textContent('#pm-cs-gate-main');
    check('asks for an email plainly', /enter your email to continue/i.test(main), main.slice(0,120));
    check('does not front-load the approval wait', !/five minutes/i.test(main), main.slice(0,200));
    check('does not front-load the 4-hour window', !/4 hours/i.test(main), main.slice(0,200));
    check('email field comes before the password field', await page.evaluate(() => {
      const e = document.querySelector('#pm-cs-access-form input[type=email]');
      const p = document.querySelector('.cs-gate-form input[type=password]');
      return !!(e && p) && (e.compareDocumentPosition(p) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
    }));
    check('password path still available', await page.isVisible('.cs-gate-form input[type=password]'));
  }

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
  await page.waitForSelector('#pm-cs-wait:not([hidden])', { timeout: 8000 });
  check('swaps to the waiting view', await page.isVisible('#pm-cs-wait'));
  check('form view is hidden', !(await page.isVisible('#pm-cs-gate-main')));
  check('still gated', !(await contentShown()));
  check('request used the edited address',
    requestAccessCalls[requestAccessCalls.length - 1] === 'stranger@else.com', requestAccessCalls);

  console.log('\n== the waiting view sets expectations ==');
  {
    const lede = (await page.textContent('#pm-cs-wait-lede')).toLowerCase();
    const note = (await page.textContent('#pm-cs-wait .cs-gate-note')).toLowerCase();
    check('says a human approves it', /i approve these personally/.test(lede), lede);
    check('promises ~five minutes', /five minutes/.test(lede), lede);
    check('states the 4-hour window', /4 hours/.test(note), note);
    check('states it covers every case study', /every gated case study/.test(note), note);
    check('echoes the address back', (await page.textContent('#pm-cs-wait-email')) === 'stranger@else.com');
    check('a live status region for screen readers',
      (await page.getAttribute('.cs-gate-wait-status', 'aria-live')) === 'polite');
  }

  console.log('\n== "Use a different email" backs out ==');
  await page.click('#pm-cs-wait-back');
  check('form view is back', await page.isVisible('#pm-cs-gate-main'));
  check('waiting view hidden', !(await page.isVisible('#pm-cs-wait')));
  check('button usable again', !(await page.isDisabled('#pm-cs-access-form button')));
  await page.fill('#pm-cs-access-form input[type=email]', 'known@acme.com');
  await page.click('#pm-cs-access-form button');
  await page.waitForSelector('#pm-cs-doc h1', { timeout: 8000 });
  check('can still get in after backing out', await contentShown());

  console.log('\n== reload while a request is pending resumes the waiting view ==');
  await page.evaluate(() => {
    localStorage.setItem('pmCsEmail', 'stranger@else.com');
    localStorage.setItem('pmCsReq:healthcare', 'req-new');
  });
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(600);
  check('waiting view restored', await page.isVisible('#pm-cs-wait'));
  check('address restored', (await page.textContent('#pm-cs-wait-email')) === 'stranger@else.com');
  check('did not auto-enter', !(await contentShown()));

  console.log('\n== reload AFTER approval must not auto-enter (regression) ==');
  {
    // The exact reported flow: submit an email, approve it, then reload while
    // the request id is still remembered. The resumed poll resolves to
    // "approved" -- which must hand control back, not open the page.
    await page.unroute('**/check-access*');
    await page.route('**/check-access*', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json',
        body: JSON.stringify({ status: 'approved', secret: SECRET }) }));

    await page.evaluate(() => {
      localStorage.setItem('pmCsEmail', 'stranger@else.com');
      localStorage.setItem('pmCsReq:healthcare', 'req-approved');
    });
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForTimeout(1500); // let the resumed poll resolve

    check('did NOT auto-enter on reload', !(await contentShown()));
    check('gate is showing', await gateVisible());
    check('form view, not the waiting view', await page.isVisible('#pm-cs-gate-main'));
    check('tells them they are approved',
      /approved/i.test(await page.textContent('#pm-cs-access-status')),
      await page.textContent('#pm-cs-access-status'));
    check('email still prefilled', (await emailValue()) === 'stranger@else.com');
    check('stale request id cleared',
      (await page.evaluate(() => localStorage.getItem('pmCsReq:healthcare'))) === null);

    // ...and one click still gets them straight in.
    await page.click('#pm-cs-access-form button');
    await page.waitForSelector('#pm-cs-doc h1', { timeout: 8000 });
    check('one click opens it', await contentShown());
  }

  console.log(failures === 0 ? '\nALL PASSED\n' : `\n${failures} FAILURE(S)\n`);
  await browser.close();
  process.exit(failures === 0 ? 0 : 1);
})();
