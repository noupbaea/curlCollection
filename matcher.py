"""Shared logic: fetch products from the Black Haircare API and rank them.
Uses only the Python standard library (no pip install needed)."""
import json, os, time, urllib.error, urllib.parse, urllib.request

BASE = os.environ.get("BHA_BASE_URL", "https://api.blackhairapi.com")
HAIR_TYPES = ["2A", "2B", "2C", "3A", "3B", "3C", "4A", "4B", "4C"]
POROSITY = ["low", "medium", "high"]
CONCERNS = ["dryness", "frizz", "definition", "moisture", "breakage"]
CATEGORIES = ["shampoo", "conditioner", "leave_in", "oil", "treatment", "styler", "ayurvedic", "other"]
SYMBOLS = {"USD": "$", "GBP": "£"}
PAGE_SIZE, MAX_PAGES = 100, 3
OFFLINE = os.environ.get("BHA_OFFLINE") == "1"  # use the saved file instead of the live API
SNAPSHOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "products_snapshot.json")
_cache = {}


class ApiError(Exception):
    def __init__(self, msg, status=502):
        super().__init__(msg)
        self.status = status


def api_get(path, params, key):
    clean = {k: ("true" if v is True else v) for k, v in params.items() if v not in (None, "", False)}
    req = urllib.request.Request(
        f"{BASE}{path}?{urllib.parse.urlencode(clean)}",
        headers={"X-API-Key": key, "Accept": "application/json", "User-Agent": "hair-recommender/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        notes = {401: "The API key was rejected.", 403: "The API key was rejected.", 429: "The API rate limit has been reached."}
        raise ApiError(notes.get(e.code, f"The API returned error {e.code}."), e.code)
    except (urllib.error.URLError, TimeoutError) as e:
        raise ApiError(f"Could not reach the API: {e}")


def fetch_products(key, hair_type, category=None, no_sulphates=False, no_silicones=False, no_parabens=False, ttl=600):
    """Server-side filters go to the API; results are cached to save your request quota."""
    if OFFLINE:  # no API calls; the sulphate/silicone/paraben filters need live data, so they are skipped
        with open(SNAPSHOT, encoding="utf-8") as f:
            return [p for p in json.load(f) if not category or p.get("category") == category]
    ck = (hair_type, category, no_sulphates, no_silicones, no_parabens)
    hit = _cache.get(ck)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    out = []
    for page in range(1, MAX_PAGES + 1):
        res = api_get("/v1/products/", {
            "hair_type": hair_type, "category": category, "exclude_sulphates": no_sulphates,
            "exclude_silicones": no_silicones, "exclude_parabens": no_parabens,
            "limit": PAGE_SIZE, "page": page}, key)
        data = res.get("data", [])
        out += data
        if len(data) < PAGE_SIZE:
            break
    _cache[ck] = (time.time(), out)
    return out


def rank(products, hair_type, porosity, concerns=(), budget=None, currency="USD", limit=5):
    """Keep products suited to the hair type and porosity, score by concerns matched, cheapest first on ties."""
    want = {c.strip().lower() for c in concerns if c.strip()}
    results = []
    for p in products:
        hp = p.get("hair_profile") or {}
        if not p.get("is_active", True) or hair_type not in (hp.get("hair_types") or []):
            continue
        if porosity not in (hp.get("porosity") or []):
            continue
        matched = sorted(want & {c.lower() for c in hp.get("concerns") or []})
        if want and not matched:
            continue
        pr = p.get("price_range") or {}
        if budget is not None and (pr.get("currency") != currency or pr.get("max") is None or pr["max"] > budget):
            continue
        results.append({"score": len(matched), "matched": matched, "product": p})
    results.sort(key=lambda r: (-r["score"], (r["product"].get("price_range") or {}).get("min") or 1e9))
    return results[:limit]


def price_text(pr):
    if not pr or pr.get("min") is None:
        return "Price not listed"
    s = SYMBOLS.get(pr.get("currency"), (pr.get("currency") or "") + " ")
    lo, hi = pr["min"], pr.get("max", pr["min"])
    return f"{s}{lo:.2f}" if lo == hi else f"{s}{lo:.2f}–{s}{hi:.2f}"


def summarise(r):
    p, b = r["product"], r["product"].get("brand") or {}
    return {"name": p.get("name"), "brand": b.get("name"), "black_owned": bool(b.get("is_black_owned")),
            "category": p.get("category"), "subcategory": p.get("subcategory") or [],
            "price": price_text(p.get("price_range")), "buy_url": p.get("buy_url"),
            "image": (p.get("images") or [None])[0], "description": p.get("description"),
            "matched": r["matched"], "regions": p.get("regions") or []}


def recommend(key, hair_type, porosity, concerns=(), budget=None, currency="USD", category=None,
              no_sulphates=False, no_silicones=False, no_parabens=False, limit=5):
    products = fetch_products(key, hair_type, category, no_sulphates, no_silicones, no_parabens)
    ranked = rank(products, hair_type, porosity, concerns, budget, currency, limit)
    return {"considered": len(products), "results": [summarise(r) for r in ranked]}


def browse_products(key, hair_type=None, porosity=None, concerns=(), category=None, budget=None,
                    currency="USD", no_sulphates=False, no_silicones=False, no_parabens=False, limit=200):
    """Free-range browsing: filter the product set by any combination of optional filters."""
    if OFFLINE:
        with open(SNAPSHOT, encoding="utf-8") as f:
            allp = json.load(f)
    else:
        allp = []
        for ht in ([hair_type] if hair_type else HAIR_TYPES):
            allp += fetch_products(key, ht)
    want = {c.lower() for c in concerns if c}
    out = []
    for p in allp:
        if not p.get("is_active", True):
            continue
        hp = p.get("hair_profile") or {}
        if hair_type and hair_type not in (hp.get("hair_types") or []):
            continue
        if porosity and porosity not in (hp.get("porosity") or []):
            continue
        if category and p.get("category") != category:
            continue
        if want and not (want & {str(x).lower() for x in hp.get("concerns") or []}):
            continue
        pr = p.get("price_range") or {}
        if budget is not None and (pr.get("currency") != currency or pr.get("max") is None or pr["max"] > budget):
            continue
        # ingredient exclusions need live ingredient data; in offline mode we cannot check them,
        # so they are skipped (same behaviour as the quiz matcher)
        matched = sorted(want & {str(x).lower() for x in hp.get("concerns") or []})
        out.append({"matched": matched, "product": p})
    out = out[:limit]
    return {"considered": len(allp), "results": [summarise(r) for r in out]}
