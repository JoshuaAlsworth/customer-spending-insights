import re
from pathlib import Path

import yaml

from csi_data.policy import ROOT, policies


def _quoted_values(block):
    return set(re.findall(r'"([A-Z_]+)"', block))


def _java_filter(source, name):
    match = re.search(
        rf"private static final Set<String> {name}\s*=\s*Set\.of\((.*?)\);",
        source,
        re.S,
    )
    assert match is not None
    return _quoted_values(match.group(1))


def _vue_filter(source, name):
    match = re.search(
        rf"const {name}: (?:TransactionType|CategoryCode)\[\] = \[(.*?)\];",
        source,
        re.S,
    )
    assert match is not None
    return _quoted_values(match.group(1))


def test_database_and_openapi_type_policy_matches_json():
    tax, cat, _ = policies()
    schema = (
        ROOT
        / "apps/api/src/main/resources/db/migration/V1__financial_and_session_schema.sql"
    ).read_text()
    openapi = yaml.safe_load((ROOT / "contracts/openapi.yaml").read_text())
    match = re.search(
        r"transaction_type text NOT NULL CHECK \(transaction_type IN \((.*?)\)\)",
        schema,
        re.S,
    )
    assert match is not None
    assert set(re.findall(r"'([A-Z_]+)'", match.group(1))) == set(tax["types"])
    sign_effect = {}
    for group, single, sign, effect in re.findall(
        r"transaction_type(?: IN \(([^)]+)\)|='([A-Z_]+)') AND amount_minor([<>])0 AND effect_group='([A-Z]+)'",
        schema,
    ):
        for name in re.findall(r"'([A-Z_]+)'", group) if group else [single]:
            sign_effect[name] = ("POSITIVE" if sign == ">" else "NEGATIVE", effect)
    assert sign_effect == {
        name: (rule["sign"], rule["effect"]) for name, rule in tax["types"].items()
    }
    category_rows = re.search(
        r"INSERT INTO categories\(code,display_name,display_order,policy_version\) VALUES\s*(.*?);",
        schema,
        re.S,
    )
    assert category_rows is not None
    contract = openapi["components"]["schemas"]
    java = (
        ROOT
        / "apps/api/src/main/java/za/co/customerinsights/insights/ActivityController.java"
    ).read_text()
    vue = (
        ROOT / "apps/web/src/features/transactions/TransactionExplorer.vue"
    ).read_text()
    assert (
        set(tax["types"])
        == _java_filter(java, "TYPES")
        == _vue_filter(vue, "types")
        == set(contract["TransactionType"]["enum"])
    )
    assert (
        set(cat["categories"])
        == _java_filter(java, "CATEGORIES")
        == _vue_filter(vue, "categories")
        == set(contract["CategoryCode"]["enum"])
        == set(re.findall(r"\('([A-Z_]+)',", category_rows.group(1)))
    )


def test_policy_files_have_no_private_path_dependency():
    for name in ("taxonomy.json", "categories.json"):
        assert (ROOT / "contracts/finance" / name).is_file()
    assert not list(Path(__file__).parents[1].glob("**/specifications/*.pdf"))
