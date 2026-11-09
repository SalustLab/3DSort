# 3DSBank compatibility work

Status: discovery component only; application integration is not implemented.

3DSBank stores the active bank at `Nintendo 3DS` and inactive banks at
`3DSBank/SlotN`. Its UI supports slots 0–39. On startup it renames the active
directory into storage and writes an intermediate directory count to its INI.
Rename results are unchecked, so configuration alone cannot prove ownership.

SD SaveData owns SD title positions and folder membership. NAND Launcher owns
system applications, DSiWare and folder definitions and is shared across banks.
An inactive layout must not be paired with an assumed independent Launcher.

The discovery component reads metadata without creating or repairing files.
It rejects redirected bank paths and treats contradictory active-slot metadata
as unknown. It does not authorize writing or recovery.

Bank selection, isolated helper extraction, bank-aware backups and transactions,
and UI integration remain required before advertising compatibility. Inactive
writes remain blocked pending helper lifecycle and shared-state validation.

No native UI or physical-console validation has been performed for this work.
