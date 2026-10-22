"""Explicit input, validation, and duplicate-disposition policy.

For each valid business order ID, keep the earliest *valid* row; otherwise reject
its earliest row. All other occurrences are audited as duplicates, even when
invalid, and preserve their own validation problems. Records missing a valid ID
are rejected individually. Thus input = accepted + rejected + duplicates.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import csv
import re
import pandas as pd

REQUIRED_COLUMNS = ["order_id", "order_date", "customer_id", "city", "product", "quantity", "unit_price"]
MAX_MONEY = Decimal("1000000000000")

@dataclass
class Result:
    clean: pd.DataFrame
    rejected: pd.DataFrame
    duplicates: pd.DataFrame
    issues: pd.DataFrame
    input_count: int
    missing: dict[str, int]


def clean_text(value: object) -> str:
    return "" if value is None or str(value).strip().lower() in ("nan", "none", "nat") else str(value).strip()


def read_csv(path: str) -> pd.DataFrame:
    # Strict first pass catches ragged rows and duplicated headers that pandas
    # might silently rename or reinterpret as an implicit index.
    try:
        with open(path, encoding="utf-8-sig", newline="") as file:
            reader = csv.reader(file, strict=True)
            header = next(reader, None)
            if not header:
                raise ValueError("CSV is empty or has no header")
            if len(header) != len(set(header)) or any(not col.strip() for col in header):
                raise ValueError("CSV has duplicate or unnamed columns")
            missing = set(REQUIRED_COLUMNS) - set(header)
            if missing:
                raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")
            count = 0
            for index, row in enumerate(reader, start=2):
                if not row: continue
                if len(row) != len(header):
                    raise ValueError(f"Malformed CSV at row {index}: expected {len(header)} columns, got {len(row)}")
                count += 1
            if not count:
                raise ValueError("CSV contains no data rows")
        return pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig", index_col=False)
    except (csv.Error, UnicodeError, pd.errors.ParserError) as exc:
        raise ValueError(f"Invalid CSV file: {exc}") from exc

def parse_date(value: str) -> str | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    return None


NUMBER_RE = re.compile(r"\d+(\.\d{1,2})?")   # ASCII digits, max 2 decimals


def parse_amount(value: str, positive: bool = True, whole: bool = False) -> Decimal | None:
    try:
        if not value: return None
        value = str(value).strip()
        if not value or not value.isascii() or not NUMBER_RE.fullmatch(value):
            return None
        d = Decimal(value)
        if not d.is_finite() or (positive and d <= 0) or abs(d) > MAX_MONEY: return None
        if whole and d != d.to_integral_value(): return None
        if not whole and d.as_tuple().exponent < -2: return None
        return d
    except (InvalidOperation, ValueError, OverflowError):
        return None


def validate(df: pd.DataFrame) -> Result:
    missing = {column: 0 for column in REQUIRED_COLUMNS}
    evaluated: list[dict] = []
    all_issues: list[dict] = []
    for pos, (_, row) in enumerate(df.iterrows(), start=1):
        original = {k: clean_text(v) for k, v in row.items()}
        data = {k: clean_text(row[k]) for k in REQUIRED_COLUMNS}
        reasons: list[str] = []
        for key, value in data.items():
            if not value:
                missing[key] += 1
                reasons.append(f"Missing {key}")
        if data["order_id"] and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", data["order_id"]):
            reasons.append("Invalid order ID")
        if data["customer_id"] and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", data["customer_id"]):
            reasons.append("Invalid customer ID")
        if data["product"] and len(data["product"]) > 100: reasons.append("Invalid product")
        if data["city"] and len(data["city"]) > 100: reasons.append("Invalid city")
        date = parse_date(data["order_date"])
        if data["order_date"] and date is None: reasons.append("Invalid order date")
        quantity = parse_amount(data["quantity"], whole=True)
        if data["quantity"] and quantity is None: reasons.append("Invalid quantity")
        price = parse_amount(data["unit_price"])
        if data["unit_price"] and price is None: reasons.append("Invalid unit price")
        if quantity and price and quantity * price > MAX_MONEY: reasons.append("Revenue overflow")
        valid = not reasons
        normalized = {"order_id": data["order_id"], "order_date": date, "customer_id": data["customer_id"],
                      "city": " ".join(data["city"].split()).title(),
                      "product": " ".join(data["product"].split()).title(),
                      "quantity": int(quantity) if quantity is not None else None,
                      "unit_price": float(price) if price is not None else None,
                      "revenue": float((quantity * price).quantize(Decimal("0.01"))) if quantity is not None and price is not None else None,
                      "order_month": date[:7] if date else None}
        evaluated.append({"source_row": pos, "raw": original, "data": normalized, "reasons": reasons, "valid": valid})
        for reason in reasons: all_issues.append({"source_row": pos, "reason": reason, "column_name": reason.split(" ")[-1]})

    groups: dict[str, list[dict]] = {}
    for entry in evaluated:
        oid = entry["data"]["order_id"]
        if oid and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", oid):
            groups.setdefault(oid, []).append(entry)
    keep: set[int] = set()
    for rows in groups.values():
        chosen = next((r for r in rows if r["valid"]), rows[0])
        keep.add(chosen["source_row"])
    accepted, rejected, duplicates = [], [], []
    for entry in evaluated:
        oid = entry["data"]["order_id"]
        in_group = oid in groups
        is_duplicate = in_group and entry["source_row"] not in keep
        audit = {"source_row": entry["source_row"], "order_id": oid,
                 "raw_json": json.dumps(entry["raw"], ensure_ascii=False),
                 "reasons_json": json.dumps(entry["reasons"], ensure_ascii=False)}
        if is_duplicate:
            duplicates.append({**audit, "disposition": "duplicate_valid" if entry["valid"] else "duplicate_invalid"})
            all_issues.append({"source_row": entry["source_row"], "reason": "Duplicate order ID", "column_name": "order_id"})
        elif entry["valid"]:
            accepted.append(entry["data"])
        else:
            rejected.append(audit)
    assert len(df) == len(accepted) + len(rejected) + len(duplicates)
    return Result(pd.DataFrame(accepted, columns=REQUIRED_COLUMNS + ["revenue", "order_month"]),
                  pd.DataFrame(rejected, columns=["source_row", "order_id", "raw_json", "reasons_json"]),
                  pd.DataFrame(duplicates, columns=["source_row", "order_id", "raw_json", "reasons_json", "disposition"]),
                  pd.DataFrame(all_issues, columns=["source_row", "reason", "column_name"]),
                  len(df), missing)
