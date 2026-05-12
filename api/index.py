@app.route("/generate", methods=["POST"])
def generate_recipe():
    # TEST 1: Sprawdzamy czy zmienna w ogóle istnieje w systemie
    all_env_vars = list(os.environ.keys())
    has_key = "GEMINI_API_KEY" in os.environ
    
    # TEST 2: Pobieramy klucz
    key = os.environ.get("GEMINI_API_KEY", "")

    # Jeśli klucza nie ma, wyślemy listę wszystkich dostępnych nazw zmiennych 
    # (bezpiecznie, same nazwy bez wartości!), żeby zobaczyć czy Vercel ich nie zmienił
    if not has_key or len(key) < 5:
        return jsonify({
            "error": "Klucz nieodnaleziony w systemie!",
            "dostepne_zmienne": all_env_vars,
            "czy_klucz_pusty": len(key) == 0
        }), 500

    try:
        # TEST 3: Ręczne przypisanie klucza bezpośrednio do konfiguracji
        genai.configure(api_key=key)
        
        # Sprawdzamy czy konfiguracja 'przeszła'
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        data = request.json
        ingredients = data.get("ingredients", [])
        
        # Króciutki test kontaktu
        response = model.generate_content("Say OK")
        
        return jsonify({"message": "Sukces! Gemini widzi klucz", "odpowiedz": response.text})

    except Exception as e:
        return jsonify({
            "error_type": str(type(e).__name__),
            "error_msg": str(e),
            "uzyty_klucz_poczatek": key[:4] + "****" # Pokaże pierwsze 4 znaki by sprawdzić czy to ten klucz
        }), 500