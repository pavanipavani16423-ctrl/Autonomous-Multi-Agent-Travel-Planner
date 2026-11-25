"""Date and budget sanity for a TripRequest. Returns human-readable problems (empty = OK)."""

from __future__ import annotations

from datetime import date

from voyager.schemas import TripRequest

# Very low daily floor per person (USD) below which a plan cannot be honest anywhere.
MIN_USD_PER_PERSON_DAY = 8.0


def date_problems(req: TripRequest, today: date | None = None, max_days: int = 14) -> list[str]:
    today = today or date.today()
    problems = []
    if req.start < today:
        problems.append(f"start_date {req.start_date} is in the past (today is {today.isoformat()}).")
    if req.end < req.start:
        problems.append("end_date is before start_date.")
    elif req.days > max_days:
        problems.append(f"trip is {req.days} days; the maximum is {max_days}.")
    if (req.start - today).days > 365:
        problems.append("start_date is more than a year away.")
    return problems


def budget_problems(req: TripRequest, usd_rate: float | None = None) -> list[str]:
    """`usd_rate` = units of req.currency per USD (when known)."""
    problems = []
    if req.budget <= 0:
        problems.append("budget must be positive.")
    elif usd_rate:
        per_day_usd = req.budget / usd_rate / max(req.days, 1) / max(req.travellers, 1)
        if per_day_usd < MIN_USD_PER_PERSON_DAY:
            problems.append(
                f"budget is about ${per_day_usd:.0f} per person per day, below any realistic floor.")
    return problems
