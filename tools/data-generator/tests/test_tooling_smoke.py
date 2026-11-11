from decimal import Decimal


def test_python_decimal_tooling_smoke() -> None:
    amounts = [Decimal("0.10"), Decimal("0.20"), Decimal("-0.30")]
    assert sum(amounts) == Decimal("0.00")
