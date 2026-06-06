"""
Flexible invoice parser supporting multiple LLM backends.
Priority:
  1. Anthropic Claude (cloud, best accuracy) — if ANTHROPIC_API_KEY is set
  2. Ollama (local or remote) — if OLLAMA_URL is reachable
  3. Return None → UI falls back to manual review
"""

import json
import os
from typing import Any

import requests

# ── Anthropic ────────────────────────────────────────────────────────────────

def _anthropic_extract(raw_text: str) -> dict[str, Any] | None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    try:
        from anthropic import Anthropic
    except ImportError:
        return None

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

    client = Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            temperature=0.0,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"Extract the invoice data from this text:\n\n---\n{raw_text}\n---",
                }
            ],
        )
        content = response.content[0].text.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        return json.loads(content)
    except Exception:
        return None


# ── Ollama (local or remote) ─────────────────────────────────────────────────

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


def _ollama_extract(raw_text: str) -> dict[str, Any] | None:
    ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
    ollama_model = os.environ.get("OLLAMA_MODEL", "qwen3:4b")
    ollama_key = os.environ.get("OLLAMA_API_KEY", "")

    generate_url = f"{ollama_url}/api/generate"

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

    payload = {
        "model": ollama_model,
        "prompt": f"Extract the invoice data from this text:\n\n---\n{raw_text}\n---",
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
        resp = requests.post(generate_url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None

    response_text = data.get("response", "")
    if not response_text:
        return None

    cleaned = _clean_json(response_text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
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
