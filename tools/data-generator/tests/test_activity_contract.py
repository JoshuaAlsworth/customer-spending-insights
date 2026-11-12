from copy import deepcopy
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker


contract = yaml.safe_load(
    (Path(__file__).parents[3] / "contracts/openapi.yaml").read_text()
)
activity_schema = {
    "$ref": "#/components/schemas/Activity",
    "components": contract["components"],
}
validator = Draft202012Validator(activity_schema, format_checker=FormatChecker())


def test_valid_typed_activity_variants() -> None:
    provisional = {
        "recordKind": "AUTHORIZATION",
        "id": "au_example",
        "accountId": "account-example",
        "maskedSuffix": "0042",
        "merchantName": None,
        "description": "Card authorization",
        "status": "PENDING",
        "type": "CARD_PURCHASE",
        "authorizedAmountMinor": "25000",
        "occurredAt": "2026-10-01T12:00:00+02:00",
        "postedAt": None,
        "amountMinor": None,
        "effectGroup": None,
        "categoryCode": None,
    }
    posted = {
        "recordKind": "POSTED_ENTRY",
        "id": "pe_example",
        "accountId": "account-example",
        "maskedSuffix": "0042",
        "merchantName": "Sample shop",
        "description": "Card purchase",
        "status": "POSTED",
        "type": "CARD_PURCHASE",
        "amountMinor": "-24000",
        "effectGroup": "SPEND",
        "categoryCode": "GROCERIES",
        "postedAt": "2026-10-02T12:00:00+02:00",
        "occurredAt": "2026-10-01T12:00:00+02:00",
        "authorizedAmountMinor": "25000",
        "authorizationActivityId": "au_example",
        "originalActivityId": None,
    }
    assert validator.is_valid(provisional)
    assert validator.is_valid(posted)
    cancelled = deepcopy(provisional)
    cancelled["status"] = "CANCELLED"
    assert validator.is_valid(cancelled)
    for field, value in [
        ("status", "POSTED"),
        ("authorizedAmountMinor", "-25000"),
        ("amountMinor", "-25000"),
    ]:
        invalid = deepcopy(provisional)
        invalid[field] = value
        assert not validator.is_valid(invalid), field
    invalid_posted = deepcopy(posted)
    invalid_posted["categoryCode"] = None
    assert not validator.is_valid(invalid_posted)
    invalid_posted = deepcopy(posted)
    invalid_posted["authorizedAmountMinor"] = "-25000"
    assert not validator.is_valid(invalid_posted)
    invalid_posted = deepcopy(posted)
    invalid_posted["effectGroup"] = "INCOME"
    assert not validator.is_valid(invalid_posted)
    invalid_posted = deepcopy(posted)
    invalid_posted["amountMinor"] = "24000"
    assert not validator.is_valid(invalid_posted)
    refund = deepcopy(posted)
    refund.update(type="SPEND_REFUND", amountMinor="24000", originalActivityId="pe_purchase",
                  authorizedAmountMinor=None, authorizationActivityId=None)
    assert validator.is_valid(refund)
    refund["originalActivityId"] = None
    assert not validator.is_valid(refund)


def test_activity_filter_contract_has_type_and_bounded_cursor_page() -> None:
    parameters = {
        parameter["name"]: parameter
        for parameter in contract["paths"]["/api/v1/transactions"]["get"]["parameters"]
    }
    assert parameters["type"]["schema"]["$ref"] == "#/components/schemas/TransactionType"
    assert parameters["status"]["schema"]["enum"] == [
        "ALL", "PENDING", "POSTED", "CANCELLED"
    ]
    assert parameters["limit"]["schema"]["maximum"] == 100
    assert "cursor" in parameters
