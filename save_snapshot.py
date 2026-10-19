#!/usr/bin/env python3
"""Save a copy of the real product list to products_snapshot.json (uses at most 5 requests).
Run once:  export BHA_API_KEY=your_key && python3 save_snapshot.py"""
import argparse, json, os, sys
import matcher as m

ap = argparse.ArgumentParser()
ap.add_argument("--pages", type=int, default=5, help="pages of 100 products to save (1 request each)")
ap.add_argument("--out", default=m.SNAPSHOT)
a = ap.parse_args()
key = os.environ.get("BHA_API_KEY")
if not key:
    sys.exit("Set your key first:  export BHA_API_KEY=your_key")

products, used = [], 0
for page in range(1, a.pages + 1):
    try:
        data = m.api_get("/v1/products/", {"limit": 100, "page": page}, key).get("data", [])
    except m.ApiError as e:
        print(f"Stopped early: {e}")
        break
    used += 1
    products += data
    if len(data) < 100:
        break
if not products:
    sys.exit("Nothing saved, so your existing file is untouched.")
with open(a.out, "w", encoding="utf-8") as f:
    json.dump(products, f, indent=1, ensure_ascii=False)
print(f"Saved {len(products)} products to {a.out} using {used} request(s).")
