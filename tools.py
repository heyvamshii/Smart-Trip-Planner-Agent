"""Trip-planning tools.

Two design choices keep the agent trustworthy:
1. Tools are DETERMINISTIC — the same query always returns the same prices
   (random values are seeded from the inputs), so numbers never drift between
   calls or between demo runs.
2. Tools record their results in a per-run context, and `calculate_budget` reads
   the REAL recorded values instead of trusting numbers passed by the LLM. This
   makes the final cost the single source of truth, immune to model arithmetic
   mistakes.
"""

import hashlib
import os
import random

import requests

# Per-run store of the latest tool results. Reset at the start of every plan.
_CONTEXT = {}


def reset_context():
    _CONTEXT.clear()


def _seeded_rng(*parts) -> random.Random:
    key = "|".join(str(p).strip().lower() for p in parts)
    seed = int(hashlib.md5(key.encode()).hexdigest(), 16) % (2**32)
    return random.Random(seed)


def search_flights(origin: str, destination: str, travel_date: str = "flexible") -> dict:
    """Search round-trip flight prices between two cities for a given date.

    Args:
        origin: The departure city.
        destination: The destination city (or nearest airport city).
        travel_date: Preferred travel date, or "flexible" if not specified.
    """
    base_prices = {
        ("Hyderabad", "Goa"): 5800,
        ("Delhi", "Goa"): 7200,
        ("Mumbai", "Goa"): 3800,
        ("Bangalore", "Goa"): 4200,
        ("Chennai", "Goa"): 4600,
        ("Pune", "Goa"): 3600,
        ("Chennai", "Madurai"): 3200,
        ("Bangalore", "Madurai"): 3600,
        ("Hyderabad", "Madurai"): 4800,
    }
    rng = _seeded_rng(origin, destination)
    key = (origin.strip().title(), destination.strip().title())
    base = base_prices.get(key, rng.randint(4000, 9000))
    price_per_person = max(2500, base + rng.randint(-300, 500))

    result = {
        "origin": origin,
        "destination": destination,
        "travel_date": travel_date,
        "airline": rng.choice(["IndiGo", "Air India", "SpiceJet", "Vistara"]),
        "price_per_person_inr": price_per_person,
        "duration_hours": round(rng.uniform(1.5, 3.0), 1),
    }
    _CONTEXT["flights"] = result
    return result


def search_hotels(city: str, nights: int, guests: int = 2) -> dict:
    """Search hotels in a city for a number of nights and guests; returns the best
    value option.

    Args:
        city: The city to find hotels in.
        nights: Number of nights of stay.
        guests: Number of guests staying.
    """
    options = [
        {"name": "Sea Breeze Resort", "rating": 4.2, "price_per_night_inr": 2800},
        {"name": "Palm Grove Inn", "rating": 3.9, "price_per_night_inr": 1900},
        {"name": "Coastal Comfort Stay", "rating": 4.5, "price_per_night_inr": 3400},
    ]
    chosen = min(options, key=lambda h: h["price_per_night_inr"])
    total = chosen["price_per_night_inr"] * nights

    result = {
        "city": city,
        "nights": nights,
        "guests": guests,
        "hotel_name": chosen["name"],
        "rating": chosen["rating"],
        "price_per_night_inr": chosen["price_per_night_inr"],
        "total_price_inr": total,
    }
    _CONTEXT["hotel"] = result
    return result


def get_weather(city: str) -> dict:
    """Get the current weather for a city. Uses a live API if a key is configured,
    otherwise falls back to a reasonable seasonal estimate.

    Args:
        city: The city to check weather for.
    """
    api_key = os.getenv("OPENWEATHER_API_KEY")
    if api_key:
        try:
            resp = requests.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": city, "appid": api_key, "units": "metric"},
                timeout=5,
            )
            if resp.ok:
                data = resp.json()
                result = {
                    "city": city,
                    "temp_celsius": data["main"]["temp"],
                    "condition": data["weather"][0]["description"],
                    "source": "OpenWeatherMap (live)",
                }
                _CONTEXT["weather"] = result
                return result
        except requests.RequestException:
            pass

    result = {
        "city": city,
        "temp_celsius": 27,
        "condition": "pleasant and mostly clear",
        "source": "seasonal estimate (no live weather key configured)",
    }
    _CONTEXT["weather"] = result
    return result


def estimate_local_costs(city: str, days: int, num_people: int) -> dict:
    """Estimate on-ground trip costs beyond flights and hotel: meals, local
    transport (cabs/scooters), and sightseeing/activities.

    Args:
        city: The destination city.
        days: Number of days of the trip.
        num_people: Number of travelers.
    """
    food_per_person_per_day = 800
    local_transport_per_day = 700  # cabs / scooter rentals for the whole group
    activities_per_person = 1500  # entry fees, sightseeing, experiences over the trip

    food_total = food_per_person_per_day * num_people * days
    transport_total = local_transport_per_day * days
    activities_total = activities_per_person * num_people
    total = food_total + transport_total + activities_total

    result = {
        "city": city,
        "days": days,
        "num_people": num_people,
        "food_total_inr": food_total,
        "local_transport_total_inr": transport_total,
        "activities_total_inr": activities_total,
        "local_costs_total_inr": total,
    }
    _CONTEXT["local"] = result
    return result


def calculate_budget(budget_limit_inr: float) -> dict:
    """Calculate the COMPLETE trip cost from the real flight, hotel and local-cost
    results already gathered, and check whether it fits the budget. Call this only
    after search_flights, search_hotels and estimate_local_costs.

    Args:
        budget_limit_inr: The user's total budget limit.
    """
    flights = _CONTEXT.get("flights")
    hotel = _CONTEXT.get("hotel")
    local = _CONTEXT.get("local")
    if not (flights and hotel and local):
        return {
            "error": "Call search_flights, search_hotels and estimate_local_costs "
            "before calculate_budget."
        }

    num_people = local["num_people"]
    total_flight_cost = flights["price_per_person_inr"] * num_people
    grand_total = (
        total_flight_cost + hotel["total_price_inr"] + local["local_costs_total_inr"]
    )
    within_budget = grand_total <= budget_limit_inr

    result = {
        "total_flight_cost_inr": total_flight_cost,
        "hotel_total_price_inr": hotel["total_price_inr"],
        "local_costs_total_inr": local["local_costs_total_inr"],
        "grand_total_inr": grand_total,
        "budget_limit_inr": budget_limit_inr,
        "within_budget": within_budget,
        "margin_inr": budget_limit_inr - grand_total,
    }
    _CONTEXT["budget"] = result
    return result


def build_cost_breakdown_md() -> str:
    """Build an authoritative markdown cost-breakdown table from the recorded tool
    results, so the numbers shown are always internally consistent."""
    flights = _CONTEXT.get("flights")
    hotel = _CONTEXT.get("hotel")
    local = _CONTEXT.get("local")
    budget = _CONTEXT.get("budget")
    if not (flights and hotel and local and budget):
        return ""

    rows = [
        ("Flights", budget["total_flight_cost_inr"]),
        ("Hotel", hotel["total_price_inr"]),
        ("Food", local["food_total_inr"]),
        ("Local Transport", local["local_transport_total_inr"]),
        ("Activities", local["activities_total_inr"]),
    ]
    md = "\n\n### 💰 Cost Breakdown\n\n| Category | Cost (INR) |\n| --- | --- |\n"
    for name, val in rows:
        md += f"| {name} | ₹{val:,.0f} |\n"
    md += f"| **Grand Total** | **₹{budget['grand_total_inr']:,.0f}** |\n\n"

    limit = budget["budget_limit_inr"]
    if budget["within_budget"]:
        md += (
            f"✅ **Within budget** — ₹{budget['grand_total_inr']:,.0f} of your "
            f"₹{limit:,.0f} budget, leaving ₹{budget['margin_inr']:,.0f} to spare."
        )
    else:
        md += (
            f"⚠️ **Over budget** by ₹{abs(budget['margin_inr']):,.0f} "
            f"(₹{budget['grand_total_inr']:,.0f} vs ₹{limit:,.0f})."
        )
    return md
