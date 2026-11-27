// Run with Playwright installed and PYTHON pointing to the project interpreter.
// This test starts its own synthetic server and never connects to a real card.
const { chromium } = require('playwright');
const { spawn, spawnSync } = require('node:child_process');
const assert = require('node:assert/strict');
const net = require('node:net');
const path = require('node:path');

(async () => {
  const port = 8398, root = path.resolve(__dirname, '..');
  const probe = net.createServer();
  await new Promise((resolve, reject) => { probe.once('error', reject); probe.listen(port, '127.0.0.1', resolve); });
  await new Promise(resolve => probe.close(resolve));
  const server = spawn(process.env.APP_EXE || process.env.PYTHON || 'python', [...(process.env.APP_EXE ? [] : ['app.py']), '--serve', '--mock', '--mock-badges', String(port)], {cwd: root, windowsHide: true});
  let browser;
  try {
    const base = `http://127.0.0.1:${port}`;
    let ready = false;
    for (let i = 0; i < 100; i++) {
      try { ready = (await fetch(base)).ok; } catch {}
      if (ready) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert(ready, 'mock server did not start');
    browser = await chromium.launch({headless: true, ...(process.env.CHROMIUM_PATH ? {executablePath: process.env.CHROMIUM_PATH} : {})});
    const page = await browser.newPage({viewport: {width: 1440, height: 900}});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(base);
    await page.locator('#grid').waitFor();
    const state = async () => (await page.request.post(base + '/api/get_state', {data: {args: []}})).json();
    assert.match((await state()).sd.root, /3dsort-mock-/);
    const tile = key => page.locator(`#grid [data-ekey="${key}"]`);
    const box = page.locator('#gameSearchInput');
    const results = page.locator('#gameSearchResults .search-result');

    // Ctrl+F focuses the box; typing filters without re-rendering (focus stays).
    const games = (await state()).items.filter(i => i.folder === -1).sort((a, b) => a.pos - b.pos);
    const target = games[games.length - 1];
    await page.keyboard.press('Control+f');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'gameSearchInput');
    await page.keyboard.type(target.name.slice(0, 4).toUpperCase());
    assert(await results.count() >= 1);
    assert.equal(await page.evaluate(() => document.activeElement.id), 'gameSearchInput');
    assert(await tile(target.key).evaluate(el => el.classList.contains('search-hit')));
    assert.equal(await page.locator('#grid.searching').count(), 1);

    // Every term must match, in any order, ignoring case and accents.
    await box.fill('');
    await box.type('zzz-no-such-title');
    assert.equal(await results.count(), 0);
    assert.match(await page.locator('#gameSearchResults').innerText(), /No titles or folders match/);
    const words = target.name.split(/\s+/);
    const reversed = await page.evaluate(q => searchMatches(q).map(r => r.key), [...words].reverse().join(' ').toLowerCase());
    assert(reversed.includes(target.key));
    assert.deepEqual(await page.evaluate(() => searchMatches('pokémon').map(r => r.name)), await page.evaluate(() => searchMatches('POKEMON').map(r => r.name)));

    // Enter jumps to a title inside a folder: opens it and selects the title.
    const act = async (name, action) => {
      const response = page.waitForResponse(r => r.url() === base + '/api/' + name);
      await action();
      const result = await (await response).json();
      assert(!result.error, result.error);
      await page.locator('#grid').waitFor();
      return result;
    };
    await box.fill('');
    await page.keyboard.press('Escape');
    const moved = await act('set_folder', () => tile(target.key).dragTo(page.locator('[data-folder-tile="0"]')));
    assert.equal(moved.items.find(i => i.key === target.key).folder, 0);
    await box.fill(target.name);
    assert.match(await results.first().innerText(), new RegExp(moved.folderNames[0] || 'Folder 1'));
    await box.press('Enter');
    await page.locator('#grid[data-in-folder="0"]').waitFor();
    assert(await tile(target.key).evaluate(el => el.classList.contains('sel')));
    assert.equal(await page.locator('#gameSearchResults').isHidden(), true);

    // Escape in the box clears the query but keeps the selection; a click on a
    // folder result goes back to the home grid.
    await box.focus();
    await box.press('Escape');
    assert.equal(await box.inputValue(), '');
    assert.equal(await page.locator('#grid.searching').count(), 0);
    assert.equal(await page.locator('#grid .sel').count(), 1);
    const folderName = moved.folderNames[0];
    await box.type(folderName);
    await page.locator('#gameSearchResults .search-result', {hasText: 'Folder'}).first().click();
    await page.locator('#grid:not([data-in-folder])').waitFor();
    assert.equal(await page.locator('#grid [data-folder-tile="0"]').count(), 1);

    assert.deepEqual(errors, []);
    console.log('Search UI: Ctrl+F, live filtering, grid highlights, term/accent matching, jump into a folder, Escape and folder results passed.');
  } finally {
    if (browser) await browser.close();
    if (process.platform === 'win32' && process.env.APP_EXE) spawnSync('taskkill', ['/PID', String(server.pid), '/T', '/F'], {windowsHide: true});
    else server.kill();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
