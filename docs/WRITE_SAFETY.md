# SD and NAND write safety

Read `core/write_api.py`, the corresponding tests and [formats](SAVE_FORMATS.md)
before changing write behavior. Never write tests against a physical SD.
The real-SD hash guard detects differences against a stored baseline; it is
not a write interceptor or proof that no writes occurred during the entire suite.
Keep it outside sandbox-dependent module skips.

Prepare payloads locally, extract a fresh base, create an automatic backup before
import, journal steps and verify re-extracted hashes. Multiple filesystem writes
are recoverable, not physically atomic. Recovery requires explicit user action;
do not auto-recover on startup. Validate card identity and local recovery hashes.

save3ds import replaces extdata: preserve the complete extracted tree, including
empty boss/. Historical omission caused HOME to rebuild layout and theme state.
Never create zero-size console files. Backup restoration is staged, not a direct
card write. New __badges__/ and __layout__/ namespaces do not enter HOME extdata;
legacy restores retain current badges. Do not restore new backups with old apps.

NAND is changed by the owner through GodMode9, never directly by the desktop app.
Require a fresh GM9 bin+sha anchor; do not fabricate one. Injection gates check
payload integrity, original NAND hash and copied bytes, then fix CMAC and emit a
receipt. HOME boot between dump and inject invalidates the anchor. Keep payload,
marker and inject-script lifecycle consistent. Badge-dependent injection cannot
be cancelled independently because old NAND positions may overlap written SD data.

Region and stale regional dump handling: [REGION_CHANGE](REGION_CHANGE.md).
One card can contain multiple id0 values and multiple regional saves. Validate
movable.sed against id0; old essential/NAND backups may contain obsolete keys.
id0 derives from SHA-256 of movable KeyY bytes 0x110:0x120, first 16 digest bytes
formatted as four little-endian u32 values. Never infer the active region from
icon counts alone or SecureInfo after CTRTransfer.

Never commit boot9.bin, movable.sed/*.sed, essential.exefs, Launcher.dat, sandbox,
personal dumps, identifiers or keys. Public reports use synthetic reproductions.
