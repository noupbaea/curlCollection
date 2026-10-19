#!/usr/bin/env python3
"""Web server: serves the site and proxies searches so the API key never reaches the browser.
Run:  python3 server.py   then open http://localhost:8000
Uses the key from .env (BHA_API_KEY) or falls back to myKey if unset. Header sent is X-API-Key."""
import collections, json, os, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import matcher as m

HERE = Path(__file__).parent


def load_env():
    """Minimal .env loader (no external deps): reads KEY=VALUE lines into os.environ."""
    env = HERE / ".env"
    if not env.exists():
        return
    for raw in env.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


load_env()
KEY = os.environ.get("BHA_API_KEY", "myKey")
hits = collections.defaultdict(list)
RATE, WINDOW = 20, 60  # requests per IP per minute


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    CTYPES = {
        ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
        ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".heic": "image/heic",
    }

    PAGES = {  # display (tail) path -> file, so nested quiz routes share the same HTML
        "/quiz": "quiz.html",
        "/quiz/porosity": "quiz_porosity.html",
        "/quiz/concerns": "quiz_concerns.html",
        "/quiz/products": "quiz_products.html",
        "/quiz/budget": "quiz_budget.html",
        "/quiz/avoid": "quiz_avoid.html",
        "/quiz/results": "quiz_results.html",
        "/browse": "browse.html",
        "/matcher.html": "matcher.html",
    }

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.reply(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path in self.PAGES:
            self.reply(200, (HERE / self.PAGES[self.path]).read_bytes(), "text/html; charset=utf-8")
        elif self.path.startswith("/assets/"):
            p = (HERE / "assets" / self.path[len("/assets/"):])
            if p.is_file():
                self.reply(200, p.read_bytes(), self.CTYPES.get(p.suffix.lower(), "application/octet-stream"))
                return
            self.reply(404, {"error": "Not found."})
        elif self.path == "/health":
            self.reply(200, {"status": "ok"})
        else:
            self.reply(404, {"error": "Not found."})

    def do_POST(self):
        if self.path not in ("/api/recommend", "/api/browse"):
            return self.reply(404, {"error": "Not found."})
        ip = self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()
        now = time.time()
        hits[ip] = [t for t in hits[ip] if now - t < WINDOW]
        if len(hits[ip]) >= RATE:
            return self.reply(429, {"error": "Too many searches. Try again in a minute."})
        hits[ip].append(now)
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n > 5000:
                raise ValueError
            d = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, TypeError, json.JSONDecodeError):
            return self.reply(400, {"error": "Bad request."})
        if self.path == "/api/browse":
            return self.do_browse(d)
        try:
            ht, po = str(d.get("hair_type", "")).upper(), str(d.get("porosity", "")).lower()
            if ht not in m.HAIR_TYPES or po not in m.POROSITY:
                raise ValueError
            cat = d.get("category") or None
            cur = d.get("currency", "USD")
            if (cat and cat not in m.CATEGORIES) or cur not in m.SYMBOLS:
                raise ValueError
            budget = float(d["budget"]) if d.get("budget") not in (None, "") else None
            concerns = [c for c in d.get("concerns", []) if c in m.CONCERNS]
        except (ValueError, TypeError, json.JSONDecodeError):
            return self.reply(400, {"error": "Please choose a hair type and porosity."})
        try:
            out = m.recommend(KEY, ht, po, concerns, budget, cur, cat, bool(d.get("no_sulphates")),
                              bool(d.get("no_silicones")), bool(d.get("no_parabens")), 6)
            self.reply(200, out)
        except m.ApiError as e:
            msg = "The product service is busy. Try again later." if e.status in (401, 403, 429) else "The product service is unavailable."
            self.log(f"recommend API error: status={e.status} hair_type={ht} porosity={po}")
            self.reply(502, {"error": msg})

    def do_browse(self, d):
        try:
            ht = str(d.get("hair_type") or "").upper() or None
            if ht and ht not in m.HAIR_TYPES:
                return self.reply(400, {"error": "Unknown hair type."})
            po = str(d.get("porosity") or "").lower() or None
            if po and po not in m.POROSITY:
                return self.reply(400, {"error": "Unknown porosity."})
            cat = d.get("category") or None
            if cat == "any":
                cat = None
            cur = d.get("currency", "USD")
            if (cat and cat not in m.CATEGORIES) or cur not in m.SYMBOLS:
                return self.reply(400, {"error": "Unknown filter value."})
            budget = float(d["budget"]) if d.get("budget") not in (None, "") else None
            concerns = [c for c in d.get("concerns", []) if c in m.CONCERNS]
            out = m.browse_products(KEY, ht, po, concerns, cat, budget, cur,
                                    bool(d.get("no_sulphates")), bool(d.get("no_silicones")), bool(d.get("no_parabens")))
            self.reply(200, out)
        except (ValueError, TypeError):
            return self.reply(400, {"error": "Bad request."})
        except m.ApiError as e:
            msg = "The product service is busy. Try again later." if e.status in (401, 403, 429) else "The product service is unavailable."
            self.log(f"browse API error: status={e.status}")
            self.reply(502, {"error": msg})

    def log(self, text):
        """Write a line to stderr so it shows up in Render's Logs tab."""
        import sys
        print(f"[{self.log_date_time_string()}] {text}", file=sys.stderr, flush=True)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    if m.OFFLINE:
        print("OFFLINE MODE: using products_snapshot.json, no API requests are made.")
    elif KEY == "myKey":
        print("LIVE MODE with placeholder key 'myKey' (edit .env -> BHA_API_KEY for a real key).")
    else:
        print(f"LIVE MODE: using API key from .env (X-API-Key header).")
    port = int(os.environ.get("PORT", 8000))
    print(f"Running on http://localhost:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
