from flask import Flask, request, jsonify
import openai
import os

app = Flask(__name__)

# W Render ustawiasz SECRET w panelu: OPENAI_API_KEY
openai.api_key = os.environ.get("OPENAI_API_KEY")

@app.route("/generate", methods=["POST"])
def generate_recipe():
    data = request.json
    ingredients = data.get("ingredients", [])

    if not ingredients:
        return jsonify({"error": "Brak składników"}), 400

    prompt = f"Stwórz przepis kulinarny na podstawie tych składników: {', '.join(ingredients)}. Podaj składniki i kroki przygotowania w formacie JSON."

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4.1-mini",
            messages=[{"role": "user", "content": prompt}]
        )

        recipe_text = response.choices[0].message.content

        return jsonify({"recipe": recipe_text})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)