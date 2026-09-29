import json
import re


class AIResponseError(ValueError):
    pass


def parse_response(content):
    if isinstance(content, dict):
        return content
    if not isinstance(content, str) or not content.strip():
        raise AIResponseError("AI returned an empty response.")
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIResponseError("AI response was not valid JSON.") from exc
    if not isinstance(value, dict):
        raise AIResponseError("AI response must be a JSON object.")
    return value
