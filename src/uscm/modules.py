"""Module-scheme detection and placement-unit mapping.

Five schemes, auto-detected per repository from its change history:

- ``dw``     : data-warehouse script repository (SQL tasks named after their
               target table ``<layer>_<domain>_<subject>``) -> placement
               unit = business subject (``domain.subject``); layer crossings
               (ods -> dwd -> dws -> ads) are normative structure, not scatter
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

import re

FRONT_MARKS = ("src/views/", "src/pages/", "/pages/", "src/components/",
               "/components/", "src/api/", "/apis/", "src/store/",
               "/stores/", "/subpackages/")

# Data-warehouse scripts. A repository is ``dw`` when nearly all of its
# changed files are SQL; Python counts as a warehouse script only when it is
# named after its target table (a PyODPS task), never as generic service code.
DW_SQL_EXTS = (".sql", ".hql")
DW_SHARE = 0.8
DW_LAYERS = ("ods", "dim", "dwd", "dws", "ads")
DW_ENGINE_DIRS = {"fs", "mc", "holo", "es", "sdb", "fsec", "mysql", "doris",
                  "hive", "kudu", "maxcompute", "aliyun", "local", "tmp"}
# Operation / placeholder words that can follow a layer in a script name
# (``ods_ops_ddl_abc``, ``dws_dml_abc``): never a domain, never a subject.
DW_NON_SUBJECTS = {"ddl", "dml", "all", "tmp", "temp", "test", "old", "new",
                   "copy", "bak", "backup", "view", "idx", "index", "xxx"}
_DW_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_DW_SPLIT = re.compile(r"[_@.\-]+")
_DW_WORD = re.compile(r"^[a-z]+$")

# Technical stereotype packages: crossing them is normative layering, not
# scatter (the DDD-layered analogue of the front-end page->api->comp rule).
STEREOTYPES = {
    "dto", "vo", "bo", "po", "entity", "model", "models", "enums", "enum",
    "constants", "config", "configuration", "utils", "util", "exception",
    "exceptions", "handler", "interceptor", "aspect", "filter", "converter",
    "convert", "assembler", "impl", "service", "services", "controller",
    "http", "api", "facade", "rpc", "remote", "feign", "gateway", "client",
    "mapper", "dao", "repository", "repo", "condition", "query", "manager",
    "task", "job", "listener", "consumer", "producer", "aop", "annotation",
    "support", "helper", "base", "integration", "wrapper", "type", "types",
    "cache", "log", "monitor", "test", "constant", "result", "response",
    "request", "context", "event", "events", "schedule", "servlet",
}


def apply_unit_style(scheme: dict, files: list[str], style: str = "module",
                     skip: list[str] | None = None) -> dict:
    """Attach a placement-unit style to a detected scheme.

    ``module`` (default): unit = Maven module / directory prefix.
    ``pkg``: unit = first *business* package segment - the package path is
    stripped of the repo-wide common prefix and the module-name segment,
    technical stereotype packages (``skip``, default STEREOTYPES) are
    stepped over, and the first remaining segment is the unit. Files that
    never reach a business segment land in no unit (normative structure).

    Use ``pkg`` for DDD-layered monorepos where modules are architecture
    layers (adapter/application/domain/infrastructure): crossing layers is
    normative, scatter means spanning >= 3 business capabilities.

    ``camel``: unit = the first CamelCase word of the file stem (class-name
    prefix). Use for single-module layered services whose packages are purely
    technical (service/controller/dao/...) and the business capability lives
    in the class name (ShopService, DeviceMapper, RiskInfoEnum -> Shop,
    Device, Risk). Files whose stem starts lowercase or with an acronym
    (application.yml, OSSKey...) land in no unit (technical/config files).

    ``dw`` repositories keep their own units: the workspace style does not
    apply (their layers are normative by the warehouse's layer-call rules,
    not by construction, and are never counted).
    """
    if style == "camel" and scheme["type"] != "dw":
        scheme = dict(scheme)
        scheme["unit_style"] = "camel"
        return scheme
    if style != "pkg" or scheme["type"] not in ("multi", "single"):
        return scheme
    pkgs = []
    for f in files:
        if f.endswith(".java") and "/src/main/java/" in f:
            pkgs.append(f.split("/src/main/java/", 1)[1].split("/")[:-1])
        elif f.endswith(".java") and f.startswith("src/main/java/"):
            pkgs.append(f.split("src/main/java/", 1)[1].split("/")[:-1])
    common = 0
    for segs in zip(*pkgs):
        if len(set(segs)) == 1:
            common += 1
        else:
            break
    scheme = dict(scheme)
    scheme["unit_style"] = "pkg"
    scheme["prefix_len"] = common
    scheme["skip"] = sorted(set(skip) if skip is not None else STEREOTYPES)
    return scheme


def _pkg_unit_of(path: str, scheme: dict) -> str | None:
    if "/src/main/java/" in path:
        pkg = path.split("/src/main/java/", 1)[1].split("/")[:-1]
        modseg = path.split("/src/main/java/")[0]
    elif path.startswith("src/main/java/"):
        pkg = path.split("src/main/java/", 1)[1].split("/")[:-1]
        modseg = ""
    else:
        return None
    rest = pkg[scheme["prefix_len"]:]
    suffix = modseg.rsplit("-", 1)[-1].lower() if modseg else ""
    if rest and rest[0].lower() == suffix:
        rest = rest[1:]
    skip = set(scheme["skip"])
    for seg in rest:
        if seg.lower() not in skip:
            return seg
    return None


def _dw_tokens(name: str) -> list[str]:
    """Name tokens: split on ``_ @ . -`` and on lower->Upper camel humps."""
    out = []
    for part in _DW_SPLIT.split(name):
        out.extend(t.lower() for t in _DW_CAMEL.split(part) if t)
    return out


def _dw_domain(t: str) -> bool:
    return bool(_DW_WORD.match(t)) and t not in DW_NON_SUBJECTS


def _dw_triple(tokens: list[str]) -> tuple[str, str, str | None] | None:
    """First ``<layer>_<domain>[_<subject>]`` run inside a token list."""
    for i, t in enumerate(tokens):
        if t in DW_LAYERS and i + 1 < len(tokens) and _dw_domain(tokens[i + 1]):
            subj = tokens[i + 2] if (i + 2 < len(tokens)
                                     and _dw_domain(tokens[i + 2])) else None
            return t, tokens[i + 1], subj
    return None


def dw_subject_of(path: str) -> tuple[str, str] | None:
    """(layer, business subject) of a warehouse script, or None.

    The subject comes from the script's own name first - the baseline
    layout (``dws_sales_trd/mc_dws_sales_trd_g0003_ord_1d.sql``), the DDL
    baseline (``hub_db@dim_sales_cust.sql``) and the deploy archive
    (``20261105@1000002/ali_cloud/mc/1000002@...@dwd_sales_fin.sql``) all
    carry the target table - then from the directories: a
    ``<layer>_<domain>_<subject>`` directory, or a bare layer directory
    followed by the domain and subject directories (``cdm/dwd/sales/trd/``).
    Scripts named some other way (DDL without the table, the platform's own
    databases, api templates) land in no unit: under-count rather than
    fabricate scatter. Name-level only - no blob is ever read.
    """
    stem = path.rsplit("/", 1)[-1]
    stem = stem.rsplit(".", 1)[0] if "." in stem else stem
    # "{id}@{dc}@{engine}@{db}@{layer}@{table}": the table is the last field;
    # a layer word in an earlier field is a folder, not the table's layer
    fields = stem.split("@")
    r = _dw_triple(_dw_tokens(fields[-1])) if len(fields) > 1 else None
    if r is None:
        r = _dw_triple(_dw_tokens(stem))
    if r is None:
        dirs = path.split("/")[:-1]
        for i in range(len(dirs) - 1, -1, -1):
            d = dirs[i].lower()
            if d in DW_LAYERS and i + 1 < len(dirs):
                dom = dirs[i + 1].lower()
                subj = dirs[i + 2].lower() if i + 2 < len(dirs) else ""
                if _dw_domain(dom):
                    r = (d, dom, subj if _dw_domain(subj)
                         and subj not in DW_ENGINE_DIRS else None)
                break
            r = _dw_triple(_dw_tokens(dirs[i]))
            if r:
                break
    if r is None:
        return None
    layer, dom, subj = r
    return layer, (f"{dom}.{subj}" if subj else dom)


def dw_profile(files: list[str]) -> dict:
    """Name-level facts of a warehouse merge, reported with every verdict.

    Layers spanned are shown in pipeline order but never counted (the
    ods -> dwd -> dws -> ads direction is the normative change path);
    deployment and rollback scripts are recognised by their path.
    """
    layers, units, scripts, attributed, deploy, rollback = set(), set(), 0, 0, 0, 0
    for f in files:
        if not is_source(f, {"type": "dw"}):
            continue
        scripts += 1
        low = "/" + f.lower()
        if "/deploy/" in low:
            deploy += 1
            rollback += "rollback" in low
        if r := dw_subject_of(f):
            attributed += 1
            layers.add(r[0])
            units.add(r[1])
    return {"layers": [l for l in DW_LAYERS if l in layers],
            "units": len(units), "scripts": scripts, "attributed": attributed,
            "deploy": deploy, "rollback": rollback}


def detect_scheme(files: list[str]) -> dict:
    """Auto-detect a repository's module scheme from its changed-file list."""
    if files:
        sql = [f for f in files if f.lower().endswith(DW_SQL_EXTS)]
        if len(sql) >= DW_SHARE * len(files):
            return {"type": "dw"}
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


def is_source(path: str, scheme: dict | None = None) -> bool:
    """Source files that count as placement landings.

    Java (src/main/java; tests excluded by construction), Go (no vendor,
    no _test.go), TS/TSX/Vue/JSX (no node_modules/dist/.d.ts/.test./.spec.).
    ``dw`` schemes count warehouse scripts only: SQL always, Python when
    named after its target table (``dw_subject_of``). Service code in
    other languages inside a script repository is not a placement landing.
    """
    p = "/" + path
    if scheme is not None and scheme.get("type") == "dw":
        if path.lower().endswith(DW_SQL_EXTS):
            return True
        return path.endswith(".py") and dw_subject_of(path) is not None
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
    api/comp/store layer crossings are normative.
    ``dw``: business subject (``sales.trd``); ods->dwd->dws->ads layer
    crossings are normative.
    ``pkg`` style (scheme["unit_style"]): business package segment.
    Other schemes: L1 module.
    """
    if scheme.get("unit_style") == "camel":
        return _camel_unit_of(path)
    if scheme.get("unit_style") == "pkg":
        return _pkg_unit_of(path, scheme)
    t = scheme["type"]
    if t == "dw":
        r = dw_subject_of(path)
        return r[1] if r else None
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


def _camel_unit_of(path: str) -> str | None:
    """First CamelCase word of the file stem, for class-prefix-named repos."""
    if not path.endswith(".java"):
        return None
    stem = _stem(path.rsplit("/", 1)[-1])
    m = re.match(r"^([A-Z][a-z0-9]+)", stem)
    return m.group(1) if m else None


def units_of(scheme: dict, files: list[str]) -> set[str]:
    """Placement units touched by a change (source files, non-test)."""
    out = set()
    for f in files:
        if not is_source(f, scheme) or is_test_module(f):
            continue
        u = unit_of(scheme, f)
        if u is not None:
            out.add(u)
    return out


def source_files(files: list[str], scheme: dict | None = None) -> list[str]:
    """Source, non-test files of a change (the placement landings)."""
    return [f for f in files
            if is_source(f, scheme) and not is_test_module(f)]


def unit_l2(scheme: dict, path: str) -> str | None:
    """Finer (L2) unit, for advisory display only."""
    t = scheme["type"]
    if t == "dw":
        r = dw_subject_of(path)
        return f"{r[0]}:{r[1]}" if r else None
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
