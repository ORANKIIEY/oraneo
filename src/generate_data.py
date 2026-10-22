"""Reproducible *synthetic*, South African sales records for a local demo.

These are not observational / government / actual merchant sales. Monetary values ZAR.
"""
import argparse
import random
from datetime import date, timedelta
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CURRENCY = "ZAR"
CITIES = ["Cape Town", "Johannesburg", "Durban", "Pretoria", "Gqeberha", "Bloemfontein", "Polokwane", "Mbombela"]
PRODUCTS = {"Laptop": 14999.00, "Smartphone": 7499.00, "Headphones": 899.00,
            "Monitor": 3299.00, "Keyboard": 549.00, "Mouse": 249.00}


def generate(n_rows: int = 1000, seed: int = 42) -> pd.DataFrame:
    if n_rows < 1:
        raise ValueError("n_rows must be positive")
    rng = random.Random(seed)
    start = date(2026, 1, 1)
    rows = []
    for i in range(1, n_rows + 1):
        product = rng.choice(list(PRODUCTS))
        rows.append({"order_id": str(1000 + i),
                     "order_date": (start + timedelta(days=rng.randint(0, 270))).isoformat(),
                     "customer_id": f"ZA{rng.randint(1, 240):04d}",
                     "city": rng.choice(CITIES), "product": product,
                     "quantity": rng.randint(1, 5), "unit_price": PRODUCTS[product]})
    df = pd.DataFrame(rows)
    df.loc[df.sample(frac=.03, random_state=seed).index, "city"] = ""
    df.loc[df.sample(frac=.02, random_state=seed+1).index, "quantity"] = -1
    df.loc[df.sample(frac=.015, random_state=seed+2).index, "order_date"] = "not-a-date"
    df.loc[df.sample(frac=.02, random_state=seed+3).index, "city"] = df["city"].str.upper()
    df = pd.concat([df, df.sample(frac=.02, random_state=seed+4)], ignore_index=True)
    return df.sample(frac=1, random_state=seed).reset_index(drop=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--rows", type=int, default=1000)
    p.add_argument("--out", default=str(ROOT / "data/raw/sales_raw.csv"))
    args = p.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    generate(args.rows).to_csv(out, index=False)
    print(f"Wrote {args.rows} synthetic South African rows to {out} (ZAR)")
