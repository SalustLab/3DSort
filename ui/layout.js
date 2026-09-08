// Spatial editing and badge collection. Loaded before app.js; called after boot.
const B = { open: false, query: "", set: "", selected: null, images: {}, revision: null,
  limit: 40, shown: {}, loading: false, pickFolder: null };
const currentContainer = () => P.openFolder === null ? -1 : P.openFolder;
const rowsOf = folder => folder === -1 ? P.viewRows : (S.folderRows[folder] || 2);
const gridRows = () => rowsOf(currentContainer());
const capacityOf = folder => folder === -1 ? 360 : 60;
const badgeById = id => (S.badges?.catalog || []).find(b => b.id === id);
const hasBadges = () => (S.badges?.catalog || []).length > 0;
const singleBadges = () => (S.badges?.catalog || []).filter(b => b.sub === 0).sort((a, b) => a.name.localeCompare(b.name));
const decorationOf = fid => (S.badges?.placed || []).find(b => b.decoration === fid);
const badgeImage = (id, size = 48) => `<img data-badge-image="${id}" alt="${esc(badgeById(id)?.name || 'Badge')}"
  width="${size}" height="${size}" ${B.images[id] ? `src="data:image/png;base64,${B.images[id]}"` : ''}>`;
function folderArt(fid, size) {
  const badge = decorationOf(fid);
  return badge ? badgeImage(badge.badge, size) : esc(finitial(fid));
}

function containerSequence(folder) {
  const entries = [
    ...S.items.filter(i => i.folder === folder).map(it => ({kind: "game", it, pos: it.pos})),
    ...(S.system || []).filter(i => i.folder === folder).map(it => ({kind: "system", it, pos: it.pos})),
    ...(S.badges?.placed || []).filter(i => i.folder === folder && i.decoration === null)
      .map(it => ({kind: "badge", it, pos: it.pos}))
  ];
  if (folder === -1) entries.push(...folderIds().map(id => ({kind: "folder", id, pos: S.folderPos[id]})));
  const result = [];
  entries.forEach(e => { if (Number.isInteger(e.pos) && e.pos >= 0) result[e.pos] = e; });
  return result;
}

// Pages of empty cells shown for a container: never fewer than the content needs.
function pageInfo(folder) {
  const rows = rowsOf(folder), per = rows * COLS[rows - 1];
  const min = Math.max(1, Math.ceil(containerSequence(folder).length / per));
  const shown = Math.max(min, Math.ceil((B.shown[folder] || 0) / per));
  return { per, min, shown, max: Math.ceil(capacityOf(folder) / per) };
}

// Empty cells before the last occupied cell of any kind: what Compact closes.
function gapCount(folder) {
  const seq = containerSequence(folder);
  let gaps = 0;
  for (let p = 0; p < seq.length; p++) if (!seq[p]) gaps++;
  return gaps;
}
// System apps, folder tiles and the Game Card that sit after a gap: compacting
// them changes the Launcher, so the write will need the GodMode9 inject.
function launcherItemsAfterGap(folder) {
  const seq = containerSequence(folder);
  let gap = false, n = 0;
  for (let p = 0; p < seq.length; p++) {
    if (!seq[p]) gap = true;
    else if (gap && (seq[p].kind === "system" || seq[p].kind === "folder")) n++;
  }
  return n;
}

function emptyTile(folder, pos, px) {
  const enabled = S.spatialWritable && !S.recovery, rows = rowsOf(folder);
  const where = `Cell ${pos + 1} · column ${Math.floor(pos / rows) + 1}, row ${pos % rows + 1}`;
  return `<div class="item empty-cell" data-key="empty-${folder}-${pos}" data-cell="${pos}"
    data-container="${folder}" ${enabled ? `data-empty="true" tabindex="0" role="button"` : ''}
    aria-label="Empty position ${pos + 1}" title="${where}${enabled ? '. Drop here to move something into this cell' : '. Import a HOME menu dump to edit empty positions'}">
    <div style="width:${px}px;height:${px}px;border:2px dashed var(--line2);border-radius:12px"></div>
    <span class="cell-number">${pos + 1}</span></div>`;
}

function badgeTile(it, px) {
  const editable = S.badges.writable && !S.recovery;
  return `<div class="item badge-tile" data-key="b${it.slot}" data-cell="${it.pos}" data-container="${it.folder}"
    ${editable ? `draggable="true" data-ekey="${it.key}"` : ''}>
    ${badgeImage(it.badge, px)}${P.showLabels ? `<div class="label">${esc(it.name)}</div>` : ''}
    ${editable ? `<button class="badge-remove" data-remove-badge="${it.key}" title="Return to collection" aria-label="Remove ${esc(it.name)}">×</button>` : ''}</div>`;
}

function spatialTile(cell, folder, pos, px) {
  if (!cell) return emptyTile(folder, pos, px);
  if (cell.kind === "badge") return badgeTile(cell.it, px);
  return cell.kind === "game" ? tileHtml(cell.it, px) : cell.kind === "system"
    ? systemTileHtml(cell.it, px) : folderTileHtml(cell.id, px);
}

function spatialFolderGrid(folder, px) {
  const seq = containerSequence(folder), rows = S.folderRows[folder] || 2;
  const cols = COLS[rows - 1], per = rows * cols;
  const count = Math.min(60, Math.max(per, Math.ceil(seq.length / per) * per, B.shown[folder] || 0));
  let html = '';
  for (let base = 0; base < count; base += per) {
    if (base) html += `<div class="page-sep">PAGE ${Math.floor(base / per) + 1}</div>`;
    for (let n = 0; n < per; n++) {
      const pos = base + (n % cols) * rows + Math.floor(n / cols);
      html += pos < 60 ? spatialTile(seq[pos], folder, pos, px) : '<div></div>';
    }
  }
  return html;
}

// Toolbar order (owner decision): container dropdown, Badges (gold), Decorate folder
// (rose), Compact games; the empty-page control sits at the far right.
function spatialControls(folder) {
  const pages = pageInfo(folder), gaps = gapCount(folder), busy = !!S.recovery;
  const decorTitle = !S.badges?.writable ? 'Import a HOME menu dump to edit folder icons' : 'Pick a badge as a folder icon';
  return `<div class="spatial-controls">
    <select id="folderNavigation" aria-label="Open container"><option value="-1">Home grid</option>${folderIds().map(fid => `<option value="${fid}" ${folder === fid ? 'selected' : ''}>${esc(fname(fid))}</option>`).join('')}</select>
    ${hasBadges() ? `<button class="chipbtn chip-gold ${B.open ? 'on' : ''}" id="badgesToggle" aria-expanded="${B.open}" title="Open the badge collection">★ Badges</button>` : ''}
    ${hasBadges() && folderIds().length ? `<button class="chipbtn chip-rose" id="decorateFolder" title="${decorTitle}" ${!S.badges?.writable || busy ? 'disabled' : ''}>✿ Decorate folder</button>` : ''}
    <button class="chipbtn chip-mint" id="compactGames" title="${gaps ? `Move everything on this grid into the first free cells, keeping the order (${gaps} gap${gaps === 1 ? '' : 's'} to close).` : 'No gaps to close: everything already sits in the lowest cells'}" ${!S.spatialWritable || busy || !gaps ? 'disabled' : ''}>⇤ Compact</button>
    <div class="seg slots" title="Empty pages shown in this grid (the console shows pages the same way)">
      <span id="slotsLess" class="${pages.shown <= pages.min ? 'off' : ''}" title="Show one page less">−</span>
      <span class="slots-label">${pages.shown} PAGE${pages.shown === 1 ? '' : 'S'}</span>
      <span id="slotsMore" class="${pages.shown >= pages.max ? 'off' : ''}" title="Show one more page of empty cells">+</span>
    </div>
    ${S.badges?.error ? `<div class="layout-error" role="alert">${esc(S.badges.error)}</div>` : ''}
    ${S.layoutErrors?.length ? `<div class="layout-error" role="alert">Resolve these positions before writing:<br>${S.layoutErrors.map(esc).join('<br>')}</div>` : ''}
    ${S.recovery ? '<div class="layout-error" role="alert">An interrupted write needs recovery in SYNC.</div>' : ''}
  </div>`;
}

function badgePanel() {
  if (!B.open) return '';
  const all = S.badges?.catalog || [];
  const sets = [...new Map(all.map(b => [b.setId, b.setName])).entries()];
  const filtered = all.filter(b => (!B.set || b.setId === +B.set) && b.name.toLowerCase().includes(B.query.toLowerCase())
    && b.shape[2] === 0 && b.shape[3] === 0);
  return `<aside class="badge-panel" aria-label="Badge collection">
    <div class="badge-panel-head"><strong>Badge collection <span class="dot" style="color:var(--mut);font-size:11px">· ${all.length}</span></strong><button class="chipbtn" id="closeBadges" title="Close (Esc)">Close</button></div>
    <form id="badgeSearchForm"><input id="badgeSearch" aria-label="Search badges" placeholder="Search badges" value="${esc(B.query)}"><button class="chipbtn">Search</button></form>
    ${sets.length > 1 ? `<select id="badgeSet" aria-label="Badge set"><option value="">All sets</option>${sets.map(([id, name]) => `<option value="${id}" ${String(id) === B.set ? 'selected' : ''}>${esc(name)}</option>`).join('')}</select>` : ''}
    <p>${B.selected !== null ? 'Click an empty position to place the selected badge.' : 'Drag a badge to a free cell, or select it and click an empty cell. Pieces of a big badge are placed one by one, like on the console.'}</p>
    <div class="badge-list">${filtered.slice(0, B.limit).map(b => `<button class="badge-choice ${B.selected === b.id ? 'chosen' : ''}"
      data-badge-id="${b.id}" title="${esc(b.name)}" ${S.badges.writable && b.available > 0 ? 'draggable="true"' : 'disabled'}>
      ${badgeImage(b.id)}<span>${esc(b.name)}</span><small>${b.available} available · ${b.shape[0]}×${b.shape[1]}</small></button>`).join('')}</div>
    ${!all.length ? '<p>No badges installed on this card.</p>' : !filtered.length ? '<p>No matching badges.</p>' : ''}
    ${filtered.length > B.limit ? '<button class="chipbtn" id="moreBadges">Show more badges</button>' : ''}
    <div id="badgeReturn" class="btn">Drop a placed badge here to return it to the collection</div>
  </aside>`;
}

function recoveryPanel() {
  if (!S.recovery) return '';
  return `<div class="layout-error" role="alert"><strong>Interrupted write</strong><p>${esc(S.recovery.error || 'Finish writing or restore the automatic backup before using the card.')}</p>
    <button class="chipbtn" data-recover="complete">Complete write</button>
    <button class="chipbtn" data-recover="restore">Restore pre-write backup</button></div>`;
}

// Badge picker shared by the decorate modal and the new-folder modal.
function badgePickList(attr, chosen, noneLabel, letter = "A") {
  return `<div class="pick-list">
    <button class="badge-choice ${chosen == null ? 'chosen' : ''}" ${attr}="none" title="Keep the first letter of the folder name"><span class="pick-none dot">${esc(letter)}</span><span>${noneLabel}</span><small>letter icon</small></button>
    ${singleBadges().map(b => `<button class="badge-choice ${chosen === b.id ? 'chosen' : ''}" ${attr}="${b.id}" title="${esc(b.name)}" ${b.available > 0 || chosen === b.id ? '' : 'disabled'}>
      ${badgeImage(b.id)}<span>${esc(b.name)}</span><small>${b.available} available</small></button>`).join('')}
  </div>`;
}

// Decorate a folder: from a folder screen the folder is known; from the home grid pick one first.
function decorateModal(fid) {
  if (fid === null) fid = B.pickFolder ?? folderIds()[0];
  B.pickFolder = fid;
  const current = decorationOf(fid);
  document.getElementById('modal').innerHTML = `<div class="modal-bg" id="modalBg"><div class="modal" style="width:520px">
    <h2>✿ Decorate folder</h2>
    ${P.openFolder === null ? `<div class="folder-pick">${folderIds().map(f => `<button class="chipbtn ${f === fid ? 'on' : ''}" data-pick-folder="${f}">${folderArt(f, 22)} ${esc(fname(f))}</button>`).join('')}</div>` : ''}
    <div class="hint">Click a badge to use it as the icon of <b>${esc(fname(fid))}</b>. It uses one copy from your collection and stays staged until you write.</div>
    ${badgePickList('data-pick-badge', current ? current.badge : null, 'No icon', finitial(fid))}
    <div class="modal-error" id="decorationError" role="alert"></div>
    <div style="display:flex;justify-content:flex-end"><div class="btn" id="cancelDecoration" style="padding:8px 16px;font-size:12.5px;border-radius:9px">Close</div></div>
  </div></div>`;
  const $m = id => document.getElementById(id);
  $m('cancelDecoration').onclick = () => { $m('modal').innerHTML = ''; };
  $m('modalBg').onclick = e => { if (e.target.id === 'modalBg') $m('modal').innerHTML = ''; };
  document.querySelectorAll('[data-pick-folder]').forEach(el => { el.onclick = () => decorateModal(+el.dataset.pickFolder); });
  document.querySelectorAll('[data-pick-badge]').forEach(el => { el.onclick = () => applyDecoration(fid, el.dataset.pickBadge === 'none' ? null : +el.dataset.pickBadge, 'decorationError'); });
  loadBadgeImages();
}

async function applyDecoration(fid, badge, errorId) {
  const result = await callRaw('decorate_folder', [fid, badge]);
  if (result.error) { const el = document.getElementById(errorId); if (el) el.textContent = result.error; else toast(result.error); return; }
  S = result; document.getElementById('modal').innerHTML = ''; render();
  toast(badge === null ? 'Folder icon removed (staged)' : 'Folder icon changed (staged)');
}

// Drop of a badge on the folder's big icon (folder screen): confirm, since it may replace the current icon.
function decorateConfirm(fid, badge) {
  const current = decorationOf(fid), b = badgeById(badge);
  if (!b) return;
  if (b.sub !== 0) return toast('Only single-piece badges can be folder icons');
  document.getElementById('modal').innerHTML = `<div class="modal-bg" id="modalBg"><div class="modal">
    <h2>✿ Use ${esc(b.name)} as the icon of ${esc(fname(fid))}?</h2>
    <div style="display:flex;align-items:center;gap:14px">${badgeImage(badge, 64)}<div class="hint">${current ? `This replaces <b>${esc(badgeById(current.badge)?.name || 'the current icon')}</b>, which goes back to the collection.` : 'One copy leaves the collection while it decorates the folder.'} Staged until you write.</div></div>
    <div class="modal-error" id="decorationError" role="alert"></div>
    <div style="display:flex;gap:10px;justify-content:flex-end">
      <div class="btn" id="cancelDecoration" style="padding:8px 16px;font-size:12.5px;border-radius:9px">Cancel</div>
      <div class="btn primary" id="confirmDecorate" style="padding:9px 18px;font-size:12.5px;border-radius:9px">Decorate</div>
    </div></div></div>`;
  const $m = id => document.getElementById(id);
  $m('cancelDecoration').onclick = () => { $m('modal').innerHTML = ''; };
  $m('modalBg').onclick = e => { if (e.target.id === 'modalBg') $m('modal').innerHTML = ''; };
  $m('confirmDecorate').onclick = () => applyDecoration(fid, badge, 'decorationError');
  loadBadgeImages();
}

function compactConfirm(folder) {
  const gaps = gapCount(folder), items = containerSequence(folder).filter(Boolean).length, sys = launcherItemsAfterGap(folder);
  document.getElementById('modal').innerHTML = `<div class="modal-bg" id="modalBg"><div class="modal">
    <h2>Compact ${folder === -1 ? 'the home grid' : esc(fname(folder))}?</h2>
    <div class="hint">Moves the ${items} items into the first free cells, keeping their order, and closes ${gaps} gap${gaps === 1 ? '' : 's'}. Nothing is left behind after the last item. Undo is available.</div>
    ${sys ? `<div class="hint" style="color:var(--red)">${sys} system app${sys === 1 ? '' : 's'} or folder${sys === 1 ? '' : 's'} sit after a gap and will move too, so this write needs the GodMode9 inject.</div>` : `<div class="hint">System apps, folders and the Game Card keep their cells, so no inject is needed.</div>`}
    <div style="display:flex;gap:10px;justify-content:flex-end">
      <div class="btn" id="cancelCompact" style="padding:8px 16px;font-size:12.5px;border-radius:9px">Cancel</div>
      <div class="btn primary" id="confirmCompact" style="padding:9px 18px;font-size:12.5px;border-radius:9px">Compact</div>
    </div></div></div>`;
  const $m = id => document.getElementById(id);
  $m('cancelCompact').onclick = () => { $m('modal').innerHTML = ''; };
  $m('modalBg').onclick = e => { if (e.target.id === 'modalBg') $m('modal').innerHTML = ''; };
  $m('confirmCompact').onclick = () => { $m('modal').innerHTML = ''; refresh('compact_games', [folder, rowsOf(folder)]).then(r => { if (r) toast('Grid compacted (staged)'); }); };
}

async function loadBadgeImages() {
  if (B.loading || !S?.badges?.revision) return;
  if (B.revision !== S.badges.revision) { B.images = {}; B.revision = S.badges.revision; }
  const ids = [...new Set([...document.querySelectorAll('[data-badge-image]')].map(e => +e.dataset.badgeImage))].filter(id => !B.images[id]);
  const revision = B.revision;
  B.loading = true;
  let failed = false;
  try {
    for (let i = 0; i < ids.length; i += 32) {
      const result = await callRaw('get_badge_images', [ids.slice(i, i + 32)]);
      if (S.badges.revision !== revision) break;
      if (!result || result.error) { failed = true; break; }
      Object.assign(B.images, result);
      document.querySelectorAll('[data-badge-image]').forEach(img => {
        if (B.images[img.dataset.badgeImage]) img.src = `data:image/png;base64,${B.images[img.dataset.badgeImage]}`;
      });
    }
  } catch (error) {
    failed = true;
    toast('Badge images could not be loaded. Reopen the collection to retry.');
  } finally {
    B.loading = false;
    if (!failed && (S.badges.revision !== revision || [...document.querySelectorAll('[data-badge-image]')]
      .some(img => !B.images[img.dataset.badgeImage] && !ids.includes(+img.dataset.badgeImage)))) queueMicrotask(loadBadgeImages);
  }
}

function bindSpatial() {
  const on = (id, fn) => { const el = document.getElementById(id); if (el) el.onclick = fn; };
  on('badgesToggle', () => { B.open = !B.open; render(); });
  const navigation = document.getElementById('folderNavigation');
  if (navigation) navigation.onchange = () => { P.openFolder = +navigation.value === -1 ? null : +navigation.value; render(); };
  on('closeBadges', () => { B.open = false; B.selected = null; render(); });
  const showPages = n => { const f = currentContainer(), p = pageInfo(f); B.shown[f] = Math.min(capacityOf(f), Math.max(p.min, n) * p.per); render(); };
  on('slotsMore', () => showPages(pageInfo(currentContainer()).shown + 1));
  on('slotsLess', () => showPages(pageInfo(currentContainer()).shown - 1));
  on('compactGames', () => compactConfirm(currentContainer()));
  on('decorateFolder', () => decorateModal(P.openFolder === null ? null : P.openFolder));
  const search = document.getElementById('badgeSearchForm');
  if (search) search.onsubmit = e => { e.preventDefault(); B.query = document.getElementById('badgeSearch').value; B.limit = 40; render(); };
  const set = document.getElementById('badgeSet');
  if (set) set.onchange = () => { B.set = set.value; B.limit = 40; render(); };
  on('moreBadges', () => { B.limit += 40; render(); });
  document.querySelectorAll('[data-badge-id]').forEach(el => {
    el.onclick = () => { B.selected = B.selected === +el.dataset.badgeId ? null : +el.dataset.badgeId; render(); };
    el.ondragstart = e => { P.dragKey = `collection:${el.dataset.badgeId}`; e.dataTransfer.effectAllowed = 'copy'; };
    el.ondragend = () => { P.dragKey = null; render(); };
  });
  document.querySelectorAll('[data-empty]').forEach(el => {
    const place = () => { if (B.selected !== null) refresh('place_badge', [B.selected, +el.dataset.container, +el.dataset.cell, gridRows()]).then(r => { if (r) toast('Badge placed (staged)'); }); };
    el.onclick = place;
    el.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); place(); } };
  });
  document.querySelectorAll('[data-remove-badge]').forEach(el => { el.onclick = e => { e.stopPropagation(); refresh('remove_badge', [el.dataset.removeBadge, gridRows()]).then(r => { if (r) toast('Badge returned to the collection (staged)'); }); }; });
  const ret = document.getElementById('badgeReturn');
  if (ret) {
    ret.ondragover = e => { if (P.dragKey?.startsWith('b:')) e.preventDefault(); };
    ret.ondrop = e => { e.preventDefault(); const key = P.dragKey; P.dragKey = null; if (key?.startsWith('b:')) refresh('remove_badge', [key, gridRows()]).then(r => { if (r) toast('Badge returned to the collection (staged)'); }); };
  }
  // The folder's big icon accepts a badge (from the collection or a placed one) as its new icon.
  const art = document.getElementById('folderArtDrop');
  if (art && S.badges?.writable && !S.recovery) {
    art.ondragover = e => { if (P.dragKey && (P.dragKey.startsWith('collection:') || P.dragKey.startsWith('b:'))) { e.preventDefault(); art.classList.add('dragover'); } };
    art.ondragleave = () => art.classList.remove('dragover');
    art.ondrop = e => {
      e.preventDefault(); art.classList.remove('dragover');
      const key = P.dragKey; P.dragKey = null;
      if (!key) return;
      const badge = key.startsWith('collection:') ? +key.split(':')[1] : S.badges.placed.find(b => b.key === key)?.badge;
      if (badge !== undefined) decorateConfirm(+art.dataset.folder, badge);
    };
  }
  document.querySelectorAll('[data-recover]').forEach(el => { el.onclick = async () => {
    const result = await callRaw('recover_write', [el.dataset.recover]);
    if (result.error) { toast(result.error); const state = await call('get_state'); if (state) S = state; }
    else S = result;
    render();
  }; });
  // Esc closes dismissible modals (those with #modalBg) or the badge panel. Blocking
  // modals (write, post-write warning) have no #modalBg on purpose.
  document.onkeydown = e => {
    if (e.key !== 'Escape') return;
    const modal = document.getElementById('modal');
    if (modal.querySelector('#modalBg')) modal.innerHTML = '';
    else if (B.open) { B.open = false; B.selected = null; render(); }
  };
  loadBadgeImages();
}

function markBadgeArea(grid, key, pos) {
  const badge = key.startsWith('collection:') ? badgeById(+key.split(':')[1])
    : badgeById(S.badges.placed.find(b => b.key === key)?.badge);
  if (!badge) return;
  const [w, h, dx, dy] = badge.shape, rows = gridRows();
  const anchor = key.startsWith('collection:') ? pos : pos - dx * rows - dy;
  if (anchor < 0 || anchor % rows + h > rows) return;
  for (let x = 0; x < w; x++) for (let y = 0; y < h; y++) {
    const target = grid.querySelector(`[data-cell="${anchor + x * rows + y}"]`);
    if (target) target.classList.add('badge-area');
  }
}
