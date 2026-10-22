// Run with Playwright installed and PYTHON pointing to the project interpreter.
// This test starts its own synthetic server and never connects to a real card.
const { chromium } = require('playwright');
const { spawn, spawnSync } = require('node:child_process');
const assert = require('node:assert/strict');
const net = require('node:net');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const port = 8396, root = path.resolve(__dirname, '..');
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
    const act = async (name, action) => {
      const response = page.waitForResponse(r => r.url() === base + '/api/' + name);
      await action();
      const result = await (await response).json();
      assert(!result.error, result.error);
      await page.locator('#grid').waitFor();
      return result;
    };

    const tile = key => page.locator(`#grid [data-ekey="${key}"]`);
    await page.evaluate(() => {
      S.system[0].pos = S.items.find(i => i.folder === -1).pos;
      S.layoutErrors = ['Two imported titles occupy one cell'];
      render();
    });
    assert.equal(await page.locator('#grid .conflict-cell').count(), 1);
    assert.equal(await page.locator('#grid .conflict-cell span').count(), 2);
    assert.equal(await page.locator('#compactGames').isDisabled(), true);
    assert.match(await page.locator('.layout-error').innerText(), /imported layouts disagree/);
    await page.evaluate(async () => { S = await call('get_state'); render(); });
    const games = (await state()).items.filter(i => i.folder === -1).sort((a,b) => a.pos-b.pos);
    const keys = games.slice(0,3).map(i => i.key);
    await tile(keys[0]).click();
    await tile(keys[2]).click({modifiers:['Shift']});
    assert.equal(await page.locator('#grid .sel').count(), 3);
    assert.match(await page.locator('#selectionStatus').innerText(), /3 selected/);
    fs.mkdirSync(path.join(root, '.cache'), {recursive:true});
    await page.screenshot({path:path.join(root,'.cache','multiselect-ui.png')});
    let result = await act('move_games', () => tile(keys[1]).dragTo(page.locator('[data-empty][data-cell="20"]')));
    assert.deepEqual(keys.map(k => result.items.find(i => i.key === k).pos), [20,21,22]);
    assert.equal(result.staged.length, 1);
    result = await act('undo', () => page.locator('#undoBtn').click());
    assert.deepEqual(keys.map(k => result.items.find(i => i.key === k).pos), keys.map(k => games.find(i => i.key === k).pos));
    await act('redo', () => page.locator('#redoBtn').click());
    await act('undo', () => page.locator('#undoBtn').click());
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#grid .sel').count(), 0);
    await tile(keys[0]).click();
    await tile(keys[2]).click({modifiers:['Control']});
    assert.equal(await page.locator('#grid .sel').count(), 2);
    await tile(keys[2]).click({modifiers:['Control']});
    assert.equal(await page.locator('#grid .sel').count(), 1);
    await tile(keys[2]).click({modifiers:['Control']});
    result = await act('move_games', () => tile(keys[0]).dragTo(tile(games[5].key)));
    const ordered = result.items.filter(i => i.folder === -1).sort((a,b) => a.pos-b.pos).map(i => i.key);
    const index = ordered.indexOf(games[5].key);
    assert.deepEqual(ordered.slice(index-2,index), [keys[0],keys[2]]);
    await act('undo', () => page.locator('#undoBtn').click());
    result = await act('move_games', () => tile(keys[0]).dragTo(page.locator('[data-folder-tile="0"]')));
    assert(keys.filter(k => k !== keys[1]).every(k => result.items.find(i => i.key === k).folder === 0));
    await page.locator('[data-folder-tile="0"]').click();
    assert.equal(await page.locator('#grid .sel').count(), 0);
    await tile(keys[0]).click();
    await tile(keys[2]).click({modifiers:['Shift']});
    result = await act('move_games', () => tile(keys[0]).dragTo(page.locator('#removeZone')));
    assert(keys.filter(k => k !== keys[1]).every(k => result.items.find(i => i.key === k).folder === -1));
    await page.locator('#closeFolder').click();
    // Dragging an unselected title must not drag the previously selected group.
    await tile(keys[0]).click();
    await tile(keys[2]).click({modifiers:['Control']});
    result = await act('move_to_position', () => tile(keys[1]).dragTo(page.locator('[data-empty][data-cell="25"]')));
    assert.equal(result.items.find(i => i.key === keys[1]).pos, 25);
    assert.equal(await page.locator('#grid .sel').count(), 1);
    assert.deepEqual(errors, []);
    console.log('MultiSelect UI: Shift range, Ctrl toggle, group drag, occupied insertion, folder in/out, Undo/Redo, Escape and unselected drag passed.');
  } finally {
    if (browser) await browser.close();
    if (process.platform === 'win32' && process.env.APP_EXE) spawnSync('taskkill', ['/PID', String(server.pid), '/T', '/F'], {windowsHide: true});
    else server.kill();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
