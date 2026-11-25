from uscm.modules import (apply_unit_style, detect_scheme, dw_profile,
                          front_module_of, is_source, is_test_module,
                          source_files, unit_l2, unit_of, units_of)


def test_pkg_unit_style_ddd_layers():
    """DDD-layered monorepo: modules are layers, units are business packages."""
    files = [
        "billing-domain/src/main/java/com/x/acme/domain/bill/A.java",
        "billing-domain/src/main/java/com/x/acme/domain/dto/B.java",
        "billing-application/src/main/java/com/x/acme/application/bill/C.java",
        "billing-application/src/main/java/com/x/acme/application/credit/D.java",
        "billing-adapter/src/main/java/com/x/acme/adapter/http/adjust/E.java",
    ]
    s = apply_unit_style(detect_scheme(files), files, style="pkg")
    assert unit_of(s, files[0]) == "bill"
    assert unit_of(s, files[1]) is None          # technical stereotype only
    assert unit_of(s, files[2]) == "bill"        # same capability, other layer
    assert unit_of(s, files[3]) == "credit"
    assert unit_of(s, files[4]) == "adjust"      # http stepped over
    assert units_of(s, files) == {"bill", "credit", "adjust"}


def test_camel_unit_style_class_prefix_naming():
    """Single-module layered service: packages are technical layers, the
    business capability lives in the class-name prefix."""
    files = [
        "src/main/java/com/x/svc/controller/ShopController.java",
        "src/main/java/com/x/svc/service/impl/ShopPointServiceImpl.java",
        "src/main/java/com/x/svc/service/DeviceService.java",
        "src/main/java/com/x/svc/common/enums/RiskInfoEnum.java",
    ]
    s = apply_unit_style(detect_scheme(files), files, style="camel")
    assert unit_of(s, files[0]) == "Shop"
    assert unit_of(s, files[1]) == "Shop"        # coarse: first word only
    assert unit_of(s, files[2]) == "Device"
    assert unit_of(s, files[3]) == "Risk"
    assert units_of(s, files) == {"Shop", "Device", "Risk"}
    # acronym-leading stems and non-Java files land in no unit
    assert _camel_stem("OSSGroupService.java") is None
    assert unit_of(s, "src/main/resources/application.yml") is None


def _camel_stem(name: str):
    from uscm.modules import _camel_unit_of
    return _camel_unit_of(name)


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


# ------------------------------------------------------- data-warehouse (dw) --

DW_FILES = [
    # baseline, current layout
    "init/dw/dml/ali_cloud/dataworks/sales_cdm/dws_sales_trd/mc_dws_sales_trd_g0003_ord_1d.sql",
    "init/dw/dml/ali_cloud/dataworks/business-process/dim_sales_cust/dim_ops_cust_partner_info_extra.sql",
    # baseline, early layout: bare layer directory, then domain / subject
    "dw-script/cdm/dwd/sales/trd/mc/dwd_sales_trd_ord_full_list_ol_v2.sql",
    # deploy archive (scripts run in production), both naming eras
    "deploy/2026/Q1/20260113-1000001/mc/1000001_ali_cloud_mc_dws_sales_trd_trd_ddl_abc.sql",
    "deploy/2026/Q2/202611/20261105@1000002/ali_cloud/mc/1000002@ali_cloud@sdb@busi@dw@dwd_sales_fin.sql",
    # DDL baseline, a non-ASCII directory, a camelCase api template
    "init/dw/ddl/ali_cloud/mc/ali_cloud@mc@hub_db@dim_sales_cust.sql",
    "init/dw/dml/ali_cloud/dataworks/sales_cdm/ads_sales_bo/门店/mc_ads_sales_bo_term_g0016_device_psi_1d.sql",
    "init/data-api/dml/ali_cloud/es/exportDimSalesCustAcctBranch-分公司客户账户信息导出.sql",
]


def test_dw_units_are_business_subjects_layers_are_normative():
    """Data-warehouse script repository: the table naming convention
    <layer>_<domain>_<subject> carries the business subject. Changing one
    subject along ods -> dwd -> dws -> ads is the normative change path,
    so layers are never units - the same rule as front-end pages."""
    s = detect_scheme(DW_FILES)
    assert s["type"] == "dw"
    assert [unit_of(s, f) for f in DW_FILES] == [
        "sales.trd", "ops.cust", "sales.trd", "sales.trd", "sales.fin",
        "sales.cust", "sales.bo", "sales.cust"]
    assert units_of(s, DW_FILES) == {"sales.trd", "ops.cust", "sales.fin",
                                     "sales.cust", "sales.bo"}
    assert unit_l2(s, DW_FILES[0]) == "dws:sales.trd"
    # early layout without a subject directory: the domain is the unit
    assert unit_of(s, "dw-script/ads/sales/mc/day/x.sql") == "sales"
    assert unit_of(s, "deploy/2026/Q4/20261106@1000007/local/hive/"
                       "local@hive@busi@ods_posp.sql") == "posp"


def test_dw_scripts_named_without_a_table_land_in_no_unit():
    """DDL that does not name its table, the platform's own databases and
    api templates without a table are not attributable by name: they count
    as scripts (size) but never invent a unit."""
    s = detect_scheme(DW_FILES)
    bare = ["deploy/2026/Q1/20260311-1000008/maxcompute/1000008_ali_cloud_mc_ddl_abc.sql",
            "init/data-platform/ddl/local/mysql/local@mysql@dplat_conf@common@dplat_conf.sql",
            "init/data-api/dml/ali_cloud/sdb/fin_accting/getTrialParentSubjectBalanceList-会计余额.sql"]
    assert [unit_of(s, f) for f in bare] == [None, None, None]
    assert units_of(s, bare) == set()
    assert source_files(bare, s) == bare
    assert dw_profile(bare) == {"layers": [], "units": 0, "scripts": 3,
                                "attributed": 0, "deploy": 1, "rollback": 0}


def test_dw_sources_sql_and_table_named_python_only():
    s = detect_scheme(DW_FILES)
    assert is_source("init/dw/dml/ali_cloud/dataworks/sales_risk/ruleopt/ads_sales_risk_ruleopt_config.py", s)
    assert not is_source("dw-script/common/python/tool.py", s)      # generic code
    assert not is_source("src/main/java/com/x/App.java", s)
    assert not is_source("README.md", s)
    # outside a dw scheme SQL was never a placement landing: unchanged
    assert not is_source("init/dw/ddl/ali_cloud/mc/ali_cloud@mc@hub_db@dim_sales_cust.sql")


def test_dw_detection_needs_a_sql_dominant_history():
    # a business script repository (DDL + config) keeps flat2, as before
    files = ["mysql/ledger/t_user.sql", "nacos/a.yml", "nacos/b.yml"]
    assert detect_scheme(files)["type"] == "flat2"
    assert detect_scheme(["a/x.sql", "b/y.sql", "c/z.sql", "d/w.sql",
                          "README.md"])["type"] == "dw"
    # workspace unit styles never override dw units
    assert apply_unit_style({"type": "dw"}, ["a/x.sql"], "camel") == {"type": "dw"}


def test_dw_profile_layers_in_pipeline_order():
    files = ["init/dw/dml/dataworks/sales_cdm/ads_sales_cust/a.sql",
             "init/dw/dml/dataworks/sales_cdm/ods_sales_cust/b.sql",
             "deploy/2026/Q1/20260113-1000001/mc/1000001_ali_cloud_mc_dwd_sales_cust_ddl_abc.sql",
             "deploy/2026/Q1/20260113-1000001/rollback/1000001_ali_cloud_mc_dwd_sales_cust_ddl_abc_rollback.sql"]
    assert dw_profile(files) == {"layers": ["ods", "dwd", "ads"], "units": 1,
                                 "scripts": 4, "attributed": 4,
                                 "deploy": 2, "rollback": 1}


def test_dw_technical_words_and_folder_layers_are_not_subjects():
    s = {"type": "dw"}
    # operation / placeholder words after the layer: the coarse domain unit
    assert unit_of(s, "dw-table/deploy/2025/Q3/20250820-1000009/"
                       "1000009_aliyun_mc_ods_ops_ddl_abc.sql") == "ops"
    assert unit_of(s, "dw-table/deploy/2023/Q4/20231114-1000010/holo/"
                       "1000010_holo_ods_sales_xxx_ddl_abc.sql") == "sales"
    # ... and never a domain
    assert unit_of(s, "deploy/2025/Q2/20250401/es/20250401_cloud_es_dws_dml_abc.sql") is None
    # "{id}@{dc}@{engine}@{db}@{layer}@{table}": a layer word in a folder
    # field is not the table's layer
    ddl = ("deploy/2026/Q3/202608/20260831@1000011/ali_cloud/mc/"
           "1000012@ali_cloud@mc@hub_db@ods@ads_sales_bkcp.sql")
    assert unit_of(s, ddl) == "sales.bkcp" and unit_l2(s, ddl) == "ads:sales.bkcp"
    # rare but real subjects are kept: no vocabulary filter
    assert unit_of(s, "init/data-api/dml/ali_cloud/sdb/"
                       "queryDimInvoiceCompanyInfo-发票企业信息查询.sql") == "invoice.company"
