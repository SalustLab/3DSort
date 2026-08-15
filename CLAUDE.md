# CLAUDE.md — 3DSort

Contexto estático para desenvolvimento assistido por IA. Leia antes de qualquer mudança.
Última revisão: 2026-08-15 (v1.1 completo: gates de hardware 0B/0C VALIDADOS no console
real, ver §10; próxima etapa é a Fase 4, empacotamento).

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
  ficaram para v2. v1.1 (implementado e validado em hardware, §10): reordenar apps
  NAND/pastas/Game Card e criar/renomear/apagar pastas via escrita do Launcher.dat com
  injeção assistida por GodMode9; desembrulho automático e preservação de tema.

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
│   ├── launcher.py         ← classe Launcher: parse/serialize do Launcher.dat (NAND)
│   ├── icons.py            ← Cache.dat/CacheD.dat → nomes + ícones PNG base64 (SMDH)
│   ├── store.py            ← Staging (undo/redo por snapshot) e Backups (.3dsl + jsonl)
│   ├── sdcard.py           ← detecção SD/console/região + wrapper save3ds (--sdext e --nandsave)
│   ├── titledates.py       ← tid → data de lançamento (tabela offline embutida)
│   └── titledates.json.gz  ← tabela gerada por tools/build_titledates.py (COMMITADA; ~16KB)
├── ui/
│   ├── index.html          ← tela única, CSS fiel ao protótipo (paleta creme/DotGothic16)
│   └── app.js              ← JS puro; render por innerHTML + bind(); estado P (prefs) + S (backend)
├── tests/
│   ├── test_savedata.py    ← unit: round-trip binário, invariantes
│   ├── test_launcher.py    ← unit: parse + round-trip/diff-locality/lifecycle do Launcher
│   ├── test_icons.py       ← unit: decode Morton/RGB565 (com encoder inverso), nomes SMDH
│   ├── test_store.py       ← unit: staging, backups, prune, histórico
│   ├── test_sdcard.py      ← unit: console/região; id0 do movable; árvore NAND sintética
│   ├── test_api_state.py   ← unit: merge launcher/SD no get_state (mock)
│   ├── test_api_launcher_edit.py ← unit: swaps entre tipos, lifecycle de pastas, inject
│   ├── test_titledates.py  ← unit: tabela de datas + presets de sort por data
│   └── test_integration.py ← integração REAL (sdext + nandsave) sobre cópias + guard do G:
├── tools/save3ds/save3ds_fuse.exe  ← v1.3.0 (wwylele/save3ds), extract/import de extdata
├── tools/build_titledates.py ← gera core/titledates.json.gz (3dsdb + GameTDB; precisa internet)
└── sandbox/                ← NUNCA versionar. Cópia do SD real + chaves do console do dev
    ├── sd/Nintendo 3DS/<id0>/<id1>/extdata/00000000/0000008f/...
    └── keys/{boot9.bin, movable.sed, essential.exefs}
```

Dados de runtime do app instalado: `%USERPROFILE%\3DSort\{work,backups,settings.json}`
(settings.json = escolhas do usuario: sd_root e backups_dir; lido pelo build_api,
`--sd` da CLI vence sem sobrescrever o arquivo).

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
# testes (113; integração real é pulada sem sandbox/chaves; o guard do SD real
# re-registra a baseline quando tests/.real_sd_hash não existe)
python -m pytest tests -q

# UI no navegador com dados reais do sandbox (modo de desenvolvimento padrão)
python app.py --serve --sd F:\Projects\3DSort\sandbox\sd    # → http://127.0.0.1:8347

# UI com dados sintéticos (sem SD/chaves — funciona em qualquer máquina)
python app.py --serve --mock

# como acima, mas sem Launcher.dat (testa a degradação: sistema/pastas read-only)
python app.py --serve --mock --no-launcher

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
- **id0 = SHA-256(KeyY)[0:16] lidos como 4 u32 little-endian, cada um em hex** (é o
  DIGEST que sofre o swap de bytes, não a KeyY), onde KeyY = bytes `0x110:0x120` do
  movable.sed. Implementado e validado contra o console real em
  `core/sdcard.py::id0_from_movable`. O save3ds usa isso para achar a pasta — se o
  movable for de outro estado do console, dá `NotFound` (pasta não existe para aquele
  id0) ou `Signature mismatch` (CMAC não bate).

### 5.3 A ARMADILHA da chave velha (custou horas — não repetir)

Backups do GodMode9 podem conter **movable.sed obsoleto**:
- `essential.exefs` (em `gm9/backups/`) e o essential **embutido a offset 0x200 dentro de
  imagens de NAND** `.bin` do GM9 refletem o estado NA ÉPOCA DO BACKUP.
- Se o console passou por formato/transferência depois, esse movable NÃO decripta o SD
  atual (sintomas acima).
- **Fonte confiável**: dump direto no console — GodMode9 → `[1:] SYSNAND CTRNAND` →
  `private/movable.sed` → Copy to `0:/gm9/out`. boot9: GodMode9 → `[M:] MEMORY VIRTUAL` →
  `boot9.bin` (65536 bytes) → Copy.
- IMPLEMENTADO (2026-08-15): o `3DSort_dump.gm9` dumpa as chaves direto do console
  (`1:/private/movable.sed` e `M:/boot9.bin` → `0:/3DSort/`) junto do container, e
  `Api._resolve_keys` valida o movable contra o id0 da pasta em todo import
  (`id0_from_movable`); chave de outro estado do console = erro pedindo re-dump.
  O onboarding da Fase 4 só precisa apontar o script; nunca aproveitar backups antigos.

### 5.4 SaveData.dat (formato v4 — fonte: 3dbrew /wiki/Home_Menu)

Tamanho exato `0x2DA0`. Offsets implementados em `core/savedata.py`:

| Offset | Tipo | Conteúdo |
|--------|------|----------|
| 0x0 | u8 | versão (só aceitamos 4) |
| 0x8 | u64[360] | title IDs dos ícones |
| 0xB48 | s8[360] | flag de embrulho (gift box): **0 = desembrulhado SEMPRE** (mecanismo do "Unwrap all" do Cthulhu, github.com/Ryuzaki-MrL/Cthulhu GPL-3, reimplementado em `set_all_status`); 1 = embrulhável (só embrulha combinado com condição de "novo" do console). NÃO é critério de exibição; nunca filtrar por ele. TODO write zera o array (decisão do usuário 2026-08-15: sem opção, sempre ligado) |
| 0xCB0 | s16[360] | posição linear no grid |
| 0xF80 | s8[360] | pasta do ícone (−1 = home grid) |
| 0x10E8–0x12C8 | ? | NÃO documentado — preservar byte a byte |
| 0x12C8 | u32[60] | nº de batismo por pasta, fid-indexado (60×4 termina exato em 0x13B8) — provado no gate 0B (2026-08-14): create escreve o próximo nº, rename não toca, delete deixa órfão |
| 0x13B8+ | — | temas/shuffle (`OFF_THEMES`). O write ENXERTA esta região da versão ATUAL do cartão (`graft_tail`, extract fresco em `write_sd`): tema trocado no console nunca regride, nem via restore |

- **Preservação é a estratégia central**: `SaveData` guarda o buffer inteiro e só reescreve
  os arrays conhecidos. Round-trip byte-idêntico é garantido por construção e testado.
- **Critério de ativo = tid ∉ {0, 0xFFFF…} e pos ≥ 0, IGUAL ao Launcher** (3dbrew:
  "equivalent to the same array in Launcher.dat"). Corrigido no gate 0C (2026-08-14):
  o critério antigo `status == 1` escondia 15 jogos reais do console do dev (9 no home
  pos 26–34, 6 dentro da pasta Homebrew pos 0–5 — por isso o H&S ficava na pos 6) e
  causou colisão real: `folder_create` pôs a pasta na pos 26, em cima de jogo oculto;
  o console exibiu a pasta e RESOLVEU sozinho reescrevendo o SaveData no boot
  (jogos 26–34 viraram 27–35), sem corromper nada.
- **Embrulho (gift box) NÃO vive nos arquivos que gerenciamos** (0C: console
  desembrulhou 5 ícones com SaveData/Cache byte-intocados). Cosmético, some ao abrir
  o título; não caçar mais. Pós-write o console também pode REORDENAR itens novos
  dentro de pasta (permuta tid↔slot content-preserving) e ajustar status de slots
  vazios — diffs assim são normais, tolerar.
- **O espaço de posições é COMPARTILHADO entre NAND e SD** (confirmado empiricamente:
  no console do dev os jogos SD ocupam 13, 15–25; 0–12 e 14 são apps NAND — pode haver
  app NAND misturado no meio dos jogos). As posições NAND vivem no Launcher.dat (§5.8).
  `apply_order` distribui posições **por contêiner** (home grid e cada pasta), pulando
  as reservadas: menores posições livres na ordem dada. COM launcher, reservas = só as
  posições do Launcher.dat (apps NAND, tiles de pasta, cart): todo dono é conhecido
  desde o fix do critério tid+pos (o "buraco da pos 11" era o cart; os demais eram
  jogos status-0), então buraco = vaga livre real e o write compacta (gate 0C; o
  console exibe buracos sem drama, mas o usuário quer compactação). SEM launcher,
  lacunas continuam reservadas (donos invisíveis possíveis). A antiga densificação
  0..n-1 foi removida; a reserva eterna de buracos com launcher também (2026-08-15).
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
- **ARMADILHA do import incompleto (custou o incidente da 0C)**: importar o extdata SEM
  o diretório `boss/` (mesmo vazio) faz o HOME menu RECONSTRUIR o SaveData.dat no boot:
  slots reindexados, status = 1 em tudo, ícones SD embrulhados, tema resetado ao
  default, membros de pasta ejetados ao home, Cache/CacheD regenerados (dados não são
  perdidos: layout precisa ser rearrumado e tema reativado à mão). Zip de backup
  descartava diretórios vazios — corrigido em `Backups.create` (entries de diretório)
  + cinto em `restore_backup` (garante `boss/`). A árvore importada deve SEMPRE
  espelhar a estrutura completa do extract.
- Releases: binário Windows só até v1.3.0 (v1.4.0 não tem assets).
- pyctr complementa: `ExeFSReader` para ler `movable` de essential.exefs; SMDH de títulos
  se um dia o CacheD não bastar.

### 5.7 Pastas (v1.1 — implementado, gates de hardware pendentes)

`SaveData.dat` (SD) guarda apenas **a qual pasta cada ícone pertence** (s8). As
**definições** das pastas — nome, posição, linhas — vivem em `Launcher.dat` (§5.8).
Desde 2026-08-14 o app EDITA o Launcher.dat via container do system save:
- Reordenar/renomear/criar/apagar pastas e mover apps NAND entre contêineres:
  implementado como mudanças staged (chaves de entidade, §6); a escrita gera payload
  de injeção + scripts GM9 (§5.8).
- Nome de pasta: 0x22 bytes UTF-16LE = **16 unidades + NUL garantido** (validado em
  `Launcher.set_folder_name`). Create usa o menor fid livre (fpos<0 e sem referência
  ativa em SD/NAND), nome "New folder", rows 2. Delete zera nome, rows=2, fpos=-1 e
  devolve membros ao home (jogos por rank no fim; NAND com posições explícitas depois).
- **GATE 0B CUMPRIDO** (2026-08-14, console real, dumps em `sandbox/gate0B/`):
  - create (console): fpos=35 (fim do grid, NÃO a menor livre), rows=1 (nosso default 2
    também é aceito — Homebrew usa 2), nome default "２" (nº fullwidth) JÁ gravado no
    Launcher; SaveData: nº de batismo escrito em `numeros[fid]` (u32 @0x12C8, §5.4);
    Launcher: contador "próximo nº de pasta" (u32 @0xD80 + byte espelho @0xD85)
    incrementado.
  - rename (console): só o campo de nome no Launcher; SaveData byte-idêntico.
  - delete (console): fpos=−1, nome zerado, rows fica como estava; nº no SaveData fica
    ÓRFÃO e o contador @0xD80 NÃO decrementa.
  - Patch de espelhamento IMPLEMENTADO (2026-08-14): `write_sd` escreve o nº de
    batismo das pastas novas (`SaveData.set_folder_number`, contador lido do Launcher
    corrente) e `_write_launcher` incrementa o contador
    (`Launcher.set_next_folder_number`). Delete não limpa nada (igual ao console).
    Prova final (boot com pasta criada pelo app) fica na Fase 0C.

### 5.8 Launcher.dat (apps NAND — leitura E escrita em core/launcher.py)

- Local: system save do HOME menu na NAND — `nand:/data/<id0>/sysdata/<ID>/00000000`,
  ID por região: **JPN `00020082` · USA `0002008F` · EUR `00020098`** (mapa
  `NAND_SAVE_IDS` em core/sdcard.py).
- **Fontes, em ordem de precedência** (`Api._find_container`/`_read_launcher`):
  1. CONTAINER `homemenu_save.bin` (o arquivo `00000000` inteiro, DISA 64KB) — canal
     EDITÁVEL. Procurado em `<sd>/3DSort/homemenu_save.bin` (onde o script GM9 de dump
     deixa), `sandbox/keys/` (dev) e `%USERPROFILE%\3DSort\`. Com escrita pendente, o
     payload gerado `homemenu_save_new.bin` tem precedência (a verdade do app).
  2. `Launcher.dat` plano (dump via mount A:) — fallback READ-ONLY (comportamento v1).
  3. Nada — inferência por lacunas (placeholders "System app").
- **Canal de escrita (validado no spike 0A de 2026-08-14)**: save3ds
  `--nandsave <ID8hex> --nand <dir> --boot9 <boot9> --extract|--import` sobre árvore
  NAND sintética `nand/{private/movable.sed, data/<id0>/sysdata/<id>/00000000}`
  (`Save3ds.build_nand_tree`). Extract do container real == dump GM9 byte a byte; o
  save contém APENAS `Launcher.dat`. Patch raw do container é INVIÁVEL (IVFC).
- **Disciplina da âncora (aprendida a ferro na 0C)**: TODA sessão do HOME drifta bytes
  voláteis do container, então `homemenu_save.bin.sha` só é confiável vindo do
  `cp --hash` do `3DSort_dump`. O app NUNCA fabrica essa âncora; escrita de launcher
  exige o par bin+sha fresco (senão erro pedindo re-dump) e o promote pós-inject
  DESCARTA as âncoras de propósito. Ciclo de escrita do launcher sempre começa com
  dump fresco. Restore total pode fazer dump+inject na mesma sessão GM9 (gate 2 vira
  tautologia, aceitável só porque a intenção é sobrescrever tudo).
- **Chaves sem cópia manual (2026-08-15)**: `3DSort_dump.gm9` é publicado em TODO
  `import_sd` (não só na escrita — mata o chicken-and-egg do usuário novo) e dumpa,
  além do container, `movable.sed` (de `1:/private/`) e `boot9.bin` (de `M:/`) em
  `0:/3DSort/`. `Api._resolve_keys` procura boot9/movable em `<sd>/3DSort/` >
  `<sd>/gm9/out/` > paths do `build_api` (`sandbox/keys/` > `%USERPROFILE%\3DSort\`),
  valida o movable contra `console.id0` e devolve erro amigável (chaves ausentes ou
  de outro estado do console) em vez do `FileNotFoundError` cru.
- **Injeção**: o app publica `<sd>/3DSort/homemenu_save_new.bin` + `.sha` + scripts
  `<sd>/gm9/scripts/3DSort_{dump,inject}.gm9`. O inject tem gates sha duros (payload
  íntegro; NAND == dump original, aborta se o HOME bootou no meio; cópia bit-perfeita)
  + `fixcmac` + recibo `inject_done.sha`. O app confirma o recibo no próximo import e
  promove o payload a dump corrente. **GATE PENDENTE (Fase 0C)**: uma escrita real
  validada no console (trocar 2 apps NAND, injetar, bootar, fotografar, restaurar).
- Tamanho: 3dbrew documenta `0x2490`, mas o console real (11.17 USA) produz **`0x2558`**
  — 200 bytes extras no FIM, offsets conhecidos idênticos (validado no dump do dev; o
  parser aceita `>= 0x2490`). Offsets: tids NAND u64[360] @0x8; posições s16[360] @0xD9A
  (locais ao contêiner, ver §5.4); pasta s8[360] @0x106A. Pastas: posições s16[60] @0x11DC
  (−1 = apagada), linhas u8[60] @0x1434, nomes UTF-16LE 0x22 bytes @0x1560.
- Campos empíricos fora dos arrays (gate 0B, 2026-08-14): u32 @0xD80 + byte espelho
  @0xD85 = "próximo nº de pasta" (nome default); bytes voláteis @0xB51/@0xB54/@0xB5C
  (estado de cursor/UI, mudam a cada sessão do HOME) e ~12 bytes de estatísticas na
  cauda (0x1FA4, 0x2298, …) — o console regenera sozinho; stale pós-inject presumido
  inofensivo (confirmar na 0C).
- Validado no dump do dev: critério de ativo = tid ∉ {0, 0xFFFF…} e pos ≥ 0; a lista de
  tids NAND inclui títulos **TWL/DSiWare** (tid high `00048004`, ex. TWiLight Menu++ =
  `0004800453524c41`, gamecode "SRLA" — NÃO é o slot de cartucho); pasta id 0 = "Homebrew"
  @pos 12 com Health & Safety dentro. **Slot do cartucho: u16 @0x2 do Launcher.dat**
  ("cart launcher position"; ≥360 = inválido) — no console do dev vale 11. Reservas sem
  dono restantes viram placeholder "System app" (união de reservas, §5.4).
- **Escrita real na NAND é SEMPRE do usuário** (script GM9 de injeção, com `ask` de
  consentimento no console) — o app só edita a CÓPIA no SD. Sem container, apps NAND
  ficam pinned (v1). Buracos abaixo do máximo: com launcher são vagas livres DE
  VERDADE (sem tile, compactadas no próximo write, 2026-08-15); sem launcher, donos
  desconhecidos ("System app", reservados para sempre).
- Sem Launcher.dat o app infere os slots NAND pelas LACUNAS nas posições SD (placeholders
  "System app" sem nome; apps NAND depois do último jogo ficam invisíveis).
- O Cache/CacheD do SD já contém nome+ícone dos títulos NAND (§5.5) — o Launcher só
  fornece as posições. Pendente validar com dump real: critério de slot ativo (tid≠0 e
  pos≥0), entrada do gamecard (tid `0004800453524c41` "SRLA" visto no cache do dev).

## 6. Backend (app.py + core/) — contratos

- **Chaves de entidade** (posicionais, JSON-simples): `"g:<slot>"` jogo SD, `"n:<slot>"`
  app NAND, `"f:<id>"` tile de pasta, `"cart"` Game Card. Int puro = `g:<slot>`
  (retrocompatível). Parse em `Api._key`.
- `Api.get_state()` → `{items: [{key,slot,pos,tid,folder,name,icon}...],
  system: [{key,slot,tid,pos,folder,pinned,name,icon,hole?}...] (pinned = launcher
  read-only; hole=True = vaga livre conhecida "Empty slot"; sem launcher, placeholders
  "System app"), folderNames/folderPos/folderRows: {fid: ...} (do STAGING),
  launcherWritable, launcherDirty, pendingInject: {sha,when,changes}|null,
  staged, canUndo, canRedo, sd, backups_dir, history}`. Toda mutação retorna o estado
  completo novo (UI re-renderiza inteira).
- Snapshot do staging: `{order, folders, tids, nand_tids, nand_pos, nand_folder,
  folder_defs: {fid:{pos,name,rows}}, cart_pos}` — undo/redo/restore cobrem tudo.
  Jogos NÃO têm posição explícita: `assign_positions` distribui as menores livres por
  contêiner, pulando `_reserved_now` (posições staged de NAND/pasta/cart; sem
  launcher, também os buracos sem dono). Invariante do swap exato: sem launcher, todo
  buraco abaixo do máximo é reservado, logo livre == ocupado pelos jogos; com
  launcher, livre ⊇ ocupado e o write compacta jogos nas menores vagas (testado em
  test_api_launcher_edit).
- Mutações staged: `move_item(slot, before|null)`, `swap_items(a, b)` (QUALQUER par de
  tipos; pasta/cart só no home), `set_folder(key, folder)` (g/n; NAND ganha posição
  explícita = menor livre no destino), `folder_create()`, `folder_rename(fid, name)`,
  `folder_empty(fid)`, `folder_delete(fid)` (membros voltam ao home), `sort_preset`,
  `undo/redo/reset_staging`. `folder_create(name=None)` aceita nome opcional (mesma
  validação do rename: 1..16 unidades UTF-16; None/"" = "New folder") — a UI pede o
  nome num modal antes de criar (Cancel não cria). `sort_preset` aceita `az`, `za`,
  `date_asc`, `date_desc`; os de data usam `core/titledates.py` (tabela offline
  tid→"YYYY-MM-DD" gerada por `tools/build_titledates.py` de 3dsdb + GameTDB;
  título sem data vai para o FIM nos dois sentidos; tabela ausente = tudo sem data,
  sort vira no-op estável). Mutações de launcher exigem `launcherWritable`.
  Todo `write_sd` zera o array de status (desembrulho sempre ligado, §5.4) e
  enxerta a região de temas 0x13B8+ da versão atual do cartão (graft, §5.4).
- `write_sd()` é **all-or-nothing** (SD + launcher do MESMO snapshot): staged>0 →
  gate de container obsoleto (sha) → gate de dump fresco (par bin+sha do GM9 ao
  lado do container, §5.8) → backup auto (inclui `__nand__/Launcher.dat` +
  container) → SaveData → se `launcherDirty`: edita Launcher no container via
  nandsave, `validate()`, publica payload+scripts no SD, marker `pending_inject.json`
  no workdir. Falha no ramo launcher NÃO limpa o staging (retry idempotente).
  `verify_inject()`/`confirm_inject()` fecham o ciclo (recibo do GM9, §5.8).
  `import_sd()`: checa recibo, re-extrai e RESETA o staging.
- Settings (2026-08-15): `list_drives()` → `{drives: [{root, current}]}` (varredura
  D..P por `Nintendo 3DS/` + sd_root atual); `set_sd_root(path)` valida, re-importa
  (staging resetado — mesma carta em letra nova é o caso comum, pending inject é
  mantido); `set_backups_dir(path)` move zips + history.jsonl junto
  (`Backups.move_root`). `pick_backups_dir()` abre o seletor de pasta NATIVO
  (`pick_folder_native`: pywebview create_file_dialog quando há janela; senão
  tkinter — o backend do --serve roda na mesma máquina do navegador) e aplica.
  Ambos persistem em `settings.json` ao lado do workdir (mock = tmp, sem tocar a
  máquina). Na UI: dropdown no chip do drive (varredura ~2ms) e o botão Change…
  do Backup folder chama o dialogo nativo (SETTINGS).
- `Staging` (core/store.py): snapshots imutáveis com deepcopy; `commit` limpa redo;
  `clear()` após write. `Backups`: zip `.3dsl` + `history.jsonl`, mantém últimos 20;
  `create(..., extra={arcname: bytes|Path})` guarda arquivos fora da árvore de extdata
  (prefixo `__nand__/`, removido do extract no restore antes de qualquer import).
- Erros da API viram `{"error": msg}` (o handler HTTP captura exceções); a UI mostra toast.
- Mock (`--mock`): `FakeSave3ds` copia árvore plana em vez de decriptar; `make_mock_extdata`
  gera 12 jogos com SMDH sintético; o "container" mock é um arquivo cujos bytes SÃO o
  Launcher.dat (nand_extract/import = cópia). `--no-launcher` testa a degradação.
  O mock exercita 100% do código real exceto a crypto — é o modo dos testes de UI.

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
  do usuário 2026-08-14): identidade do drag = `P.dragKey` (chave de entidade, §6) lida
  de `data-ekey` — jogos sempre; apps NAND/pastas/cart só com `launcherWritable`. Drop
  sobre qualquer tile com ekey = `swap_items` (`.swap-with`); jogo/NAND sobre pasta =
  `set_folder` (`.drop-into`, anel azul de pasta) — para trocar COM a pasta,
  arrasta-se a PASTA sobre o item. Células vazias e holes não são alvo (swap não tem
  par). Nada muda no DOM durante o drag; commit no drop + animação FLIP
  (`captureGrid`/`playFlip`, WAAPI) por `data-key` (`s<slot>`/`n<slot>`/`cart`/
  `f<id>`/`h<pos>`). Clique abre pasta; `#removeZone` = tirar da pasta; drag cancelado
  limpa via `render()` no dragend. Separadores `.page-sep` = quebras de página do
  console. Lifecycle de pastas: botão `+ Folder` no grid-head abre modal de nome
  (Save cria com o nome ou "New folder" se vazio; Cancel não cria), rename por input
  (commit em Enter/blur — NUNCA por tecla, o innerHTML rouba o foco), delete com modal
  de confirmação. SYNC mostra banner de inject pendente com Verify/`Mark as done`.
- Decisões visuais de 2026-08-15: pastas são SEMPRE azuis (`FOLDER_BLUE = #3b4cca`;
  seletor de cor removido — não existe no 3DS real) e tiles de sistema sem
  transparência (o fluxo NAND é cidadão de primeira classe desde a 0C).
- **Projeto é inglês-only** (decisão do usuário 2026-08-15): UI, comentários de
  código, mensagens de erro e scripts GM9 gerados. O seletor de idioma do SETTINGS
  foi removido (era stub sem i18n); não reintroduzir i18n sem pedido novo.

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

**Feito (2026-08-14, manhã)**: spike round-trip OK em dados reais; core completo;
UI GRID/SYNC/SETTINGS portada e validada em tela com ícones reais; modo mock; backups +
restore staged; apps NAND no grid com Launcher.dat REAL dumpado e validado — visão do
console reproduzida 1:1. Sandbox re-copiado do SD real.

**Feito (2026-08-14, v1.1 — 77 testes)**: escrita do Launcher.dat de ponta a ponta.
Spike 0A validou o canal save3ds --nandsave (extract == dump GM9 byte a byte).
`Launcher` com preservação/validate/lifecycle; canal NAND no `Save3ds` + FakeSave3ds;
modelo unificado de entidades (g:/n:/f:/cart) com reservas dinâmicas e staging
completo (undo/redo/restore cobrem launcher); swap entre QUAISQUER tipos; pastas
criar/renomear/esvaziar/apagar; write all-or-nothing com payload de injeção + scripts
GM9 gerados + recibo verificado; backups incluem launcher/container; UI com drag por
ekey, lifecycle de pastas, banner de inject no SYNC — tudo validado em tela
(Playwright, mock) incluindo degradação `--no-launcher`.

**Feito (2026-08-15, gates de hardware no console real)**: além dos gates abaixo, a
sessão rendeu: critério de ativo corrigido (tid+pos; 15 jogos status-0 invisíveis e
colisão real de pasta, §5.4); incidente do `boss/` no restore (§5.6) corrigido;
disciplina da âncora de inject (§5.8: dump fresco obrigatório, promote descarta
âncoras); buracos livres com launcher (§5.4); desembrulho automático em todo write
(§5.4, Cthulhu); tema preservado via graft (§5.4). 89 testes.

**Feito (2026-08-15, tarde)**: fluxo sem cópia manual (§5.3/§5.8): `3DSort_dump.gm9`
publicado em todo import e dumpando container + movable.sed + boot9.bin em
`0:/3DSort/`; `Api._resolve_keys` (SD > gm9/out > sandbox/APP_DIR, com validação
de id0 e erros amigáveis). VALIDADO NO CONSOLE REAL no mesmo dia: `3DSort_dump`
novo rodado no GM9 deixou movable.sed (320B), boot9.bin (64KB) e container+.sha
em `0:/3DSort/`; id0 do movable bateu com a pasta; o app resolveu as chaves do
próprio SD (`G:\3DSort\`). 98 testes (novos em `tests/test_api_keys.py`).

**Feito (2026-08-15, SETTINGS)**: linhas "SD card drive" e "Backup folder" funcionais
(§6: list_drives/set_sd_root/set_backups_dir + settings.json; UI com dropdown e
modal; import re-autodetecta drive se a letra persistida sumiu). 106 testes
(novos em `tests/test_api_settings.py`). Validado em tela (mock, Playwright).

**GATES DE HARDWARE (CONCLUÍDOS em 2026-08-14/15)**:
- Fase 0B: FEITA em 2026-08-14 (ver §5.7). Veredito: create/delete SHIPA. Patch de
  espelhamento (`numeros[fid]` no SaveData @0x12C8 + contador @0xD80/@0xD85 no
  Launcher) implementado e testado no mesmo dia.
- Fase 0C: INJEÇÃO VALIDADA em 2026-08-14 (console real, foto conferida): swap de 2
  apps NAND + pasta criada pelo app (com nº de batismo e contador do gate 0B) chegaram
  ao HOME exatamente como o modelo previu. Scripts GM9 validados em hardware
  (dump com `--hash`, inject com os 3 gates, `allow`, `fixcmac`, recibo; `ask` ok).
  O gate 2 foi validado AO VIVO (abortou corretamente sempre que o HOME bootou entre
  write e inject; recovery: dump fresco + Import + re-staging). RESTORE validado em
  hardware (expôs e corrigiu o incidente do `boss/`, §5.6). **GATE 0C FECHADO em
  2026-08-15**: ciclo final limpo no console (pasta compactada, swap NAND↔jogo dentro
  de pasta, desembrulho em massa, tema preservado via graft). Resíduo conhecido:
  1 título ficou embrulhado (condição interna de "novo" do console, fora dos nossos
  arquivos) — abre-se uma vez e resolve.

**Feito (2026-08-15, polish inglês-only + sort por data)**: seletor de idioma
removido do SETTINGS (projeto inglês-only, §7); todos os comentários/docstrings e
mensagens de erro do código traduzidos para inglês (incluindo os comentários dentro
dos scripts GM9 gerados); transparência dos tiles de sistema removida; cor de pasta
fixa em azul (seletor removido); sort por data de lançamento asc/desc
(`core/titledates.py` + tabela offline de 3756 títulos, 16KB gz, §6); `+ Folder`
com modal de nome (Cancel não cria). 113 testes.

**Fase 4 (próxima)**: PyInstaller onefile embutindo `save3ds_fuse.exe`, `ui/` e
`core/titledates.json.gz` (data file!); requirements.txt; primeira execução com
onboarding guiado (dump boot9/movable com validação de id0, escolha do drive);
README de distribuição; testar janela pywebview; smoke em máquina limpa.

**v1.1 restante (pré-release)**: `cancel_inject` (abandonar payload pendente sem
limpeza manual); erro de `write_sd` DESTACADO no modal da UI (hoje é toast e passou
despercebido, custando idas ao console); fontes offline.

**v2**: aba RULES (motor de regras), THEMES/badges.

**Dívidas conscientes**: `spike.py` não usa core/ (era pra ser descartável; apagar ou
refatorar sobre core na Fase 4). Observações de hardware já incorporadas: console
exibe buracos sem drama (0B/0C) e o app compacta por decisão de produto quando o
launcher está presente (§5.4); boot do HOME entre write e inject → gate 2 aborta
corretamente e o app exige dump fresco antes de escrita de launcher (§5.8); console
tolera SaveData novo + launcher velho sem corromper; embrulho residual em título
recém-movido é estado interno do console (abre-se uma vez, §5.4/§10).

## 11. Regras de trabalho para a IA neste repo

- Antes de mexer em formato binário, releia §5 e os testes de round-trip; qualquer campo
  novo descoberto empiricamente → documentar AQUI e no 3dbrew-style (offset/tamanho/prova).
- Simplicidade primeiro (stdlib > dependência nova), mas NUNCA à custa das regras do §3.
- Não versionar/expor `sandbox/`, chaves, ou dados do console do usuário.
- Mudanças em `Api`: manter os dois canais (js_api posicional + HTTP `{"args": []}`).
- Validar sempre com `python -m pytest tests -q` + fluxo Playwright quando houver UI.
- O protótipo `.dc.html` é REFERÊNCIA visual, não código: não importar seu runtime.
