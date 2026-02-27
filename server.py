from flask import Flask, request, jsonify
from flask_cors import CORS
import random

app = Flask(__name__)
CORS(app)

# prosta pamięć historii (na razie w RAM)
history = []

@app.route("/")
def home():
    return "FridgeMate API działa 🚀"

# =============================
# GENEROWANIE PRZEPISU
# =============================
@app.route("/generate", methods=["POST"])
def generate_recipe():
    data = request.get_json()
    ingredients = data.get("ingredients", [])

    # Na razie prosta symulacja AI
    title = f"Przepis z: {', '.join(ingredients)}"
    description = (
        f"1. Przygotuj: {', '.join(ingredients)}.\n"
        f"2. Wymieszaj wszystko razem.\n"
        f"3. Gotuj 15 minut.\n"
        f"4. Smacznego!"
    )

    recipe = {
        "title": title,
        "description": description
    }

    history.append(recipe)

    return jsonify(recipe)

# =============================
# GOTOWE PRZEPISY
# =============================
@app.route("/ready_recipes", methods=["GET"])
def ready_recipes():
    recipes = [
        {
            "title": "Jajecznica klasyczna",
            "description": "1. Rozbij jajka.\n2. Smaż 5 minut.\n3. Dopraw solą."
        },
        {
            "title": "Owsianka z owocami",
            "description": "1. Zagotuj mleko.\n2. Dodaj płatki.\n3. Dorzuć owoce."
        }
    ]

    return jsonify({"recipes": recipes})

# =============================
# HISTORIA
# =============================
@app.route("/history", methods=["GET"])
def get_history():
    return jsonify({"history": history})


if __name__ == "__main__":
    app.run()