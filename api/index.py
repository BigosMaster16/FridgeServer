import base64
import binascii
import json
import os
from datetime import datetime
from io import BytesIO
from urllib.parse import parse_qs
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import firebase_admin
import google.generativeai as genai
from firebase_admin import auth, credentials, db
from flask import Flask, Response, jsonify, request
from flask_cors import CORS
from PIL import Image, ImageOps, UnidentifiedImageError

app = Flask(__name__)
CORS(app)

DAILY_GENERATION_LIMIT = 2
MAX_REWARDED_GENERATION_BALANCE = 1
ADMOB_VERIFIER_KEYS_URL = "https://www.gstatic.com/admob/reward/verifier-keys.json"
PHOTO_WEEKLY_GENERATION_LIMIT = 5
PHOTO_MAX_UPLOAD_BYTES = 3 * 1024 * 1024
PHOTO_MAX_IMAGE_SIDE = 640
PHOTO_JPEG_QUALITY = 45
# Set to True temporarily when the public health page is needed for debugging.
STRONA_HEALTH_WLACZONA = False
DEFAULT_DATABASE_URL = (
    "https://fridgemateai-325db-default-rtdb.firebaseio.com"
)


class DailyLimitExceeded(Exception):
    pass


class PhotoWeeklyLimitExceeded(Exception):
    pass


class DuplicateRewardTransaction(Exception):
    pass


FIREBASE_WEB_CONFIG = json.dumps(
    {
        "apiKey": "AIzaSyDcMNFLNUovqKhtzYJE9M__9rObhR9hMpA",
        "authDomain": "fridgemateai-325db.firebaseapp.com",
        "projectId": "fridgemateai-325db",
        "storageBucket": "fridgemateai-325db.firebasestorage.app",
        "messagingSenderId": "18764183102",
        "appId": "1:18764183102:android:99d3430a6c0c19497b036f",
    }
)


DELETE_ACCOUNT_PAGE = r"""<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Usun konto | FridgeMate</title>
  <script src="https://www.gstatic.com/firebasejs/10.14.1/firebase-app-compat.js"></script>
  <script src="https://www.gstatic.com/firebasejs/10.14.1/firebase-auth-compat.js"></script>
  <style>
    :root { color-scheme: light; font-family: Georgia, serif; }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh; color: #1f2a22;
      background: radial-gradient(circle at 12% 8%, #dbead2 0 16%, transparent 38%),
        linear-gradient(135deg, #f7f1e3, #fffaf1 56%, #e8f2df);
      display: grid; place-items: center; padding: 24px;
    }
    main { width: min(100%, 500px); }
    .brand { text-align: center; color: #1f5c3f; font-size: 18px; font-weight: 700; letter-spacing: .08em; margin-bottom: 10px; }
    .language-wrap { display: flex; justify-content: center; margin-bottom: 18px; }
    select { border: 1px solid #dce6d5; border-radius: 999px; padding: 8px 14px; color: #2f6040; background: rgba(255,255,255,.86); font: inherit; cursor: pointer; }
    .card { background: rgba(255,255,255,.92); border: 1px solid rgba(255,255,255,.8); border-radius: 30px; padding: clamp(24px, 6vw, 42px); box-shadow: 0 24px 60px rgba(32,70,50,.14); }
    h1 { margin: 0 0 12px; font-size: clamp(27px, 6vw, 38px); line-height: 1.1; }
    .lead { color: #5c665f; line-height: 1.55; margin: 0 0 26px; }
    label { display: block; color: #46524a; font-size: 14px; font-weight: 700; margin: 14px 0 7px; }
    input { width: 100%; border: 1px solid #dce6d5; border-radius: 16px; padding: 15px 16px; font: inherit; font-size: 16px; background: #fffdf8; outline: none; }
    input:focus { border-color: #2f7a4a; box-shadow: 0 0 0 3px rgba(47,122,74,.12); }
    button { width: 100%; border: 0; border-radius: 17px; padding: 15px 18px; margin-top: 16px; font: inherit; font-weight: 700; font-size: 16px; cursor: pointer; background: #2f7a4a; color: white; }
    button:hover { filter: brightness(.96); }
    button:disabled { opacity: .55; cursor: wait; }
    .google { background: #fff; color: #1f2a22; border: 1px solid #dce6d5; }
    .danger { background: #b5542f; }
    .divider { display: flex; align-items: center; gap: 12px; color: #8a958d; margin: 20px 0 4px; font-size: 13px; }
    .divider:before, .divider:after { content: ''; height: 1px; background: #e5ebe1; flex: 1; }
    .account { background: #eef6e9; border-radius: 18px; padding: 15px; margin: 20px 0; color: #2f6040; line-height: 1.45; overflow-wrap: anywhere; }
    .warning { background: #fff3ec; color: #71351f; border: 1px solid #f1c2aa; border-radius: 18px; padding: 15px; line-height: 1.45; margin-top: 20px; }
    .hint, .message { color: #68736b; font-size: 14px; line-height: 1.45; margin-top: 14px; }
    .message.error { color: #a44225; }
    .message.success { color: #2f7a4a; font-weight: 700; }
    .hidden { display: none !important; }
  </style>
</head>
<body>
  <main>
    <div class="brand">FRIDGEMATE AI</div>
    <div class="language-wrap">
      <select id="languageSelect" aria-label="Language">
        <option value="pl">Polski</option>
        <option value="en">English</option>
        <option value="es">Español</option>
      </select>
    </div>
    <section class="card">
      <div id="loginPanel">
        <h1 data-i18n="loginTitle">Usun swoje konto</h1>
        <p class="lead" data-i18n="loginLead">Zaloguj się na konto FridgeMate AI, aby trwale usunąć konto i dane zapisane na serwerze.</p>
        <form id="loginForm">
          <label for="email" data-i18n="emailLabel">Email</label>
          <input id="email" type="email" autocomplete="email" required data-placeholder="emailPlaceholder">
          <label for="password" data-i18n="passwordLabel">Hasło</label>
          <input id="password" type="password" autocomplete="current-password" required data-placeholder="passwordPlaceholder">
          <button id="emailButton" type="submit" data-i18n="emailLogin">Zaloguj się przez email</button>
        </form>
        <div class="divider" data-i18n="or">lub</div>
        <button id="googleButton" class="google" type="button" data-i18n="googleLogin">Zaloguj się przez Google</button>
        <p id="loginMessage" class="message error"></p>
      </div>

      <div id="deletePanel" class="hidden">
        <h1 data-i18n="deleteTitle">Usunąć konto?</h1>
        <p class="lead" data-i18n="deleteLead">Ta operacja jest nieodwracalna. Usunięte zostaną konto logowania, limity generowań i dane zapisane na serwerze.</p>
        <div class="account"><span data-i18n="loggedAccount">Zalogowane konto:</span><br><strong id="accountEmail"></strong></div>
        <div class="warning"><strong data-i18n="warningTitle">Uwaga:</strong> <span data-i18n="warningText">po usunięciu nie będzie można odzyskać tego konta ani jego danych.</span></div>
        <label for="confirmation" data-i18n="confirmationLabel">Wpisz USUN, aby potwierdzić</label>
        <input id="confirmation" autocomplete="off" spellcheck="false">
        <button id="deleteButton" class="danger" type="button" disabled data-i18n="deleteButton">Trwale usuń konto</button>
        <button id="logoutButton" class="google" type="button" data-i18n="logoutButton">Wyloguj</button>
        <p id="deleteMessage" class="message"></p>
      </div>
    </section>
  </main>
  <script>
    const translations = {
      pl: {
        loginTitle: 'Usun swoje konto', loginLead: 'Zaloguj się na konto FridgeMate AI, aby trwale usunąć konto i dane zapisane na serwerze.',
        emailLabel: 'Email', emailPlaceholder: 'Wpisz email', passwordLabel: 'Hasło', passwordPlaceholder: 'Wpisz hasło',
        emailLogin: 'Zaloguj się przez email', googleLogin: 'Zaloguj się przez Google', or: 'lub',
        deleteTitle: 'Usunąć konto?', deleteLead: 'Ta operacja jest nieodwracalna. Usunięte zostaną konto logowania, limity generowań i dane zapisane na serwerze.',
        loggedAccount: 'Zalogowane konto:', warningTitle: 'Uwaga:', warningText: 'po usunięciu nie będzie można odzyskać tego konta ani jego danych.',
        confirmationLabel: 'Wpisz USUN, aby potwierdzić', confirmationWord: 'USUN', deleteButton: 'Trwale usuń konto', logoutButton: 'Wyloguj',
        loggingIn: 'Logowanie...', googleOpening: 'Otwieranie Google...', deleting: 'Usuwanie...',
        loginError: 'Nie udało się zalogować. Sprawdź email i hasło.', googleError: 'Nie udało się zalogować przez Google. Sprawdź dozwolone domeny Firebase.',
        deletingMessage: 'Usuwanie konta...', deleteError: 'Nie udało się usunąć konta.', deleted: 'Konto zostało trwale usunięte.'
      },
      en: {
        loginTitle: 'Delete your account', loginLead: 'Sign in to your FridgeMate AI account to permanently delete your account and data stored on the server.',
        emailLabel: 'Email', emailPlaceholder: 'Enter your email', passwordLabel: 'Password', passwordPlaceholder: 'Enter your password',
        emailLogin: 'Sign in with email', googleLogin: 'Sign in with Google', or: 'or',
        deleteTitle: 'Delete account?', deleteLead: 'This action cannot be undone. Your sign-in account, generation limits and server data will be deleted.',
        loggedAccount: 'Signed-in account:', warningTitle: 'Warning:', warningText: 'this account and its data cannot be recovered after deletion.',
        confirmationLabel: 'Type DELETE to confirm', confirmationWord: 'DELETE', deleteButton: 'Permanently delete account', logoutButton: 'Sign out',
        loggingIn: 'Signing in...', googleOpening: 'Opening Google...', deleting: 'Deleting...',
        loginError: 'Could not sign in. Check your email and password.', googleError: 'Could not sign in with Google. Check Firebase authorized domains.',
        deletingMessage: 'Deleting account...', deleteError: 'Could not delete the account.', deleted: 'Your account was permanently deleted.'
      },
      es: {
        loginTitle: 'Eliminar tu cuenta', loginLead: 'Inicia sesión en tu cuenta de FridgeMate AI para eliminar permanentemente tu cuenta y los datos del servidor.',
        emailLabel: 'Correo electrónico', emailPlaceholder: 'Escribe tu correo', passwordLabel: 'Contraseña', passwordPlaceholder: 'Escribe tu contraseña',
        emailLogin: 'Iniciar sesión con correo', googleLogin: 'Iniciar sesión con Google', or: 'o',
        deleteTitle: '¿Eliminar la cuenta?', deleteLead: 'Esta acción no se puede deshacer. Se eliminarán tu cuenta, los límites de generación y los datos del servidor.',
        loggedAccount: 'Cuenta conectada:', warningTitle: 'Atención:', warningText: 'después de eliminarla, la cuenta y sus datos no se podrán recuperar.',
        confirmationLabel: 'Escribe ELIMINAR para confirmar', confirmationWord: 'ELIMINAR', deleteButton: 'Eliminar cuenta permanentemente', logoutButton: 'Cerrar sesión',
        loggingIn: 'Iniciando sesión...', googleOpening: 'Abriendo Google...', deleting: 'Eliminando...',
        loginError: 'No se pudo iniciar sesión. Comprueba tu correo y contraseña.', googleError: 'No se pudo iniciar sesión con Google. Comprueba los dominios autorizados de Firebase.',
        deletingMessage: 'Eliminando la cuenta...', deleteError: 'No se pudo eliminar la cuenta.', deleted: 'Tu cuenta se eliminó permanentemente.'
      }
    };
    let language = localStorage.getItem('fridgemate-delete-language') || (navigator.language || 'pl').slice(0, 2);
    if (!translations[language]) language = 'pl';
    const t = (key) => translations[language][key] || translations.pl[key] || key;
    const languageSelect = document.getElementById('languageSelect');
    const applyLanguage = (nextLanguage) => {
      language = translations[nextLanguage] ? nextLanguage : 'pl';
      localStorage.setItem('fridgemate-delete-language', language);
      languageSelect.value = language;
      document.documentElement.lang = language;
      document.querySelectorAll('[data-i18n]').forEach((element) => { element.textContent = t(element.dataset.i18n); });
      document.querySelectorAll('[data-placeholder]').forEach((element) => { element.placeholder = t(element.dataset.placeholder); });
    };
    languageSelect.addEventListener('change', () => applyLanguage(languageSelect.value));
    applyLanguage(language);
    firebase.initializeApp(__FIREBASE_CONFIG__);
    const auth = firebase.auth();
    const loginPanel = document.getElementById('loginPanel');
    const deletePanel = document.getElementById('deletePanel');
    const loginForm = document.getElementById('loginForm');
    const loginMessage = document.getElementById('loginMessage');
    const deleteMessage = document.getElementById('deleteMessage');
    const confirmation = document.getElementById('confirmation');
    const deleteButton = document.getElementById('deleteButton');
    const setMessage = (element, message, success = false) => {
      element.textContent = message || '';
      element.className = `message ${success ? 'success' : 'error'}`;
    };
    const setBusy = (button, busy, label) => {
      button.disabled = busy;
      if (busy) button.dataset.label = button.textContent;
      button.textContent = busy ? label : (button.dataset.label || button.textContent);
    };

    let deletionSucceeded = false;
    auth.onAuthStateChanged((user) => {
      loginPanel.classList.toggle('hidden', !!user || deletionSucceeded);
      deletePanel.classList.toggle('hidden', !user && !deletionSucceeded);
      if (user && !deletionSucceeded) document.getElementById('accountEmail').textContent = user.email || 'Konto Google';
    });

    loginForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      setMessage(loginMessage, '');
      const button = document.getElementById('emailButton');
      setBusy(button, true, t('loggingIn'));
      try {
        await auth.signInWithEmailAndPassword(document.getElementById('email').value.trim(), document.getElementById('password').value);
      } catch (error) {
        setMessage(loginMessage, t('loginError'));
      } finally { setBusy(button, false, t('emailLogin')); }
    });

    document.getElementById('googleButton').addEventListener('click', async () => {
      const button = document.getElementById('googleButton');
      setBusy(button, true, t('googleOpening'));
      try { await auth.signInWithPopup(new firebase.auth.GoogleAuthProvider()); }
      catch (error) { setMessage(loginMessage, t('googleError')); }
      finally { setBusy(button, false, t('googleLogin')); }
    });

    confirmation.addEventListener('input', () => { deleteButton.disabled = confirmation.value.trim().toUpperCase() !== t('confirmationWord'); });
    deleteButton.addEventListener('click', async () => {
      const user = auth.currentUser;
      if (!user || confirmation.value.trim().toUpperCase() !== t('confirmationWord')) return;
      setMessage(deleteMessage, t('deletingMessage'));
      setBusy(deleteButton, true, t('deleting'));
      try {
        const token = await user.getIdToken(true);
        const response = await fetch('/delete-account', { method: 'DELETE', headers: { 'Authorization': `Bearer ${token}` } });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || t('deleteError'));
        deletionSucceeded = true;
        setMessage(deleteMessage, t('deleted'), true);
        setBusy(deleteButton, false, t('deleteButton'));
        deleteButton.disabled = true;
        document.getElementById('logoutButton').disabled = true;
        try { await auth.signOut(); } catch (_) { /* Account is already deleted. */ }
      } catch (error) {
        setMessage(deleteMessage, error.message || t('deleteError'));
        setBusy(deleteButton, false, t('deleteButton'));
      }
    });
    document.getElementById('logoutButton').addEventListener('click', () => auth.signOut());
  </script>
</body>
</html>"""


DELETE_ACCOUNT_PAGE = DELETE_ACCOUNT_PAGE.replace(
    "__FIREBASE_CONFIG__",
    FIREBASE_WEB_CONFIG,
)


PRIVACY_POLICY_PAGE = r"""<!doctype html>
<html lang="pl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Polityka prywatności | FridgeMate</title>
  <style>
    :root { color-scheme: light; font-family: Georgia, serif; }
    * { box-sizing: border-box; }
    body {
      margin: 0; min-height: 100vh; color: #1f2a22;
      background: radial-gradient(circle at 12% 8%, #dbead2 0 16%, transparent 38%),
        linear-gradient(135deg, #f7f1e3, #fffaf1 56%, #e8f2df);
      display: grid; place-items: center; padding: 24px;
    }
    main { width: min(100%, 680px); }
    .brand { text-align: center; color: #1f5c3f; font-size: 18px; font-weight: 700; letter-spacing: .08em; margin-bottom: 18px; }
    .card { background: rgba(255,255,255,.92); border: 1px solid rgba(255,255,255,.8); border-radius: 30px; padding: clamp(26px, 6vw, 48px); box-shadow: 0 24px 60px rgba(32,70,50,.14); }
    .badge { display: inline-block; background: #e3f0d9; color: #2f6040; border-radius: 999px; padding: 8px 13px; font-size: 13px; font-weight: 700; letter-spacing: .03em; margin-bottom: 20px; }
    h1 { margin: 0 0 16px; font-size: clamp(30px, 6vw, 44px); line-height: 1.1; }
    p { color: #5c665f; font-size: 17px; line-height: 1.65; margin: 0; }
    .note { margin-top: 26px; padding: 18px 20px; border-radius: 20px; background: #fff3ec; border: 1px solid #f1c2aa; color: #71351f; line-height: 1.5; }
    .footer { margin-top: 24px; text-align: center; color: #7a857d; font-size: 13px; }
  </style>
</head>
<body>
  <main>
    <div class="brand">FRIDGEMATE AI</div>
    <section class="card">
      <div class="badge">INFORMACJE</div>
      <h1>Polityka prywatności</h1>
      <p>Dbamy o przejrzystość i bezpieczeństwo korzystania z FridgeMate AI.</p>
      <div class="note">Tu będzie później dostępna pełna polityka prywatności aplikacji.</div>
    </section>
    <div class="footer">FridgeMate AI</div>
  </main>
</body>
</html>"""


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
    # Checking revocation also makes tokens from deleted accounts unusable
    # immediately instead of trusting a locally cached Firebase session.
    decoded_token = auth.verify_id_token(token, check_revoked=True)
    return decoded_token["uid"]


def _usage_reference(uid):
    timezone_name = os.environ.get("GENERATION_TIMEZONE", "Europe/Warsaw")
    day_key = datetime.now(ZoneInfo(timezone_name)).strftime("%Y-%m-%d")
    return db.reference(f"generation_usage/{uid}/{day_key}")


def _rewarded_generation_reference(uid):
    return db.reference(f"rewarded_generation_balance/{uid}")


def _reward_transaction_reference(transaction_id):
    return db.reference(f"admob_reward_transactions/{transaction_id}")


def _delete_account_data(uid):
    """Remove every server-side record that is owned by one Firebase user."""
    root_reference = db.reference()
    root_reference.update(
        {
            f"generation_usage/{uid}": None,
            f"photo_generation_usage/{uid}": None,
            f"rewarded_generation_balance/{uid}": None,
        }
    )

    # Reward transactions are keyed by AdMob transaction ID, so remove only
    # records whose owner is the account being deleted.
    transactions_reference = db.reference("admob_reward_transactions")
    transactions = transactions_reference.get() or {}
    transaction_deletions = {
        transaction_id: None
        for transaction_id, value in transactions.items()
        if isinstance(value, dict) and value.get("uid") == uid
    }
    if transaction_deletions:
        transactions_reference.update(transaction_deletions)


def _reserve_generation(uid):
    usage_ref = _usage_reference(uid)

    def increment(current_value):
        current_count = int(current_value or 0)
        if current_count >= DAILY_GENERATION_LIMIT:
            raise DailyLimitExceeded()
        return current_count + 1

    try:
        used_count = int(usage_ref.transaction(increment))
        daily_remaining = max(0, DAILY_GENERATION_LIMIT - used_count)
        rewarded_remaining = _get_rewarded_generation_balance(uid)
        return {
            "remaining": daily_remaining + rewarded_remaining,
            "rewardedRemaining": rewarded_remaining,
            "usedRewarded": False,
        }
    except DailyLimitExceeded:
        pass

    reward_ref = _rewarded_generation_reference(uid)

    def consume_reward(current_value):
        current_count = int(current_value or 0)
        if current_count <= 0:
            raise DailyLimitExceeded()
        return current_count - 1

    rewarded_remaining = int(reward_ref.transaction(consume_reward))
    return {
        "remaining": rewarded_remaining,
        "rewardedRemaining": rewarded_remaining,
        "usedRewarded": True,
    }


def _release_generation(uid, used_rewarded=False):
    if used_rewarded:
        reward_ref = _rewarded_generation_reference(uid)

        def restore_reward(current_value):
            current_count = int(current_value or 0)
            return min(MAX_REWARDED_GENERATION_BALANCE, current_count + 1)

        reward_ref.transaction(restore_reward)
        return

    usage_ref = _usage_reference(uid)

    def decrement_daily(current_value):
        current_count = int(current_value or 0)
        return max(0, current_count - 1)

    usage_ref.transaction(decrement_daily)


def _get_rewarded_generation_balance(uid):
    return int(_rewarded_generation_reference(uid).get() or 0)


def _grant_rewarded_generation(uid):
    reward_ref = _rewarded_generation_reference(uid)

    def grant(current_value):
        current_count = int(current_value or 0)
        return min(MAX_REWARDED_GENERATION_BALANCE, current_count + 1)

    return int(reward_ref.transaction(grant))


def _base64_url_decode(value):
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _fetch_admob_public_keys():
    from cryptography.hazmat.primitives import serialization

    keys_url = os.environ.get("ADMOB_VERIFIER_KEYS_URL", ADMOB_VERIFIER_KEYS_URL)
    with urlopen(keys_url, timeout=5) as response:
        payload = response.read().decode("utf-8")

    keys = {}
    for key in json.loads(payload).get("keys", []):
        key_id = str(key.get("keyId"))
        key_bytes = base64.b64decode(key.get("base64", ""))
        keys[key_id] = serialization.load_der_public_key(key_bytes)

    return keys


def _verify_admob_reward_callback():
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec

    query_bytes = request.query_string
    signature_marker = b"&signature="
    signature_index = query_bytes.find(signature_marker)
    if signature_index <= 0:
        raise PermissionError("Brak podpisu AdMob")

    signed_data = query_bytes[:signature_index]
    query = parse_qs(query_bytes.decode("utf-8"), keep_blank_values=True)
    signature = query.get("signature", [""])[0]
    key_id = query.get("key_id", [""])[0]
    transaction_id = query.get("transaction_id", [""])[0]
    uid = query.get("user_id", [""])[0]
    custom_data = query.get("custom_data", [""])[0]
    ad_unit = query.get("ad_unit", [""])[0]

    if not signature or not key_id or not transaction_id or not uid:
        raise PermissionError("Niepelny callback AdMob")

    expected_custom_data = os.environ.get(
        "ADMOB_REWARD_CUSTOM_DATA",
        "recipe_generation",
    )
    if custom_data and custom_data != expected_custom_data:
        raise PermissionError("Nieprawidlowe custom_data AdMob")

    expected_ad_unit = os.environ.get("ADMOB_REWARDED_AD_UNIT_ID")
    if expected_ad_unit and ad_unit != expected_ad_unit:
        raise PermissionError("Nieprawidlowa jednostka reklamy AdMob")

    public_key = _fetch_admob_public_keys().get(key_id)
    if public_key is None:
        raise PermissionError("Nieznany klucz AdMob")

    try:
        public_key.verify(
            _base64_url_decode(signature),
            signed_data,
            ec.ECDSA(hashes.SHA256()),
        )
    except InvalidSignature as error:
        raise PermissionError("Nieprawidlowy podpis AdMob") from error

    return uid, transaction_id


def _mark_reward_transaction(transaction_id, uid):
    transaction_ref = _reward_transaction_reference(transaction_id)

    def reserve(current_value):
        if current_value:
            raise DuplicateRewardTransaction()

        return {
            "uid": uid,
            "createdAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }

    transaction_ref.transaction(reserve)


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
        daily_remaining = max(0, DAILY_GENERATION_LIMIT - used_count)
        rewarded_remaining = _get_rewarded_generation_balance(uid)
        return jsonify(
            {
                "remaining": daily_remaining + rewarded_remaining,
                "dailyRemaining": daily_remaining,
                "rewardedRemaining": rewarded_remaining,
                "limit": DAILY_GENERATION_LIMIT,
            }
        )
    except Exception as error:
        return _authentication_error(error)


@app.route("/admob-reward-callback", methods=["GET"])
def admob_reward_callback():
    try:
        _initialize_firebase()
        uid, transaction_id = _verify_admob_reward_callback()
        _mark_reward_transaction(transaction_id, uid)
        rewarded_remaining = _grant_rewarded_generation(uid)
        return jsonify(
            {
                "status": "ok",
                "rewardedRemaining": rewarded_remaining,
            }
        )
    except DuplicateRewardTransaction:
        return jsonify({"status": "duplicate"}), 200
    except Exception as error:
        return jsonify({"error": str(error)}), 403


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


@app.route("/health", methods=["GET"])
def health():
    if not STRONA_HEALTH_WLACZONA:
        return jsonify({"error": "Not Found"}), 404

    checks = {
        "ok": True,
        "firebaseServiceAccountJson": bool(
            os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON")
        ),
        "geminiApiKey": bool(os.environ.get("GEMINI_API_KEY")),
        "firebaseDatabaseUrl": os.environ.get(
            "FIREBASE_DATABASE_URL",
            DEFAULT_DATABASE_URL,
        ),
        "geminiModel": os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        "photoGeminiModel": os.environ.get(
            "PHOTO_GEMINI_MODEL",
            "gemini-3.5-flash-lite",
        ),
    }

    try:
        import PIL  # noqa: F401

        checks["pillow"] = True
    except Exception as error:
        checks["ok"] = False
        checks["pillow"] = str(error)

    try:
        import cryptography  # noqa: F401

        checks["cryptography"] = True
    except Exception as error:
        checks["cryptography"] = str(error)

    try:
        _initialize_firebase()
        checks["firebase"] = True
    except Exception as error:
        checks["ok"] = False
        checks["firebase"] = str(error)

    return jsonify(checks), 200 if checks["ok"] else 500


@app.route("/delete-account", methods=["GET"])
def delete_account_page():
    return Response(DELETE_ACCOUNT_PAGE, mimetype="text/html")


@app.route("/privacy-policy", methods=["GET"])
def privacy_policy_page():
    return Response(PRIVACY_POLICY_PAGE, mimetype="text/html")


@app.route("/delete-account", methods=["DELETE"])
def delete_account():
    try:
        uid = _get_authenticated_uid()
    except Exception as error:
        app.logger.exception("Nie udalo sie potwierdzic konta do usuniecia")
        return jsonify(
            {
                "error": "Nie udalo sie potwierdzic konta.",
                "errorCode": "account-authentication-failed",
            }
        ), 401

    try:
        _delete_account_data(uid)
    except Exception as error:
        app.logger.exception("Nie udalo sie usunac danych konta")
        return jsonify(
            {
                "error": "Nie udalo sie usunac danych konta.",
                "errorCode": "account-data-delete-failed",
            }
        ), 500

    try:
        try:
            auth.delete_user(uid)
        except auth.UserNotFoundError:
            # A previous request may have deleted Auth successfully but lost
            # its response before the app could sign out locally.
            pass
        return jsonify({"status": "deleted"})
    except Exception as error:
        app.logger.exception("Nie udalo sie usunac konta")
        return jsonify(
            {
                "error": "Nie udalo sie usunac konta.",
                "errorCode": "firebase-auth-delete-failed",
            }
        ), 500


@app.route("/generate", methods=["POST"])
def generate_recipe():
    data = request.json or {}
    ingredients = data.get("ingredients", [])
    if not isinstance(ingredients, list) or not ingredients:
        return jsonify({"error": "Brak skladnikow"}), 400

    try:
        uid = _get_authenticated_uid()
        reservation = _reserve_generation(uid)
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
        parsed["remaining"] = reservation["remaining"]
        parsed["rewardedRemaining"] = reservation["rewardedRemaining"]
        return jsonify(parsed)
    except Exception as error:
        _release_generation(uid, reservation["usedRewarded"])
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
        reservation = _reserve_generation(uid)
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
        parsed["remaining"] = reservation["remaining"]
        parsed["rewardedRemaining"] = reservation["rewardedRemaining"]
        return jsonify(parsed)
    except Exception as error:
        _release_generation(uid, reservation["usedRewarded"])
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
