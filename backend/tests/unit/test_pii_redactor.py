import pytest

from app.utils.pii_redactor import redact_pii


@pytest.mark.parametrize(
    ("text", "expected", "kind"),
    [
        ("mail jane.doe+x@example.co.uk now", "mail [EMAIL] now", "EMAIL"),
        ("ssn 123-45-6789", "ssn [SSN]", "SSN"),
        ("card 4111 1111 1111 1111", "card [CREDIT_CARD]", "CREDIT_CARD"),
        ("card 4111-1111-1111-1111", "card [CREDIT_CARD]", "CREDIT_CARD"),
        ("host 10.0.0.255", "host [IPV4]", "IPV4"),
        ("call (415) 555-2671", "call [PHONE]", "PHONE"),
        ("call 415-555-2671", "call [PHONE]", "PHONE"),
        ("call +1 415 555 2671", "call [PHONE]", "PHONE"),
        ("call +44 20 7946 0958", "call [PHONE]", "PHONE"),
        ("call 555.123.4567 ext 42", "call [PHONE]", "PHONE"),
    ],
)
def test_redacts_pii(text: str, expected: str, kind: str) -> None:
    result = redact_pii(text)
    assert result.text == expected
    assert result.counts == {kind: 1}
    assert result.redacted


@pytest.mark.parametrize(
    "text",
    [
        "Companies with revenue over 1000000 in 2024",
        "ARR between 1,000,000 and 5,000,000",
        "market cap above 3000000000000",
        "statements dated 2023-09-30",
        "churn of 0.015 over 12 months",
        "version 1.2.3",
        "number 1234567890123",  # 13 digits, fails Luhn
    ],
)
def test_leaves_financial_text_untouched(text: str) -> None:
    result = redact_pii(text)
    assert result.text == text
    assert not result.redacted


def test_counts_multiple_matches() -> None:
    result = redact_pii("a@b.io and c@d.io from 1.2.3.4")
    assert result.counts == {"EMAIL": 2, "IPV4": 1}


def test_empty_input() -> None:
    assert redact_pii("").text == ""
