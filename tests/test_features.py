from uscm.features import feature_key, list_merges, merge_author, merge_files

from conftest import make_merge


def test_feature_key_patterns():
    assert feature_key("Merge S000123 into main from feature/x (--story=000123)") == "S000123"
    assert feature_key("Merge pull request #42 from org/PROJ-101-fix") == "PROJ-101"
    assert feature_key("fix: handle TAPD 123456 timeout") == "S123456"
    assert feature_key("chore: bump deps") is None


def test_list_merges_order_and_payload(tiny_repo):
    make_merge(tiny_repo, 1, ["core/src/main/java/com/x/core/A.java"], "Alice",
               "2025-05-01T10:00:00+00:00")
    make_merge(tiny_repo, 2, ["api/src/main/java/com/x/api/B.java"], "Bob",
               "2025-05-02T10:00:00+00:00")
    ms = list_merges(tiny_repo)
    assert len(ms) == 2 and ms[0]["date"] < ms[1]["date"]   # oldest first
    assert feature_key(ms[0]["subject"]) == "S000001"
    files = merge_files(tiny_repo, ms[1]["sha"])
    assert any(f.endswith("B.java") for f in files)
    assert merge_author(tiny_repo, ms[1]["sha"]) == "Bob"


def test_list_merges_since(tiny_repo):
    make_merge(tiny_repo, 1, ["core/src/main/java/com/x/core/A.java"])
    make_merge(tiny_repo, 2, ["core/src/main/java/com/x/core/C.java"])
    ms = list_merges(tiny_repo, since="2026-01-01")
    assert ms == []


# ------------------------------------------------------ path-keyed features --

DW_PATTERNS = [("Merge branch 'feature/(\\d{5,})'", "S{0}"),
               ("/\\d{8}[-@](\\d{5,})/", "S{0}", "path")]


def test_merge_key_subject_first_then_paths():
    from uscm.features import merge_key
    # the subject wins even when the paths carry another id
    k = merge_key("Merge branch 'feature/1000003' into 'master'",
                  ["deploy/2025/Q1/20250306-1000004/mc/a.sql"], DW_PATTERNS)
    assert k == {"key": "S1000003", "key_source": "subject", "path_keys": {}}
    # a bare subject: the per-story deploy archive keys the merge
    k = merge_key("Merge branch 'branch_exp' into 'master'",
                  ["dw-script/cdm/ods/sales/trd/a.sql",
                   "dw-table/deploy/20230816-1000005/holo/a.sql"], DW_PATTERNS)
    assert k == {"key": "S1000005", "key_source": "path",
                 "path_keys": {"S1000005": 1}}
    # a merge bundling two stories goes to the story with the most paths
    files = ["deploy/2023/Q3/20230816-1000005/a.sql",
             "deploy/2023/Q3/20230816-1000006/b.sql",
             "deploy/2023/Q3/20230816-1000006/c.sql"]
    assert merge_key("Merge branch 'branch_exp' into 'master'", files,
                     DW_PATTERNS)["key"] == "S1000006"
    # nothing anywhere: no feature, statistics only
    assert merge_key("chore: deps", ["a/b.sql"], DW_PATTERNS)["key"] is None


def test_merge_key_tie_is_deterministic():
    from uscm.features import merge_key
    tie = ["deploy/2023/Q3/20230816-1000006/b.sql",
           "deploy/2023/Q3/20230816-1000005/a.sql"]
    assert [merge_key("x", tie, DW_PATTERNS)["key"] for _ in range(3)] == \
        ["S1000005"] * 3


def test_path_patterns_never_read_subjects_and_vice_versa():
    from uscm.features import compile_patterns, path_keys
    c = compile_patterns(DW_PATTERNS)
    assert feature_key("deploy/2023/Q3/20230816-1000005/a.sql", c) is None
    assert path_keys(["Merge branch 'feature/1000003'"], c) == {}


def test_merge_files_keeps_non_ascii_paths(tiny_repo):
    """git quotes non-ASCII paths by default; the merge diff must not."""
    import unicodedata
    from conftest import git
    first = "init/dw/dml/dataworks/sales_cdm/ads_sales_bo/门店/x.sql"
    second = "init/dw/dml/dataworks/sales_cdm/ads_sales_bo/明细/y.sql"
    for f in (first, second):
        p = tiny_repo / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("select 1\n")
        git(tiny_repo, "add", f)
    git(tiny_repo, "commit", "-q", "-m", "baseline")
    git(tiny_repo, "checkout", "-q", "-b", "feature/1000003")
    third = "init/dw/dml/dataworks/sales_cdm/ads_sales_bo/明细/z.sql"
    (tiny_repo / third).parent.mkdir(parents=True, exist_ok=True)
    (tiny_repo / third).write_text("select 1\n")
    git(tiny_repo, "add", third)
    git(tiny_repo, "commit", "-q", "-m", "wip")
    git(tiny_repo, "checkout", "-q", "main")
    git(tiny_repo, "merge", "--no-ff", "-q", "feature/1000003",
        "-m", "Merge branch 'feature/1000003' into 'master'")
    sha = git(tiny_repo, "rev-parse", "HEAD").stdout.strip()
    norm = lambda xs: [unicodedata.normalize("NFC", x) for x in xs]
    assert norm(merge_files(tiny_repo, sha)) == norm([third])


def test_merge_author_tie_is_deterministic(tiny_repo):
    """Two branch commits by two authors: the tie goes to the first name in
    lexical order, never to set iteration order (which is hash-seeded)."""
    import os
    from conftest import git
    git(tiny_repo, "checkout", "-q", "-b", "feature/7")
    for name, author in (("a.sql", "Zed"), ("b.sql", "Amy")):
        p = tiny_repo / name
        p.write_text("-- touch\n")
        git(tiny_repo, "add", name)
        env = {**os.environ, "GIT_AUTHOR_NAME": author,
               "GIT_AUTHOR_EMAIL": "a@e.com",
               "GIT_COMMITTER_NAME": "CI", "GIT_COMMITTER_EMAIL": "ci@e.com"}
        git(tiny_repo, "commit", "-q", "-m", f"wip {name}", env=env)
    git(tiny_repo, "checkout", "-q", "main")
    git(tiny_repo, "merge", "--no-ff", "-q", "feature/7",
        "-m", "Merge branch 'feature/7' into 'master'")
    sha = git(tiny_repo, "rev-parse", "HEAD").stdout.strip()
    assert merge_author(tiny_repo, sha) == "Amy"
