import re
from pathlib import Path

from csi_data.policy import ROOT, policies


def test_database_and_openapi_type_policy_matches_json():
    tax, cat, _ = policies()
    schema = (
        ROOT
        / "apps/api/src/main/resources/db/migration/V1__financial_and_session_schema.sql"
    ).read_text()
    openapi = (ROOT / "contracts/openapi.yaml").read_text()
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
    for code in cat["categories"]:
        assert f"'{code}'" in schema
        assert code in openapi
    for name in tax["types"]:
        assert name in openapi


def test_policy_files_have_no_private_path_dependency():
    for name in ("taxonomy.json", "categories.json"):
        assert (ROOT / "contracts/finance" / name).is_file()
    assert not list(Path(__file__).parents[1].glob("**/specifications/*.pdf"))
