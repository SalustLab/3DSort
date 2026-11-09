// Exercises real Python discovery/parsing on an exclusively synthetic SD.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
(async () => {
  const root = path.resolve(__dirname, '..'), port = 8398, base = `http://127.0.0.1:${port}`;
  let server, browser;
  async function start(args) {
    server = spawn(process.env.PYTHON || 'python', args, {cwd:root, windowsHide:true, env:{...process.env, NO_PROXY:'localhost,127.0.0.1'}});
    let output = '';
    server.stderr.on('data', d => output += d);
    for (let i=0; i<100; i++) {
      try {if ((await fetch(base)).ok) return;} catch {}
      if (server.exitCode !== null) throw new Error(output);
      await new Promise(r => setTimeout(r,100));
    }
    throw new Error('Theme fixture server did not start: ' + output);
  }
  async function stop() {
    if (server.exitCode !== null) return;
    const done = new Promise(resolve => server.once('exit', resolve));
    server.kill(); await done;
  }
  try {
    await start(['-m','tools.theme_fixtures',String(port)]);
    browser = await chromium.launch({headless:true});
    const page = await browser.newPage({viewport:{width:1440,height:1000}}), errors=[];
    page.on('pageerror', e => errors.push(e.message));
    const api = async (name,args=[]) => {
      const result = await (await page.request.post(base+'/api/'+name,{data:{args}})).json();
      assert(!result.error,result.error); return result;
    };
    await page.goto(base); await page.locator('#grid').waitFor();
    const before = await api('get_state');
    const layoutState = ({sd, ...s}) => s;
    const gridBackground = await page.locator('.console-top > div').first().evaluate(el => el.style.background);
    await page.locator('[data-tab="THEMES"]').click();
    const card = name => page.locator('.theme-card').filter({has:page.locator('strong', {hasText:name})});
    await card('Synthetic 星').waitFor();
    assert.match(await card('Synthetic 星').innerText(), /Test author[\s\S]*Directory package[\s\S]*BGM: present/);
    assert(await card('Synthetic 星').locator('img').evaluate(el => el.complete && el.naturalWidth > 0));
    await card('Synthetic 星').click();
    await page.locator('#themeDetails h3', {hasText:'Synthetic 星'}).waitFor();
    assert.match(await page.locator('#themeDetails').innerText(), /Package-supplied preview/);
    await card('Texture artwork').click();
    await page.locator('#themeDetails h3', {hasText:'Texture artwork'}).waitFor();
    assert.match(await page.locator('#themeDetails').innerText(), /Texture author[\s\S]*BGM: absent/);
    const artwork = page.locator('#themeDetails .theme-artwork');
    assert.equal(await artwork.count(),2);
    assert.deepEqual(await artwork.evaluateAll(els => els.map(el => [el.naturalWidth,el.naturalHeight])), [[412,240],[320,240]]);
    // Verify actual decoded pixels, screen assignment and orientation in browser.
    assert.deepEqual(await artwork.first().evaluate(el => {
      const c=document.createElement('canvas');c.width=el.naturalWidth;c.height=el.naturalHeight;
      const ctx=c.getContext('2d');ctx.drawImage(el,0,0);return [...ctx.getImageData(0,17,1,1).data];
    }),[0,0,255,255]);
    const scroll = await page.locator('.themes-screen').evaluate(el => {el.scrollTop=80;return el.scrollTop;});
    await card('Texture artwork').evaluate(el => el.click());
    await page.locator('#themeDetails h3', {hasText:'Texture artwork'}).waitFor();
    assert.equal(await page.locator('.themes-screen').evaluate(el => el.scrollTop),scroll);
    await card('no-preview').click();
    await page.locator('#themeDetails h3', {hasText:'no-preview'}).waitFor();
    assert.match(await page.locator('#themeDetails').innerText(), /Preview unavailable/);
    await card('corrupt').click();
    await page.locator('#themeDetails h3', {hasText:'corrupt'}).waitFor();
    assert.match(await page.locator('#themeDetails').innerText(), /unsupported[\s\S]*LZ11/);
    await page.locator('#inspectThemeCache').click();
    await page.locator('#themeCurrent p', {hasText:'Theme cache unavailable'}).waitFor();
    assert(!/\b(Installed|Active|IN USE)\b/.test(await page.locator('.themes-screen').innerText()));
    assert.deepEqual(layoutState(await api('get_state')),layoutState(before));
    await card('Texture artwork').click();
    await page.locator('#themeDetails h3', {hasText:'Texture artwork'}).waitFor();
    fs.mkdirSync(path.join(root,'.cache'),{recursive:true});
    await page.screenshot({path:path.join(root,'.cache','themes-ui.png')});
    await page.locator('[data-tab="RULES"]').click();
    await page.locator('#newSortPreset').waitFor();
    await page.locator('[data-tab="GRID"]').click(); await page.locator('#grid').waitFor();
    assert.equal(await page.locator('.console-top > div').first().evaluate(el => el.style.background),gridBackground);
    assert.deepEqual(layoutState(await api('get_state')),layoutState(before));
    assert.deepEqual(errors,[]);
    await stop();
    await start(['app.py','--serve','--mock',String(port)]);
    await page.reload(); await page.locator('#grid').waitFor();
    await page.locator('[data-tab="THEMES"]').click();
    await page.locator('#themeLibraryMessage', {hasText:'SD:/Themes/ is missing'}).waitFor();
    assert.equal(await page.locator('.theme-card').count(),0);
    assert.deepEqual(errors,[]);
    console.log('THEMES UI checks passed');
  } finally {if(browser) await browser.close(); if(server) await stop();}
})().catch(e => {console.error(e);process.exitCode=1;});
