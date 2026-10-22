"""Catalog readiness. Writes docs/PRODUCT_READINESS.md and the CSV beside it."""
import asyncio
from pathlib import Path

from product_readiness import (
    catalog_items,
    counts_for,
    evaluate_all,
    render_csv,
    render_markdown,
    write_docs,
)


ROOT = Path(__file__).resolve().parents[2]


def test_every_print2go_catalog_item():
    rows = asyncio.run(evaluate_all())
    markdown, csv_text = write_docs(rows, ROOT)
    assert markdown == render_markdown(rows)
    assert csv_text == render_csv(rows)
    assert (ROOT / "docs" / "PRODUCT_READINESS.md").read_text(encoding="utf-8") == markdown
    assert (ROOT / "docs" / "PRODUCT_READINESS.csv").read_text(encoding="utf-8") == csv_text
    assert len(rows) == 139
    assert len(catalog_items()) == 139
    assert set(counts_for(rows)) <= {"pass", "fail", "unsupported", "n/a"}
    assert sum(counts_for(rows).values()) == 139
    assert "| Friction |" in markdown
    for row in rows:
        assert row["result"] in {"pass", "fail", "unsupported", "n/a"}
        assert row["friction"].strip()
        assert row["reason"].strip()
        assert row["fix"].strip()
    services = [row for row in rows if row["cause"] == "service"]
    assert len(services) == 5
    assert all(row["result"] == "n/a" for row in services)
    booklets = next(row for row in rows if row["product"] == "Booklets")
    assert booklets["result"] == "unsupported"
    giant = next(row for row in rows if row["product"] == "Giant Cheques")
    assert giant["result"] == "pass"
    assert "24" in giant["reason"]
    die = next(row for row in rows if row["product"] == "Die-Cut Stickers")
    assert die["result"] == "pass"
    assert die["fix"] != "—"
    labels = next(row for row in rows if row["product"] == "Rectangle Labels Sheet")
    assert labels["result"] == "unsupported"
    assert "safe zone" in labels["reason"]
    cardstock = next(row for row in rows if row["product"] == "Cardstock Posters")
    assert cardstock["result"] == "pass"
    assert "1200" in cardstock["reason"] and "150" in cardstock["reason"]
    storefront = next(row for row in rows if row["product"] == "Store Front Signs")
    assert storefront["result"] == "pass"
    assert "does not publish" in storefront["reason"]
    cheque = next(row for row in rows if row["product"].startswith("Business Laser Cheques (source 321)"))
    assert cheque["result"] == "unsupported"
    other = next(row for row in rows if row["product"].startswith("Business Laser Cheques (source 449)"))
    assert other["result"] == "pass"
    assert "MICR" in other["reason"]
    assert counts_for(rows).get("pass", 0) >= 80
    failures = [row for row in rows if row["result"] == "fail"]
    assert not failures, "; ".join(f"{row['product']}: {row['reason']}" for row in failures)
