# FridgeServer

Serverless API dla FridgeMateAI.

## Endpointy

- `GET /generation-status` - dzienny limit generowania tekstowego.
- `POST /generate` - przepis z listy skladnikow.
- `POST /generate-craving` - przepis pod zachcianke.
- `GET /admob-reward-callback` - callback AdMob SSV, ktory przyznaje bonusowe generowanie po obejrzeniu reklamy.
- `GET /photo-generation-status` - tygodniowy limit generowania ze zdjec.
- `POST /generate-photo` - przepis ze skladnikow widocznych na zdjeciu.

## Bonus za reklame AdMob

Rewarded ad musi miec wlaczone Server-side verification w panelu AdMob.
Domyslne testowe ID reklam w aplikacji sluza tylko do wyswietlenia reklamy testowej. Aby bonus realnie dopisywal sie na serwerze, uzyj wlasnej jednostki rewarded ad z AdMob i ustaw dla niej callback SSV ponizej.

Callback URL:

```text
https://fridge-mate-ai-server.vercel.app/admob-reward-callback
```

Aplikacja przekazuje do AdMob `user_id` jako Firebase UID oraz `custom_data` jako `recipe_generation`.
Serwer weryfikuje podpis callbacka AdMob publicznymi kluczami Google, sprawdza unikalny `transaction_id`, a dopiero potem dopisuje jedno bonusowe generowanie w Firebase pod `rewarded_generation_balance/{uid}`.

Bonus:

- dziala tylko dla tekstowych generowan przepisu,
- jest jednorazowy,
- maksymalnie 1 niewykorzystany bonus moze czekac na koncie,
- zostaje zuzyty dopiero, gdy dzienny limit `2` jest wyczerpany.

## Generowanie ze zdjecia

`POST /generate-photo` wymaga zalogowanego uzytkownika Firebase i naglowka:

```http
Authorization: Bearer <firebase_id_token>
Content-Type: application/json
```

Body:

```json
{
  "imageBase64": "<base64 albo data URL>",
  "description": "Opcjonalny opis, np. Zrob z tych rzeczy przepis na ciasto"
}
```

Serwer automatycznie kompresuje zdjecie do JPEG przed wyslaniem do OpenAI:

- `PHOTO_MAX_IMAGE_SIDE` domyslnie `640`.
- `PHOTO_JPEG_QUALITY` domyslnie `45`.
- `PHOTO_MAX_UPLOAD_BYTES` domyslnie `3145728`.

Limit zdjec: `5` generowan na tydzien na konto Firebase. Licznik zapisuje sie w Realtime Database pod `photo_generation_usage/{uid}/{YYYY-Www}` i resetuje sie automatycznie po zmianie tygodnia.

## Zmienne srodowiskowe

- `OPENAI_API_KEY` - klucz API OpenAI (wymagany).
- `OPENAI_MODEL` - opcjonalny model, domyslnie `gpt-6-luna`.
- `FIREBASE_SERVICE_ACCOUNT_JSON` - JSON konta serwisowego Firebase.
- `FIREBASE_DATABASE_URL` - opcjonalnie URL Realtime Database.
- `GENERATION_TIMEZONE` - opcjonalnie, domyslnie `Europe/Warsaw`.
- `ADMOB_REWARDED_AD_UNIT_ID` - opcjonalnie oczekiwany rewarded ad unit ID w callbacku SSV.
- `ADMOB_REWARD_CUSTOM_DATA` - opcjonalnie, domyslnie `recipe_generation`.
- `ADMOB_VERIFIER_KEYS_URL` - opcjonalnie, domyslnie publiczne klucze Google AdMob.
