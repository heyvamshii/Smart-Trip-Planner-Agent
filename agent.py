import json
import os

from dotenv import load_dotenv
from groq import BadRequestError, Groq

from tools import (
    build_cost_breakdown_md,
    calculate_budget,
    estimate_local_costs,
    get_weather,
    reset_context,
    search_flights,
    search_hotels,
)

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# Llama 3.3 70B on Groq supports tool calling and has a generous free tier.
MODEL_NAME = "llama-3.3-70b-versatile"

TOOL_FUNCTIONS = {
    "search_flights": search_flights,
    "search_hotels": search_hotels,
    "get_weather": get_weather,
    "estimate_local_costs": estimate_local_costs,
    "calculate_budget": calculate_budget,
}

# OpenAI-style tool schemas that tell the model what each tool does and expects.
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "search_flights",
            "description": "Search round-trip flight prices between two cities. If the "
            "destination has no airport, use the nearest major airport.",
            "parameters": {
                "type": "object",
                "properties": {
                    "origin": {"type": "string", "description": "Departure city."},
                    "destination": {
                        "type": "string",
                        "description": "Destination city or nearest airport city.",
                    },
                    "travel_date": {
                        "type": "string",
                        "description": "Preferred date, or 'flexible'.",
                    },
                },
                "required": ["origin", "destination"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_hotels",
            "description": "Find the best-value hotel in a city for a number of nights.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "nights": {"type": "integer"},
                    "guests": {"type": "integer"},
                },
                "required": ["city", "nights"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for the destination city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "estimate_local_costs",
            "description": "Estimate on-ground costs: meals, local transport, and "
            "sightseeing/activities for the whole trip.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {"type": "string"},
                    "days": {"type": "integer"},
                    "num_people": {"type": "integer"},
                },
                "required": ["city", "days", "num_people"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_budget",
            "description": "Calculate the COMPLETE trip cost from the flight, hotel "
            "and local-cost data already gathered, and check whether it fits the "
            "budget. Call this only after the other tools. Pass only the budget "
            "limit; the real costs are used automatically.",
            "parameters": {
                "type": "object",
                "properties": {
                    "budget_limit_inr": {
                        "type": "number",
                        "description": "The user's total budget for the trip.",
                    },
                },
                "required": ["budget_limit_inr"],
            },
        },
    },
]

SYSTEM_INSTRUCTION = """You are a travel planning agent.

When the user describes a trip (destination, duration, number of people, budget),
you MUST use ALL of the available tools to gather real data before answering:
1. Call search_flights for the route. If the user did NOT give a departure city,
   assume a specific real major city as the origin (for example Chennai,
   Bengaluru, Mumbai, or Delhi — whichever is nearest to the destination) and
   mention that assumption in your intro line. NEVER pass a placeholder such as
   "nearest airport" as a city name — always use a real city name.
2. Call search_hotels for the destination and trip length.
3. Call get_weather for the destination.
4. Call estimate_local_costs for meals, local transport, and activities.
5. Call calculate_budget (passing only the budget limit) to get the COMPLETE trip
   total and verify it fits the budget.

Call each tool exactly once, in that order.

Only after you have all five tool results, respond in this exact markdown format:

Start with a one-line intro sentence. Then a day-by-day itinerary where EACH day
is its own markdown heading on its own line, followed by 2-4 bullet points, using
this exact structure (keep the blank lines):

### Day 1 — <short title>
- Morning: ...
- Afternoon: ...
- Evening: ...

### Day 2 — <short title>
- ...

(continue for every day)

Do NOT write a cost breakdown table yourself — an accurate one is added
automatically after your itinerary. End with ONE short sentence noting whether
the trip is within the budget, and if it is over budget, suggest one concrete
adjustment (e.g. fewer days or activities).
"""


def run_agent(user_message: str, log_callback=None) -> str:
    """Runs one turn of the agent loop against `user_message`.

    Calls log_callback(event: dict) for every step (user input, each tool call,
    each tool result, and the final output) so a UI can render live progress.
    Returns the agent's final markdown itinerary as a string.
    """

    def log(event_type: str, **kwargs):
        if log_callback:
            log_callback({"type": event_type, **kwargs})

    def create_completion(msgs):
        # Llama occasionally emits a malformed tool call (Groq 'tool_use_failed').
        # It is stochastic, so a couple of retries almost always recovers.
        last_err = None
        for _ in range(4):
            try:
                return client.chat.completions.create(
                    model=MODEL_NAME,
                    messages=msgs,
                    tools=TOOLS_SCHEMA,
                    tool_choice="auto",
                    temperature=0.4,
                )
            except BadRequestError as exc:
                if "tool_use_failed" in str(exc):
                    last_err = exc
                    continue
                raise
        raise last_err

    reset_context()  # start each plan with a clean set of tool results
    messages = [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": user_message},
    ]
    log("user_input", message=user_message)

    # Keep looping while the model wants to call tools.
    while True:
        response = create_completion(messages)
        msg = response.choices[0].message

        if not msg.tool_calls:
            # Append an authoritative cost table built from the real tool results,
            # so the numbers are always correct regardless of the model's text.
            final_text = (msg.content or "").rstrip() + build_cost_breakdown_md()
            log("final_output", text=final_text)
            return final_text

        # Record the assistant's tool-call request in the conversation.
        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ],
            }
        )

        for tc in msg.tool_calls:
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            log("tool_call", tool=tool_name, args=args)

            func = TOOL_FUNCTIONS.get(tool_name)
            try:
                result = (
                    func(**args) if func else {"error": f"Unknown tool {tool_name}"}
                )
            except Exception as exc:  # feed the error back so the model can recover
                result = {"error": str(exc)}

            log("tool_result", tool=tool_name, result=result)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tool_name,
                    "content": json.dumps(result),
                }
            )
