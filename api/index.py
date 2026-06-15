import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai

app = Flask(__name__)
CORS(app)


def _get_model():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Brak klucza w srodowisku")

    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-3.1-flash-lite")


def _parse_json_response(response):
    raw_text = response.text.strip()
    if "```" in raw_text:
        raw_text = raw_text.split("```")[1].replace("json", "").strip()

    return json.loads(raw_text)


@app.route("/")
def hello():
    return "Serwer dziala!"


@app.route("/generate", methods=["POST"])
def generate_recipe():
    try:
        model = _get_model()
        data = request.json or {}
        ingredients = data.get("ingredients", [])

        prompt = (
            f"Napisz przepis z: {', '.join(ingredients)}. "
            "Przepis powinien byc w tym samym jezyku, w ktorym napisano skladniki. "
            "Zwroc tylko JSON bez markdown: "
            "{\"title\": \"\", \"description\": \"\", \"steps\": []}"
        )

        response = model.generate_content(prompt)
        return jsonify(_parse_json_response(response))

    except Exception as error:
        return jsonify({"error": str(error)}), 500


@app.route("/generate-craving", methods=["POST"])
def generate_craving_recipe():
    try:
        model = _get_model()
        data = request.json or {}

        craving = str(data.get("craving", "")).strip()
        include_shopping_list = bool(data.get("includeShoppingList", True))
        available_ingredients = data.get("availableIngredients", [])

        if not craving:
            return jsonify({"error": "Brak zachcianki uzytkownika"}), 400

        owned_text = ", ".join(available_ingredients) if available_ingredients else "nic nie podano"
        shopping_instruction = (
            "Dodaj shoppingList jako liste brakujacych skladnikow do kupienia. "
            "Nie dodawaj rzeczy, ktore uzytkownik juz ma."
            if include_shopping_list
            else "Zwroc shoppingList jako pusta liste."
        )

        prompt = f"""
Uzytkownik ma konkretna zachcianke: {craving}.
Rzeczy, ktore uzytkownik juz ma: {owned_text}.

Stworz praktyczny, zdrowy przepis dopasowany do tej zachcianki.
{shopping_instruction}
Dodaj orientacyjne skladniki odzywcze dla jednej porcji.
Odpowiedz w tym samym jezyku, w ktorym napisana jest zachcianka.

Zwroc tylko poprawny JSON bez markdown i bez dodatkowego tekstu w takim formacie:
{{
  "title": "",
  "description": "",
  "steps": [],
  "shoppingList": [],
  "nutrition": {{
    "kcal": "",
    "protein": "",
    "carbs": "",
    "fat": "",
    "fiber": ""
  }}
}}
"""

        response = model.generate_content(prompt)
        parsed = _parse_json_response(response)
        parsed.setdefault("shoppingList", [])
        parsed.setdefault("nutrition", {})
        parsed.setdefault("steps", [])
        parsed.setdefault("description", "")

        return jsonify(parsed)

    except Exception as error:
        return jsonify({"error": str(error)}), 500


if __name__ == "__main__":
    app.run()
