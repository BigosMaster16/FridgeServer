from flask import Flask, request, jsonify
from openai import OpenAI
import os
import json

app = Flask(__name__)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

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

Nie dodawaj żadnego tekstu poza JSON.
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        recipe_text = response.choices[0].message.content

        # 🔥 próbujemy sparsować JSON (ważne!)
        try:
            recipe_json = json.loads(recipe_text)
        except:
            return jsonify({
                "error": "AI zwróciło niepoprawny JSON",
                "raw": recipe_text
            }), 500

        return jsonify({
            "title": recipe_json.get("title"),
            "description": recipe_json.get("description"),
            "steps": recipe_json.get("steps"),
            "remaining": 999  # na razie fake limit
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run()