import base64
import binascii
import json
import os
from io import BytesIO
from datetime import datetime
from zoneinfo import ZoneInfo

import firebase_admin
import google.generativeai as genai
from firebase_admin import auth, credentials, db
from flask import Flask, jsonify, request
from flask_cors import CORS
from PIL import Image, ImageOps, UnidentifiedImageError

app = Flask(__name__)
CORS(app)

DAILY_GENERATION_LIMIT = 2
PHOTO_WEEKLY_GENERATION_LIMIT = 5
PHOTO_MAX_UPLOAD_BYTES = 3 * 1024 * 1024
PHOTO_MAX_IMAGE_SIDE = 640
PHOTO_JPEG_QUALITY = 45
DEFAULT_DATABASE_URL = (
    "https://fridgemateai-325db-default-rtdb.firebaseio.com"
)


class DailyLimitExceeded(Exception):
    pass


class PhotoWeeklyLimitExceeded(Exception):
    pass


def _initialize_firebase():
    if firebase_admin._apps:
        return

    service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
    if not service_account_json:
        raise RuntimeError("Brak FIREBASE_SERVICE_ACCOUNT_JSON w srodowisku")

    service_account = json.loads(service_account_json)
    firebase_credential = credentials.Certificate(service_account)
    database_url = os.environ.get(
        "FIREBASE_DATABASE_URL",
        DEFAULT_DATABASE_URL,
    )
    firebase_admin.initialize_app(
        firebase_credential,
        {"databaseURL": database_url},
    )


def _get_authenticated_uid():
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise PermissionError("Brak tokenu autoryzacyjnego")

    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise PermissionError("Brak tokenu autoryzacyjnego")

    _initialize_firebase()
    decoded_token = auth.verify_id_token(token)
    return decoded_token["uid"]


def _usage_reference(uid):
    timezone_name = os.environ.get("GENERATION_TIMEZONE", "Europe/Warsaw")
    day_key = datetime.now(ZoneInfo(timezone_name)).strftime("%Y-%m-%d")
    return db.reference(f"generation_usage/{uid}/{day_key}")


def _reserve_generation(uid):
    usage_ref = _usage_reference(uid)

    def increment(current_value):
        current_count = int(current_value or 0)
        if current_count >= DAILY_GENERATION_LIMIT:
            raise DailyLimitExceeded()
        return current_count + 1

    used_count = int(usage_ref.transaction(increment))
    return DAILY_GENERATION_LIMIT - used_count


def _release_generation(uid):
    usage_ref = _usage_reference(uid)

    def decrement(current_value):
        current_count = int(current_value or 0)
        return max(0, current_count - 1)

    usage_ref.transaction(decrement)


def _photo_usage_reference(uid):
    timezone_name = os.environ.get("GENERATION_TIMEZONE", "Europe/Warsaw")
    now = datetime.now(ZoneInfo(timezone_name))
    iso_year, iso_week, _ = now.isocalendar()
    week_key = f"{iso_year}-W{iso_week:02d}"
    return db.reference(f"photo_generation_usage/{uid}/{week_key}")


def _reserve_photo_generation(uid):
    usage_ref = _photo_usage_reference(uid)

    def increment(current_value):
        current_count = int(current_value or 0)
        if current_count >= PHOTO_WEEKLY_GENERATION_LIMIT:
            raise PhotoWeeklyLimitExceeded()
        return current_count + 1

    used_count = int(usage_ref.transaction(increment))
    return PHOTO_WEEKLY_GENERATION_LIMIT - used_count


def _release_photo_generation(uid):
    usage_ref = _photo_usage_reference(uid)

    def decrement(current_value):
        current_count = int(current_value or 0)
        return max(0, current_count - 1)

    usage_ref.transaction(decrement)


def _clean_base64_image(image_base64):
    if "," in image_base64 and image_base64.strip().lower().startswith("data:"):
        return image_base64.split(",", 1)[1]

    return image_base64


def _compress_image_to_jpeg(image_base64):
    cleaned_image = _clean_base64_image(image_base64)

    try:
        image_bytes = base64.b64decode(cleaned_image, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("Nieprawidlowy format zdjecia") from error

    max_upload_bytes = int(os.environ.get(
        "PHOTO_MAX_UPLOAD_BYTES",
        PHOTO_MAX_UPLOAD_BYTES,
    ))
    if len(image_bytes) > max_upload_bytes:
        raise ValueError("Zdjecie jest za duze")

    try:
        image = Image.open(BytesIO(image_bytes))
        image = ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("Nie udalo sie odczytac zdjecia") from error

    max_side = int(os.environ.get("PHOTO_MAX_IMAGE_SIDE", PHOTO_MAX_IMAGE_SIDE))
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

    output = BytesIO()
    quality = int(os.environ.get("PHOTO_JPEG_QUALITY", PHOTO_JPEG_QUALITY))
    image.save(output, format="JPEG", quality=quality, optimize=True)
    return output.getvalue()


def _get_model(model_name=None):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Brak klucza w srodowisku")

    genai.configure(api_key=api_key)
    selected_model = model_name or os.environ.get(
        "GEMINI_MODEL",
        "gemini-3.1-flash-lite",
    )
    return genai.GenerativeModel(selected_model)


def _get_photo_model():
    return _get_model(
        os.environ.get("PHOTO_GEMINI_MODEL", "gemini-3.5-flash-lite"),
    )


def _parse_json_response(response):
    raw_text = response.text.strip()
    if "```" in raw_text:
        raw_text = raw_text.split("```")[1].replace("json", "").strip()

    return json.loads(raw_text)


def _authentication_error(error):
    return jsonify({"error": str(error), "remaining": 0}), 401


def _limit_error():
    return jsonify(
        {
            "error": "Wykorzystales dzisiejszy limit generowan.",
            "remaining": 0,
        }
    ), 403


def _photo_limit_error():
    return jsonify(
        {
            "error": "Wykorzystales tygodniowy limit generowan ze zdjecia.",
            "photoRemaining": 0,
            "photoLimit": PHOTO_WEEKLY_GENERATION_LIMIT,
        }
    ), 403


@app.route("/generation-status", methods=["GET"])
def generation_status():
    try:
        uid = _get_authenticated_uid()
        used_count = int(_usage_reference(uid).get() or 0)
        remaining = max(0, DAILY_GENERATION_LIMIT - used_count)
        return jsonify({"remaining": remaining, "limit": DAILY_GENERATION_LIMIT})
    except Exception as error:
        return _authentication_error(error)


@app.route("/photo-generation-status", methods=["GET"])
def photo_generation_status():
    try:
        uid = _get_authenticated_uid()
        used_count = int(_photo_usage_reference(uid).get() or 0)
        remaining = max(0, PHOTO_WEEKLY_GENERATION_LIMIT - used_count)
        return jsonify(
            {
                "photoRemaining": remaining,
                "photoLimit": PHOTO_WEEKLY_GENERATION_LIMIT,
            }
        )
    except Exception as error:
        return _authentication_error(error)


@app.route("/")
def hello():
    return "Serwer dziala!"


@app.route("/generate", methods=["POST"])
def generate_recipe():
    data = request.json or {}
    ingredients = data.get("ingredients", [])
    if not isinstance(ingredients, list) or not ingredients:
        return jsonify({"error": "Brak skladnikow"}), 400

    try:
        uid = _get_authenticated_uid()
        remaining = _reserve_generation(uid)
    except DailyLimitExceeded:
        return _limit_error()
    except Exception as error:
        return _authentication_error(error)

    try:
        model = _get_model()
        prompt = (
            f"Napisz przepis z: {', '.join(ingredients)}. "
            "Przepis powinien byc w tym samym jezyku, w ktorym napisano "
            "skladniki. Zwroc tylko JSON bez markdown: "
            "{\"title\": \"\", \"description\": \"\", \"steps\": []}"
        )

        response = model.generate_content(prompt)
        parsed = _parse_json_response(response)
        parsed["remaining"] = remaining
        return jsonify(parsed)
    except Exception as error:
        _release_generation(uid)
        return jsonify({"error": str(error)}), 500


@app.route("/generate-craving", methods=["POST"])
def generate_craving_recipe():
    data = request.json or {}
    craving = str(data.get("craving", "")).strip()
    include_shopping_list = bool(data.get("includeShoppingList", True))
    available_ingredients = data.get("availableIngredients", [])

    if not craving:
        return jsonify({"error": "Brak zachcianki uzytkownika"}), 400
    if not isinstance(available_ingredients, list):
        return jsonify({"error": "Nieprawidlowa lista skladnikow"}), 400

    try:
        uid = _get_authenticated_uid()
        remaining = _reserve_generation(uid)
    except DailyLimitExceeded:
        return _limit_error()
    except Exception as error:
        return _authentication_error(error)

    try:
        model = _get_model()
        owned_text = (
            ", ".join(available_ingredients)
            if available_ingredients
            else "nic nie podano"
        )
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

Zwroc tylko poprawny JSON bez markdown i bez dodatkowego tekstu:
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
        parsed["remaining"] = remaining
        return jsonify(parsed)
    except Exception as error:
        _release_generation(uid)
        return jsonify({"error": str(error)}), 500


@app.route("/generate-photo", methods=["POST"])
def generate_photo_recipe():
    data = request.json or {}
    image_base64 = str(data.get("imageBase64", "")).strip()
    description = str(data.get("description", "")).strip()

    if not image_base64:
        return jsonify({"error": "Brak zdjecia"}), 400

    try:
        compressed_image = _compress_image_to_jpeg(image_base64)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    try:
        uid = _get_authenticated_uid()
        photo_remaining = _reserve_photo_generation(uid)
    except PhotoWeeklyLimitExceeded:
        return _photo_limit_error()
    except Exception as error:
        return _authentication_error(error)

    try:
        model = _get_photo_model()
        user_instruction = (
            f"Dodatkowa prosba uzytkownika: {description}."
            if description
            else "Uzytkownik nie podal dodatkowego opisu."
        )

        prompt = f"""
Na zdjeciu widac produkty spozywcze lub danie.
Rozpoznaj skladniki widoczne na zdjeciu i stworz praktyczny, zdrowy przepis.
{user_instruction}

Jesli czegos nie da sie rozpoznac ze zdjecia, nie wymyslaj zbyt wielu szczegolow.
Mozesz dodac 2-5 prostych skladnikow do shoppingList, jesli sa potrzebne.
Dodaj orientacyjne skladniki odzywcze dla jednej porcji.
Odpowiedz w tym samym jezyku, w ktorym napisano dodatkowy opis.
Jesli opis jest pusty, odpowiedz po polsku.

Zwroc tylko poprawny JSON bez markdown i bez dodatkowego tekstu:
{{
  "title": "",
  "description": "",
  "detectedIngredients": [],
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

        response = model.generate_content(
            [
                prompt,
                {
                    "mime_type": "image/jpeg",
                    "data": compressed_image,
                },
            ]
        )
        parsed = _parse_json_response(response)
        parsed.setdefault("detectedIngredients", [])
        parsed.setdefault("shoppingList", [])
        parsed.setdefault("nutrition", {})
        parsed.setdefault("steps", [])
        parsed.setdefault("description", "")
        parsed["photoRemaining"] = photo_remaining
        parsed["photoLimit"] = PHOTO_WEEKLY_GENERATION_LIMIT
        return jsonify(parsed)
    except Exception as error:
        _release_photo_generation(uid)
        return jsonify({"error": str(error)}), 500


if __name__ == "__main__":
    app.run()
