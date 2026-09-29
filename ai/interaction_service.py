"""Live AI interaction screening. Results are cached in process memory only."""
import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ai.prompt_builder import build_messages
from ai.response_parser import AIResponseError, parse_response
from ai.safety_validator import SafetyValidationError, validate_result

logger = logging.getLogger("medishield.ai_guardian")
_CACHE = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 180
_CACHE_MAX = 128
_BRANDS_PATH = Path(__file__).with_name("brand_mapping.json")
with _BRANDS_PATH.open(encoding="utf-8") as _file:
    BRAND_MAPPING = json.load(_file)


def _canonical(value):
    return " ".join(str(value or "").casefold().split())


def normalize_medicine(medicine, quantity):
    brand = str(medicine.brand_name or "").strip()
    generic = str(medicine.generic_name or "").strip()
    ingredients = None
    brand_key = _canonical(brand)
    for known_brand in sorted(BRAND_MAPPING, key=len, reverse=True):
        if brand_key == _canonical(known_brand) or brand_key.startswith(_canonical(known_brand) + " "):
            ingredients = BRAND_MAPPING[known_brand]
            break
    if ingredients is None:
        from utils.interaction_engine import ingredients_for
        ingredients = ingredients_for(medicine)
    ingredients = list(dict.fromkeys(_canonical(x) for x in ingredients if _canonical(x)))
    return {"label": brand, "generic_name": generic, "strength": str(medicine.strength or ""),
            "ingredients": ingredients, "quantity": int(quantity)}


def _unavailable(message="AI temporarily unavailable."):
    return {"available": False, "overall_status": "UNCERTAIN", "confidence": 0,
            "summary": message, "interactions": [], "allergy_warnings": [],
            "recommendations": ["Review the prescription using an authoritative clinical reference."],
            "billing_action": "ACKNOWLEDGEMENT_REQUIRED"}


def _cache_key(medicines, patient_context, model, endpoint, cache_scope):
    payload = json.dumps({"medicines": medicines, "patient": patient_context, "model": model, "endpoint": endpoint, "scope": cache_scope},
                         sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _extract_content(response):
    choices = response.get("choices") if isinstance(response, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise AIResponseError("AI provider response has no choices.")
    message = choices[0].get("message") or {}
    return message.get("content")


def analyze_interactions(medicines, patient_context=None, cache_scope=""):
    api_key = os.environ.get("AI_API_KEY", "").strip()
    endpoint = os.environ.get("AI_API_URL", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions").strip()
    model = os.environ.get("AI_MODEL", "gemini-3.8-flash").strip()
    if not api_key:
        return _unavailable("AI Guardian is not configured. Add AI_API_KEY to the server environment.")
    if not endpoint.startswith("https://") or not model:
        return _unavailable("AI Guardian configuration is invalid.")
    key = _cache_key(medicines, patient_context or {}, model, endpoint, cache_scope)
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached[0] < _CACHE_TTL:
            _CACHE.move_to_end(key)
            return {**cached[1], "cache_hit": True}
        if cached:
            _CACHE.pop(key, None)
    body = {"model": model, "messages": build_messages(medicines, patient_context),
            "temperature": 0, "response_format": {"type": "json_object"}}
    request = Request(endpoint, data=json.dumps(body).encode("utf-8"), method="POST",
                      headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        for attempt in range(2):
            try:
                with urlopen(request, timeout=20) as response:
                    raw_response = json.loads(response.read(1_000_000).decode("utf-8"))
                break
            except HTTPError as exc:
                if attempt == 0 and (exc.code == 429 or 500 <= exc.code <= 599):
                    time.sleep(0.5)
                    continue
                raise
        parsed = parse_response(_extract_content(raw_response))
        result = validate_result(parsed, medicines)
    except HTTPError as exc:
        logger.warning("AI Guardian provider rejected the request (HTTP %s)", exc.code)
        if exc.code in {401, 403}:
            return _unavailable("Gemini rejected the API key or its permissions. Check AI_API_KEY in the server environment.")
        if exc.code == 429:
            return _unavailable("Gemini rate limit reached. Wait briefly and retry the analysis.")
        return _unavailable("Gemini is temporarily unavailable. Please retry shortly.")
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        logger.warning("AI Guardian provider request failed (%s)", type(exc).__name__)
        return _unavailable()
    except (AIResponseError, SafetyValidationError, TypeError, ValueError) as exc:
        logger.warning("AI Guardian response rejected (%s)", type(exc).__name__)
        return _unavailable("Unable to analyze prescription. Please retry or use an authoritative clinical reference.")
    with _CACHE_LOCK:
        _CACHE[key] = (now, result)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return {**result, "cache_hit": False}
