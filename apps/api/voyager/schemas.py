"""Pydantic v2 mirror of the TypeScript contract in docs/SPEC.md. Field names are authoritative."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AgentId = Literal[
    "guard", "brief", "destination", "weather", "stays", "food", "logistics",
    "itinerary", "budget", "critic", "finalize",
]
AGENT_IDS: tuple[str, ...] = (
    "guard", "brief", "destination", "weather", "stays", "food", "logistics",
    "itinerary", "budget", "critic", "finalize",
)
Provenance = Literal["live", "guidebook", "estimate", "cached", "unavailable"]
CitationSource = Literal["wikivoyage", "openstreetmap", "open-meteo", "frankfurter", "budget-analyst"]
Pace = Literal["relaxed", "balanced", "packed"]
StayStyle = Literal["budget", "mid", "luxury"]
Slot = Literal["morning", "afternoon", "evening"]
Category = Literal["sight", "food", "activity", "transit", "shopping", "nature", "culture", "nightlife"]
Rating = Literal["Good", "OK", "Weak"]
TripStatus = Literal["queued", "running", "done", "error"]


class Money(BaseModel):
    amount: float
    currency: str


class GeoPoint(BaseModel):
    lat: float
    lon: float


class TripRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    origin: str | None = None
    destination: str = Field(min_length=1, max_length=120)
    start_date: str
    end_date: str
    adults: int = Field(1, ge=1, le=20)
    children: int = Field(0, ge=0, le=20)
    budget: float = Field(gt=0)
    currency: str = Field("USD", min_length=3, max_length=3)
    interests: list[str] = Field(default_factory=list, max_length=12)
    pace: Pace = "balanced"
    diet: list[str] = Field(default_factory=list, max_length=8)
    stay_style: StayStyle = "mid"
    notes: str | None = Field(None, max_length=1000)
    client_id: str | None = Field(None, max_length=80)

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @field_validator("start_date", "end_date")
    @classmethod
    def _iso(cls, v: str) -> str:
        date.fromisoformat(v)  # raises -> 422
        return v

    @field_validator("interests", "diet")
    @classmethod
    def _norm_list(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for item in v:
            item = (item or "").strip().lower()[:40]
            if item and item not in out:
                out.append(item)
        return out

    @property
    def start(self) -> date:
        return date.fromisoformat(self.start_date)

    @property
    def end(self) -> date:
        return date.fromisoformat(self.end_date)

    @property
    def nights(self) -> int:
        return max(0, (self.end - self.start).days)

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def travellers(self) -> int:
        return self.adults + self.children


class Citation(BaseModel):
    id: str
    title: str
    url: str
    snippet: str
    source: CitationSource


class DailyWeather(BaseModel):
    date: str
    t_min: float
    t_max: float
    precip_mm: float
    precip_prob: float | None = None
    code: int
    summary: str
    provenance: Provenance


class Activity(BaseModel):
    id: str
    slot: Slot
    time: str
    duration_min: int
    title: str
    description: str
    place: str | None = None
    location: GeoPoint | None = None
    category: Category
    cost: Money
    indoor: bool
    citations: list[str] = Field(default_factory=list)
    tip: str | None = None


class DayPlan(BaseModel):
    day: int
    date: str
    title: str
    theme: str
    weather: DailyWeather | None = None
    activities: list[Activity]
    day_cost: Money
    walking_km: float | None = None


class Stay(BaseModel):
    name: str
    kind: Literal["hotel", "hostel", "guest_house", "apartment", "resort"]
    area: str
    location: GeoPoint | None = None
    price_per_night: Money
    rating: float | None = None
    why: str
    provenance: Provenance
    url: str | None = None
    citations: list[str] = Field(default_factory=list)


class FoodPick(BaseModel):
    name: str
    cuisine: str
    area: str | None = None
    location: GeoPoint | None = None
    price_level: Literal[1, 2, 3, 4]
    must_try: str
    diet_ok: list[str] = Field(default_factory=list)
    provenance: Provenance
    citations: list[str] = Field(default_factory=list)


class BudgetLine(BaseModel):
    category: Literal["stay", "food", "activities", "transport", "travel", "misc"]
    amount: Money
    note: str


class Budget(BaseModel):
    total: Money
    limit: Money
    per_person: Money
    lines: list[BudgetLine]
    within_budget: bool
    utilisation: float
    savings_tips: list[str]
    analyst: str


class GettingThere(BaseModel):
    mode: str
    duration: str
    cost: Money
    note: str


class PreTrip(BaseModel):
    getting_there: GettingThere
    getting_around: str
    visa: str
    currency_note: str
    safety: list[str]
    packing: list[str]
    local_tips: list[str]
    best_areas: list[str]
    citations: list[str] = Field(default_factory=list)


class QualityScore(BaseModel):
    name: str
    value: float
    rating: Rating
    explain: str


class Check(BaseModel):
    name: str
    passed: bool
    detail: str


class Quality(BaseModel):
    confidence: float
    grounding_coverage: float
    guidebook: Literal["covered", "expanded", "none"]
    checks: list[Check]
    scores: list[QualityScore]


class DestinationInfo(BaseModel):
    name: str
    country: str
    location: GeoPoint
    image: str | None = None
    blurb: str


class Timing(BaseModel):
    agent: AgentId
    ms: int


class TripPlan(BaseModel):
    trip_id: str
    revision: int
    request: TripRequest
    title: str
    summary: str
    destination: DestinationInfo
    weather_overview: str
    days: list[DayPlan]
    stays: list[Stay]
    food: list[FoodPick]
    budget: Budget
    pre_trip: PreTrip
    citations: list[Citation]
    quality: Quality
    timings: list[Timing]
    model: str
    created_at: str


class Trip(BaseModel):
    id: str
    status: TripStatus
    revision: int
    request: TripRequest
    plan: TripPlan | None = None
    error: str | None = None
    created_at: str
    updated_at: str


class TripSummary(BaseModel):
    id: str
    title: str
    destination: str
    start_date: str
    end_date: str
    status: TripStatus
    image: str | None = None
    created_at: str


# ---- request / response bodies -------------------------------------------------------------
class ParseBody(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    client_id: str | None = Field(None, max_length=80)  # optional: pre-fill from the preference profile


class RefineBody(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=6000)


class ChatBody(BaseModel):
    """POST /api/chat. Only the last 10 history turns are used; the server re-checks all of them."""

    message: str = Field(min_length=1, max_length=1000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)
    trip_id: str | None = Field(None, max_length=40)
    client_id: str | None = Field(None, max_length=80)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be blank")
        return v.strip()


class TripCreated(BaseModel):
    trip_id: str


class RefineAccepted(BaseModel):
    trip_id: str
    revision: int


class DestinationCoverage(BaseModel):
    name: str
    country: str
    passages: int


class PlaceSuggestion(BaseModel):
    name: str
    country: str
    lat: float
    lon: float
    covered: bool


def rating_for(value: float) -> Rating:
    if value >= 0.70:
        return "Good"
    if value >= 0.40:
        return "OK"
    return "Weak"


def dump(model: BaseModel | None) -> dict[str, Any] | None:
    return None if model is None else model.model_dump(mode="json")
