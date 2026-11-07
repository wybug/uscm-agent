"""Module-scheme detection and placement-unit mapping.

Four schemes, auto-detected per repository from its change history:

- ``multi``  : >= 2 Maven-style modules (path segment before ``/src/main/java/``)
- ``single`` : Java sources at repo root -> L1 = package segment after the
               longest common package prefix
- ``front``  : front-end repo (views/pages/api/components/store paths dominate)
               -> placement unit = distinct *page*; layer crossings
               (page -> api -> comp) are normative structure, not scatter
- ``flat2``  : Go/TS/etc. without Java -> module = first two directory levels

Placement accounting only counts source files (``is_source``) and excludes
test modules (``is_test_module``). Semantics follow the USCM-CC paper's
measurement pipeline; see THEORY.md.
"""
from __future__ import annotations

FRONT_MARKS = ("src/views/", "src/pages/", "/pages/", "src/components/",
               "/components/", "src/api/", "/apis/", "src/store/",
               "/stores/", "/subpackages/")


def detect_scheme(files: list[str]) -> dict:
    """Auto-detect a repository's module scheme from its changed-file list."""
    java = [f for f in files if f.endswith(".java")]
    mods = sorted({f.split("/src/main/java/")[0]
                   for f in java if "/src/main/java/" in f})
    if len(mods) >= 2:
        return {"type": "multi", "dirs": mods}
    if java:
        prefixes = []
        for f in java:
            if "/src/main/java/" in f:
                prefixes.append(f.split("/src/main/java/", 1)[1].split("/")[:-1])
            elif f.startswith("src/main/java/"):
                prefixes.append(f.split("src/main/java/", 1)[1].split("/")[:-1])
        common: list[str] = []
        for segs in zip(*prefixes):
            if len(set(segs)) == 1:
                common.append(segs[0])
            else:
                break
        return {"type": "single", "prefix": common}
    if files:
        hit = sum(1 for f in files if any(m in f.lower() for m in FRONT_MARKS))
        if hit >= 0.4 * len(files):
            return {"type": "front"}
    return {"type": "flat2"}


def _stem(fn: str) -> str:
    return fn.rsplit(".", 1)[0]


def front_module_of(path: str) -> str:
    """Map a front-end file to page:/api:/comp:/store:, falling back to dirs."""
    p = path.split("/")
    for i, seg in enumerate(p):
        low = seg.lower()
        if low in ("views", "pages") and i + 1 < len(p):
            nxt = p[i + 1]
            return "page:" + (nxt if i + 2 < len(p) else _stem(nxt))
        if low in ("api", "apis") and i + 1 < len(p):
            nxt = p[i + 1]
            return "api:" + (_stem(nxt) if nxt.rsplit(".", 1)[-1] in ("js", "ts") else nxt)
        if low in ("components", "component") and i + 1 < len(p):
            nxt = p[i + 1]
            return "comp:" + (nxt if i + 2 < len(p) else _stem(nxt))
        if low in ("store", "stores") and i + 1 < len(p):
            return "store:" + _stem(p[i + 1])
    d = p[:-1]
    if not d:
        return "root"
    return "/".join(d[:2]) if len(d) >= 2 else d[0]


def is_source(path: str) -> bool:
    """Source files that count as placement landings.

    Java (src/main/java; tests excluded by construction), Go (no vendor,
    no _test.go), TS/TSX/Vue/JSX (no node_modules/dist/.d.ts/.test./.spec.).
    """
    p = "/" + path
    if path.endswith(".java"):
        return "src/main/java/" in path
    if path.endswith(".go"):
        return "/vendor/" not in p and not path.endswith("_test.go")
    if path.endswith((".tsx", ".vue", ".jsx")) or \
            (path.endswith(".ts") and not path.endswith(".d.ts")):
        return ("/node_modules/" not in p and "/dist/" not in p
                and ".test." not in path and ".spec." not in path)
    return False


def is_test_module(path: str) -> bool:
    """Maven modules whose directory part mentions 'test' are test projects."""
    if "/src/main/java/" in path:
        return "test" in path.split("/src/main/java/")[0].lower()
    return False


def unit_of(scheme: dict, path: str) -> str | None:
    """Placement unit of one file, or None if the file lands in no unit.

    ``front``: only pages are units (scatter = touching >= 2 pages);
    api/comp/store layer crossings are normative. Other schemes: L1 module.
    """
    t = scheme["type"]
    if t == "front":
        m = front_module_of(path)
        return m if m.startswith("page:") else None
    if t == "flat2":
        d = path.split("/")[:-1]
        if not d:
            return "root"
        return "/".join(d[:2]) if len(d) >= 2 else d[0]
    if t == "multi":
        if "/src/main/java/" in path:
            m = path.split("/src/main/java/")[0]
            if m in scheme["dirs"]:
                return m
        return "other"
    # single: package L1 after common prefix
    if "/src/main/java/" in path:
        pk = path.split("/src/main/java/", 1)[1].split("/")[:-1]
    elif path.startswith("src/main/java/"):
        pk = path.split("src/main/java/", 1)[1].split("/")[:-1]
    else:
        return "root"
    pre = scheme["prefix"]
    tail = pk[len(pre):] if pk[:len(pre)] == pre else pk
    return tail[0] if tail else "root"


def units_of(scheme: dict, files: list[str]) -> set[str]:
    """Placement units touched by a change (source files, non-test)."""
    out = set()
    for f in files:
        if not is_source(f) or is_test_module(f):
            continue
        u = unit_of(scheme, f)
        if u is not None:
            out.add(u)
    return out


def unit_l2(scheme: dict, path: str) -> str | None:
    """Finer (L2) unit, for advisory display only."""
    t = scheme["type"]
    if t == "front":
        return front_module_of(path)
    if t == "flat2":
        d = path.split("/")[:-1]
        if not d:
            return "root"
        l1 = "/".join(d[:2]) if len(d) >= 2 else d[0]
        return f"{l1}:{d[2]}" if len(d) > 2 else l1
    u = unit_of(scheme, path)
    return u
