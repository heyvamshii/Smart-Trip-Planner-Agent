# Smart Trip Planner Agent

An agentic AI that plans a trip by deciding which tools to call — flight search,
hotel search, weather, on-ground cost estimates, and a full budget check — then
writes a day-by-day itinerary.
Built for zero cost: Groq's free API tier (Llama 3.3 70B) as the agent brain,
Streamlit for the interface.

## Setup

1. Create a virtual environment and install dependencies:

   ```
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Get a free Groq API key: https://console.groq.com/keys

3. Copy `.env.example` to `.env` and paste in your key:

   ```
   copy .env.example .env
   ```

   (Optional) Add a free OpenWeatherMap key from https://openweathermap.org/api
   for live weather. If left blank, the weather tool uses a seasonal estimate
   instead — the app still works fully without it.

4. Run the app:

   ```
   streamlit run app.py
   ```

## How it works

- `tools.py` — five plain Python functions: `search_flights`, `search_hotels`,
  `get_weather`, `estimate_local_costs`, `calculate_budget`.
- `agent.py` — gives those functions to Groq's Llama 3.3 as tools, runs the tool-call loop,
  and reports every step (input, each tool call, each tool result, final output)
  through a callback.
- `app.py` — Streamlit UI with two panels: chat on the left, a live "Agent
  Activity" log on the right that shows each tool call as it happens.

Flight and hotel data are realistic mock values (no paid travel API required).
Swap `search_flights`/`search_hotels` in `tools.py` for a real provider (e.g.
Amadeus Self-Service) later if you want live pricing.
