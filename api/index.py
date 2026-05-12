import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai

app = Flask(__name__)
CORS(app)

@app.route("/generate", methods=["POST"])
def generate_recipe():
    # 1. Sprawdzenie klucza - czy Vercel go w ogóle widzi?
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": "Serwer nie widzi klucza API (GEMINI_API_KEY is None)"}), 500

    try:
        # 2. Próba konfiguracji
        genai.configure(api_key=api_key)
        
        # Używamy modelu, który na 100% istnieje i jest stabilny
        model = genai.GenerativeModel("gemini-1.5-flash")

        data = request.json
        ingredients = data.get("ingredients", [])
        
        # 3. Próba kontaktu z Google
        prompt = f"Napisz krótki przepis z: {', '.join(ingredients)}. Zwróć tylko JSON: {{\"title\": \"\", \"description\": \"\", \"steps\": []}}"
        response = model.generate_content(prompt)
        
        if not response:
            return jsonify({"error": "Brak odpowiedzi od Google AI"}), 500

        # Wyciąganie tekstu
        text = response.text.strip()
        if text.startswith("```"):
            text = text.replace("```json", "").replace("```", "").strip()

        return jsonify(json.loads(text))

    except Exception as e:
        # TO JEST KLUCZOWE: Wyśle Ci konkretny błąd (np. brak biblioteki, zły model)
        return jsonify({
            "error": f"Błąd Python: {str(type(e).__name__)} - {str(e)}",
            "remaining": 0
        }), 500

# Vercel wymaga tego, by app był dostępny