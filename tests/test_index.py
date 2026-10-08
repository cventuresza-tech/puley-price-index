import json
from decimal import Decimal

import pytest

from puley_price_index.build import assign_periods, plan_key
from puley_price_index.money import parse_price
from puley_price_index.parse import parse_app_page


@pytest.mark.parametrize("text,currency,expected", [
    ("$19.99", "USD", "19.99"),
    ("R399.99", "ZAR", "399.99"),
    ("R1,839.00", "ZAR", "1839.00"),
    ("₺999,99", "TRY", "999.99"),
    ("₺5.299,99", "TRY", "5299.99"),
    ("22,99\xa0€", "EUR", "22.99"),
    ("¥3,000", "JPY", "3000"),
    ("₩29,000", "KRW", "29000"),
    ("₹\xa01,999", "INR", "1999"),
    ("₹1,99,999.00", "INR", "199999.00"),
    ("Rp 299.000", "IDR", "299000"),
    ("Rp299,000.00", "IDR", "299000.00"),
    ("Ft 7,990", "HUF", "7990"),
    ("1 099,00 kr", "SEK", "1099.00"),
    ("CHF 20.00", "CHF", "20.00"),
    ("₫59.000", "VND", "59000"),
    ("KD 6.990", "KWD", "6.990"),
    ("Rp\xa0349ribu", "IDR", "349000"),
    ("Rp\xa01,889juta", "IDR", "1889000"),
    ("Rp\xa014.500", "IDR", "14500"),
    ("$\xa0129.900,00", "COP", "129900.00"),
    ("HUF12,990.00", "HUF", "12990.00"),
    ("14,990.00₸", "KZT", "14990.00"),
    ("1\xa0000,00\xa0€", "EUR", "1000.00"),
    ("$34.990", "CLP", "34990"),
    ("", "USD", None),
    ("Free", "USD", None),
])
def test_parse_price(text, currency, expected):
    got = parse_price(text, currency)
    assert (str(got) if got is not None else None) == expected


def _page(iaps, currency="ZAR"):
    data = {"data": [{"data": {"shelfMapping": {"information": {"items": [
        {"$kind": "Annotation", "title": "Size", "items": [{"$kind": "textPair", "leadingText": "iPhone", "trailingText": "84.1 MB"}]},
        {"$kind": "Annotation", "title": "In-App Purchases", "items": [
            {"$kind": "textPair", "leadingText": n, "trailingText": p} for n, p in iaps] + [{"$kind": "button"}]},
    ]}}}}]}
    ld = {"@type": "SoftwareApplication", "name": "ChatGPT", "offers": {"@type": "Offer", "price": 0, "priceCurrency": currency}}
    return (f'<script id=software-application type="application/ld+json">{json.dumps(ld)}</script>'
            f'<script type="application/json" id="serialized-server-data">{json.dumps(data)}</script>')


def test_parse_app_page_reads_only_the_purchases():
    page = parse_app_page(_page([("ChatGPT Plus", "R399.99"), ("ChatGPT Go", "R149.99")]))
    assert page.name == "ChatGPT" and page.currency == "ZAR" and page.has_iap_shelf
    assert page.iaps == [("ChatGPT Plus", "R399.99"), ("ChatGPT Go", "R149.99")]


def test_page_without_purchases():
    page = parse_app_page(_page([]))
    assert page.iaps == [] and page.has_iap_shelf


def test_periods_from_names_and_prices():
    rows = assign_periods([
        ("ChatGPT Plus", "R399.99", Decimal("399.99")), ("ChatGPT Go", "R149.99", Decimal("149.99")),
        ("ChatGPT Plus", "R3,999.99", Decimal("3999.99")), ("Premium (Yearly)", "$99.99", Decimal("99.99")),
        ("Premium (Monthly)", "$9.99", Decimal("9.99")), ("Pro", "$5", Decimal("5")), ("Pro", "$6", Decimal("6")),
    ])
    got = {(r["name"], str(r["price"])): (r["key"], r["period"], r["inferred"]) for r in rows}
    assert got[("ChatGPT Plus", "399.99")] == ("chatgpt-plus", "month", True)
    assert got[("ChatGPT Plus", "3999.99")] == ("chatgpt-plus", "year", True)
    assert got[("Premium (Yearly)", "99.99")] == ("premium", "year", False)
    assert got[("Premium (Monthly)", "9.99")] == ("premium", "month", False)
    assert got[("Pro", "6")][1] == "variant"  # two close prices under one name: only the first counts


def test_plan_key_ignores_period_words():
    assert plan_key("Super Duolingo - 12 Months") == plan_key("Super Duolingo") == "super-duolingo"
    assert plan_key("Snapchat+ (Annual)") == "snapchat+"
