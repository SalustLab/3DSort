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
    const checkHeader=async(state)=>{for (const [width,height] of [[929,800],[1280,800],[1920,1080]]) {
      await page.setViewportSize({width,height});
      const bad=await page.evaluate(()=>{
        const bar=document.querySelector('.topbar').getBoundingClientRect(), out=[];
        const els=[document.querySelector('.topbar').firstElementChild,...['tabs','sdinfo','bankStatus','writeBtn','gearBtn'].map(id=>document.getElementById(id))];
        const rects=els.map(e=>[e.id||'logo',e.getBoundingClientRect()]);
        for (const [id,r] of rects) if (r.top<bar.top-0.5||r.bottom>bar.bottom+0.5) out.push(id+' leaves the header');
        for (let i=1;i<rects.length;i++) if (rects[i][1].left<rects[i-1][1].right-0.5) out.push(rects[i][0]+' overlaps '+rects[i-1][0]);
        for (const [id,r] of rects) {const e=id==='logo'?els[0]:document.getElementById(id); if (id!=='bankStatus'&&e.scrollWidth>e.clientWidth+1) out.push(id+' is squeezed');}
        const gear=document.getElementById('gearBtn').getBoundingClientRect();
        if (gear.width<gear.height-1) out.push('gearBtn is squeezed');
        const bankRow=document.querySelector('#bankStatus .bank-row');
        if (!bankRow.querySelector('button')&&bankRow.scrollWidth>bankRow.clientWidth+1) out.push('bank selector row scrolls');
        const sd=document.getElementById('sdinfo');
        if (sd.getBoundingClientRect().height>parseFloat(getComputedStyle(sd).lineHeight)*2+1) out.push('SD info wraps past two lines');
        const bank=document.getElementById('bankStatus');
        if (bank.scrollHeight>bank.clientHeight+1) out.push('bank status overflows vertically');
        const select=document.getElementById('bankSelect').getBoundingClientRect(), row=bank.querySelector('.bank-row').getBoundingClientRect();
        if (Math.min(select.right,row.right)-select.left<120) out.push('bank selector too narrow to read');
        if (document.documentElement.scrollWidth>innerWidth) out.push('horizontal page scroll');
        return out;});
      assert.deepEqual(bad,[],`${state} header at ${width}px`);
    }};
    let accept=false; page.on('dialog',d=>accept ? d.accept() : d.dismiss());
    await page.goto(base); await page.locator('#bankSelect').waitFor();
    assert.deepEqual(await page.locator('#bankSelect option').allInnerTexts(), ['Active bank (slot unknown)','Archive (inactive)']);
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
    assert.match(await page.locator('#bankStatus').innerText(),/Partial SD layout/);
    await checkHeader('inactive'); await page.setViewportSize({width:1280,height:800});
    assert((await api('sort_preset',['az'])).error.includes('read-only'));
    await page.locator('[data-tab="SYNC"]').click();
    assert.equal(await page.locator('#bankSelect').inputValue(),'slot:1');
    await page.selectOption('#bankSelect','active');
    await page.waitForFunction(()=>document.querySelector('#bankSelect')?.value==='active' && !document.querySelector('#bankSelect').disabled);
    assert.deepEqual((await api('get_state')).items,active.items);
    await page.locator('[data-tab="GRID"]').click();
    require('node:fs').mkdirSync('.cache',{recursive:true});
    await page.screenshot({path:'.cache/3dsbank-ui.png'});
    await page.goto('http://127.0.0.1:8396'); await page.locator('#grid').waitFor();
    assert.equal(await page.locator('#bankSelect').count(),0);
    assert(await page.locator('[draggable="true"]').count()>0);
    assert.deepEqual(errors,[]);
    console.log('3DSBank UI checks passed');
  } finally {if(browser) await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;});
