import pytest

from app.agents.name_matching import name_words, names_match


@pytest.mark.parametrize(
    ("claimed", "stored"),
    [
        ("Coca-Cola", "COCA COLA CO"),
        ("Coca‑Cola Co", "COCA COLA CO"),
        ("Bank of America", "BANK AMER CORP"),
        ("Bank of America", "BANK OF AMER CORP"),
        ("Bank of America Corp", "BANK AMERICA CORP"),
        ("American Express Company", "AMERICAN EXPRESS CO"),
        ("Procter & Gamble", "PROCTER AND GAMBLE CO"),
        ("Wells Fargo", "WELLS FARGO CO NEW"),
        ("Berkshire Hathaway", "BERKSHIRE HATHAWAY INC DEL"),
        ("Occidental Petroleum", "OCCIDENTAL PETE CORP"),
        ("General Motors", "GENERAL MTRS CO"),
        ("Goldman Sachs", "GOLDMAN SACHS GROUP INC"),
        ("JP Morgan", "JPMORGAN CHASE & CO"),
        ("ExxonMobil", "EXXON MOBIL CORP"),
        ("AT&T", "AT&T INC"),
        ("State Street SPDR", "STATE STR SPDR S&P 500 ETF T"),
    ],
)
def test_spellings_of_the_same_company_match(claimed: str, stored: str) -> None:
    assert names_match(claimed, stored)


@pytest.mark.parametrize(
    ("claimed", "stored"),
    [
        ("Bank of Canada", "BANK AMER CORP"),
        ("American Airlines", "AMERICAN EXPRESS CO"),
        ("Coca-Cola Europacific", "COCA COLA CO"),
        ("General Electric", "GENERAL MTRS CO"),
        ("America Bank", "BANK AMER CORP"),
        ("Morgan Stanley", "JPMORGAN CHASE & CO"),
        ("Pepsi", "COCA COLA CO"),
    ],
)
def test_different_companies_do_not_match(claimed: str, stored: str) -> None:
    assert not names_match(claimed, stored)


@pytest.mark.parametrize("claimed", ["Inc", "The Company", "", "&"])
def test_names_without_identifying_words_match_nothing(claimed: str) -> None:
    assert name_words(claimed) == ()
    assert not names_match(claimed, "APPLE INC")
