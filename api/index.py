import os
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
import google.generativeai as genai

# VERCEL SZUKA TEGO TUTAJ:
app = Flask(__name__)
CORS(app)

@app.route("/")
def hello():
    return "Serwer działa!"

@app.route("/generate", methods=["POST"])
def generate_recipe():
    # Pobieramy klucz
    api_key = os.environ.get("GEMINI_API_KEY")
    
    if not api_key:
        return jsonify({"error": "Brak klucza w środowisku"}), 500

    try:
        # Konfiguracja
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")

        data = request.json
        ingredients = data.get("ingredients", [])
        
        prompt = f"Napisz przepis z: {', '.join(ingredients)}. Zwróć JSON: {{\"title\": \"\", \"description\": \"\", \"steps\": []}}"
        
        response = model.generate_content(prompt)
        
        # Wyciągamy tekst i czyścimy z ```json ... ```
        raw_text = response.text.strip()
        if "```" in raw_text:
            raw_text = raw_text.split("```")[1].replace("json", "").strip()

        return jsonify(json.loads(raw_text))

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# To jest tylko dla testów lokalnych, Vercel tego nie używa, 
# ale ważne, żeby 'app' był zdefiniowany wyżej
if __name__ == "__main__":
    app.run()