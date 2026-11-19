import base64
import json
import os
import sys
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "api"))

# Endpoint tests replace Firebase-facing helpers and never contact Firebase.
if "flask_cors" not in sys.modules:
    try:
        import flask_cors  # noqa: F401
    except ModuleNotFoundError:
        flask_cors = types.ModuleType("flask_cors")
        flask_cors.CORS = lambda _app: None
        sys.modules["flask_cors"] = flask_cors

if "firebase_admin" not in sys.modules:
    firebase_admin = types.ModuleType("firebase_admin")
    firebase_admin._apps = {}
    firebase_admin.initialize_app = Mock()
    auth = types.ModuleType("firebase_admin.auth")
    credentials = types.ModuleType("firebase_admin.credentials")
    credentials.Certificate = Mock()
    db = types.ModuleType("firebase_admin.db")
    db.reference = Mock()
    firebase_admin.auth = auth
    firebase_admin.credentials = credentials
    firebase_admin.db = db
    sys.modules.update({
        "firebase_admin": firebase_admin,
        "firebase_admin.auth": auth,
        "firebase_admin.credentials": credentials,
        "firebase_admin.db": db,
    })

import index


class FakeResponse:
    def __init__(self, text="", status="completed", output=None):
        self.output_text = text
        self.status = status
        self.output = output or []


class FakeOpenAIClient:
    def __init__(self, response):
        self.responses = self
        self.response = response
        self.last_request = None

    def create(self, **kwargs):
        self.last_request = kwargs
        return self.response


def recipe():
    return {"title": "Zupa", "description": "Lekka", "steps": ["Ugotuj."]}


def nutrition():
    return {"kcal": "250", "protein": "10 g", "carbs": "30 g", "fat": "8 g", "fiber": "4 g"}


def craving_recipe():
    return {**recipe(), "shoppingList": [], "nutrition": nutrition()}


def photo_recipe():
    return {**craving_recipe(), "detectedIngredients": ["pomidor"]}


class OpenAIMigrationTests(unittest.TestCase):
    def setUp(self):
        self.client = index.app.test_client()
        self.auth = patch.object(index, "_get_authenticated_uid", return_value="test-uid")
        self.auth.start()
        self.addCleanup(self.auth.stop)
        for name, value in (
            ("_reserve_generation", {"remaining": 1, "rewardedRemaining": 0, "usedRewarded": False}),
            ("_reserve_photo_generation", 4),
        ):
            patcher = patch.object(index, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name in ("_release_generation", "_release_photo_generation"):
            patcher = patch.object(index, name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def post(self, path, body):
        return self.client.post(path, json=body, headers={"Authorization": "Bearer test-token"})

    def test_text_endpoint_preserves_contract_across_pl_en_es(self):
        with patch.object(index, "_generate_structured_response", return_value=recipe()) as generate:
            for ingredients in (["pomidory", "ryz"], ["tomatoes", "rice"], ["tomates", "arroz"]):
                response = self.post("/generate", {"ingredients": ingredients})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["title"], "Zupa")
                self.assertEqual(response.get_json()["remaining"], 1)
        self.assertEqual(generate.call_count, 3)

    def test_craving_optional_list_and_nutrition(self):
        with patch.object(index, "_generate_structured_response", return_value=craving_recipe()) as generate:
            response = self.post("/generate-craving", {
                "craving": "Quiero sopa", "includeShoppingList": False,
                "availableIngredients": ["tomate"],
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["shoppingList"], [])
        self.assertEqual(response.get_json()["nutrition"], nutrition())
        self.assertIn("pusta liste", generate.call_args.args[0])

    def test_craving_defaults_optional_fields(self):
        with patch.object(index, "_generate_structured_response", return_value=craving_recipe()):
            response = self.post("/generate-craving", {"craving": "Apple pie"})
        self.assertEqual(response.status_code, 200)

    def test_photo_authenticates_before_decoding_and_preserves_fields(self):
        events = []
        auth = patch.object(index, "_get_authenticated_uid", side_effect=lambda: events.append("auth") or "test-uid")
        decode = patch.object(index, "_compress_image_to_jpeg", side_effect=lambda _: events.append("decode") or b"jpeg")
        generated = Mock(return_value=photo_recipe())
        generate = patch.object(index, "_generate_structured_response", generated)
        with auth, decode, generate:
            response = self.post("/generate-photo", {"imageBase64": "ignored", "description": "Haz ensalada"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(events, ["auth", "decode"])
        data = response.get_json()
        self.assertEqual(data["detectedIngredients"], ["pomidor"])
        self.assertEqual((data["photoRemaining"], data["photoLimit"]), (4, 5))
        self.assertEqual(generated.call_args.kwargs["image_bytes"], b"jpeg")

    def test_invalid_image_returns_reserved_quota(self):
        with patch.object(index, "_generate_structured_response") as generate:
            response = self.post("/generate-photo", {"imageBase64": "not-base64"})
        self.assertEqual(response.status_code, 400)
        index._release_photo_generation.assert_called_once_with("test-uid")
        generate.assert_not_called()

    def test_photo_upload_configuration_cannot_raise_existing_size_cap(self):
        with patch.dict(os.environ, {"PHOTO_MAX_UPLOAD_BYTES": str(8 * 1024 * 1024)}):
            self.assertEqual(index._max_photo_upload_bytes(), 3 * 1024 * 1024)

    def test_invalid_inputs_do_not_authenticate_or_consume_quota(self):
        cases = [
            ("/generate", {"ingredients": [" "]}),
            ("/generate", {"ingredients": [4]}),
            ("/generate-craving", {"craving": "x" * 1001}),
            ("/generate-craving", {"craving": "Pie", "includeShoppingList": "false"}),
            ("/generate-photo", {"imageBase64": "abc", "description": "x" * 1001}),
        ]
        for path, body in cases:
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path, json=body).status_code, 400)
        index._get_authenticated_uid.assert_not_called()
        index._reserve_generation.assert_not_called()
        index._reserve_photo_generation.assert_not_called()

    def test_auth_error_does_not_expose_firebase_details(self):
        with patch.object(index, "_get_authenticated_uid", side_effect=RuntimeError("private firebase details")):
            response = self.post("/generate", {"ingredients": ["rice"]})
        self.assertEqual(response.status_code, 401)
        self.assertNotIn("private firebase details", response.get_data(as_text=True))
        index._reserve_generation.assert_not_called()

    def test_daily_limit_remains_enforced(self):
        with patch.object(index, "_reserve_generation", side_effect=index.DailyLimitExceeded):
            response = self.post("/generate", {"ingredients": ["rice"]})
        self.assertEqual(response.status_code, 403)

    def test_photo_weekly_limit_remains_enforced(self):
        with patch.object(index, "_reserve_photo_generation", side_effect=index.PhotoWeeklyLimitExceeded):
            response = self.post("/generate-photo", {"imageBase64": "a"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["photoRemaining"], 0)

    def test_failed_generation_restores_consumed_rewarded_credit(self):
        with patch.object(index, "_reserve_generation", return_value={
            "remaining": 0, "rewardedRemaining": 0, "usedRewarded": True,
        }), patch.object(index, "_generate_structured_response", side_effect=index.AIProviderError("provider")):
            response = self.post("/generate", {"ingredients": ["rice"]})
        self.assertEqual(response.status_code, 503)
        index._release_generation.assert_called_once_with("test-uid", True)

    def test_api_error_and_timeout_refund_limit_without_leaking_details(self):
        cases = [(index.AIProviderError("provider"), 503), (index.AIProviderError("timeout"), 504)]
        for error, status in cases:
            index._release_generation.reset_mock()
            with self.subTest(status=status), patch.object(
                index, "_generate_structured_response", side_effect=error,
            ):
                response = self.post("/generate-craving", {"craving": "soup"})
            self.assertEqual(response.status_code, status)
            self.assertNotIn("private API detail", response.get_data(as_text=True))
            index._release_generation.assert_called_once_with("test-uid", False)

    def test_refusal_and_incomplete_results_refund_limit(self):
        for error, status in ((index.AIRefusalError("refusal"), 422), (index.AIIncompleteError("cut off"), 502)):
            index._release_generation.reset_mock()
            with self.subTest(status=status), patch.object(index, "_generate_structured_response", side_effect=error):
                response = self.post("/generate", {"ingredients": ["rice"]})
            self.assertEqual(response.status_code, status)
            index._release_generation.assert_called_once()

    def test_responses_api_request_is_strict_and_not_stored(self):
        fake = FakeOpenAIClient(FakeResponse(json.dumps(recipe())))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test", "OPENAI_MODEL": "gpt-6-luna"}), \
             patch.object(index, "_get_openai_client", return_value=fake):
            index._generate_structured_response("prompt", "recipe", index.RECIPE_SCHEMA)
        self.assertEqual(fake.last_request["model"], "gpt-6-luna")
        self.assertIs(fake.last_request["store"], False)
        self.assertTrue(fake.last_request["text"]["format"]["strict"])
        self.assertEqual(fake.last_request["max_output_tokens"], index.AI_MAX_OUTPUT_TOKENS)

    def test_openai_client_uses_timeout_and_disables_sdk_retries(self):
        fake = FakeOpenAIClient(FakeResponse())
        openai_module = types.ModuleType("openai")
        openai_module.OpenAI = Mock(return_value=fake)
        previous_client = index._OPENAI_CLIENT
        try:
            index._OPENAI_CLIENT = None
            with patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test"}), \
                 patch.dict(sys.modules, {"openai": openai_module}):
                client = index._get_openai_client()
            self.assertIs(client, fake)
            openai_module.OpenAI.assert_called_once_with(
                api_key="unit-test", timeout=20, max_retries=0,
            )
        finally:
            index._OPENAI_CLIENT = previous_client

    def test_craving_schema_and_output_are_validated(self):
        fake = FakeOpenAIClient(FakeResponse(json.dumps(craving_recipe())))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test"}), \
             patch.object(index, "_get_openai_client", return_value=fake):
            parsed = index._generate_structured_response(
                "prompt", "craving_recipe", index.CRAVING_RECIPE_SCHEMA,
            )
        self.assertEqual(parsed["nutrition"], nutrition())
        self.assertEqual(fake.last_request["text"]["format"]["name"], "craving_recipe")

    def test_openai_refusal_incomplete_and_timeout_are_classified(self):
        refusal = FakeResponse(output=[types.SimpleNamespace(
            content=[types.SimpleNamespace(type="refusal")],
        )])
        incomplete = FakeResponse(status="incomplete")
        for response, error_type in (
            (refusal, index.AIRefusalError),
            (incomplete, index.AIIncompleteError),
        ):
            with patch.object(index, "_get_openai_client", return_value=FakeOpenAIClient(response)):
                with self.assertRaises(error_type):
                    index._generate_structured_response("prompt", "recipe", index.RECIPE_SCHEMA)

        fake = FakeOpenAIClient(FakeResponse())
        fake.create = Mock(side_effect=TimeoutError("private timeout detail"))
        with patch.object(index, "_get_openai_client", return_value=fake):
            with self.assertRaises(index.AIProviderError) as raised:
                index._generate_structured_response("prompt", "recipe", index.RECIPE_SCHEMA)
        self.assertEqual(str(raised.exception), "timeout")

    def test_photo_request_sends_compressed_jpeg_as_data_url(self):
        jpeg = b"compressed-jpeg"
        fake = FakeOpenAIClient(FakeResponse(json.dumps(photo_recipe())))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test"}), \
             patch.object(index, "_get_openai_client", return_value=fake):
            index._generate_structured_response("prompt", "photo_recipe", index.PHOTO_RECIPE_SCHEMA, jpeg)
        image_part = fake.last_request["input"][0]["content"][1]
        self.assertEqual(image_part["image_url"], "data:image/jpeg;base64," + base64.b64encode(jpeg).decode())
        self.assertEqual(image_part["detail"], "low")

    def test_malformed_json_and_invalid_recipe_are_rejected(self):
        for text in ("not json", json.dumps({"title": "", "description": "", "steps": []})):
            fake = FakeOpenAIClient(FakeResponse(text))
            with patch.object(index, "_get_openai_client", return_value=fake):
                with self.assertRaises(index.AIResponseError):
                    index._generate_structured_response("prompt", "recipe", index.RECIPE_SCHEMA)

    def test_ssv_callback_still_grants_reward(self):
        with patch.object(index, "_initialize_firebase"), \
             patch.object(index, "_verify_admob_reward_callback", return_value=("uid", "transaction")), \
             patch.object(index, "_mark_reward_transaction") as mark, \
             patch.object(index, "_grant_rewarded_generation", return_value=1) as grant:
            response = self.client.get("/admob-reward-callback")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok", "rewardedRemaining": 1})
        mark.assert_called_once_with("transaction", "uid")
        grant.assert_called_once_with("uid")

    def test_duplicate_ssv_transaction_remains_idempotent(self):
        with patch.object(index, "_initialize_firebase"), \
             patch.object(index, "_verify_admob_reward_callback", return_value=("uid", "transaction")), \
             patch.object(index, "_mark_reward_transaction", side_effect=index.DuplicateRewardTransaction), \
             patch.object(index, "_grant_rewarded_generation") as grant:
            response = self.client.get("/admob-reward-callback")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "duplicate"})
        grant.assert_not_called()


if __name__ == "__main__":
    unittest.main()
