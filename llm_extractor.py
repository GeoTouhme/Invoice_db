"""
Flexible invoice parser supporting multiple LLM backends.
Priority:
  1. Anthropic Claude (cloud, best accuracy) — if ANTHROPIC_API_KEY is set
  2. Ollama (local or remote) — if OLLAMA_URL is reachable
  3. Return None → UI falls back to manual review
"""

import json
import logging
import os
from typing import Any

import requests

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an invoice data extraction assistant.
Read the provided invoice text and return ONLY a valid JSON object.
Do not add explanations, markdown, or any text outside the JSON.

Schema:
{
  "invoice_number": "string",
  "invoice_date": "YYYY-MM-DD",
  "invoice_due_date": "YYYY-MM-DD or null",
  "process_date": "YYYY-MM-DD or null",
  "invoice_total": number,
  "item_count": integer,
  "vendor_name": "string",
  "retailer_name": "string",
  "customer_id": "string",
  "store_id": "string",
  "line_items": [
    {
      "product_number": "string",
      "upc_number": "string",
      "pack_upc": "string or null",
      "product_description": "string",
      "gl_code": "string (Beer, Wine, Spirits, Non-Alcohol, Misc)",
      "quantity": number,
      "unit_cost": number,
      "unit_of_measure": "string (EA, CA, CS, etc.)",
      "total_adjustments": number or 0,
      "total_discount": number or 0,
      "extended_price": number,
      "ppc": number or null
    }
  ]
}

Rules:
- Use null for missing values. Never omit keys.
- invoice_total should equal the sum of extended_price values when calculable.
- Convert all dates to YYYY-MM-DD.
- Infer gl_code from product description when not explicit.
- UPC Number should be digits only when available.
- Return ONLY the JSON object, nothing else.
"""

USER_PROMPT_TEMPLATE = "Extract the invoice data from this text:\n\n---\n{raw_text}\n---"

_HEADER_STR_FIELDS = ("invoice_number", "invoice_date", "invoice_due_date",
                      "process_date", "vendor_name", "retailer_name",
                      "customer_id", "store_id")
_ITEM_STR_FIELDS = ("product_number", "upc_number", "pack_upc",
                    "product_description", "gl_code", "unit_of_measure")
_ITEM_NUM_FIELDS = ("quantity", "unit_cost", "total_adjustments",
                    "total_discount", "extended_price", "ppc")


def _as_num(val) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(str(val).replace("$", "").replace(",", ""))
    except ValueError:
        return None


def _normalize(data: Any) -> dict[str, Any] | None:
    """Validate/normalize the LLM's JSON so malformed output never reaches
    the review form. Returns None if the shape is unusable."""
    if not isinstance(data, dict):
        log.warning("LLM returned non-object JSON: %r", type(data))
        return None

    out: dict[str, Any] = {}
    for field in _HEADER_STR_FIELDS:
        val = data.get(field)
        out[field] = str(val).strip() if val not in (None, "") else ""
    out["invoice_total"] = _as_num(data.get("invoice_total"))
    item_count = _as_num(data.get("item_count"))
    out["item_count"] = int(item_count) if item_count is not None else ""

    raw_items = data.get("line_items")
    items = []
    if isinstance(raw_items, list):
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            item: dict[str, Any] = {}
            for field in _ITEM_STR_FIELDS:
                val = raw.get(field)
                item[field] = str(val).strip() if val not in (None, "") else ""
            for field in _ITEM_NUM_FIELDS:
                item[field] = _as_num(raw.get(field))
            if item["product_number"] or item["product_description"]:
                items.append(item)
    out["line_items"] = items

    if not out["invoice_number"] and not items:
        log.warning("LLM output had neither invoice_number nor line items; discarding")
        return None
    return out


def _clean_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    return text


# ── Anthropic ────────────────────────────────────────────────────────────────

def _anthropic_extract(raw_text: str) -> dict[str, Any] | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        from anthropic import Anthropic
    except ImportError:
        log.warning("anthropic package not installed; skipping Claude extraction")
        return None

    model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")

    client = Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            temperature=0.0,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": USER_PROMPT_TEMPLATE.format(raw_text=raw_text),
                }
            ],
        )
        content = _clean_json(response.content[0].text)
        return _normalize(json.loads(content))
    except Exception:
        log.exception("Anthropic extraction failed")
        return None


# ── Ollama (local or remote) ─────────────────────────────────────────────────

def _ollama_extract(raw_text: str) -> dict[str, Any] | None:
    ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    ollama_model = os.environ.get("OLLAMA_MODEL", "qwen3:4b")
    ollama_key = os.environ.get("OLLAMA_API_KEY", "")

    generate_url = f"{ollama_url}/api/generate"

    payload = {
        "model": ollama_model,
        "prompt": USER_PROMPT_TEMPLATE.format(raw_text=raw_text),
        "system": SYSTEM_PROMPT,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.0,
            "num_ctx": 8192,
        },
    }

    headers = {}
    if ollama_key:
        headers["Authorization"] = f"Bearer {ollama_key}"

    try:
        resp = requests.post(generate_url, json=payload, headers=headers, timeout=180)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        log.exception("Ollama request failed (%s)", generate_url)
        return None

    response_text = data.get("response", "")
    if not response_text:
        log.warning("Ollama returned an empty response")
        return None

    cleaned = _clean_json(response_text)
    try:
        return _normalize(json.loads(cleaned))
    except json.JSONDecodeError:
        log.warning("Ollama returned invalid JSON")
        return None


# ── Public entrypoint ────────────────────────────────────────────────────────

def extract_invoice_data(raw_text: str) -> dict[str, Any] | None:
    """Try Anthropic first, then Ollama, then give up."""
    # 1. Try Anthropic (cloud, highest accuracy)
    result = _anthropic_extract(raw_text)
    if result:
        return result

    # 2. Try Ollama (local or remote)
    result = _ollama_extract(raw_text)
    if result:
        return result

    return None
