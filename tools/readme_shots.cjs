// README screenshots from SYNTHETIC data only (--mock --mock-badges): no console
// data ever reaches the repository. Starts its own server; needs Playwright,
// PYTHON (interpreter) and optionally CHROMIUM_PATH, like tools/test_spatial_ui.cjs.
//   node tools/readme_shots.cjs   -> docs/images/grid.png, docs/images/badges.png
const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const path = require('node:path');

(async () => {
  const port = 8395, root = path.resolve(__dirname, '..'), out = path.join(root, 'docs', 'images');
  const server = spawn(process.env.PYTHON || 'python', ['app.py', '--serve', '--mock', '--mock-badges', String(port)], {cwd: root, windowsHide: true});
  let browser;
  try {
    const base = `http://127.0.0.1:${port}`;
    for (let i = 0; i < 100; i++) { try { if ((await fetch(base)).ok) break; } catch {} await new Promise(r => setTimeout(r, 100)); }
    browser = await chromium.launch({headless: true, ...(process.env.CHROMIUM_PATH ? {executablePath: process.env.CHROMIUM_PATH} : {})});
    const page = await browser.newPage({viewport: {width: 1440, height: 900}, deviceScaleFactor: 1});
    await page.goto(base);
    await page.locator('#grid').waitFor();
    const api = (name, args) => page.request.post(`${base}/api/${name}`, {data: {args}});
    // a small readable scene: two badges on the grid, a 2x2 block, a decorated folder
    await api('place_badge', [0, -1, 21, 4]);
    await api('place_badge', [1, -1, 25, 4]);
    await api('place_badge', [4, -1, 22, 4]);
    await api('decorate_folder', [0, 1]);
    await page.reload();
    await page.locator('#grid').waitFor();
    await page.locator('#badgesToggle').click();
    const settled = () => page.waitForFunction(() => [...document.querySelectorAll('[data-badge-image]')].every(img => !img.isConnected || (img.complete && img.naturalWidth > 0)));
    await settled();
    await page.evaluate(() => Promise.all(document.getAnimations().map(a => a.finished.catch(() => {}))));
    await page.screenshot({path: path.join(out, 'grid.png')});
    await page.locator('#closeBadges').click();
    await page.locator('#decorateFolder').click();
    await settled();
    await page.screenshot({path: path.join(out, 'badges.png')});
    console.log('README screenshots written to docs/images (grid.png, badges.png), synthetic data only.');
  } finally {
    if (browser) await browser.close();
    server.kill();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
