from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/recipe", methods=["POST"])
def recipe():
    data = request.json
    products = data.get("products", "")

    # FAKE AI - póki co tylko tekst
    recipe_text = f"""
PRZEPIS:

Z podanych składników ({products}) możesz zrobić szybki omlet:

1. Pokrój składniki
2. Rozbij 2-3 jajka
3. Wymieszaj
4. Smaż 5 minut na patelni

Smacznego 😄
"""

    return jsonify({"recipe": recipe_text})

app.run(host="0.0.0.0", port=5000)