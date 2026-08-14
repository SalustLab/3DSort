# CLAUDE.md — 3DSort

Contexto estático para desenvolvimento assistido por IA. Leia antes de qualquer mudança.
Última revisão: 2026-08-14 (fases 1–3 concluídas).

## 1. O que é o projeto

**3DSort** é um app desktop (Windows-first) que reorganiza o layout do HOME menu do
Nintendo 3DS editando o SD card do console montado no PC: reordenar ícones por
drag-and-drop, mover jogos entre pastas, presets de ordenação, preview ao vivo de como
ficará no console, escrita staged com backup automático e histórico restaurável.

- **Público**: comunidade 3DS (consoles com CFW — Luma3DS + GodMode9). Será distribuído
  como **exe portátil sem instalador** (PyInstaller onefile).
- **Protótipo visual de referência**: `prototype/3DSort Prototype.dc.html` (com
  `prototype/support.js`, que é apenas o runtime do mockup — ignorar como código de
  produção). A UI real em `ui/` porta esse visual; em dúvida de UX/estética, consultar o
  protótipo.
- **Escopo v1**: abas GRID, SYNC e SETTINGS; ícones reais dos jogos (requisito firme do
  usuário); staging/undo/redo; backups. Abas RULES (auto-sort por regras) e THEMES/badges
  ficaram para v2. Criar/renomear pastas: v1.1 (ver §5.7).

## 2. Arquitetura (decidida e aprovada — não reabrir sem motivo novo)

**Backend Python + UI HTML via pywebview + binário `save3ds` embarcado.**

- Webapp hospedado foi **descartado**: servidor não acessa o SD local do usuário.
- Tauri/Rust descartado: save3ds já resolve a parte difícil como CLI; reescrever o backend
  em Rust não traz ganho funcional.
- Webapp estático + File System Access API descartado: Chromium-only e exigiria
  reimplementar a criptografia do 3DS em JS.
- A UI conversa com a MESMA classe `Api` por dois canais: ponte `js_api` do pywebview
  (app real, janela nativa via WebView2) e modo dev `--serve` (stdlib `http.server`,
  `POST /api/<metodo>` com corpo `{"args": [...]}` posicional). O modo `--serve` existe
  para testes Playwright e desenvolvimento.

### Mapa do repositório

```
F:\Projects\3DSort\
├── CLAUDE.md               ← este arquivo
├── prototype/              ← mockup visual de referência (não é código de produção)
├── app.py                  ← Api (camada única UI↔core), FakeSave3ds/mock, --serve, main
├── spike.py                ← prova de viabilidade da Fase 1 (histórico; já cumpriu o papel)
├── conftest.py             ← vazio; existe só para o pytest achar core/ no sys.path
├── core/
│   ├── savedata.py         ← parse/serialize do SaveData.dat (layout do HOME menu)
│   ├── icons.py            ← Cache.dat/CacheD.dat → nomes + ícones PNG base64 (SMDH)
│   ├── store.py            ← Staging (undo/redo por snapshot) e Backups (.3dsl + jsonl)
│   └── sdcard.py           ← detecção SD/console/região + wrapper do save3ds_fuse
├── ui/
│   ├── index.html          ← tela única, CSS fiel ao protótipo (paleta creme/DotGothic16)
│   └── app.js              ← JS puro; render por innerHTML + bind(); estado P (prefs) + S (backend)
├── tests/
│   ├── test_savedata.py    ← unit: round-trip binário, invariantes
│   ├── test_icons.py       ← unit: decode Morton/RGB565 (com encoder inverso), nomes SMDH
│   ├── test_store.py       ← unit: staging, backups, prune, histórico
│   ├── test_sdcard.py      ← unit: descoberta de console/região; extração movable (fixture real)
│   └── test_integration.py ← integração REAL com save3ds sobre cópia do sandbox + guard do G:
├── tools/save3ds/save3ds_fuse.exe  ← v1.3.0 (wwylele/save3ds), extract/import de extdata
└── sandbox/                ← NUNCA versionar. Cópia do SD real + chaves do console do dev
    ├── sd/Nintendo 3DS/<id0>/<id1>/extdata/00000000/0000008f/...
    └── keys/{boot9.bin, movable.sed, essential.exefs}
```

Dados de runtime do app instalado: `%USERPROFILE%\3DSort\{work,backups}`.

## 3. Regras de segurança INEGOCIÁVEIS

1. **Nenhum teste, script ou experimento escreve no SD real** (`G:` na máquina do dev).
   Todo trabalho roda contra o **sandbox** (cópia). `tests/test_integration.py::test_real_sd_untouched_guard`
   compara hash do extdata real entre execuções e FALHA se algo escreveu lá — não remover
   nem enfraquecer esse teste.
2. **Toda escrita no SD é precedida de backup automático** (`Backups.create(kind="auto")`
   dentro de `Api.write_sd`). Regra de produto, não detalhe: nunca remover.
3. **Escrita real só por ação explícita do usuário** (modal de confirmação no app).
4. `sandbox/`, `*.sed`, `boot9.bin`, `essential.exefs` são **segredos/dados pessoais do
   console** — nunca commitar, nunca publicar, nunca embutir no exe (boot9 é copyright
   Nintendo; movable é único por console).
5. Restaurar backup vira mudança **staged** (commit "Restored backup …") — o usuário
   precisa poder ESCREVER o estado restaurado; não "otimizar" isso para aplicar direto.

## 4. Como rodar

```powershell
# testes (30 no total; integração real é pulada se sandbox/chaves não existirem)
python -m pytest tests -q

# UI no navegador com dados reais do sandbox (modo de desenvolvimento padrão)
python app.py --serve --sd F:\Projects\3DSort\sandbox\sd    # → http://127.0.0.1:8347

# UI com dados sintéticos (sem SD/chaves — funciona em qualquer máquina)
python app.py --serve --mock

# janela nativa (pywebview/WebView2)
python app.py --sd F:\Projects\3DSort\sandbox\sd

# spike histórico da Fase 1 (round-trip completo no sandbox)
python spike.py
```

Dependências: Python 3.10 (pyenv-win), `pyctr`, `Pillow`, `pytest`, `pywebview`.
Sem requirements.txt ainda — criar na Fase 4 junto do empacotamento.

## 5. Conhecimento de domínio 3DS (caro de redescobrir — confie nisto)

### 5.1 Estrutura do SD

```
SD:\Nintendo 3DS\<id0 32 hex>\<id1 32 hex>\
├── extdata\00000000\<extdataID baixo>\00000000\{00000001..00000005}
├── title\...   (jogos instalados, também criptografados)
└── dbs\...
```

- extdata do HOME menu por região: **JPN `00000082` · USA `0000008f` · EUR `00000098`**
  (mapa em `core/sdcard.py::HOME_EXTDATA_IDS`). O console do dev é **USA**.
- Após decriptação via save3ds, o extdata vira: `user/SaveData.dat`, `user/Cache.dat`,
  `user/CacheD.dat`, `icon`, `boss/`.

### 5.2 Criptografia

- Tudo sob `Nintendo 3DS/<id0>/<id1>/` é AES por chaves únicas do console:
  KeyX 0x34 (vem do **boot9.bin**, bootrom, igual em todos os consoles) + KeyY (vem do
  **movable.sed**, único por console, MUDA a cada formato de sistema/transferência).
- O CTR deriva do caminho do arquivo RELATIVO à raiz id1 — renomear id0/id1 não quebra a
  decriptação (útil para montar sandboxes).
- **id0 = primeiros 16 bytes de SHA-256(KeyY)** onde KeyY = bytes `0x110:0x120` do
  movable.sed, formatados como 4 u32 little-endian em hex. O save3ds usa isso para achar a
  pasta — se o movable for de outro estado do console, dá `NotFound` (pasta não existe
  para aquele id0) ou `Signature mismatch` (CMAC não bate).

### 5.3 A ARMADILHA da chave velha (custou horas — não repetir)

Backups do GodMode9 podem conter **movable.sed obsoleto**:
- `essential.exefs` (em `gm9/backups/`) e o essential **embutido a offset 0x200 dentro de
  imagens de NAND** `.bin` do GM9 refletem o estado NA ÉPOCA DO BACKUP.
- Se o console passou por formato/transferência depois, esse movable NÃO decripta o SD
  atual (sintomas acima).
- **Fonte confiável**: dump direto no console — GodMode9 → `[1:] SYSNAND CTRNAND` →
  `private/movable.sed` → Copy to `0:/gm9/out`. boot9: GodMode9 → `[M:] MEMORY VIRTUAL` →
  `boot9.bin` (65536 bytes) → Copy.
- O onboarding do app (Fase 4) deve instruir SEMPRE o dump direto, nunca aproveitar
  backups antigos. Validar a chave contra o id0 da pasta antes de usar (código do check:
  derivação em §5.2; há utilitário de verificação nos scripts do scratchpad da sessão de
  2026-08-14 — vale promover para `core/sdcard.py` na Fase 4).

### 5.4 SaveData.dat (formato v4 — fonte: 3dbrew /wiki/Home_Menu)

Tamanho exato `0x2DA0`. Offsets implementados em `core/savedata.py`:

| Offset | Tipo | Conteúdo |
|--------|------|----------|
| 0x0 | u8 | versão (só aceitamos 4) |
| 0x8 | u64[360] | title IDs dos ícones |
| 0xB48 | s8[360] | status (1 = ícone ativo) |
| 0xCB0 | s16[360] | posição linear no grid |
| 0xF80 | s8[360] | pasta do ícone (−1 = home grid) |
| 0x10E8–0x13B8 | ? | NÃO documentado — preservar byte a byte |
| 0x13B8+ | — | temas/shuffle (não mexemos) |

- **Preservação é a estratégia central**: `SaveData` guarda o buffer inteiro e só reescreve
  os arrays conhecidos. Round-trip byte-idêntico é garantido por construção e testado.
- **O espaço de posições é COMPARTILHADO entre NAND e SD** (confirmado empiricamente:
  no console do dev os jogos SD ocupam 13, 15–25; 0–12 e 14 são apps NAND — pode haver
  app NAND misturado no meio dos jogos). As posições NAND vivem no Launcher.dat (§5.8).
  `apply_order` distribui posições **por contêiner** (home grid e cada pasta), pulando
  as reservadas: menores posições livres na ordem dada. Reservas = lacunas do próprio
  arquivo no load ∪ posições do Launcher.dat (apps NAND, tiles de pasta) — a união cobre
  entidades desconhecidas (ex.: buraco na posição 11 do console do dev, dono não
  identificado). A antiga densificação 0..n-1 (que colidiria com os NAND) foi removida.
- **Posições são LOCAIS ao contêiner** (CONFIRMADO no dump real do Launcher.dat: Health &
  Safety tem pos=6 dentro da pasta 0 enquanto AR Games tem pos=6 no home grid). Item de
  pasta reinicia a contagem na própria pasta.
- **O console exibe o grid em ordem COLUNA-MAJOR**: posição linear `n` → coluna `n÷linhas`,
  linha `n mod linhas` (preenche de cima para baixo, depois para a direita). Provado pelas
  6 fotos em `sample/` (2026-08-14, uma por modo de visão): o buraco da pos 11 e a pasta
  na pos 12 caem exatamente onde a fórmula prevê em todos os modos. O preview da UI
  transpõe por isso (`ui/app.js::previewCol`); desde 2026-08-14 o grid de edição usa a
  MESMA transposição/paginação (pedido do usuário — antes era row-major). Colunas
  inteiras visíveis por modo (contadas nas fotos): 3/3/5/7/9/10.

### 5.5 Ícones e nomes (Cache.dat / CacheD.dat)

- `Cache.dat`: header 8 bytes (byte 0 = versão) + entradas de 16 bytes
  `{u64 titleID, u32 versão, u32 ?}`; tid `0xFFFF…` = slot vazio. Índice da entrada = índice
  no CacheD.
- `CacheD.dat`: um **SMDH completo (0x36C0)** por entrada — dá ícone E nomes localizados.
  Nome curto UTF-16LE em `0x8 + lang*0x200` (lang 1 = inglês). Ícone grande 48×48 a
  `0x24C0`, RGB565, tiles 8×8 em **ordem Morton** (z-curve, tabela `MORTON` em
  `core/icons.py`). Entradas sem magic `SMDH` são títulos **TWL/DSiWare**: header SRL
  @0x0 (título 12 bytes + gamecode) + **banner NDS @0x378** (validado em dump real) —
  versão u16 ∈ {1,2,3,0x103}, ícone 32×32 4bpp @+0x20 (tiles 8×8 lineares, nibble baixo
  = pixel esquerdo), paleta RGB555 @+0x220 (índice 0 = transparente), títulos UTF-16
  0x100 bytes/língua @+0x240 (lang 1 = inglês; 1ª linha = nome). Decode em
  `core/icons.py::twl_short_name/twl_icon_png_b64`.
- O cache do console pode ter MAIS nomes que ícones ativos (39 nomes vs 12 ativos no SD do
  dev) — normal, inclui títulos NAND.

### 5.6 save3ds (tools/save3ds/save3ds_fuse.exe, v1.3.0)

```
save3ds_fuse --sdext <16 dígitos hex, ex 000000000000008f>
             --sd <raiz do SD> --boot9 <boot9.bin> --movable <movable.sed>
             --extract|--import <dir>
```

- `--extract` LÊ o SD; `--import` LIMPA e reescreve o extdata a partir do dir. Import é o
  modo recomendado pelo autor para modificar extdata (mount FUSE não existe no Windows).
- Extdata não suporta resize nativo; save3ds recria arquivos ao redimensionar (lento) e
  **arquivos de tamanho zero quebram no console** — nunca criar.
- Releases: binário Windows só até v1.3.0 (v1.4.0 não tem assets).
- pyctr complementa: `ExeFSReader` para ler `movable` de essential.exefs; SMDH de títulos
  se um dia o CacheD não bastar.

### 5.7 Limitação de pastas (v1.1 pendente)

`SaveData.dat` (SD) guarda apenas **a qual pasta cada ícone pertence** (s8). As
**definições** das pastas — nome, posição, linhas — vivem em `Launcher.dat` dentro de um
**system save no NAND** (fora do SD; offsets no 3dbrew: posições @0x11DC s16[60],
linhas @0x1434 u8[60], nomes UTF-16 0x22 @0x1560). Consequência:
- Mover jogos entre pastas EXISTENTES: funciona só com o SD (implementado).
- Criar/renomear/reposicionar pastas: exigirá fluxo extra (script GM9 exportando/importando
  Launcher.dat, ou similar). Investigar na v1.1; a região não documentada do SaveData.dat
  (§5.4) pode conter espelho parcial — comparar dumps antes/depois de criar pasta no console.
- Na UI, pastas mostram o nome real quando há Launcher.dat (§5.8); sem ele, "Folder N+1".
  Criar/renomear/reposicionar pastas continua exigindo ESCRITA do Launcher.dat (v1.1).

### 5.8 Launcher.dat (apps NAND — leitura implementada em core/launcher.py)

- Local: system save do HOME menu na NAND — `nand:/data/<id0>/sysdata/<ID>/00000000`,
  ID por região: **JPN `00020082` · USA `0002008F` · EUR `00020098`**. Dump manual via
  GodMode9: montar esse arquivo (A: → mount) e copiar `/Launcher.dat` para `0:/gm9/out`.
  O app procura em `sandbox/keys/Launcher.dat` (dev) e `%USERPROFILE%\3DSort\Launcher.dat`.
- Tamanho: 3dbrew documenta `0x2490`, mas o console real (11.17 USA) produz **`0x2558`**
  — 200 bytes extras no FIM, offsets conhecidos idênticos (validado no dump do dev; o
  parser aceita `>= 0x2490`). Offsets: tids NAND u64[360] @0x8; posições s16[360] @0xD9A
  (locais ao contêiner, ver §5.4); pasta s8[360] @0x106A. Pastas: posições s16[60] @0x11DC
  (−1 = apagada), linhas u8[60] @0x1434, nomes UTF-16LE 0x22 bytes @0x1560.
- Validado no dump do dev: critério de ativo = tid ∉ {0, 0xFFFF…} e pos ≥ 0; a lista de
  tids NAND inclui títulos **TWL/DSiWare** (tid high `00048004`, ex. TWiLight Menu++ =
  `0004800453524c41`, gamecode "SRLA" — NÃO é o slot de cartucho); pasta id 0 = "Homebrew"
  @pos 12 com Health & Safety dentro. **Slot do cartucho: u16 @0x2 do Launcher.dat**
  ("cart launcher position"; ≥360 = inválido) — no console do dev vale 11. Reservas sem
  dono restantes viram placeholder "System app" (união de reservas, §5.4).
- **v1 nunca escreve o Launcher.dat** — apps NAND são exibidos fixos (pinned) na UI;
  reordená-los exigiria reinjetar o save na NAND (v1.1+, fluxo GM9).
- Sem Launcher.dat o app infere os slots NAND pelas LACUNAS nas posições SD (placeholders
  "System app" sem nome; apps NAND depois do último jogo ficam invisíveis).
- O Cache/CacheD do SD já contém nome+ícone dos títulos NAND (§5.5) — o Launcher só
  fornece as posições. Pendente validar com dump real: critério de slot ativo (tid≠0 e
  pos≥0), entrada do gamecard (tid `0004800453524c41` "SRLA" visto no cache do dev).

## 6. Backend (app.py + core/) — contratos

- `Api.get_state()` → `{items: [{slot,pos,tid,folder,name,icon(b64 png)}...] em ordem
  (pos = posição real POR CONTÊINER, a mesma que write_sd gravará), system:
  [{tid,pos,folder,pinned,name,icon}...] (apps NAND identificados via Launcher.dat +
  placeholders "System app" para reservas sem dono), folderNames/folderPos: {id: ...}
  (do Launcher.dat, vazios sem ele), staged: [rótulos], canUndo, canRedo,
  sd: {region, root}, history: [backups, mais novo 1º]}`.
  Toda mutação retorna o estado completo novo (UI re-renderiza inteira — simples e barato
  para ≤360 itens).
- Mutações: `move_item(slot, before_slot|null)`, `swap_items(slot_a, slot_b)` (troca
  exata de posição/pasta entre dois itens — gesto padrão do drag), `set_folder(slot,
  folder)`, `sort_preset('az'|'za')`, `undo()`, `redo()` — todas **staged** (memória),
  nada toca o SD.
- `write_sd()`: exige staged>0 → backup auto → aplica ordem+pastas no SaveData.dat do
  workdir → `save3ds --import`. `import_sd()`: re-extrai e RESETA o staging.
- `Staging` (core/store.py): snapshots imutáveis com deepcopy; `commit` limpa redo;
  `clear()` após write. `Backups`: zip `.3dsl` + `history.jsonl`, mantém últimos 20.
- Erros da API viram `{"error": msg}` (o handler HTTP captura exceções); a UI mostra toast.
- Mock (`--mock`): `FakeSave3ds` copia árvore plana em vez de decriptar; `make_mock_extdata`
  gera 12 jogos com SMDH sintético. O mock exercita 100% do código real exceto a crypto —
  é o modo dos testes de UI que precisam rodar em qualquer máquina.

## 7. Frontend (ui/) — convenções

- **JS puro, sem framework, sem build step.** Render = template strings + `innerHTML` +
  `bind()` re-liga handlers após cada render. Estado: `S` (espelho do backend) e `P`
  (prefs locais: tab, iconSize, viewRows, page, showLabels → localStorage).
- `call(name, args[])` roteia pywebview vs fetch automaticamente — **argumentos sempre
  posicionais** para manter os dois canais idênticos.
- Visual: seguir o protótipo (fundo `#fdf5e8`, cartões `#fffdf8`, vermelho `#d31e40`,
  fonte Nunito + DotGothic16 para elementos "de console"). Google Fonts é online-only;
  fallback system-ui aceitável offline (empacotar fontes na Fase 4 se importar).
- Drag-and-drop HTML5 nativo (`draggable`), sem lib, com semântica de **SWAP** (decisão
  do usuário 2026-08-14, substituiu o reflow-ao-vivo por inserção — que oscilava e
  cascateava posições): drop sobre jogo = `swap_items` (troca exata, ninguém mais se
  move; alvo marcado `.swap-with`); drop sobre pasta = `set_folder` (`.drop-into`, anel
  na cor da pasta); tiles system não são alvo. Nada muda no DOM durante o drag — o
  commit acontece no drop e a animação FLIP (`captureGrid`/`playFlip`, WAAPI) mostra a
  troca. Clique simples abre pasta; `#removeZone` na visão de pasta = tirar da pasta;
  drag cancelado limpa via `render()` no dragend. FLIP roda em todo render do `#grid` —
  cobre swap/sort/undo/redo. Separadores `.page-sep` mostram as quebras de página do
  console (mesma paginação do preview).
- Strings hoje em inglês (como o protótipo); i18n pt-BR/EN é pendência de polish.

## 8. Testes — estratégia em camadas (manter TODAS)

1. **Unit** (`pytest`, rápidos, qualquer máquina): fixtures sintéticas construídas byte a
   byte; round-trip binário idêntico; invariantes (nenhum título perdido/duplicado);
   decode de ícone testado com ENCODER inverso no próprio teste.
2. **Integração real** (pulada sem chaves): save3ds de verdade sobre **cópia fresca do
   sandbox por teste** (fixture `sd`); extract → editar → import → re-extract → comparar.
   Inclui o **guard do SD real** (§3.1).
3. **UI em tela via Playwright** (MCP, manual-assistido): contra `--serve` (mock ou
   sandbox). Cobertura já validada: drag reordena + staging; pastas (entrar/tirar/drill-in);
   presets; undo/redo; modal write (confirmar/cancelar); persistência pós-import; restore;
   toggles; preview (contagem de células por modo de visão). Screenshots `0*-*.png` na raiz.
4. Bug real já pego por essa pirâmide: restore não deixava escrever o estado restaurado
   (staging vazio) — corrigido tornando o restore uma mudança staged.

Ao adicionar operação nova na Api: teste unit do core + caso de integração se tocar o SD +
passo Playwright se tiver gesto de UI.

## 9. Ambiente de dev (Windows) — pegadinhas conhecidas

- **PowerShell 5.1**: sem `&&`/`||`; `Get-Process` NÃO tem `.CommandLine` (usar
  `Get-CimInstance Win32_Process` para matar por linha de comando); `python -c` multilinha
  quebra (hooks embrulham o comando) — escrever script no scratchpad e executar.
- **Dois servidores na mesma porta**: `http.server` usa SO_REUSEADDR; no Windows isso
  permite DOIS processos escutando 127.0.0.1:8347 ao mesmo tempo (requests vão para o
  antigo → parece que o hot-fix "não funcionou"). SEMPRE matar o servidor antigo antes de
  subir outro.
- SD do dev monta em `G:`; console serial REDACTED-SERIAL, USA, id0 `REDACTED…`, Luma + GM9.
- Encoding: manter arquivos .py sem acento em strings de código quando possível (console
  Windows cp1252 já corrompeu saída de erro do save3ds); UI/HTML é UTF-8 normal.

## 10. Estado atual e roadmap

**Feito (2026-08-14)**: spike round-trip OK em dados reais; core completo (41 testes);
UI GRID/SYNC/SETTINGS portada e validada em tela com ícones reais; modo mock; backups +
restore staged; apps NAND no grid (core/launcher.py, pinned) com Launcher.dat REAL
dumpado e validado — visão do console reproduzida 1:1 (11 apps identificados, pasta
"Homebrew", Game Card na pos 14); apply_order por contêiner com reservas (§5.4/§5.8);
fallback por lacunas sem Launcher.dat. Sandbox re-copiado do SD real.

**Fase 4 (próxima)**: PyInstaller onefile embutindo `save3ds_fuse.exe` e `ui/`;
requirements.txt; primeira execução com onboarding guiado (dump boot9/movable com validação
de id0, escolha do drive); README de distribuição; testar janela pywebview; smoke em
máquina limpa.

**v1.1**: pastas completas via Launcher.dat (§5.7); validação de posições < 13 (§5.4);
i18n pt-BR/EN; fontes offline.

**v2**: aba RULES (motor de regras), THEMES/badges.

**Dívidas conscientes**: `spike.py` não usa core/ (era pra ser descartável; ou apagar ou
refatorar sobre core na Fase 4); comportamento do console diante de buracos deixados ao
mover jogo para pasta ainda não observado em hardware (write real pendente).

## 11. Regras de trabalho para a IA neste repo

- Antes de mexer em formato binário, releia §5 e os testes de round-trip; qualquer campo
  novo descoberto empiricamente → documentar AQUI e no 3dbrew-style (offset/tamanho/prova).
- Simplicidade primeiro (stdlib > dependência nova), mas NUNCA à custa das regras do §3.
- Não versionar/expor `sandbox/`, chaves, ou dados do console do usuário.
- Mudanças em `Api`: manter os dois canais (js_api posicional + HTTP `{"args": []}`).
- Validar sempre com `python -m pytest tests -q` + fluxo Playwright quando houver UI.
- O protótipo `.dc.html` é REFERÊNCIA visual, não código: não importar seu runtime.
