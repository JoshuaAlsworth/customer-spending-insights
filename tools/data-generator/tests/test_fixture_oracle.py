"""Internal consistency checks for independently authored known-answer fixtures."""

import json

from csi_data.policy import ROOT


def test_independent_fixture_answers_are_complete_and_reconcile():
    fixtures = json.loads((ROOT / "contracts/finance/fixtures.json").read_text())
    assert all(f"F-{number:02d}" in fixtures for number in range(1, 13))
    for name in ("F-01", "F-02", "F-03", "F-09"):
        case = fixtures[name]
        assert int(case["netSpendingMinor"]) == int(case["grossSpendingMinor"]) - int(
            case["spendingCreditsMinor"]
        )
        assert int(case["netMovementMinor"]) == int(case["incomeMinor"]) - int(
            case["netSpendingMinor"]
        ) + int(case["ownAccountFlowMinor"])
        if "categories" in case:
            assert sum(map(int, case["categories"].values())) == int(
                case["netSpendingMinor"]
            )
    assert sum(map(int, fixtures["F-09"]["weeklyBuckets"])) == int(
        fixtures["F-09"]["netSpendingMinor"]
    )
    cross_month = fixtures["F-04"]
    assert (
        int(cross_month["october2025"]["ownAccountFlowMinor"])
        + int(cross_month["november2025"]["ownAccountFlowMinor"])
        == 0
    )
    assert int(cross_month["combined"]["ownAccountFlowMinor"]) == 0
    assert fixtures["F-05"]["logicalPurchaseCount"] == 1
    assert fixtures["F-06"]["postedCount"] == 0
    assert fixtures["F-07"]["extraRefundOutcome"] == "REJECT_NO_MUTATION"
    assert fixtures["F-08"]["spendReversalAfterPartialRefund"] == "REJECT_NO_MUTATION"
