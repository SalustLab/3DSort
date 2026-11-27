// 3DSort UI — game search. Finds titles and folders by name across the home grid
// and every folder, highlights matches in the open grid, and jumps to a result.
// Typing never calls render(): render() rebuilds #screen and would drop the
// input's focus, so results and highlights are patched in place instead.
"use strict";

const SEARCH_LIMIT = 50;
const Q = { query: "", open: false, active: 0 };

// Case- and accent-insensitive: "pokemon" finds "Pokémon".
const searchFold = s => String(s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

// Where a title or folder lives, as the user would describe it.
function searchPlace(folder, pos) {
  const rows = rowsOf(folder), per = rows * COLS[rows - 1];
  const page = Number.isInteger(pos) && pos >= 0 ? ` · page ${Math.floor(pos / per) + 1}` : "";
  return (folder === -1 ? "Home" : fname(folder)) + page;
}

// Every search term must appear in the name. Games and named system apps come
// first, then folders; within each, names that start with the query lead.
function searchMatches(query) {
  const terms = searchFold(query).split(/\s+/).filter(Boolean);
  if (!terms.length) return [];
  const hit = name => { const n = searchFold(name); return terms.every(t => n.includes(t)); };
  const titles = [...S.items, ...(S.system || []).filter(s => !s.hole && s.key)]
    .filter(it => hit(it.name))
    .map(it => ({ kind: "title", key: it.key, name: it.name, icon: it.icon, folder: it.folder, pos: it.pos }));
  const folders = folderIds().filter(id => hit(fname(id)))
    .map(id => ({ kind: "folder", key: `f:${id}`, id, name: fname(id), folder: -1, pos: S.folderPos[id] }));
  const head = searchFold(query).trim();
  const rank = r => (searchFold(r.name).startsWith(head) ? 0 : 1);
  titles.sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
  folders.sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
  return [...titles, ...folders];
}

function searchBox() {
  return `<div class="game-search" id="gameSearch">
    <input id="gameSearchInput" type="search" autocomplete="off" spellcheck="false"
      placeholder="Search games" aria-label="Search games" title="Search games (Ctrl+F)"
      role="combobox" aria-controls="gameSearchResults" aria-expanded="false" value="${esc(Q.query)}">
    <div class="search-results hidden" id="gameSearchResults" role="listbox"></div>
  </div>`;
}

function searchResultHtml(r, i) {
  const icon = r.kind === "folder"
    ? `<span class="search-icon search-folder dot">${esc(finitial(r.id))}</span>`
    : r.icon ? `<img class="search-icon" src="data:image/png;base64,${r.icon}" alt="">`
    : `<span class="search-icon" style="background:${hashColor(r.name)}"></span>`;
  return `<div class="search-result ${i === Q.active ? "active" : ""}" role="option" id="searchResult${i}"
      aria-selected="${i === Q.active}" data-search-index="${i}">
    ${icon}<span class="search-name">${esc(r.name)}</span>
    <span class="search-place">${r.kind === "folder" ? "Folder · " : ""}${esc(searchPlace(r.folder, r.pos))}</span>
  </div>`;
}

// Dims the open grid's tiles that do not match, so matches stand out in place.
function paintSearchHits(matches) {
  const grid = document.getElementById("grid");
  if (!grid) return;
  const keys = new Set(matches.map(r => r.key));
  grid.classList.toggle("searching", !!Q.query.trim());
  grid.querySelectorAll(".item").forEach(el => {
    const key = el.dataset.ekey || (el.dataset.folderTile !== undefined ? `f:${el.dataset.folderTile}` : null);
    el.classList.toggle("search-hit", !!key && keys.has(key));
  });
}

function updateSearch() {
  const input = document.getElementById("gameSearchInput");
  const list = document.getElementById("gameSearchResults");
  if (!input || !list) return;
  const matches = searchMatches(Q.query);
  paintSearchHits(matches);
  Q.active = Math.min(Q.active, Math.max(0, matches.length - 1));
  const show = Q.open && !!Q.query.trim();
  list.classList.toggle("hidden", !show);
  input.setAttribute("aria-expanded", String(show));
  input.setAttribute("aria-activedescendant", show && matches.length ? `searchResult${Q.active}` : "");
  if (!show) return;
  list.innerHTML = matches.length
    ? matches.slice(0, SEARCH_LIMIT).map(searchResultHtml).join("") +
      (matches.length > SEARCH_LIMIT ? `<div class="search-more">${matches.length - SEARCH_LIMIT} more · keep typing to narrow it down</div>` : "")
    : `<div class="search-more">No titles or folders match</div>`;
  list.querySelectorAll("[data-search-index]").forEach(el => {
    el.onmousedown = e => e.preventDefault();   // keep focus in the input
    el.onclick = () => goToSearchResult(matches[+el.dataset.searchIndex]);
  });
  const active = list.querySelector(".search-result.active");
  if (active) active.scrollIntoView({ block: "nearest" });
}

// Opens the container that holds the result, selects it when it is selectable,
// turns the live preview to its page and brings the tile into view.
function goToSearchResult(r) {
  if (!r) return;
  Q.open = false;
  P.openFolder = r.folder === -1 ? null : r.folder;
  if (r.folder === -1 && Number.isInteger(r.pos)) P.page = Math.floor(r.pos / (P.viewRows * COLS[P.viewRows - 1])) + 1;
  P.selectionFolder = r.folder;
  const selectable = selectableTitles().some(i => i.key === r.key);
  P.selectedKeys = selectable ? [r.key] : [];
  P.selectionAnchor = selectable ? r.key : null;
  P.selected = r.key.startsWith("g:") ? +r.key.split(":")[1] : null;
  render();
  const sel = r.kind === "folder" ? `[data-folder-tile="${r.id}"]` : `[data-ekey="${r.key}"]`;
  const tile = document.querySelector(`#grid ${sel}`);
  if (tile) {
    tile.scrollIntoView({ block: "center" });
    tile.classList.add("search-found");
    setTimeout(() => tile.classList.remove("search-found"), 1400);
  }
}

function bindSearch() {
  const input = document.getElementById("gameSearchInput");
  if (!input) return;
  input.oninput = () => { Q.query = input.value; Q.open = true; Q.active = 0; updateSearch(); };
  input.onfocus = () => { Q.open = true; updateSearch(); };
  input.onblur = () => { Q.open = false; updateSearch(); };
  input.onkeydown = e => {
    const count = Math.min(SEARCH_LIMIT, searchMatches(Q.query).length);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!count) return;
      Q.open = true;
      Q.active = (Q.active + (e.key === "ArrowDown" ? 1 : count - 1)) % count;
      updateSearch();
    } else if (e.key === "Enter") {
      e.preventDefault();
      goToSearchResult(searchMatches(Q.query)[Q.active]);
    } else if (e.key === "Escape") {
      // Handled here only: the page-level Esc would also clear the selection.
      e.stopPropagation();
      if (Q.query) { Q.query = ""; input.value = ""; Q.active = 0; updateSearch(); }
      else input.blur();
    }
  };
  updateSearch();
}

// Ctrl+F (Cmd+F on macOS) jumps to the search box on the GRID tab.
document.addEventListener("keydown", e => {
  if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "f") return;
  const input = document.getElementById("gameSearchInput");
  if (!input) return;
  e.preventDefault();
  input.focus();
  input.select();
});
