// Exercises real bank API selection against isolated synthetic SD data.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const assert = require('node:assert/strict');
(async () => {
  const base = 'http://127.0.0.1:8398';
  const server = spawn(process.env.PYTHON || 'python', ['-c', "import sys; sys.path.insert(0, 'tests'); from test_bank_integration import bank_api; from app import serve, build_api; import threading; threading.Thread(target=serve,args=(build_api(mock=True),8396),daemon=True).start(); api, home = bank_api(); ini = api.sd_root / '3DSBank' / '3DSBank.ini'; ini.write_text(ini.read_text() + 'FOLDER_SLOT = 0' + chr(10)); serve(api, 8398)"], {cwd:require('node:path').resolve(__dirname,'..'),windowsHide:true});
  let browser;
  try {
    let ready = false;
    for (let i=0;i<100;i++) {try {ready=(await fetch(base)).ok;} catch {} if(ready) break; await new Promise(r=>setTimeout(r,100));}
    assert(ready);
    browser = await chromium.launch({headless:true, ...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} : {})});
    const page = await browser.newPage();
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    // Header must hold the bank selector without spilling over the grid or squeezing SD info.
    const checkHeader=async(state,longName=false)=>{for (const [width,height] of [[929,800],[1280,800],[1920,1080]]) {
      await page.setViewportSize({width,height});
      const bad=await page.evaluate((longName)=>{
        const bar=document.querySelector('.topbar').getBoundingClientRect(), out=[];
        const els=[document.querySelector('.topbar').firstElementChild,...['tabs','sdinfo','bankStatus','writeBtn','gearBtn'].map(id=>document.getElementById(id))].filter(Boolean);
        const rects=els.map(e=>[e.id||'logo',e.getBoundingClientRect()]);
        for (const [id,r] of rects) if (r.top<bar.top-0.5||r.bottom>bar.bottom+0.5) out.push(id+' leaves the header');
        for (let i=1;i<rects.length;i++) if (rects[i][1].left<rects[i-1][1].right-0.5) out.push(rects[i][0]+' overlaps '+rects[i-1][0]);
        for (const [id,r] of rects) {const e=id==='logo'?els[0]:document.getElementById(id); if (id!=='bankStatus'&&e.scrollWidth>e.clientWidth+1) out.push(id+' is squeezed');}
        const gear=document.getElementById('gearBtn').getBoundingClientRect();
        if (gear.width<gear.height-1) out.push('gearBtn is squeezed');
        const sd=document.getElementById('sdinfo');
        if (sd.getBoundingClientRect().height>parseFloat(getComputedStyle(sd).lineHeight)*2+1) out.push('SD info wraps past two lines');
        const bank=document.getElementById('bankStatus');
        if (bank) {
          const bankRow=bank.querySelector('.bank-row');
          if (!bankRow.querySelector('button')&&bankRow.scrollWidth>bankRow.clientWidth+1) out.push('bank selector row scrolls');
          const note=bank.querySelector('.bank-note').getBoundingClientRect();
          if (note.height&&(note.top<bar.top-0.5||note.bottom>bar.bottom+0.5)) out.push('bank note leaves the header');
          // The selector row sits on the same line as the SD text, in the same type.
          const mid=r=>r.top+r.height/2, rowR=bankRow.getBoundingClientRect();
          if (Math.abs(mid(rowR)-mid(sd.getBoundingClientRect()))>1.5) out.push('bank row misaligned with SD text');
          if (getComputedStyle(bank.querySelector('label')).fontFamily!==getComputedStyle(sd).fontFamily) out.push('bank label font differs from SD text');
          // The selected bank name must never be truncated: compare with an unconstrained clone.
          const sel=document.getElementById('bankSelect'), clone=sel.cloneNode(true);
          clone.style.cssText='position:absolute;flex:none;width:auto;visibility:hidden'; sel.after(clone);
          const natural=clone.getBoundingClientRect().width; clone.remove();
          const select=sel.getBoundingClientRect(), row=bankRow.getBoundingClientRect();
          // A very long configured name may be cut by the native select; normal names never are.
          if (!longName&&Math.min(select.right,row.right)-select.left<natural-1) out.push('bank selector truncates its label');
          // An actionable alert keeps a fully visible indicator whatever the name or width.
          // Info and alert icons are drawn centered in their boxes (font glyphs were not).
          for (const id of ['bankInfo','bankAlert']) {
            const box=document.getElementById(id); if (!box) continue;
            const icon=box.querySelector('svg'), b=box.getBoundingClientRect();
            if (!icon) {out.push(id+' icon is not a centered drawing'); continue;}
            const i=icon.getBoundingClientRect();
            if (Math.abs((i.left+i.right)-(b.left+b.right))>1||Math.abs((i.top+i.bottom)-(b.top+b.bottom))>1) out.push(id+' icon off-center');
          }
          const ind=document.getElementById('bankAlert');
          if (ind) {const ir=ind.getBoundingClientRect(); if (ir.width<10||ir.left<row.left-0.5||ir.right>row.right+0.5) out.push('alert indicator not visible');}
          if (/FOLDER_SLOT|ownership|NAND|slot unknown|Configuration/i.test(bank.innerText)) out.push('internal diagnostics shown');
        }
        if (document.documentElement.scrollWidth>innerWidth) out.push('horizontal page scroll');
        return out;},longName);
      assert.deepEqual(bad,[],`${state} header at ${width}px`);
    }};
    const INFO="Switching banks here only changes what 3DSort displays. It doesn't switch banks on your console. Inactive bank layouts may be incomplete.";
    const statusText=()=>page.locator('#bankStatus [role=status]').innerText();
    let accept=false; page.on('dialog',d=>accept ? d.accept() : d.dismiss());
    await page.goto(base); await page.locator('#bankSelect').waitFor();
    assert.deepEqual(await page.locator('#bankSelect option').allInnerTexts(), ['Active bank','Archive']);
    assert.equal((await statusText()).trim(),'');
    assert.equal(await page.locator('#bankStatus [role=alert]').count(),0);
    assert.equal(await page.locator('#bankInfo').getAttribute('aria-label'),INFO);
    assert.equal(await page.locator('#bankInfo').getAttribute('title'),INFO);
    assert.equal(await page.locator('#bankInfo').getAttribute('tabindex'),'0');
    await checkHeader('active');
    const api=async(name,args=[]) => (await page.request.post(base+'/api/'+name,{data:{args}})).json();
    const active=await api('get_state');
    await api('move_item',[0]); await page.reload(); await page.locator('#bankSelect').waitFor();
    await page.selectOption('#bankSelect','slot:1');
    await page.waitForFunction(()=>document.querySelector('#bankSelect')?.value==='active' && !document.querySelector('#bankSelect').disabled);
    accept=true; await page.selectOption('#bankSelect','slot:1');
    await page.waitForFunction(()=>document.querySelector('#bankSelect')?.value==='slot:1' && !document.querySelector('#bankSelect').disabled);
    const inactive=await api('get_state');
    assert(inactive.banks.readOnly); assert.notDeepEqual(inactive.items,active.items);
    assert.equal(await page.locator('[draggable="true"]').count(),0);
    assert.equal((await statusText()).trim(),"Read-only · Some system items aren't shown.");
    assert.equal(await page.locator('#bankAlert').count(),0);  // a read-only limitation is not an alert
    await checkHeader('inactive'); await page.setViewportSize({width:1280,height:800});
    assert.equal(await page.locator('#writeBtn').getAttribute('aria-disabled'),'true');
    await page.locator('#writeBtn').click();
    assert.match(await page.locator('#toast').innerText(),/Inactive bank is read-only/);
    assert((await api('sort_preset',['az'])).error.includes('read-only'));
    await page.locator('[data-tab="SYNC"]').click();
    assert.equal(await page.locator('#bankSelect').inputValue(),'slot:1');
    await page.selectOption('#bankSelect','active');
    await page.waitForFunction(()=>document.querySelector('#bankSelect')?.value==='active' && !document.querySelector('#bankSelect').disabled);
    assert.deepEqual((await api('get_state')).items,active.items);
    await page.locator('[data-tab="GRID"]').click();
    // Back on the active bank, the read-only lock must be gone without a reload.
    assert.equal(await page.locator('#writeBtn').getAttribute('aria-disabled'),null);
    assert.equal(await page.locator('#writeBtn').evaluate(e=>e.style.opacity),'');
    await page.locator('#writeBtn').click();
    assert.doesNotMatch(await page.locator('#toast').innerText(),/read-only/);
    require('node:fs').mkdirSync('.cache',{recursive:true});
    await page.screenshot({path:'.cache/3dsbank-ui.png'});
    // Actionable alerts stay visible in the header without growing it.
    const ALERT='Active bank changed or disconnected. Re-import before editing.';
    const LONG='Archive of every cartridge dump from the 2019 collection before the big reorganisation';
    await page.route('**/api/**',async route=>{const r=await route.fetch(); const j=await r.json(); if (j&&j.banks) {j.banks.alerts=[ALERT]; j.banks.banks[1].name=LONG;} await route.fulfill({response:r,json:j});});
    await page.reload(); await page.locator('#bankAlert').waitFor();
    assert.match(await page.locator('#bankStatus [role=alert]').innerText(),/Re-import before editing/);
    assert.equal(await page.locator('#bankAlert').getAttribute('aria-label'),'Action needed: '+ALERT);
    assert.equal(await page.locator('#bankAlert').getAttribute('title'),ALERT);
    await checkHeader('alert with a long bank name',true);
    await page.setViewportSize({width:929,height:800});
    await page.locator('#bankAlert').focus(); await page.keyboard.press('Enter');  // keyboard reaches the full text
    assert.equal(await page.locator('#toast').innerText(),ALERT);
    await page.unroute('**/api/**');
    await page.goto('http://127.0.0.1:8396'); await page.locator('#grid').waitFor();
    assert.equal(await page.locator('#bankSelect').count(),0);
    await checkHeader('ordinary card');
    assert(await page.locator('[draggable="true"]').count()>0);
    assert.deepEqual(errors,[]);
    console.log('3DSBank UI checks passed');
  } finally {if(browser) await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
