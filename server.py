from flask import Flask, request, jsonify
from datetime import datetime
import time

app = Flask(__name__)

# Prosta pamięć w RAM (MVP)
user_limits = {}
last_request_time = {}

DAILY_LIMIT = 2
COOLDOWN_SECONDS = 3
MAX_INGREDIENTS = 10
MAX_INGREDIENT_LENGTH = 30


@app.route("/")
def home():
    return "FridgeServer działa 🚀"


@app.route("/generate", methods=["POST"])
def generate_recipe():
    user_ip = request.remote_addr
    now_time = time.time()

    # --- Anty-spam (cooldown) ---
    if user_ip in last_request_time:
        if now_time - last_request_time[user_ip] < COOLDOWN_SECONDS:
            return jsonify({
                "error": "Za szybko! Poczekaj chwilę.",
                "remaining": get_remaining(user_ip)
            }), 429

    last_request_time[user_ip] = now_time

    # --- Reset limitu o północy ---
    today = datetime.now().date()

    if user_ip not in user_limits:
        user_limits[user_ip] = {"date": today, "count": 0}

    if user_limits[user_ip]["date"] != today:
        user_limits[user_ip] = {"date": today, "count": 0}

    # --- Sprawdzenie limitu ---
    if user_limits[user_ip]["count"] >= DAILY_LIMIT:
        return jsonify({
            "error": "Wykorzystałeś dzisiejszy limit.",
            "remaining": 0
        }), 403

    data = request.get_json()

    if not data or "ingredients" not in data:
        return jsonify({"error": "Brak składników", "remaining": get_remaining(user_ip)}), 400

    ingredients = data.get("ingredients", [])

    # --- Zabezpieczenia ---
    if not isinstance(ingredients, list):
        return jsonify({"error": "Niepoprawny format składników", "remaining": get_remaining(user_ip)}), 400

    if len(ingredients) == 0 or len(ingredients) > MAX_INGREDIENTS:
        return jsonify({"error": "Niepoprawna liczba składników", "remaining": get_remaining(user_ip)}), 400

    for i in ingredients:
        if not isinstance(i, str) or len(i) > MAX_INGREDIENT_LENGTH:
            return jsonify({"error": "Niepoprawny składnik", "remaining": get_remaining(user_ip)}), 400

    # --- Fake generowanie ---
    fake_recipe = {
        "title": f"Szybkie danie z {', '.join(ingredients[:2])}",
        "description": "Prosty przepis wygenerowany testowo.",
        "steps": [
            "Pokrój wszystkie składniki.",
            "Podsmaż je na patelni przez 5–7 minut.",
            "Dopraw solą i pieprzem do smaku.",
            "Podawaj na ciepło."
        ]
    }

    # Zwiększamy licznik
    user_limits[user_ip]["count"] += 1

    remaining = get_remaining(user_ip)

    return jsonify({
        "title": fake_recipe["title"],
        "description": fake_recipe["description"],
        "steps": fake_recipe["steps"],
        "remaining": remaining
    })


def get_remaining(user_ip):
    today = datetime.now().date()

    if user_ip not in user_limits:
        return DAILY_LIMIT

    if user_limits[user_ip]["date"] != today:
        return DAILY_LIMIT

    return DAILY_LIMIT - user_limits[user_ip]["count"]


if __name__ == "__main__":
    app.run()