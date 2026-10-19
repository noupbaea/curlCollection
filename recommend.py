#!/usr/bin/env python3
"""Terminal hair product recommender.
Usage:  export BHA_API_KEY=your_key
        python3 recommend.py                      (asks questions)
        python3 recommend.py --hair-type 4C --porosity high --concerns dryness,frizz --budget 20"""
import argparse, os, sys
import matcher as m


def ask(label, choices=None, optional=False):
    hint = f" ({'/'.join(choices)})" if choices else ""
    while True:
        v = input(f"{label}{hint}{' [Enter to skip]' if optional else ''}: ").strip()
        if not v and optional:
            return None
        if v and (not choices or v.lower() in [c.lower() for c in choices]):
            return v
        print("  Please pick one of the listed options." if choices else "  This one is required.")


def main():
    ap = argparse.ArgumentParser(description="Find hair products that suit your hair.")
    ap.add_argument("--hair-type", type=str.upper, choices=m.HAIR_TYPES)
    ap.add_argument("--porosity", type=str.lower, choices=m.POROSITY)
    ap.add_argument("--concerns", default=None, help="comma-separated, e.g. dryness,frizz")
    ap.add_argument("--budget", type=float, help="maximum price")
    ap.add_argument("--currency", default="USD", type=str.upper, choices=["USD", "GBP"])
    ap.add_argument("--category", choices=m.CATEGORIES)
    ap.add_argument("--no-sulphates", action="store_true")
    ap.add_argument("--no-silicones", action="store_true")
    ap.add_argument("--no-parabens", action="store_true")
    ap.add_argument("--limit", type=int, default=5)
    a = ap.parse_args()

    key = os.environ.get("BHA_API_KEY")
    if not key and not m.OFFLINE:
        sys.exit("Set your key first:  export BHA_API_KEY=your_key")

    if not (a.hair_type and a.porosity):
        a.hair_type = (a.hair_type or ask("Hair type", m.HAIR_TYPES)).upper()
        a.porosity = (a.porosity or ask("Porosity", m.POROSITY)).lower()
        if a.concerns is None:
            a.concerns = ask("Concerns, comma-separated: " + ", ".join(m.CONCERNS), optional=True)
    concerns = [c for c in (a.concerns or "").split(",") if c.strip()]

    try:
        out = m.recommend(key, a.hair_type, a.porosity, concerns, a.budget, a.currency, a.category,
                          a.no_sulphates, a.no_silicones, a.no_parabens, a.limit)
    except m.ApiError as e:
        sys.exit(f"Error: {e}")

    print(f"\nChecked {out['considered']} products for {a.hair_type}, {a.porosity} porosity.\n")
    if not out["results"]:
        sys.exit("No matches. Try fewer concerns, a higher budget, or a different category.")
    for i, r in enumerate(out["results"], 1):
        tag = "  [Black-owned]" if r["black_owned"] else ""
        print(f"{i}. {r['name']} - {r['brand']}{tag}")
        print(f"   {r['category']}, {r['price']}" + (f"  | helps with: {', '.join(r['matched'])}" if r["matched"] else ""))
        print(f"   {r['buy_url'] or 'No buy link listed'}\n")


if __name__ == "__main__":
    main()
