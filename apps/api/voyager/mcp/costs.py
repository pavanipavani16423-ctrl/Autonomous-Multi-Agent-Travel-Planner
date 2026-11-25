"""Curated daily travel-cost bands (USD) by country price tier.

These are ESTIMATES, written by hand from typical guidebook ranges (late 2025), grouped into five
price tiers. They are always returned with `provenance: "estimate"`; nothing here is a live price.
`stay` is per room-night (double room), the rest per person per day.
"""

from __future__ import annotations

# tier -> style -> {stay, food, transport, activities}
TIERS: dict[str, dict[str, dict[str, float]]] = {
    "A": {"budget": {"stay": 75, "food": 45, "transport": 15, "activities": 20},
          "mid": {"stay": 230, "food": 95, "transport": 25, "activities": 45},
          "luxury": {"stay": 600, "food": 210, "transport": 70, "activities": 110}},
    "B": {"budget": {"stay": 55, "food": 35, "transport": 10, "activities": 15},
          "mid": {"stay": 170, "food": 75, "transport": 20, "activities": 40},
          "luxury": {"stay": 450, "food": 170, "transport": 55, "activities": 90}},
    "C": {"budget": {"stay": 35, "food": 25, "transport": 8, "activities": 12},
          "mid": {"stay": 120, "food": 55, "transport": 15, "activities": 30},
          "luxury": {"stay": 340, "food": 130, "transport": 40, "activities": 70}},
    "D": {"budget": {"stay": 22, "food": 15, "transport": 5, "activities": 8},
          "mid": {"stay": 70, "food": 35, "transport": 10, "activities": 20},
          "luxury": {"stay": 240, "food": 90, "transport": 30, "activities": 50}},
    "E": {"budget": {"stay": 12, "food": 8, "transport": 3, "activities": 5},
          "mid": {"stay": 45, "food": 20, "transport": 7, "activities": 15},
          "luxury": {"stay": 190, "food": 60, "transport": 25, "activities": 40}},
}

COUNTRY_TIER: dict[str, str] = {
    **dict.fromkeys(["CH", "NO", "IS", "MC", "LI"], "A"),
    **dict.fromkeys(["GB", "DK", "SE", "US", "AU", "NZ", "SG", "IE", "NL", "FR", "CA", "AE", "QA",
                     "HK", "DE", "AT", "BE", "LU", "FI", "IL", "BS"], "B"),
    **dict.fromkeys(["JP", "KR", "IT", "ES", "PT", "GR", "CZ", "SI", "HR", "TW", "EE", "CY", "MT",
                     "SA", "KW", "BH", "OM", "UY", "CL", "SK"], "C"),
    **dict.fromkeys(["TR", "PL", "HU", "MX", "BR", "AR", "MY", "ZA", "MA", "PE", "CN", "RO", "BG",
                     "RS", "ME", "BA", "AL", "GE", "AM", "JO", "CO", "CR", "EC", "RU", "LT", "LV",
                     "MU", "TN", "PA", "DO"], "D"),
    **dict.fromkeys(["IN", "TH", "VN", "ID", "EG", "NP", "LK", "UZ", "KH", "LA", "PH", "BD", "PK",
                     "MM", "BO", "KE", "TZ", "ET", "GT", "NI", "KG", "TJ", "MN"], "E"),
}

COUNTRY_CURRENCY: dict[str, str] = {
    "JP": "JPY", "IN": "INR", "TH": "THB", "VN": "VND", "ID": "IDR", "MY": "MYR", "SG": "SGD", "KR": "KRW",
    "CN": "CNY", "HK": "HKD", "TW": "TWD", "AE": "AED", "QA": "QAR", "SA": "SAR", "EG": "EGP", "MA": "MAD",
    "ZA": "ZAR", "TR": "TRY", "GB": "GBP", "CH": "CHF", "NO": "NOK", "SE": "SEK", "DK": "DKK", "IS": "ISK",
    "CZ": "CZK", "HU": "HUF", "PL": "PLN", "RO": "RON", "BG": "BGN", "US": "USD", "CA": "CAD", "MX": "MXN",
    "BR": "BRL", "AR": "ARS", "PE": "PEN", "CL": "CLP", "CO": "COP", "AU": "AUD", "NZ": "NZD", "UZ": "UZS",
    "NP": "NPR", "LK": "LKR", "KH": "KHR", "PH": "PHP", "IL": "ILS", "JO": "JOD", "KE": "KES", "GE": "GEL",
    **dict.fromkeys(["FR", "DE", "IT", "ES", "PT", "NL", "BE", "AT", "IE", "FI", "GR", "SI", "HR", "SK",
                     "EE", "LV", "LT", "LU", "MT", "CY", "ME", "MC"], "EUR"),
}

# Rough USD -> X rates for currencies the ECB (Frankfurter) does not publish. Estimates only.
STATIC_USD_RATES: dict[str, float] = {
    "AED": 3.67, "QAR": 3.64, "SAR": 3.75, "EGP": 48.0, "MAD": 9.2, "VND": 26000.0, "PEN": 3.45,
    "ARS": 1350.0, "UZS": 12000.0, "NPR": 140.0, "LKR": 300.0, "TWD": 31.0, "KHR": 4000.0,
    "CLP": 940.0, "COP": 3900.0, "JOD": 0.709, "KES": 129.0, "GEL": 2.7, "BGN": 1.67,
}


def tier_for(country_code: str) -> str:
    return COUNTRY_TIER.get((country_code or "").upper(), "C")


def currency_for(country_code: str) -> str:
    return COUNTRY_CURRENCY.get((country_code or "").upper(), "USD")


def profile(country_code: str, style: str) -> dict[str, float]:
    style = style if style in ("budget", "mid", "luxury") else "mid"
    return dict(TIERS[tier_for(country_code)][style])
