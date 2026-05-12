import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai

app = Flask(__name__)
CORS(app)

@app.route("/")
def home():
    return "FridgeMateAI Backend is running!"

@app.route("/generate", methods=["POST"])
def generate_recipe():
    # 1. Pobranie klucza wewnątrz funkcji (najbezpieczniejsza opcja na Vercel)
    api_key = os.environ.get("GEMINI_API_KEY")
    
    if not api_key:
        return jsonify({
            "error": "Błąd konfiguracji: Serwer nie widzi klucza GEMINI_API_KEY w zmiennych środowiskowych.",
            "remaining": 0
        }), 500

    try:
        # 2. Konfiguracja Gemini bezpośrednio przed użyciem
        genai.configure(api_key=api_key)
        
        # Używamy stabilnego modelu 1.5-flash
        model = genai.GenerativeModel("gemini-1.5-flash")

        # 3. Pobranie danych z Fluttera
        data = request.json
        if not data:
            return jsonify({"error": "Brak danych wejściowych"}), 400
            
        ingredients = data.get("ingredients", [])
        
        # 4. Przygotowanie promptu
        prompt = (
            f"Napisz krótki przepis z następujących składników: {', '.join(ingredients)}. "
            "Zwróć odpowiedź WYŁĄCZNIE w formacie JSON o strukturze: "
            "{\"title\": \"Nazwa dania\", \"description\": \"Krótki opis\", \"steps\": [\"krok 1\", \"krok 2\"]}"
        )

        # 5. Generowanie treści
        response = model.generate_content(prompt)
        
        if not response or not response.text:
            return jsonify({"error": "Gemini zwróciło pustą odpowiedź."}), 500

        # Czyszczenie odpowiedzi (na wypadek gdyby AI dodało ```json ... ```)
        text = response.text.strip()
        if text.startswith("```"):
            text = text.replace("```json", "").replace("```", "").strip()

        # Próba sparsowania JSONa
        recipe_json = json.loads(text)
        
        return jsonify({
            "title": recipe_json.get("title", "Przepis"),
            "description": recipe_json.get("description", ""),
            "steps": recipe_json.get("steps", []),
            "remaining": 999  # Na razie na sztywno, póki nie dodasz licznika
        })

    except json.JSONDecodeError:
        return jsonify({"error": "Błąd formatowania przepisu. Spróbuj ponownie."}), 500
    except Exception as e:
        # Przekazujemy dokładny błąd do Fluttera
        error_msg = str(e)
        return jsonify({
            "error": f"Błąd Python/Gemini: {error_msg}",
            "remaining": 0
        }), 500

# To jest ważne dla Vercela, by widział obiekt 'app'
if __name__ == "__main__":
    app.run(debug=True)