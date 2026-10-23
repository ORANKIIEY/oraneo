import sqlite3
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import etl  # noqa: E402
from generate_data import generate  # noqa: E402


def test_transform_removes_duplicates_and_invalid_rows():
    raw = generate(500, seed=1)
    clean, rejected = etl.transform(raw)
    assert clean["order_id"].is_unique
    assert (clean["quantity"] > 0).all()
    assert clean["city"].notna().all()
    assert len(rejected) > 0


def test_revenue_is_quantity_times_price():
    raw = generate(200, seed=2)
    clean, _ = etl.transform(raw)
    assert (clean["revenue"] == clean["quantity"] * clean["unit_price"]).all()


def test_city_names_are_normalised():
    raw = generate(500, seed=3)
    clean, _ = etl.transform(raw)
    assert (clean["city"] == clean["city"].str.title()).all()


def test_extract_fails_on_missing_columns(tmp_path):
    bad = tmp_path / "bad.csv"
    pd.DataFrame({"order_id": [1]}).to_csv(bad, index=False)
    with pytest.raises(ValueError):
        etl.extract(str(bad))


def test_full_pipeline_loads_warehouse(tmp_path):
    raw = tmp_path / "raw.csv"
    generate(300, seed=4).to_csv(raw, index=False)
    db = tmp_path / "wh.db"
    stats = etl.run(str(raw), str(db), str(tmp_path / "processed"))
    with sqlite3.connect(db) as conn:
        n = conn.execute("SELECT COUNT(*) FROM fact_sales").fetchone()[0]
    assert n == stats["clean"]
    assert stats["clean"] + stats["rejected"] <= stats["raw"]
    assert stats["export_status"] == "complete"
    assert (tmp_path / "processed" / "sales_clean.csv").is_file()


def test_export_clean_csv_uses_database_as_source_of_truth(tmp_path):
    raw = tmp_path / "raw.csv"
    generate(100, seed=5).to_csv(raw, index=False)
    db = tmp_path / "wh.db"
    processed = tmp_path / "processed"
    etl.run(str(raw), str(db), str(processed))

    # Mutate a record directly in fact_sales database table
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE fact_sales SET city='SourceOfTruthCity' WHERE order_id=(SELECT order_id FROM fact_sales LIMIT 1)")
        conn.commit()

    # Regenerate CSV from database
    exported = etl.export_clean_csv(str(db), str(processed))
    assert exported.is_file()
    df = pd.read_csv(exported)
    assert "SourceOfTruthCity" in df["city"].values


def test_export_failure_preserves_committed_run_and_tracks_failed_status(tmp_path, monkeypatch):
    raw = tmp_path / "raw.csv"
    generate(100, seed=6).to_csv(raw, index=False)
    db = tmp_path / "wh.db"
    processed = tmp_path / "processed"

    # Simulate export failure after database commit
    def failing_export(*args, **kwargs):
        raise OSError("Simulated disk write failure")

    monkeypatch.setattr(etl, "export_clean_csv", failing_export)

    with pytest.raises(OSError, match="Simulated disk write failure"):
        etl.run(str(raw), str(db), str(processed))

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        run_row = conn.execute("SELECT status, export_status, export_error FROM pipeline_runs LIMIT 1").fetchone()
        assert run_row["status"] == "success"  # DB transaction committed and is preserved
        assert run_row["export_status"] == "failed"
        assert "Simulated disk write failure" in run_row["export_error"]


def test_retry_failed_exports_and_diagnostics(tmp_path, monkeypatch):
    raw = tmp_path / "raw.csv"
    generate(100, seed=7).to_csv(raw, index=False)
    db = tmp_path / "wh.db"
    processed = tmp_path / "processed"

    # Fail export first
    original_export = etl.export_clean_csv
    monkeypatch.setattr(etl, "export_clean_csv", lambda *a, **kw: (_ for _ in ()).throw(OSError("Disk failure")))

    with pytest.raises(OSError):
        etl.run(str(raw), str(db), str(processed))

    # Restore export function
    monkeypatch.setattr(etl, "export_clean_csv", original_export)

    # Check diagnostics before retry
    diag_before = etl.diagnostics(str(db), str(processed), retry_failed=False)
    assert diag_before["failed_exports"] == 1
    assert diag_before["export_status"] == "failed"

    # Diagnostics with retry_failed=True recovers the export
    diag_after = etl.diagnostics(str(db), str(processed), retry_failed=True)
    assert diag_after["failed_exports"] == 0
    assert diag_after["export_status"] == "complete"
    assert len(diag_after["retried_exports"]) == 1
    assert (processed / "sales_clean.csv").is_file()

    # Database run status has export_status complete
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        run_row = conn.execute("SELECT export_status FROM pipeline_runs LIMIT 1").fetchone()
        assert run_row["export_status"] == "complete"

