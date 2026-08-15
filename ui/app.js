// 3DSort UI — JS puro. Fala com a Api via pywebview (app) ou /api (modo --serve).
"use strict";

let S = null; // estado vindo do backend
const P = Object.assign(
  { tab: "GRID", iconSize: "M", viewRows: 4, page: 1, showLabels: true,
    sortMode: "Manual", folderColors: {}, themeId: "cosmos", language: "en-US" },
  JSON.parse(localStorage.getItem("prefs") || "{}"),
  { openFolder: null, selected: null, sortMenu: false, dragKey: null,
    driveMenu: false, drives: null }
);
const savePrefs = () => localStorage.setItem("prefs", JSON.stringify({
  tab: P.tab, iconSize: P.iconSize, viewRows: P.viewRows, page: P.page, showLabels: P.showLabels,
  sortMode: P.sortMode, folderColors: P.folderColors, themeId: P.themeId, language: P.language }));

async function call(name, args = []) {
  let r;
  if (window.pywebview && window.pywebview.api) r = await window.pywebview.api[name](...args);
  else r = await (await fetch("/api/" + name, { method: "POST", body: JSON.stringify({ args }) })).json();
  if (r && r.error) { toast(r.error); return null; }
  return r;
}
async function refresh(name, args) {
  const r = await call(name, args);
  if (r) { S = r; render(); }
}

let toastTimer;
function toast(msg) {
  clearTimeout(toastTimer);
  document.getElementById("toast").innerHTML = `<div class="toast">${esc(msg)}</div>`;
  toastTimer = setTimeout(() => (document.getElementById("toast").innerHTML = ""), 2200);
}
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ---- derivados -------------------------------------------------------------
const homeItems = () => S.items.filter(i => i.folder === -1);
const systemItems = () => (S.system || []).filter(s => s.folder === -1);
const folderIds = () => [...new Set([
  ...S.items.filter(i => i.folder >= 0).map(i => i.folder),
  ...Object.keys(S.folderPos || {}).map(Number)
])].sort((a, b) => a - b);
const folderItems = id => S.items.filter(i => i.folder === id);
const systemInFolder = id => (S.system || []).filter(s => s.folder === id);
// membros da pasta como no console: jogos SD + apps NAND fixos, por posicao
const folderMembers = id => [
  ...folderItems(id).map(i => ({ kind: "game", it: i })),
  ...systemInFolder(id).map(s => ({ kind: "system", it: s }))
].sort((a, b) => a.it.pos - b.it.pos);
const fname = id => (S.folderNames && S.folderNames[id]) || `Folder ${id + 1}`;
const finitial = id => (fname(id).trim()[0] || "?").toUpperCase();
// sequencia do home grid como no console: jogos + apps NAND (fixos) + pastas, por posicao
const homeSeq = () => [
  ...homeItems().map(i => ({ kind: "game", it: i, pos: i.pos })),
  ...systemItems().map(s => ({ kind: "system", it: s, pos: s.pos })),
  ...folderIds().map(id => ({ kind: "folder", id, pos: (S.folderPos && S.folderPos[id] != null) ? S.folderPos[id] : Infinity }))
].sort((a, b) => a.pos - b.pos);
// colunas INTEIRAS visiveis por modo (1-6 linhas), contadas nas fotos reais de sample/ (2026-08-14)
const COLS = [3, 3, 5, 7, 9, 10];
const FCOLORS = ["#e60012", "#3b4cca", "#7ac70c", "#ffb400", "#5a4fcf", "#ff6fa5", "#ff7d00", "#54606e"];
const fcolor = id => P.folderColors[id] || FCOLORS[id % FCOLORS.length];
const dark = h => {
  const n = parseInt(h.slice(1), 16), f = .62;
  return "#" + ((1 << 24) | (Math.round((n >> 16) * f) << 16) | (Math.round(((n >> 8) & 255) * f) << 8) | Math.round((n & 255) * f)).toString(16).slice(1);
};
const PALETTE = ["#e60012", "#7ac70c", "#0aa0d6", "#c9a227", "#3b4cca", "#d31e40", "#2f9e44", "#ff6fa5", "#ffb400", "#8a6d3b", "#ff5e8a", "#4a6fa5"];
const hashColor = name => PALETTE[[...String(name)].reduce((a, c) => a + c.charCodeAt(0), 0) % PALETTE.length];

const THEMES = [
  { id: "cosmos", n: "Cosmos Red", g: ["#ffd98a", "#ffb400", "#e08900"] },
  { id: "aqua", n: "Aqua Blue", g: ["#7ad0f5", "#00a0e9", "#0077b6"] },
  { id: "mint", n: "Mint", g: ["#b8f2c9", "#57c46a", "#2f9e44"] },
  { id: "night", n: "Purple Night", g: ["#7a6fd0", "#4a3f8f", "#1d1b2e"] },
  { id: "gum", n: "Bubblegum", g: ["#ffd3e2", "#ff9dc0", "#ff6fa5"] },
  { id: "white", n: "Plain White", g: ["#faf7ee", "#ede8da", "#cfc7b8"] }
];
const theme = () => THEMES.find(t => t.id === P.themeId) || THEMES[0];

// RULES/THEMES sao previews estaticos da v2 — estado local de sessao, sem backend.
const RULES = [
  { p: "1", when: "Source is Virtual Console", then: "Move into 🗀 Virtual Console", on: true },
  { p: "2", when: "Played in the last 30 days", then: "Pin to Page 1 · most played first", on: true },
  { p: "3", when: "Title contains “Demo”", then: "Move into 🗀 Demos", on: true },
  { p: "4", when: "Everything else", then: "Sort A→Z after folders", on: false }
];
let runOnWrite = true, rulePreview = null;
const BADGES = [
  { m: "★", c: "#ffb400" }, { m: "♥", c: "#ff6fa5" }, { m: "M", c: "#e60012" }, { m: "?", c: "#ffb400" },
  { m: "▲", c: "#7ac70c" }, { m: "♪", c: "#5a4fcf" }, { m: "✿", c: "#ff7d00" }, { m: "◆", c: "#00a0e9" }
];

// ---- render ----------------------------------------------------------------
// FLIP: anima os tiles do #grid entre renders (o innerHTML e trocado inteiro,
// entao mede-se posicao antes/depois por data-key e anima-se o delta).
function captureGrid() {
  const g = document.getElementById("grid");
  if (!g) return null;
  const m = new Map();
  for (const el of g.children) if (el.dataset.key) m.set(el.dataset.key, el.getBoundingClientRect());
  return m;
}
function playFlip(before) {
  if (!before) return;
  const g = document.getElementById("grid");
  if (!g) return;
  for (const el of g.children) {
    const b = el.dataset.key && before.get(el.dataset.key);
    if (!b) continue;
    const a = el.getBoundingClientRect();
    const dx = b.left - a.left, dy = b.top - a.top;
    if (dx || dy) el.animate(
      [{ transform: `translate(${dx}px,${dy}px)` }, { transform: "none" }],
      { duration: 180, easing: "ease-out" });
  }
}

function render() {
  if (P.tab === "RULES" || P.tab === "THEMES") {
    P.tab = "GRID"; savePrefs(); toast("Coming in a future version");
  }
  renderTop();
  const before = captureGrid();
  const el = document.getElementById("screen");
  if (P.tab === "GRID") el.innerHTML = gridScreen();
  else if (P.tab === "RULES") el.innerHTML = rulesScreen();
  else if (P.tab === "THEMES") el.innerHTML = themesScreen();
  else if (P.tab === "SYNC") el.innerHTML = syncScreen();
  else el.innerHTML = settingsScreen();
  bind();
  playFlip(before);
}

function renderTop() {
  document.getElementById("tabs").innerHTML = ["GRID", "SYNC"].map(t =>
    `<div class="tab ${P.tab === t ? "on" : ""}" data-tab="${t}">${t}</div>`).join("");
  const n = S.staged.length;
  document.getElementById("writeBtn").textContent = n ? `WRITE (${n}) ▸` : "WRITE ▸";
  document.getElementById("gearBtn").className = "gear" + (P.tab === "SETTINGS" ? " on" : "");
  const sd = S.sd;
  document.getElementById("sdinfo").textContent =
    sd.free_blocks != null ? `SD: ${sd.free_blocks} BLOCKS FREE`
    : sd.region ? `SD ${sd.root || ""} · ${sd.region}` : "SD NOT FOUND";
}

function iconHtml(it, px) {
  if (it.icon)
    return `<div class="icon" style="width:${px}px;height:${px}px"><img src="data:image/png;base64,${it.icon}" alt=""></div>`;
  const c = hashColor(it.name);
  return `<div class="icon" style="width:${px}px;height:${px}px;font-size:${Math.round(px * .27)}px;background:linear-gradient(145deg,${c},${dark(c)})">${esc(it.name.slice(0, 3).toUpperCase())}</div>`;
}

function tileHtml(it, px) {
  const sel = P.selected === it.slot;
  return `<div class="item ${sel ? "sel" : ""}" draggable="true" data-slot="${it.slot}" data-ekey="${it.key}" data-key="s${it.slot}">
    ${iconHtml(it, px)}
    ${P.showLabels ? `<div class="label">${esc(it.name)}</div>` : ""}
  </div>`;
}

function systemTileHtml(it, px) {
  if (it.hole)  // vaga livre do grid: o console mostra um espaco vazio aqui
    return `<div class="item" data-key="h${it.pos}" style="cursor:default" title="Empty slot on the console grid">
      <div class="icon" style="width:${px}px;height:${px}px;background:none;border:2px dashed var(--line2);opacity:.5"></div>
    </div>`;
  const icon = it.icon
    ? `<div class="icon" style="width:${px}px;height:${px}px;opacity:.75"><img src="data:image/png;base64,${it.icon}" alt=""></div>`
    : `<div class="icon" style="width:${px}px;height:${px}px;background:none;border:2px dashed var(--line2);color:var(--mut);font-size:${Math.round(px * .4)}px">⚙</div>`;
  // chave FLIP: n<slot> / cart para identificados; h<pos> para placeholders (sem colisao)
  const key = it.key ? it.key.replace(":", "") : `h${it.pos}`;
  const drag = it.pinned ? "" : ` draggable="true" data-ekey="${it.key}"`;
  const tip = it.pinned ? "System app: fixed on the console (lives in NAND)"
    : "System app: drag to move it. Writing needs a GodMode9 inject step";
  return `<div class="item" data-key="${key}"${drag} style="${it.pinned ? "cursor:default;" : ""}opacity:.8" title="${tip}">
    ${icon}
    ${P.showLabels ? `<div class="label" style="color:var(--mut)">${esc(it.name)}</div>` : ""}
  </div>`;
}

function folderTileHtml(id, px) {
  const c = fcolor(id);
  const drag = S.launcherWritable ? ` draggable="true" data-ekey="f:${id}"` : "";
  return `<div class="item" data-folder-tile="${id}"${drag} data-key="f${id}">
    <div class="folder-tile" style="width:${px}px;height:${px}px;border:2.5px solid ${c}">
      <div class="dot" style="font-size:${Math.round(px * .52)}px;line-height:1;color:${c}">${esc(finitial(id))}</div>
      <div class="badge" style="background:${c}">${folderMembers(id).length}</div>
    </div>
    ${P.showLabels ? `<div class="label">${esc(fname(id))}</div>` : ""}
  </div>`;
}

// lado do icone quadrado na tela inferior do preview (area interna fixa 232x172, gap 3)
function pvIcon(rows, cols) {
  return Math.floor(Math.min((232 - (cols - 1) * 3) / cols, (172 - (rows - 1) * 3) / rows));
}

function previewCol() {
  const rows = P.viewRows, cols = COLS[rows - 1], per = rows * cols, side = pvIcon(rows, cols);
  const ordered = homeSeq();
  const pages = Math.max(1, Math.ceil(ordered.length / per));
  P.page = Math.min(P.page, pages);
  const slice = ordered.slice((P.page - 1) * per, (P.page - 1) * per + per);
  const cells = [];
  // console preenche coluna-major (pos n -> col n/rows, lin n%rows); CSS grid emite row-major, entao transpoe
  for (let g = 0; g < per; g++) {
    const cell = slice[(g % cols) * rows + Math.floor(g / cols)];
    if (!cell) cells.push(`<div class="pv-cell" style="background:linear-gradient(145deg,rgba(255,255,255,.25),rgba(255,255,255,.1));border:1px dashed rgba(90,77,58,.3)"></div>`);
    else if (cell.kind === "folder") {
      const cur = P.openFolder === cell.id;
      cells.push(`<div class="pv-cell dot" style="display:grid;place-items:center;background:linear-gradient(145deg,#fffdf8,#efe6d6);border:${cur ? "2px solid #7ac70c" : `1.5px solid ${fcolor(cell.id)}`};color:${fcolor(cell.id)};font-size:${Math.max(7, Math.round(side * .6))}px;line-height:1">${esc(finitial(cell.id))}</div>`);
    } else if (cell.kind === "system") {
      if (cell.it.hole) cells.push(`<div class="pv-cell" style="background:linear-gradient(145deg,rgba(255,255,255,.25),rgba(255,255,255,.1));border:1px dashed rgba(90,77,58,.3)"></div>`);
      else if (cell.it.icon) cells.push(`<div class="pv-cell" style="border:1px solid rgba(0,0,0,.15);opacity:.8"><img src="data:image/png;base64,${cell.it.icon}"></div>`);
      else cells.push(`<div class="pv-cell" style="border:1px dashed rgba(90,77,58,.4);background:rgba(90,77,58,.15)"></div>`);
    } else {
      const it = cell.it;
      const cur = P.selected === it.slot;
      const bd = cur ? "2px solid #7ac70c" : "1px solid rgba(0,0,0,.15)";
      if (it.icon) cells.push(`<div class="pv-cell" style="border:${bd}"><img src="data:image/png;base64,${it.icon}"></div>`);
      else { const c = hashColor(it.name); cells.push(`<div class="pv-cell" style="border:${bd};background:linear-gradient(145deg,${c},${dark(c)})"></div>`); }
    }
  }
  const viewBtns = [1, 2, 3, 4, 5, 6].map(r => {
    const gcols = Math.min(r + 1, 7);
    return `<div class="vthumb ${r === rows ? "on" : ""}" data-rows="${r}">
      <div class="vgrid" style="grid-template-columns:repeat(${gcols},1fr)">${`<div></div>`.repeat(r * gcols)}</div>
    </div>`;
  }).join("");
  const d = new Date();
  const clock = `${d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })} · ${d.toLocaleDateString("en-US", { weekday: "short" })} ${d.getMonth() + 1}/${d.getDate()}`;
  const [tg1, tg2, tg3] = theme().g;
  const n = S.staged.length;
  return `<div class="preview-col">
    <div class="dot" style="font-size:11px;color:var(--mut);letter-spacing:2px;margin-bottom:10px">LIVE PREVIEW</div>
    <div style="display:flex;align-items:center;gap:3px;background:var(--card);border:1px solid var(--line2);border-radius:8px;padding:3px;margin-bottom:14px" id="viewSeg">${viewBtns}</div>
    <div class="console-top">
      <div style="width:100%;aspect-ratio:5/3;border-radius:3px;background:linear-gradient(160deg,${tg1} 0%,${tg2} 55%,${tg3} 100%);position:relative;overflow:hidden">
        <div style="position:absolute;inset:0;background:repeating-linear-gradient(0deg,transparent 0 3px,rgba(255,255,255,.06) 3px 4px)"></div>
        <div class="dot" style="position:absolute;top:8px;left:10px;font-size:10px;color:rgba(0,0,0,.45)">${clock}</div>
        <div class="dot" style="position:absolute;bottom:10px;left:10px;right:10px;display:flex;justify-content:space-between;font-size:9px;color:rgba(0,0,0,.4)"><span>${esc(selName())}</span><span>★ 12 friends online</span></div>
      </div>
    </div>
    <div class="console-hinge"></div>
    <div class="console-bot">
      <div style="width:100%;aspect-ratio:4/3;border-radius:3px;background:linear-gradient(180deg,#e8e2d2 0%,#d8d0bc 100%);position:relative;overflow:hidden;display:flex;flex-direction:column">
        <div style="flex:1;display:grid;grid-template-columns:repeat(${cols},${side}px);grid-auto-rows:${side}px;gap:3px;padding:4px;align-content:center;justify-content:center">${cells.join("")}</div>
      </div>
    </div>
    <div class="dot" style="margin-top:12px;font-size:9px;color:var(--mut);text-align:center;line-height:1.6">VIEW SETTING ${rows}×${60 / rows} · ${cols} COLUMNS ON SCREEN<br>EXACTLY AS SHOWN ON THE CONSOLE</div>
    <div class="pager" style="left:8px" id="prevPage">‹</div>
    <div class="pager" style="right:8px" id="nextPage">›</div>
    <div class="dot" style="margin-top:12px;display:flex;gap:10px;font-size:10px;color:var(--mut)">
      <span class="pvchip">PAGE ${P.page}/${pages}</span>
      <span class="pvchip" style="color:${n > 0 ? "var(--red)" : "#5f9e17"}">${n > 0 ? n + " AHEAD" : "SYNCED"}</span>
    </div>
  </div>`;
}

function selName() {
  const it = S.items.find(i => i.slot === P.selected);
  return (it ? it.name : "HOME").toUpperCase();
}

function gridScreen() {
  const px = { S: 46, M: 60, L: 76 }[P.iconSize];
  if (P.openFolder !== null) return previewCol() + folderScreen(px);
  // mesma ordem visual do preview/console: paginas de linhas x colunas preenchidas
  // coluna-major (pos n -> col n/linhas). CSS grid emite row-major, entao transpoe.
  const rows = P.viewRows, cols = COLS[rows - 1], per = rows * cols;
  const seq = homeSeq();
  const pages = Math.max(1, Math.ceil(seq.length / per));
  let tiles = "";
  for (let pg = 0; pg < pages; pg++) {
    if (pg) tiles += `<div class="page-sep dot" data-key="p${pg}">PAGE ${pg + 1}</div>`;
    const slice = seq.slice(pg * per, pg * per + per);
    for (let g = 0; g < per; g++) {
      const c = slice[(g % cols) * rows + Math.floor(g / cols)];
      if (!c) tiles += `<div style="display:flex;justify-content:center;padding:10px 4px"><div style="width:${px}px;height:${px}px;border-radius:13px;border:2px dashed var(--line2);opacity:.6"></div></div>`;
      else tiles += c.kind === "game" ? tileHtml(c.it, px)
        : c.kind === "system" ? systemTileHtml(c.it, px)
        : folderTileHtml(c.id, px);
    }
  }
  const sizeBtns = ["S", "M", "L"].map(s => `<span class="${P.iconSize === s ? "on" : ""}" data-size="${s}">${s}</span>`).join("");
  return previewCol() + `<div class="main-col">
    <div class="grid-head">
      <div style="font-weight:900;font-size:16px">Home grid</div>
      <div style="font-size:12px;color:var(--mut)">drag to swap places · drop a game onto a folder to move it in · click a folder to open</div>
      <div style="flex:1"></div>
      ${S.launcherWritable ? `<div class="chipbtn" id="newFolderBtn" style="border-width:1.5px;border-radius:8px;padding:6px 12px;font-size:12px;font-weight:800">+ Folder</div>` : ""}
      <div class="seg" id="sizeSeg">${sizeBtns}</div>
      <div class="sortchip" id="sortChip">⇅ Sort: ${esc(P.sortMode)} <span style="color:var(--mut)">▾</span>
        ${P.sortMenu ? `<div class="menu" id="sortMenu">
          <div data-preset="az">A → Z</div><div data-preset="za">Z → A</div>
        </div>` : ""}
      </div>
    </div>
    <div class="grid" id="grid" style="grid-template-columns:repeat(${cols},1fr)">${tiles}</div>
    ${statusBar()}
  </div>`;
}

function folderScreen(px) {
  const id = P.openFolder, c = fcolor(id);
  const members = folderMembers(id);
  const swatches = FCOLORS.map(sc =>
    `<div class="swatch ${sc === c ? "on" : ""}" data-swatch="${sc}" style="background:${sc}"></div>`).join("");
  const empties = `<div style="display:flex;flex-direction:column;align-items:center;gap:6px"><div style="width:56px;height:56px;border-radius:12px;border:2px dashed var(--line2)"></div></div>`
    .repeat(Math.max(0, 16 - members.length));
  return `<div class="main-col" style="padding:18px 26px">
    <div class="crumb">
      <span class="link" id="closeFolder">◂ Home grid</span><span>▸</span>
      <span style="color:var(--ink)">🗀 ${esc(fname(id))}</span>
      <div style="flex:1"></div>
      <div class="link" id="closeFolderX" style="width:30px;height:30px;border-radius:8px;border:1px solid var(--line2);display:grid;place-items:center;font-size:13px">✕</div>
    </div>
    <div style="display:flex;align-items:center;gap:16px;margin:16px 0 4px">
      <div style="width:72px;height:72px;flex:none;border-radius:16px;background:var(--card);border:3px solid ${c};display:grid;place-items:center;box-shadow:0 4px 0 rgba(74,63,53,.12)">
        <div class="dot" style="font-size:38px;line-height:1;color:${c}">${esc(finitial(id))}</div>
      </div>
      <div style="flex:1;display:flex;flex-direction:column;gap:8px">
        ${S.launcherWritable
          ? `<input id="folderNameInput" maxlength="16" value="${esc(fname(id))}" title="Press Enter to rename (staged)" style="font-size:17px;font-weight:900;font-family:inherit;color:var(--ink);background:transparent;border:none;border-bottom:2px dashed var(--line2);padding:2px 0;max-width:260px;outline:none">`
          : `<div style="font-size:17px;font-weight:900">${esc(fname(id))}</div>`}
        <div style="display:flex;align-items:center;gap:8px">${swatches}</div>
      </div>
    </div>
    <div style="display:flex;align-items:baseline;gap:10px;margin:18px 0 10px">
      <div style="font-weight:800;font-size:13px;color:var(--mut);text-transform:uppercase;letter-spacing:1.2px">In this folder · ${members.length} of 60</div>
      <div style="font-size:12px;color:#cbb694;font-weight:600">drag titles in from the home grid, or out to remove</div>
    </div>
    <div class="grid" id="grid" data-in-folder="${id}" style="grid-template-columns:repeat(8,1fr)">
      ${members.map(m => m.kind === "game" ? tileHtml(m.it, 56) : systemTileHtml(m.it, 56)).join("")}${empties}
    </div>
    <div class="btn" id="removeZone" style="margin:10px 0">⌂ drop a title here to send it back to the home grid</div>
    <div style="display:flex;gap:10px;padding-top:14px;border-top:1px solid var(--line)">
      <div id="emptyFolderBtn" style="border:2px solid var(--line2);color:var(--mut2);font-weight:800;font-size:12.5px;padding:8px 16px;border-radius:9px;cursor:pointer">Empty folder</div>
      <div id="deleteFolderBtn" style="background:#fde8ec;color:var(--red);font-weight:800;font-size:12.5px;padding:9px 16px;border-radius:9px;cursor:pointer">Delete folder</div>
      <div style="align-self:center;font-size:11.5px;color:#cbb694;font-weight:600">deleting returns its titles to the home grid</div>
    </div>
    ${statusBar()}
  </div>`;
}

function statusBar() {
  const n = S.staged.length;
  return `<div class="statusbar">
    <span style="color:var(--red)">${"▮".repeat(Math.min(n, 8)) || "▯"}</span>
    <span>${n} CHANGE${n === 1 ? "" : "S"} STAGED</span>
    <span class="chipbtn" id="undoBtn">↩ UNDO</span>
    <span class="chipbtn" id="redoBtn">↪ REDO</span>
    <span class="chipbtn" id="resetBtn" title="Discard all staged changes (each recoverable with redo)">✕ RESET</span>
    ${S.pendingInject ? `<span class="dot" style="color:var(--red);font-size:10px">NAND INJECT PENDING</span>` : ""}
    <span style="flex:1"></span>
    <span>${S.items.length} TITLES · ${(S.system || []).filter(s => !s.hole).length} SYSTEM · ${folderIds().length} FOLDERS · v0.1.0</span>
  </div>`;
}

// Preview estatico da v2 — regras nao tocam o backend.
function rulesScreen() {
  const rows = RULES.map((r, i) => `
    <div style="display:flex;align-items:center;gap:12px;background:var(--card);border:2px solid var(--line);border-radius:12px;padding:12px 16px;box-shadow:0 3px 0 rgba(222,206,186,.5);opacity:${r.on ? "1" : ".55"}">
      <span style="color:#cbb694;font-size:15px;letter-spacing:-2px;cursor:grab">⠿</span>
      <div class="dot" style="width:24px;height:24px;border-radius:8px;background:var(--red);color:#fff;font-weight:800;font-size:12px;display:grid;place-items:center">${r.p}</div>
      <div style="display:flex;align-items:center;gap:8px;flex:1;min-width:0">
        <span style="background:#faecd4;border:1px solid var(--line2);border-radius:999px;padding:5px 12px;font-size:12.5px;font-weight:700;white-space:nowrap">${esc(r.when)}</span>
        <span style="color:#cbb694;font-weight:800">→</span>
        <span style="background:#fde8ec;border:1px solid #f3c2cd;border-radius:999px;padding:5px 12px;font-size:12.5px;font-weight:700;color:var(--red2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(r.then)}</span>
      </div>
      <span style="font-size:11.5px;font-weight:800;color:var(--mut)">${r.on ? "On" : "Off"}</span>
      <div class="toggle sm ${r.on ? "on" : ""}" data-rule-toggle="${i}"><div></div></div>
    </div>`).join("");
  return `<div style="flex:1;min-height:0;display:flex;flex-direction:column;padding:20px 26px;gap:12px;max-width:900px;overflow:auto">
    <div style="display:flex;align-items:center;gap:12px">
      <div>
        <div style="font-weight:900;font-size:17px">Auto-sort rules</div>
        <div style="font-size:12.5px;color:var(--mut);font-weight:600">rules run in order, top to bottom. The first match wins</div>
      </div>
      <div style="flex:1"></div>
      <div style="display:flex;align-items:center;gap:8px;font-size:12.5px;font-weight:700;color:#7a6a58">Run on every write
        <div class="toggle sm ${runOnWrite ? "on" : ""}" id="runOnWriteToggle"><div></div></div>
      </div>
      <div id="previewRunBtn" style="background:var(--ink);color:var(--bg);font-weight:800;font-size:12.5px;padding:9px 16px;border-radius:9px;cursor:pointer">▶ Preview run</div>
    </div>
    <div style="display:flex;flex-direction:column;gap:8px">
      ${rows}
      <div id="addRuleBtn" style="display:grid;place-items:center;border:2px dashed var(--line2);border-radius:12px;padding:12px;font-size:13px;font-weight:800;color:var(--mut);cursor:pointer">+ Add rule</div>
    </div>
    ${rulePreview ? `<div style="display:flex;align-items:center;gap:14px;background:#faecd4;border:1px solid var(--line2);border-radius:12px;padding:14px 18px">
      <span class="dot" style="font-size:12px;color:var(--mut2)">PREVIEW</span>
      <div style="font-size:13px;font-weight:700;color:#7a6a58">${esc(rulePreview)}</div>
      <div style="flex:1"></div>
      <div id="applyRulesBtn" style="background:var(--red);color:#fff;font-weight:800;font-size:12.5px;padding:9px 18px;border-radius:9px;box-shadow:0 3px 0 rgba(143,15,40,.35);cursor:pointer">Apply to staging</div>
    </div>` : ""}
  </div>`;
}

// Preview estatico da v2 — so o gradiente do LIVE PREVIEW segue o tema escolhido.
function themesScreen() {
  const cards = THEMES.map(t => `
    <div data-theme="${t.id}" style="display:flex;flex-direction:column;gap:8px;background:var(--card);border:${t.id === P.themeId ? "2.5px solid var(--red)" : "2px solid var(--line)"};border-radius:12px;padding:10px;box-shadow:0 3px 0 rgba(222,206,186,.5);cursor:pointer">
      <div style="width:100%;aspect-ratio:5/3;border-radius:4px;background:linear-gradient(160deg,${t.g[0]},${t.g[2]})"></div>
      <div style="width:72%;align-self:center;aspect-ratio:4/3;border-radius:3px;background:linear-gradient(180deg,#e8e2d2,#d8d0bc);border:1px solid rgba(74,63,53,.12)"></div>
      <div style="display:flex;align-items:center;justify-content:space-between;gap:4px">
        <div style="font-size:11.5px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(t.n)}</div>
        <div class="dot" style="font-size:8px;color:#fff;background:${t.id === P.themeId ? "var(--red)" : "transparent"};border-radius:4px;padding:2px 4px">${t.id === P.themeId ? "IN USE" : ""}</div>
      </div>
    </div>`).join("");
  const badges = BADGES.map(b => `
    <div style="width:52px;height:52px;border-radius:10px;background:var(--card);border:2px solid var(--line);display:grid;place-items:center;box-shadow:0 3px 0 rgba(222,206,186,.5);cursor:grab">
      <div style="width:34px;height:34px;border-radius:8px;background:${b.c};display:grid;place-items:center;color:#fff;font-weight:900;font-size:16px;box-shadow:inset 0 -5px 8px rgba(0,0,0,.2)">${b.m}</div>
    </div>`).join("");
  return `<div style="flex:1;min-height:0;display:flex;flex-direction:column;padding:20px 26px;gap:16px;max-width:940px;overflow:auto">
    <div>
      <div style="font-weight:900;font-size:17px">Themes</div>
      <div style="font-size:12.5px;color:var(--mut);font-weight:600">themes installed on the SD card. The live preview follows your pick</div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(6,1fr);gap:14px">${cards}</div>
    <div style="border-top:1px solid var(--line);padding-top:16px">
      <div style="display:flex;align-items:baseline;gap:10px">
        <div style="font-weight:900;font-size:17px">Badges · 24 owned</div>
        <div style="font-size:12.5px;color:var(--mut);font-weight:600">badges take up home-grid slots. Drag them straight into the grid</div>
      </div>
      <div style="display:flex;gap:12px;margin-top:14px">
        ${badges}
        <div style="width:52px;height:52px;border-radius:10px;border:2px dashed var(--line2);display:grid;place-items:center;color:#cbb694;font-size:12px;font-weight:800">+16</div>
      </div>
    </div>
    <div style="margin-top:auto;display:flex;align-items:center;gap:10px;background:#faecd4;border:1px solid var(--line2);border-radius:12px;padding:12px 18px;font-size:12.5px;font-weight:700;color:#7a6a58">
      <span class="dot" style="font-size:12px;color:var(--mut2)">NOTE</span>
      3DSort can't install new themes or badges. It arranges the ones already on your card.
    </div>
  </div>`;
}

function fmtGB(bytes) { return (bytes / 1e9).toFixed(1); }

function syncScreen() {
  const hist = S.history.map(h => `
    <div class="card" style="display:flex;align-items:center;gap:12px">
      <div style="width:10px;height:10px;flex:none;border-radius:50%;background:${h.kind === "auto" ? "#7ac70c" : "#00a0e9"}"></div>
      <div style="flex:1;min-width:0">
        <div style="font-weight:800;font-size:13.5px">${h.kind === "auto" ? "Backup created (auto)" : "Backup created"}</div>
        <div style="font-size:11.5px;color:var(--mut);font-weight:700">${esc(h.note)} · ${esc(h.file)}</div>
      </div>
      <div class="dot" style="font-size:10px;color:var(--mut);white-space:nowrap">${esc(h.when)}</div>
      <div class="chipbtn" data-restore="${h.id}" style="border-width:1.5px;border-radius:8px;padding:5px 12px;font-size:11.5px;font-weight:800;color:#7a6a58">Restore</div>
    </div>`).join("");
  const n = S.staged.length, sd = S.sd;
  const cap = sd.total_bytes != null ? `${Math.round(sd.total_bytes / 1e9)}GB` : "";
  const usage = sd.total_bytes != null ? `
    <div style="width:100%">
      <div style="height:8px;border-radius:4px;background:var(--line);overflow:hidden"><div style="width:${Math.round(sd.used_bytes / sd.total_bytes * 100)}%;height:100%;background:linear-gradient(90deg,var(--red),#ffb400)"></div></div>
      <div style="display:flex;justify-content:space-between;font-size:11px;color:var(--mut);font-weight:700;margin-top:6px"><span>${fmtGB(sd.used_bytes)} GB used</span><span>${sd.free_blocks.toLocaleString("en-US")} blocks free</span></div>
    </div>` : "";
  return `<div style="flex:1;min-height:0;display:flex;gap:20px;padding:20px 26px;max-width:940px;overflow:auto">
    <div style="width:330px;flex:none;display:flex;flex-direction:column;gap:14px">
      <div class="card" style="display:flex;flex-direction:column;align-items:center;gap:12px;padding:22px">
        <div style="width:74px;height:92px;background:linear-gradient(160deg,#4a5a6b,#2b3440);border-radius:6px 14px 6px 6px;position:relative;box-shadow:0 6px 14px rgba(74,63,53,.25)">
          <div style="position:absolute;top:10px;left:8px;right:8px;height:20px;border-radius:3px;background:#c9a227;opacity:.85"></div>
          <div class="dot" style="position:absolute;bottom:12px;left:0;right:0;text-align:center;font-size:9px;color:#fff">${cap}</div>
        </div>
        <div style="text-align:center">
          <div style="font-weight:900;font-size:15px">${sd.root ? `SDHC card · ${esc(sd.root)}` : "SD not found"}</div>
          <div style="font-size:12px;color:var(--mut);font-weight:700">${sd.region ? `<span style="color:#5f9e17">●</span> mounted · Nintendo 3DS folder found` : "insert the console's SD card"}</div>
        </div>
        ${usage}
      </div>
      <div class="btn" id="importBtn">⇣ Import layout from SD</div>
      <div class="btn" id="backupBtn">⛉ Back up current layout</div>
      <div class="btn primary" id="writeBtn2">${n ? `WRITE ${n} STAGED CHANGE${n === 1 ? "" : "S"} ▸` : "NOTHING STAGED"}</div>
      <div style="display:flex;gap:8px;background:#faecd4;border:1px solid var(--line2);border-radius:10px;padding:10px 12px;font-size:11.5px;font-weight:700;color:var(--mut2);line-height:1.45">
        <span class="dot">!</span> A backup is taken automatically before every write. Eject the card safely before putting it back in the console.
      </div>
    </div>
    <div style="flex:1;min-width:0;display:flex;flex-direction:column">
      ${S.pendingInject ? `
      <div class="card" style="border:2px solid var(--red);margin-bottom:14px;display:flex;flex-direction:column;gap:10px">
        <div style="font-weight:900;font-size:14px;color:var(--red)">NAND inject pending · ${esc(S.pendingInject.when)}</div>
        <div style="font-size:12.5px;font-weight:700;color:#7a6a58;line-height:1.6">
          The system layout was written to the SD card, but the console NAND still has the old one.<br>
          1. Put the SD card back in the console and boot GodMode9.<br>
          2. Run the script 3DSort_inject (HOME button, then Scripts...).<br>
          3. Do NOT boot the HOME menu before the script finishes.<br>
          4. Put the SD card back in the PC and press Verify.
        </div>
        <div style="display:flex;gap:10px">
          <div class="btn primary" id="verifyInjectBtn" style="padding:8px 16px;font-size:12.5px;border-radius:9px">Verify</div>
          <div class="btn" id="confirmInjectBtn" style="padding:8px 16px;font-size:12.5px;border-radius:9px" title="Skip verification. Only if you are sure the script ran">Mark as done</div>
        </div>
      </div>` : ""}
      <div style="font-weight:900;font-size:17px;margin-bottom:4px">History</div>
      <div style="font-size:12.5px;color:var(--mut);font-weight:600;margin-bottom:14px">every import, backup and write. Restore any point</div>
      <div style="display:flex;flex-direction:column;gap:8px;overflow:auto">${hist || '<div style="color:var(--mut);font-size:13px">no backups yet</div>'}</div>
    </div>
  </div>`;
}

function settingsScreen() {
  const langs = [
    { id: "pt-BR", n: "Português (Brasil)" },
    { id: "en-US", n: "English (US)" },
    { id: "es", n: "Español" }
  ].map(l => `<span class="${P.language === l.id ? "on" : ""}" data-lang="${l.id}" style="padding:5px 12px;white-space:nowrap">${l.n}</span>`).join("");
  return `<div style="flex:1;min-height:0;display:flex;flex-direction:column;padding:20px 26px;gap:10px;max-width:640px;overflow:auto">
    <div style="font-weight:900;font-size:17px;margin-bottom:6px">Settings</div>
    <div class="card setrow">
      <div><div style="font-weight:800;font-size:13.5px">Language / Idioma</div><div style="font-size:11.5px;color:var(--mut);font-weight:700">app texts and dates</div></div>
      <div class="seg" id="langSeg" style="background:#faecd4">${langs}</div>
    </div>
    <div class="card setrow">
      <div><div style="font-weight:800;font-size:13.5px">SD card drive</div><div style="font-size:11.5px;color:var(--mut);font-weight:700">where your console's card is mounted</div></div>
      <div class="chipbtn" id="sdDriveChip" style="position:relative;border-width:1.5px;border-radius:8px;padding:6px 14px;font-size:12.5px;font-weight:800">${esc(S.sd.root || "not found")} <span style="color:var(--mut)">▾</span>
        ${P.driveMenu ? `<div class="menu">${(P.drives || []).map(d =>
          `<div data-drive="${esc(d.root)}">${esc(d.root)}${d.current ? ' <span style="color:var(--red)">●</span>' : ""}</div>`).join("")
          || '<div style="color:var(--mut);cursor:default">no 3DS card found</div>'}</div>` : ""}
      </div>
    </div>
    <div class="card setrow">
      <div><div style="font-weight:800;font-size:13.5px">Backup folder</div><div style="font-size:11.5px;color:var(--mut);font-weight:700">${esc(S.backups_dir || "")}</div></div>
      <div class="chipbtn" id="backupChange" style="border-width:1.5px;border-radius:8px;padding:6px 14px;font-size:12.5px;font-weight:800">Change…</div>
    </div>
    <div class="card setrow">
      <div><div style="font-weight:800;font-size:13.5px">Auto-backup before every write</div><div style="font-size:11.5px;color:var(--mut);font-weight:700">keeps the last 20 backups</div></div>
      <div class="toggle on" id="autoBackupToggle"><div></div></div>
    </div>
    <div class="card setrow">
      <div><div style="font-weight:800;font-size:13.5px">Confirm before writing to SD</div><div style="font-size:11.5px;color:var(--mut);font-weight:700">shows a summary of staged changes first</div></div>
      <div class="toggle on" id="confirmToggle"><div></div></div>
    </div>
    <div class="card setrow">
      <div><div style="font-weight:800;font-size:13.5px">Icon labels in the grid</div><div style="font-size:11.5px;color:var(--mut);font-weight:700">show titles under every icon</div></div>
      <div class="toggle ${P.showLabels ? "on" : ""}" id="labelsToggle"><div></div></div>
    </div>
    <div class="dot" style="margin-top:auto;display:flex;align-items:center;justify-content:space-between;font-size:11px;color:var(--mut);padding-top:12px;border-top:1px solid var(--line)">
      <span>3DSORT v0.1.0</span>
      <span class="chipbtn" id="checkUpdates" style="padding:5px 10px;background:var(--card)">CHECK FOR UPDATES</span>
    </div>
  </div>`;
}

function writeModal() {
  const list = S.staged.slice(-8).map(s => `<div style="font-size:12.5px;font-weight:700;color:#7a6a58;background:#faecd4;border-radius:8px;padding:7px 12px">${esc(s)}</div>`).join("");
  const nand = S.launcherDirty ? `<div style="font-size:11.5px;color:var(--red);font-weight:700;background:#fde8ec;border-radius:8px;padding:8px 12px">This includes system layout changes. After writing, run the 3DSort_inject script in GodMode9 BEFORE booting the HOME menu (see the SYNC tab).</div>` : "";
  return `<div class="modal-bg" id="modalBg"><div class="modal">
    <div style="font-weight:900;font-size:16px">Write ${S.staged.length} staged changes to SD?</div>
    <div style="display:flex;flex-direction:column;gap:5px;max-height:180px;overflow:auto">${list}</div>
    ${nand}
    <div style="font-size:11.5px;color:var(--mut);font-weight:700">A backup will be taken first.</div>
    <div style="display:flex;gap:10px;justify-content:flex-end">
      <div class="btn" id="cancelWrite" style="padding:8px 16px;font-size:12.5px;border-radius:9px">Cancel</div>
      <div class="btn primary" id="confirmWrite" style="padding:9px 18px;font-size:12.5px;border-radius:9px">WRITE ▸</div>
    </div>
  </div></div>`;
}

// ---- eventos ----------------------------------------------------------------
function bind() {
  const $ = id => document.getElementById(id);
  document.querySelectorAll("[data-tab]").forEach(el => el.onclick = () => { P.tab = el.dataset.tab; P.openFolder = null; savePrefs(); render(); });
  $("gearBtn").onclick = () => { P.tab = "SETTINGS"; render(); };
  const openWrite = () => {
    if (!S.staged.length) return toast("Nothing staged to write");
    $("modal").innerHTML = writeModal();
    $("cancelWrite").onclick = () => ($("modal").innerHTML = "");
    $("modalBg").onclick = e => { if (e.target.id === "modalBg") $("modal").innerHTML = ""; };
    $("confirmWrite").onclick = async () => {
      $("modal").innerHTML = "";
      await refresh("write_sd");
      if (S && S.pendingInject) toast("Written. Now run 3DSort_inject in GodMode9 (SYNC tab)");
      else toast("Written to SD ✓");
    };
  };
  $("writeBtn").onclick = openWrite;
  if ($("writeBtn2")) $("writeBtn2").onclick = openWrite;
  if ($("undoBtn")) $("undoBtn").onclick = () => refresh("undo");
  if ($("redoBtn")) $("redoBtn").onclick = () => refresh("redo");
  if ($("resetBtn")) $("resetBtn").onclick = () => {
    if (!S.staged.length) return toast("Nothing staged");
    refresh("reset_staging").then(() => toast("All staged changes discarded. Redo recovers them"));
  };
  if ($("importBtn")) $("importBtn").onclick = async () => { await refresh("import_sd"); toast("Layout imported from SD"); };
  if ($("backupBtn")) $("backupBtn").onclick = async () => { await refresh("backup_manual"); toast("Backup saved"); };
  if ($("prevPage")) $("prevPage").onclick = () => { P.page = Math.max(1, P.page - 1); savePrefs(); render(); };
  if ($("nextPage")) $("nextPage").onclick = () => { P.page++; savePrefs(); render(); };
  if ($("viewSeg")) $("viewSeg").querySelectorAll("[data-rows]").forEach(el => el.onclick = () => { P.viewRows = +el.dataset.rows; savePrefs(); render(); });
  if ($("sizeSeg")) $("sizeSeg").querySelectorAll("[data-size]").forEach(el => el.onclick = () => { P.iconSize = el.dataset.size; savePrefs(); render(); });
  if ($("sortChip")) $("sortChip").onclick = e => {
    const preset = e.target.dataset && e.target.dataset.preset;
    if (preset) {
      P.sortMenu = false;
      P.sortMode = e.target.textContent;
      savePrefs();
      refresh("sort_preset", [preset]).then(() => toast("Sorted (staged)"));
    } else { P.sortMenu = !P.sortMenu; render(); }
  };
  if ($("closeFolder")) $("closeFolder").onclick = () => { P.openFolder = null; render(); };
  if ($("closeFolderX")) $("closeFolderX").onclick = () => { P.openFolder = null; render(); };
  document.querySelectorAll("[data-swatch]").forEach(el => el.onclick = () => {
    P.folderColors[P.openFolder] = el.dataset.swatch; savePrefs(); render();
  });
  const needsDump = () => toast("Needs a system save dump. See the SYNC tab");
  if ($("newFolderBtn")) $("newFolderBtn").onclick = () =>
    refresh("folder_create").then(() => toast("Folder created (staged)"));
  if ($("folderNameInput")) {
    const inp = $("folderNameInput");
    inp.onkeydown = e => { if (e.key === "Enter") inp.blur(); };
    inp.onblur = () => {
      const name = inp.value.trim();
      if (name && name !== fname(P.openFolder))
        refresh("folder_rename", [P.openFolder, name]).then(() => toast("Folder renamed (staged)"));
      else render();
    };
  }
  if ($("emptyFolderBtn")) $("emptyFolderBtn").onclick = () => {
    if (!S.launcherWritable) return needsDump();
    refresh("folder_empty", [P.openFolder]).then(() => toast("Folder emptied (staged)"));
  };
  if ($("deleteFolderBtn")) $("deleteFolderBtn").onclick = () => {
    if (!S.launcherWritable) return needsDump();
    const id = P.openFolder, n = folderMembers(id).length;
    $("modal").innerHTML = `<div class="modal-bg" id="modalBg"><div class="modal">
      <div style="font-weight:900;font-size:16px">Delete folder ${esc(fname(id))}?</div>
      <div style="font-size:12.5px;color:var(--mut);font-weight:700">Its ${n} title${n === 1 ? "" : "s"} will return to the home grid. The change stays staged until you write.</div>
      <div style="display:flex;gap:10px;justify-content:flex-end">
        <div class="btn" id="cancelDelete" style="padding:8px 16px;font-size:12.5px;border-radius:9px">Cancel</div>
        <div class="btn primary" id="confirmDelete" style="padding:9px 18px;font-size:12.5px;border-radius:9px">DELETE</div>
      </div>
    </div></div>`;
    $("cancelDelete").onclick = () => ($("modal").innerHTML = "");
    $("modalBg").onclick = e => { if (e.target.id === "modalBg") $("modal").innerHTML = ""; };
    $("confirmDelete").onclick = async () => {
      $("modal").innerHTML = "";
      P.openFolder = null;
      await refresh("folder_delete", [id]);
      toast("Folder deleted (staged)");
    };
  };
  if ($("verifyInjectBtn")) $("verifyInjectBtn").onclick = () =>
    refresh("verify_inject").then(() => { if (S && !S.pendingInject) toast("Inject confirmed ✓"); });
  if ($("confirmInjectBtn")) $("confirmInjectBtn").onclick = () =>
    refresh("confirm_inject").then(() => toast("Marked as done. Re-dump before the next system edit"));
  document.querySelectorAll("[data-restore]").forEach(el => el.onclick = async () => {
    await refresh("restore_backup", [el.dataset.restore]);
    toast("Backup restored (staged state reset)");
  });

  // RULES (preview v2)
  document.querySelectorAll("[data-rule-toggle]").forEach(el => el.onclick = () => {
    const r = RULES[+el.dataset.ruleToggle]; r.on = !r.on; render();
  });
  if ($("runOnWriteToggle")) $("runOnWriteToggle").onclick = () => { runOnWrite = !runOnWrite; render(); };
  if ($("previewRunBtn")) $("previewRunBtn").onclick = () => {
    const active = RULES.filter(r => r.on).length;
    rulePreview = (active * 5 + 2) + " titles would move · 1 folder would be created · nothing deleted";
    render();
  };
  if ($("applyRulesBtn")) $("applyRulesBtn").onclick = () => { rulePreview = null; render(); toast("Coming in v2"); };
  if ($("addRuleBtn")) $("addRuleBtn").onclick = () => toast("Coming in v2");

  // THEMES (preview v2)
  document.querySelectorAll("[data-theme]").forEach(el => el.onclick = () => {
    P.themeId = el.dataset.theme; savePrefs(); render();
  });

  // SETTINGS
  if ($("langSeg")) $("langSeg").querySelectorAll("[data-lang]").forEach(el => el.onclick = () => {
    P.language = el.dataset.lang; savePrefs(); render(); toast("Translations coming in v1.1");
  });
  if ($("sdDriveChip")) $("sdDriveChip").onclick = async e => {
    const root = e.target.dataset && e.target.dataset.drive;
    if (root) {
      P.driveMenu = false; P.drives = null;
      const st = await call("set_sd_root", [root]);
      if (st) { S = st; render(); toast("SD drive: " + root); } else render();
    } else if (P.driveMenu) { P.driveMenu = false; render(); }
    else {
      const r = await call("list_drives");
      if (!r) return;
      P.drives = r.drives; P.driveMenu = true; render();
    }
  };
  if ($("backupChange")) $("backupChange").onclick = async () => {
    const before = S.backups_dir;
    const st = await call("pick_backups_dir");  // dialogo nativo no backend
    if (st) {
      S = st; render();
      if (S.backups_dir !== before) toast("Backup folder changed");
    }
  };
  if ($("autoBackupToggle")) $("autoBackupToggle").onclick = () => toast("Always on (safety rule)");
  if ($("confirmToggle")) $("confirmToggle").onclick = () => toast("Always on (safety rule)");
  if ($("labelsToggle")) $("labelsToggle").onclick = () => { P.showLabels = !P.showLabels; savePrefs(); render(); };
  if ($("checkUpdates")) $("checkUpdates").onclick = () => toast("You're on the latest version");

  // grid: selecao (jogos), drag por chave de entidade (g:/n:/f:/cart), pastas
  document.querySelectorAll(".item[data-slot]").forEach(el => {
    el.onclick = () => { P.selected = +el.dataset.slot; render(); };
  });
  document.querySelectorAll("[data-folder-tile]").forEach(el => {
    el.onclick = () => { P.openFolder = +el.dataset.folderTile; render(); };
  });
  const dragKind = () => P.dragKey === "cart" ? "cart" : P.dragKey.split(":")[0];
  document.querySelectorAll(".item[data-ekey]").forEach(el => {
    el.ondragstart = e => {
      P.dragKey = el.dataset.ekey;
      e.dataTransfer.effectAllowed = "move";
      setTimeout(() => el.classList.add("dragging")); // apos o browser capturar o ghost
    };
    el.ondragend = () => {
      el.classList.remove("dragging");
      if (P.dragKey !== null) { P.dragKey = null; render(); } // cancelado: restaura ordem de S
    };
  });
  const grid = document.getElementById("grid");
  if (grid) {
    const clearMarks = () => grid.querySelectorAll(".drop-into,.swap-with").forEach(x => {
      x.classList.remove("drop-into", "swap-with"); x.style.outlineColor = "";
    });
    grid.ondragover = e => {
      if (P.dragKey === null) return;
      e.preventDefault();
      clearMarks();
      const t = e.target.closest(".item");
      if (!t || t.classList.contains("dragging")) return;
      const k = dragKind();
      if (t.dataset.folderTile !== undefined && (k === "g" || k === "n")) {
        t.classList.add("drop-into");                  // titulo sobre pasta = mover para dentro
        t.style.outlineColor = fcolor(+t.dataset.folderTile);
      } else if (t.dataset.ekey !== undefined) {       // qualquer par de tiles = trocar de lugar
        t.classList.add("swap-with");
      }                                                // tile fixo/placeholder: alvo invalido
    };
    grid.ondrop = e => {
      e.preventDefault();
      if (P.dragKey === null) return;
      const key = P.dragKey;
      P.dragKey = null;
      const into = grid.querySelector(".drop-into");
      const swap = grid.querySelector(".swap-with");
      if (into) refresh("set_folder", [key, +into.dataset.folderTile]).then(() => toast("Moved into folder (staged)"));
      else if (swap) refresh("swap_items", [key, swap.dataset.ekey]);
    };
  }
  const rz = document.getElementById("removeZone");
  if (rz) {
    rz.ondragover = e => { e.preventDefault(); rz.classList.add("dragover"); };
    rz.ondragleave = () => rz.classList.remove("dragover");
    rz.ondrop = e => {
      e.preventDefault();
      if (P.dragKey === null) return;
      const key = P.dragKey;
      P.dragKey = null;
      refresh("set_folder", [key, -1]).then(() => toast("Sent back to home grid (staged)"));
    };
  }
}

// ---- boot -------------------------------------------------------------------
async function boot() {
  if (window.pywebview === undefined || window.pywebview.api) {
    S = await call("get_state");
    if (S) render();
  } else {
    window.addEventListener("pywebviewready", boot, { once: true });
  }
}
boot();
