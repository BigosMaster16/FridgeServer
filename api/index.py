from flask import Flask, request, jsonify
from flask_cors import CORS  # Dodajemy obsługę połączeń z zewnątrz
import google.generativeai as genai
import os
import json

app = Flask(__name__)
CORS(app) # To pozwoli Twojej apce we Flutterze bez problemu pobierać dane

# Konfiguracja Gemini
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

# Zmieniamy na stabilny model 1.5 Flash - jest błyskawiczny
model = genai.GenerativeModel("3.1-flash-lite-preview")

@app.route("/generate", methods=["POST"])
def generate_recipe():
    data = request.json
    ingredients = data.get("ingredients", [])

    if not ingredients:
        return jsonify({"error": "Brak składników"}), 400

    prompt = f"""
Stwórz przepis kulinarny na podstawie tych składników: {', '.join(ingredients)}.

Przepis MUSI być w tym samym języku, w którym napisano składniki.

Zwróć WYŁĄCZNIE poprawny JSON w formacie:
{{
  "title": "Nazwa przepisu",
  "description": "Krótki opis",
  "steps": ["krok 1", "krok 2", "krok 3"]
}}

STRICT JSON ONLY. NO MARKDOWN. NO EXTRA TEXT.
"""

    try:
        response = model.generate_content(prompt)
        text = response.text.strip()

        # Usuwanie znaczników markdown, jeśli Gemini je doda
        if text.startswith("```"):
            text = text.replace("```json", "").replace("```", "").strip()

        try:
            recipe_json = json.loads(text)
        except Exception as e:
            return jsonify({
                "error": "Brak poprawnej odpowiedzi od AI",
                "raw": text
            }), 500

        return jsonify({
            "title": recipe_json.get("title", "Przepis"),
            "description": recipe_json.get("description", ""),
            "steps": recipe_json.get("steps", []),
            "remaining": 999
        })

    except Exception as e:
        return jsonify({"error": "Błąd połączenia z AI. Spróbuj za chwilę."}), 500

# Na Vercel NIE dodajemy app.run() - Vercel sam zarządza startem aplikacji