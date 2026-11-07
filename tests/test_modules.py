from uscm.modules import (detect_scheme, front_module_of, is_source,
                          is_test_module, unit_of, units_of)


def test_detect_multi():
    files = ["core/src/main/java/com/x/core/A.java",
             "api/src/main/java/com/x/api/B.java",
             "core/src/main/java/com/x/core/C.java"]
    s = detect_scheme(files)
    assert s == {"type": "multi", "dirs": ["api", "core"]}


def test_detect_single():
    files = ["src/main/java/com/x/order/A.java",
             "src/main/java/com/x/pay/B.java"]
    s = detect_scheme(files)
    assert s["type"] == "single"
    assert unit_of(s, "src/main/java/com/x/order/A.java") == "order"


def test_detect_flat2():
    s = detect_scheme(["cmd/server/main.go", "internal/auth/a.go"])
    assert s["type"] == "flat2"
    assert unit_of(s, "cmd/server/main.go") == "cmd/server"
    assert unit_of(s, "README.md") == "root"


def test_detect_front_and_units():
    files = ["src/views/orders/index.tsx", "src/views/profile/x.tsx",
             "src/api/order.ts", "src/components/Btn.tsx"]
    s = detect_scheme(files)
    assert s["type"] == "front"
    # only pages are placement units; layer crossings are normative
    assert units_of(s, files) == {"page:orders", "page:profile"}
    assert front_module_of("src/api/order.ts") == "api:order"
    assert front_module_of("src/components/Btn.tsx") == "comp:Btn"
    assert front_module_of("src/store/cart.ts") == "store:cart"


def test_front_via_vue_files():
    files = ["src/views/a/index.vue", "src/views/b/x.vue"]
    assert detect_scheme(files)["type"] == "front"
    assert units_of(detect_scheme(files), files) == {"page:a", "page:b"}


def test_is_source_filters():
    assert is_source("core/src/main/java/A.java")
    assert not is_source("core/src/test/java/A.java")
    assert is_source("cmd/x/main.go")
    assert not is_source("vendor/pkg/x.go")
    assert not is_source("pkg/x_test.go")
    assert is_source("src/a.ts")
    assert not is_source("src/a.d.ts")
    assert not is_source("src/a.test.ts")
    assert not is_source("node_modules/x/y.ts")
    assert is_source("src/views/a/index.vue")
    assert not is_source("src/logo.png")


def test_is_test_module():
    assert is_test_module("foo-test/src/main/java/com/x/A.java")
    assert not is_test_module("foo/src/main/java/com/x/A.java")
