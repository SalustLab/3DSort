# Historical hardware evidence

Source: main CLAUDE.md at a4aef85, sections 5, 7, 10 and 12. These are retained
reports, not hardware tests performed by this audit. Private dumps are not
published and cannot independently substantiate new claims here.

- USA developer and second New 3DS: reported dump/sort/write/inject/boot,
  folders, baptism counters, restore, theme graft, multi-id0 and gate-2 abort.
- 2026-09-30 reporter: 0x2CB0 v4 read/write and DSiWare/forwarder sorting.
- 2026-10-22 owner: multiselect and regional cache fix before v1.3.0.
- macOS arm64 contributor: v1.1.0 app read/write/inject on New 2DS XL.
  Exact OS version in the old note is unverified; do not use it as compatibility proof.
- Region-changed JPN-to-USA console: see [regional evidence](REGION_CHANGE.md).
- Badge placement, stock, decorations and independent mega-badge pieces:
  [dated badge observations](BADGES_TESTING.md).
- JPN/USA/EUR were historically reported validated; CHN/KOR/TWN remain untested.

Important observations: HOME can reindex all slots after title installation
while preserving tid/position/folder tuples. Never persist slot identity across
imports. Positions are local to containers; holes are supported by hardware.
Folder baptism numbers can remain orphaned after deletion and disappear later.
Console-internal wrapping and occasional post-boot reordering are not fully
controlled by the files edited here. Badge alpha orientation remains synthetic-tested.

Still required: physical console acceptance of new Folder Sort/Rules combinations,
clean-machine Windows native smoke, Linux distro/native drag checks and current
macOS packaging checks. Headless Chromium and automated binary tests do not
validate native engines or console boot behavior. No emulator result substitutes
for hardware evidence.
