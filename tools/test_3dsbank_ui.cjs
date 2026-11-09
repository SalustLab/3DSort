// Exercises real bank API selection against isolated synthetic SD data.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const assert = require('node:assert/strict');
(async () => {
  const base = 'http://127.0.0.1:8398';
  const server = spawn(process.env.PYTHON || 'python', ['-c', "import sys; sys.path.insert(0, 'tests'); from test_bank_integration import bank_api; from app import serve, build_api; import threading; threading.Thread(target=serve,args=(build_api(mock=True),8396),daemon=True).start(); api, home = bank_api(); serve(api, 8398)"], {cwd:require('node:path').resolve(__dirname,'..'),windowsHide:true});
  let browser;
  try {
    let ready = false;
    for (let i=0;i<100;i++) {try {ready=(await fetch(base)).ok;} catch {} if(ready) break; await new Promise(r=>setTimeout(r,100));}
    assert(ready);
    browser = await chromium.launch({headless:true});
    const page = await browser.newPage();
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    let accept=false; page.on('dialog',d=>accept ? d.accept() : d.dismiss());
    await page.goto(base); await page.locator('#bankSelect').waitFor();
    assert.match(await page.locator('#bankSelect').innerText(), /Archive - Inactive/);
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
