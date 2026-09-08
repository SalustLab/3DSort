// Run with Playwright installed and PYTHON pointing to the project interpreter.
// This test starts its own synthetic server and never connects to a real card.
const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');
const net = require('node:net');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  const port = 8394, root = path.resolve(__dirname, '..');
  const probe = net.createServer();
  await new Promise((resolve, reject) => { probe.once('error', reject); probe.listen(port, '127.0.0.1', resolve); });
  await new Promise(resolve => probe.close(resolve));
  const server = spawn(process.env.PYTHON || 'python', ['app.py', '--serve', '--mock', '--mock-badges', String(port)], {cwd: root, windowsHide: true});
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
    const emptyCells = () => page.locator('#grid .empty-cell').count();

    // toolbar: dropdown, Badges (gold), Decorate folder (rose), Compact, pages segment
    const toolbar = await page.locator('.spatial-controls').first().evaluate(el => [...el.children].map(c => c.id || c.className));
    assert.deepEqual(toolbar.slice(0, 5), ['folderNavigation', 'badgesToggle', 'decorateFolder', 'compactGames', 'seg slots']);
    assert.equal(await page.locator('#badgesToggle.chip-gold').count(), 1);
    assert.equal(await page.locator('#decorateFolder.chip-rose').count(), 1);

    // pages - / +
    const before = await emptyCells();
    assert.equal(await page.locator('#slotsLess.off').count(), 1, 'cannot show fewer pages than the content needs');
    await page.locator('#slotsMore').click();
    assert(await emptyCells() > before, 'one more page of empty cells');
    await page.locator('#slotsLess').click();
    assert.equal(await emptyCells(), before, 'back to the minimum');

    let result = await act('move_to_position', () => page.locator('[data-ekey="g:0"]').dragTo(page.locator('[data-empty][data-cell="20"]')));
    assert.equal(result.items.find(i => i.key === 'g:0').pos, 20);
    assert.equal(await page.locator('[data-empty][data-cell="3"]').count(), 1);
    assert.match(result.staged.at(-1), /^Moved .* to cell 21$/);
    // compact asks first (and warns that system items after the gap will move), then closes every gap
    await page.locator('#compactGames').click();
    await page.locator('#confirmCompact').waitFor();
    assert.match(await page.locator('.modal').innerText(), /needs the GodMode9 inject/);
    result = await act('compact_games', () => page.locator('#confirmCompact').click());
    assert.equal(result.items.find(i => i.key === 'g:0').pos, 17, 'order kept: the moved game takes the last packed cell');
    assert.equal(result.launcherDirty, true, 'the Game Card and system apps behind the gap moved');
    assert.equal(await page.locator('#compactGames:disabled').count(), 1, 'no gaps left to close');
    await act('undo', () => page.locator('#undoBtn').click());
    await act('undo', () => page.locator('#undoBtn').click());

    await page.getByRole('button', {name: '★ Badges', exact: true}).click();
    assert.equal(await page.locator('#badgeSet').count(), 0, 'single set: no set filter');
    await page.locator('[data-badge-id="0"]').click();
    result = await act('place_badge', () => page.locator('[data-empty][data-cell="20"]').click());
    assert.equal(result.badges.placed.length, 1);
    assert.equal(result.staged.at(-1), 'Placed Sun at cell 21');
    // a preset lays the grid out by type: system + folder first, sorted games, then badges
    await page.locator('#sortChip').click();
    result = await act('sort_preset', () => page.locator('[data-preset="az"]').click());
    assert.equal(result.folderPos[0], 5, 'folder tile right after the system apps and the Game Card');
    assert.deepEqual(result.badges.placed.map(b => b.pos), [6], 'badge after the folder, before the games');
    assert.equal(result.launcherDirty, true);
    await act('undo', () => page.locator('#undoBtn').click());
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.badge-panel').count(), 0, 'Esc closes the badge panel');
    await act('move_to_position', () => page.locator('[data-ekey="b:0"]').dragTo(page.locator('[data-empty][data-cell="21"]')));
    await act('swap_items', () => page.locator('[data-ekey="g:0"]').dragTo(page.locator('[data-ekey="b:0"]')));
    await act('reset_staging', () => page.locator('#resetBtn').click());
    await page.getByRole('button', {name: '★ Badges', exact: true}).click();
    await page.locator('[data-badge-id="4"]').click();
    result = await act('place_badge', () => page.locator('[data-empty][data-cell="20"]').click());
    assert.deepEqual(result.badges.placed.map(b => b.pos).sort((a,b) => a-b), [20,21,24,25]);
    await page.locator('#slotsMore').click();
    result = await act('move_to_position', () => page.locator('[data-ekey="b:0"]').dragTo(page.locator('[data-empty][data-cell="40"]')));
    assert.deepEqual(result.badges.placed.map(b => b.pos).sort((a,b) => a-b), [40,41,44,45]);
    await page.locator('#writeBtn').click();
    const written = page.waitForResponse(r => r.url() === base + '/api/write_sd');
    await page.locator('#confirmWrite').click();
    result = await (await written).json();
    assert(!result.error, result.error);
    assert.equal(result.pendingInject, null);
    await page.reload();
    await page.locator('[data-ekey="b:0"]').waitFor();
    assert.equal((await state()).badges.placed.length, 4);

    // decorate from the HOME grid: pick the folder, then a badge by its image card
    await page.locator('#decorateFolder').click();
    await page.locator('[data-pick-folder="0"]').click();
    result = await act('decorate_folder', () => page.locator('[data-pick-badge="0"]').click());
    assert(result.badges.placed.some(b => b.decoration === 0));
    assert.equal(result.staged.at(-1), 'Icon of Homebrew: Sun');
    assert.equal(await page.locator('#modalBg').count(), 0, 'modal closes after applying');

    // new folder with an icon in one staged change
    await page.locator('#newFolderBtn').click();
    await page.locator('#newFolderName').fill('Gems');
    await page.locator('[data-new-folder-icon="1"]').click();
    result = await act('folder_create', () => page.locator('#confirmNewFolder').click());
    const gems = Object.entries(result.folderNames).find(([, n]) => n === 'Gems');
    assert(gems && result.badges.placed.some(b => b.decoration === +gems[0]));
    assert.equal(result.staged.at(-1), 'Created folder Gems with icon Leaf');

    // inside a folder: a badge dropped on the big icon asks before replacing the icon
    await page.locator('[data-folder-tile="0"]').click();
    await page.getByRole('button', {name: '★ Badges', exact: true}).click();
    await page.locator('[data-badge-id="1"]').dragTo(page.locator('#folderArtDrop'));
    await page.locator('#confirmDecorate').waitFor();
    assert.match(await page.locator('.modal').innerText(), /replaces/);
    result = await act('decorate_folder', () => page.locator('#confirmDecorate').click());
    assert.equal(result.badges.placed.find(b => b.decoration === 0).badge, 1);
    await page.locator('#closeFolder').click();

    if (!(await page.locator('.badge-panel').count())) await page.getByRole('button', {name: '★ Badges', exact: true}).click();
    await page.locator('[data-badge-id="0"] img').waitFor();
    await page.waitForFunction(() => [...document.querySelectorAll('[data-badge-image]')].every(img => img.complete && img.naturalWidth > 0));
    await page.evaluate(() => Promise.all(document.getAnimations().map(a => a.finished.catch(() => {}))));
    fs.mkdirSync(path.join(root, '.cache'), {recursive: true});
    await page.screenshot({path: path.join(root, '.cache', 'spatial-ui.png')});
    assert.equal(await page.locator('#grid').evaluate(el => el.scrollWidth <= el.clientWidth + 2), true, 'grid clips horizontally');
    assert.deepEqual(errors, []);
    console.log('Spatial UI: toolbar, pages, compact, moves, undo, badges, composites, swaps, write/reload, decoration (grid, new folder, drop on icon), labels and images passed.');
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
