"""Exact positions and shared occupancy for the HOME menu and folders."""

HOME_CAPACITY = 360
FOLDER_CAPACITY = 60


def capacity(folder):
    return HOME_CAPACITY if folder == -1 else FOLDER_CAPACITY


def entities(st):
    out = {("g", s): (st["folders"][s], p) for s, p in st["game_pos"].items()}
    out.update({("n", s): (st["nand_folder"][s], p) for s, p in st["nand_pos"].items()})
    out.update({("f", f): (-1, d["pos"]) for f, d in st["folder_defs"].items()})
    if st["cart_pos"] is not None:
        out[("cart", None)] = (-1, st["cart_pos"])
    for slot, b in st.get("badge_layout", {}).items():
        if b.get("decoration") is None:
            out[("b", slot)] = (b["folder"], b["pos"])
    return out


def issues(st, unknown=()):
    occupied = {}
    errors = []
    for key, (folder, pos) in entities(st).items():
        if type(folder) is not int or type(pos) is not int:
            errors.append(f"Item {key} needs integer grid coordinates.")
            continue
        if folder != -1 and (not 0 <= folder < 60 or
                             (st.get("folders_known", bool(st["folder_defs"])) and folder not in st["folder_defs"])):
            errors.append(f"Item {key} references a missing folder.")
        if not 0 <= pos < capacity(folder):
            errors.append(f"Item {key}: position {pos} is outside this grid.")
        cell = folder, pos
        if cell in occupied:
            errors.append(f"Items {occupied[cell]} and {key} occupy folder {folder}, position {pos}.")
        if pos in dict(unknown).get(folder, ()):
            errors.append(f"Item {key}: position {pos} has an unknown owner. Import a HOME menu dump first.")
        occupied[cell] = key
    if set(st["game_pos"]) != set(st["tids"]) or set(st["folders"]) != set(st["tids"]):
        errors.append("The layout does not contain exactly the imported games.")
    return errors


def validate(st, unknown=()):
    errors = issues(st, unknown)
    if errors:
        raise ValueError(errors[0])


def place(st, key, folder, pos):
    kind, n = key
    if kind in ("f", "cart") and folder != -1:
        raise ValueError("Folders and the Game Card can only sit on the home grid.")
    if kind == "g":
        st["folders"][n], st["game_pos"][n] = folder, pos
    elif kind == "n":
        st["nand_folder"][n], st["nand_pos"][n] = folder, pos
    elif kind == "f":
        st["folder_defs"][n]["pos"] = pos
    elif kind == "cart":
        st["cart_pos"] = pos
    elif kind == "b":
        st["badge_layout"][n].update(folder=folder, pos=pos, decoration=None)
    else:
        raise ValueError("Unknown item type.")


def first_free(st, folder, unknown=(), taken=()):
    used = {p for c, p in entities(st).values() if c == folder}
    used.update(dict(unknown).get(folder, ()))
    used.update(taken)
    for p in range(capacity(folder)):
        if p not in used:
            return p
    raise ValueError("This grid is full.")
