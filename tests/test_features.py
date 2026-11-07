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
