from flask import Flask, request, jsonify
import google.generativeai as genai
import os
import json

app = Flask(__name__)

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

model = genai.GenerativeModel("gemini-1.5-flash")

@app.route("/generate", methods=["POST"])
def generate_recipe():
    data = request.json
    ingredients = data.get("ingredients", [])

    if not ingredients:
        return jsonify({"error": "Brak składników"}), 400

    prompt = f"""
Stwórz przepis kulinarny na podstawie tych składników: {', '.join(ingredients)}.

Zwróć WYŁĄCZNIE poprawny JSON w formacie:
{{
  "title": "Nazwa przepisu",
  "description": "Krótki opis",
  "steps": ["krok 1", "krok 2", "krok 3"]
}}

Bez żadnego dodatkowego tekstu.
"""

    try:
        response = model.generate_content(prompt)

        text = response.text

        try:
            recipe_json = json.loads(text)
        except:
            return jsonify({
                "error": "AI zwróciło zły JSON",
                "raw": text
            }), 500

        return jsonify({
            "title": recipe_json.get("title"),
            "description": recipe_json.get("description"),
            "steps": recipe_json.get("steps"),
            "remaining": 999
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run()