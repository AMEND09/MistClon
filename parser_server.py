"""Single-file Flask server exposing the ingredient parser.

Endpoints
- GET /health -> {"status":"ok"}
- POST /parse -> JSON body {"text": "..."} returns {"ingredients": [{"name":..., "quantity":...}, ...]}

Usage:
  pip install flask gliner2
  # optionally set PIONEER_API_KEY to use the GLiNER2 API
  python parser_server.py

Example:
  curl -s -X POST -H "Content-Type: application/json" -d '{"text":"A burger with a fried chicken patty two brioche buns lettuce a slice of tomato"}' http://127.0.0.1:5000/parse | jq

Notes:
- The server tries to load the local GLiNER2 model by default. If model download is not desired,
  set the environment variable PIONEER_API_KEY and the code will use GLiNER2.from_api().
- This file intentionally contains only the parser logic and the minimal server wrapper.
"""

from flask import Flask, request, jsonify
import os
import re
import logging

# Try to import GLiNER2 lazily; the server will still run and return a helpful error
try:
    from gliner2 import GLiNER2
except Exception:
    GLiNER2 = None

DEFAULT_MODEL = os.getenv("GLINER2_MODEL", "fastino/gliner2-base-v1")

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)


def load_extractor(use_api=False, model_name=DEFAULT_MODEL):
    """Return a GLiNER2 extractor instance or raise an Exception if not available."""
    if use_api:
        if GLiNER2 is None:
            raise RuntimeError("GLiNER2 library not available; install gliner2 or run without API mode")
        return GLiNER2.from_api()

    if GLiNER2 is None:
        raise RuntimeError("GLiNER2 library not available; install gliner2 or set PIONEER_API_KEY to use API mode")
    return GLiNER2.from_pretrained(model_name)


def _normalize_quantity_and_name(name, qty_text):
    """Apply demo-specific normalizations: 'a' -> '1', fractions -> '1/2', trim."""
    qty_text = (qty_text or "").strip()
    lqty = qty_text.lower()

    # Convert 'a' or 'an' to '1' (e.g., 'a slice' -> '1 slice')
    m_a = re.match(r"^(?:a|an)(?:\s+(.*))?$", lqty)
    if m_a:
        rest = m_a.group(1)
        qty_text = "1" + (f" {rest}" if rest else "")
        lqty = qty_text.lower()

    # Normalize fraction words to numeric form
    if "half" in lqty or "quarter" in lqty:
        if "half" in lqty:
            frac = "1/2"
        else:
            frac = "1/4"
        m = re.search(r"(?:half|quarter)\s+(?:an|a|the)?\s*([a-zA-Z\-]+)", lqty)
        if m:
            referred = m.group(1)
            if "toast" in name.lower() and referred in name.lower():
                name = referred
                qty_text = frac
            else:
                qty_text = f"{frac} {referred}"
        else:
            qty_text = frac

    return name.strip(), qty_text.strip()


def parse_ingredients(text, extractor=None):
    """Extract ingredients from free text using GLiNER2 if available.

    Returns a list of dicts: [{"name":..., "quantity": ...}, ...]
    If GLiNER2 can't be loaded, raises RuntimeError.
    """
    if extractor is None:
        # default behavior: try to load a local extractor; if PIONEER_API_KEY is set, use API mode
        use_api = bool(os.getenv("PIONEER_API_KEY"))
        extractor = load_extractor(use_api=use_api)

    schema = {
        "ingredients": [
            "name::str::Ingredient name or food item",
            "quantity::str::Approximate quantity like 'half an avocado' or '2 slices'",
        ]
    }

    out = extractor.extract_json(text, schema)
    results = out.get("ingredients", [])
    parsed = []
    for item in results:
        name = item.get("name")
        qty = item.get("quantity")
        if isinstance(name, dict):
            name = name.get("text")
        if isinstance(qty, dict):
            qty = qty.get("text")
        if not name:
            continue
        name = name.strip()
        name, qty = _normalize_quantity_and_name(name, qty)
        parsed.append({"name": name, "quantity": qty})

    # Merge duplicates (case-insensitive), prefer explicit quantities
    merged = {}
    for p in parsed:
        key = p["name"].strip().lower()
        if key not in merged:
            merged[key] = p
        else:
            # prefer the entry that has a non-empty quantity
            if (not merged[key].get("quantity")) and p.get("quantity"):
                merged[key] = p

    return list(merged.values())


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/parse", methods=["POST"])
def parse_route():
    payload = request.get_json(silent=True)
    if not payload or "text" not in payload:
        return jsonify({"error": "missing 'text' in JSON body"}), 400

    text = payload["text"]
    try:
        # lazy-load extractor for each request to keep memory small; caller can override by passing
        # extractor function when integrating
        use_api = bool(os.getenv("PIONEER_API_KEY"))
        extractor = load_extractor(use_api=use_api)
    except Exception as e:
        # Return useful error message rather than 500 to make debugging easier
        return jsonify({"error": str(e)}), 500

    try:
        ingredients = parse_ingredients(text, extractor=extractor)
    except Exception as e:
        return jsonify({"error": f"parse failed: {e}"}), 500

    return jsonify({"ingredients": ingredients})


if __name__ == "__main__":
    # Run with: python parser_server.py
    # Note: GLiNER2 may download a model on first run which can take time
    logging.info("Starting parser server on http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=True)
