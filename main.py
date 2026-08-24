# ============================================================
# main.py — CLI Entry Point (flat folder structure)
# ============================================================
import sys
import os

# Add current directory to path so all imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The plan text is LLM-authored and routinely contains typographic characters
# (en dashes, non-breaking hyphens, °). On a stock Windows console stdout is
# cp1252 and printing those raises UnicodeEncodeError mid-plan, losing the
# whole run. Force UTF-8 and degrade unmappable glyphs instead of crashing.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

from graph import run_travel_pipeline
from models import TravelRequest

def main():
    print("\n===== Autonomous Multi-Agent Travel Planner =====\n")

    # User inputs
    origin          = input("Enter source city: ")
    destination     = input("Enter destination city: ")
    departure_date  = input("Enter departure date (YYYY-MM-DD): ")
    return_date     = input("Enter return date (YYYY-MM-DD): ")
    budget          = float(input("Enter budget (USD): "))
    travelers       = int(input("Enter number of travelers: "))

    purpose         = input("Travel purpose (leisure/business/adventure/family) [leisure]: ").strip() or "leisure"
    dietary         = input("Dietary preference (no preference/vegetarian/vegan) [no preference]: ").strip() or "no preference"
    accommodation   = input("Accommodation tier (budget/mid-range/luxury) [mid-range]: ").strip() or "mid-range"
    special         = input("Any special requests? (press Enter to skip): ").strip() or None

    # Create request object
    request = TravelRequest(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        return_date=return_date,
        budget_usd=budget,
        travellers=travelers,
        travel_purpose=purpose,
        dietary_preference=dietary,
        accommodation_preference=accommodation,
        special_requests=special,
    )

    print("\n⏳ Running agents... this takes 30-60 seconds...\n")

    # Run the pipeline
    result = run_travel_pipeline(request)

    # Show errors if any
    errors = result.get("errors", [])
    if errors:
        print("\n❌ Errors:")
        for e in errors:
            print(f"  - {e}")
        return

    # Show warnings
    warnings = result.get("warnings", [])
    if warnings:
        print(f"\n⚠️  {len(warnings)} warning(s):")
        for w in warnings:
            print(f"  - {w}")

    # Display the plan
    plan = result.get("final_plan")
    if not plan:
        print("\n❌ Failed to generate plan. Check your GROQ_API_KEY in .env")
        return

    print("\n" + "="*60)
    print(f"✅ TRAVEL PLAN — {plan.plan_id}")
    print("="*60)
    print(f"\n📋 SUMMARY\n{plan.executive_summary}")
    print(f"\n🎯 Overall Confidence: {plan.overall_confidence:.0%}")

    # ── Data provenance ───────────────────────────────────────
    if plan.data_sources:
        mocked = plan.mocked_sources
        print(f"\n{'='*60}")
        print("📊 DATA SOURCES")
        print(f"{'='*60}")
        for name, src in sorted(plan.data_sources.items()):
            icon = {"live": "🟢", "curated": "🔵"}.get(src, "🟡")
            print(f"  {icon} {name:12} {src}")
        if mocked:
            print(
                f"\n  ⚠️  {len(mocked)} of {len(plan.data_sources)} sources are SIMULATED "
                f"({', '.join(mocked)})."
            )
            print("     Prices, weather and availability there are placeholders,")
            print("     not real figures. Add the matching API keys to .env.")

    # ── Route ─────────────────────────────────────────────────
    if plan.route:
        r = plan.route
        print(f"\n{'='*60}")
        print(f"🗺️  ROUTE PLAN")
        print(f"{'='*60}")
        print(f"Route: {r.best_route_summary}")
        print(f"Distance: {r.distance_km:,.0f} km | Duration: {r.total_days} days")
        print(f"\nTransport Options:")
        for opt in r.transportation_options:
            print(f"  • {opt}")
        print(f"\nDay-by-Day Itinerary:")
        for day in r.day_wise_itinerary:
            print(f"\n  Day {day.day} — {day.date}")
            for act in day.activities:
                print(f"    - {act}")
            print(f"    🚗 Transport : {day.transportation}")
            print(f"    🏨 Stay      : {day.accommodation}")
            print(f"    💵 Est. Cost : ${day.estimated_cost_usd:.0f}")

    # ── Weather ───────────────────────────────────────────────
    if plan.weather:
        w = plan.weather
        print(f"\n{'='*60}")
        print(f"🌤️  WEATHER")
        print(f"{'='*60}")
        print(f"Condition : {w.condition}")
        print(f"Temp      : {w.current_temp_celsius}°C | Humidity: {w.humidity_percent}% | Wind: {w.wind_speed_kmh:.0f} km/h")
        if w.travel_warnings:
            print(f"\n🚨 Warnings:")
            for warn in w.travel_warnings:
                print(f"  ⚠️  {warn}")
        print(f"\n👗 What to pack:")
        for item in w.clothing_suggestions:
            print(f"  • {item}")
        print(f"\n📅 7-Day Forecast:")
        for day in w.forecast_7days[:7]:
            print(f"  {day.get('date','?'):12} ↑{day.get('temp_high','?')}° ↓{day.get('temp_low','?')}°  {day.get('condition','')}")

    # ── Hotels ────────────────────────────────────────────────
    if plan.hotels:
        h = plan.hotels
        print(f"\n{'='*60}")
        print(f"🏨  HOTELS  (Best area: {h.recommended_area})")
        print(f"{'='*60}")
        for tier_name, tier_list in [
            ("💚 BUDGET",  h.budget_hotels),
            ("💛 PREMIUM", h.premium_hotels),
            ("💙 FAMILY",  h.family_hotels),
        ]:
            print(f"\n{tier_name}")
            for hotel in tier_list:
                print(f"  {hotel.name}")
                print(f"    💵 ${hotel.price_per_night_usd:.0f}/night  ⭐{hotel.rating}")
                print(f"    📍 {hotel.location_description}")
                print(f"    🏷️  {', '.join(hotel.amenities)}")
                print(f"    💡 {hotel.booking_tip}")

    # ── Budget ────────────────────────────────────────────────
    if plan.budget:
        b = plan.budget
        bd = b.per_person_breakdown
        print(f"\n{'='*60}")
        print(f"💰  BUDGET  ({b.budget_tier.upper()})")
        print(f"{'='*60}")
        print(f"  ✈️  Flights       : ${bd.flights_usd:,.0f}")
        print(f"  🏨  Accommodation : ${bd.accommodation_usd:,.0f}")
        print(f"  🍽️  Food          : ${bd.food_usd:,.0f}")
        print(f"  🚌  Transport     : ${bd.local_transport_usd:,.0f}")
        print(f"  🎭  Activities    : ${bd.activities_usd:,.0f}")
        print(f"  📦  Miscellaneous : ${bd.miscellaneous_usd:,.0f}")
        print(f"  {'─'*30}")
        print(f"  👤  Per Person    : ${bd.total_usd:,.0f}")
        print(f"  👥  TOTAL TRIP    : ${b.total_trip_cost_usd:,.0f}")
        print(f"\n  Currency: {b.currency_info}")
        print(f"\n💡 Saving Tips:")
        for tip in b.saving_tips:
            print(f"  • {tip}")

    # ── Food ──────────────────────────────────────────────────
    if plan.food:
        f = plan.food
        print(f"\n{'='*60}")
        print(f"🍜  FOOD  (Avg meal: ${f.average_meal_cost_usd:.0f}/person)")
        print(f"{'='*60}")
        print(f"\n🌿 Vegetarian Dishes:")
        for dish in f.vegetarian_dishes:
            print(f"  • {dish}")
        print(f"\n🍖 Non-Vegetarian Dishes:")
        for dish in f.non_vegetarian_dishes:
            print(f"  • {dish}")
        print(f"\n🌮 Street Food:")
        for item in f.street_food_recommendations:
            print(f"  • {item}")
        print(f"\n🍴 Restaurants:")
        for rest in f.restaurant_suggestions:
            print(f"  {rest.name}  {rest.price_range}  ⭐{rest.rating}")
            print(f"    Cuisine: {rest.cuisine_type} | Must-try: {rest.must_try_dish}")
            print(f"    📍 {rest.location_hint}")
        if f.food_safety_tips:
            print(f"\n🛡️  Food Safety:")
            for tip in f.food_safety_tips:
                print(f"  ⚠️  {tip}")

    print(f"\n{'='*60}")
    print(f"✅ Plan {plan.plan_id} generated successfully!")
    print(f"{'='*60}\n")

    # Optional: save to JSON
    save = input("\n💾 Save plan to JSON file? (y/n): ").strip().lower()
    if save == 'y':
        filename = f"travel_plan_{plan.plan_id}.json"
        with open(filename, 'w') as f_out:
            f_out.write(plan.model_dump_json(indent=2))
        print(f"✅ Saved to {filename}")


if __name__ == "__main__":
    main()