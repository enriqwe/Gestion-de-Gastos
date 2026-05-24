#!/usr/bin/env python3
import argparse
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import xlrd

from categorize_movements import apply_category_rules


BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR / "gastos-repository"
DATA_PATH = REPO_DIR / "movements.json"
RAW_DIR = BASE_DIR / "raw"


HEADER = ["F. VALOR", "CATEGORÍA", "SUBCATEGORÍA", "DESCRIPCIÓN", "COMENTARIO", "IMPORTE (€)", "SALDO (€)"]


def money(value):
    if value in ("", None):
        return None
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def clean(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def date_value(book, sheet, row, col):
    cell = sheet.cell(row, col)
    if cell.ctype == xlrd.XL_CELL_DATE:
        return xlrd.xldate_as_datetime(cell.value, book.datemode).date().isoformat()
    text = clean(cell.value)
    if "T" in text:
        return text.split("T", 1)[0]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return text


def load_existing():
    if not DATA_PATH.exists():
        return {"schema": 1, "imports": [], "movements": []}
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


def movement_id(row):
    fields = [
        row["account"],
        row["date"],
        row["category"],
        row["subcategory"],
        row["description"],
        row["comment"],
        f'{row["amount"]:.2f}',
        "" if row["balance"] is None else f'{row["balance"]:.2f}',
    ]
    return hashlib.sha256("\u241f".join(fields).encode("utf-8")).hexdigest()[:24]


def parse_xls(path):
    book = xlrd.open_workbook(path)
    sheet = book.sheet_by_index(0)
    account = ""
    owner = ""
    exported_at = ""
    header_row = None

    for r in range(min(sheet.nrows, 20)):
        row = [clean(sheet.cell_value(r, c)) for c in range(sheet.ncols)]
        if row[: len(HEADER)] == HEADER:
            header_row = r
            break
        if "Número de cuenta:" in row:
            idx = row.index("Número de cuenta:")
            account = clean(row[idx + 1]) if idx + 1 < len(row) else ""
        if "Titular:" in row:
            idx = row.index("Titular:")
            owner = clean(row[idx + 1]) if idx + 1 < len(row) else ""
        if "Fecha exportación:" in row:
            idx = row.index("Fecha exportación:")
            exported_at = clean(row[idx + 1]) if idx + 1 < len(row) else ""

    if header_row is None:
        raise SystemExit("No encuentro la fila de cabeceras esperada en el Excel.")

    rows = []
    for r in range(header_row + 1, sheet.nrows):
        if all(clean(sheet.cell_value(r, c)) == "" for c in range(min(sheet.ncols, len(HEADER)))):
            continue
        row = {
            "account": account,
            "owner": owner,
            "date": date_value(book, sheet, r, 0),
            "category": clean(sheet.cell_value(r, 1)),
            "subcategory": clean(sheet.cell_value(r, 2)),
            "description": clean(sheet.cell_value(r, 3)),
            "comment": clean(sheet.cell_value(r, 4)),
            "amount": money(sheet.cell_value(r, 5)),
            "balance": money(sheet.cell_value(r, 6)),
            "source_file": path.name,
        }
        if row["amount"] is None or not row["date"]:
            continue
        row["id"] = movement_id(row)
        row["original_category"] = row["category"]
        row["original_subcategory"] = row["subcategory"]
        apply_category_rules(row)
        rows.append(row)

    return {
        "source_file": path.name,
        "account": account,
        "owner": owner,
        "exported_at": exported_at,
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser(description="Importa movimientos bancarios exportados a XLS.")
    parser.add_argument("xls", help="Ruta del Excel de movimientos")
    args = parser.parse_args()

    source = Path(args.xls).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"No existe el fichero: {source}")

    REPO_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    parsed = parse_xls(source)
    data = load_existing()
    existing_ids = {m["id"] for m in data["movements"]}

    new_rows = []
    duplicate_rows = []
    for row in parsed["rows"]:
        if row["id"] in existing_ids:
            duplicate_rows.append(row)
            continue
        new_rows.append(row)
        existing_ids.add(row["id"])

    data["movements"].extend(new_rows)
    data["movements"].sort(key=lambda m: (m["date"], m["description"], m["amount"]))

    imported_copy = RAW_DIR / source.name
    if not imported_copy.exists():
        shutil.copy2(source, imported_copy)

    import_record = {
        "source_file": source.name,
        "imported_at": datetime.now().isoformat(timespec="seconds"),
        "exported_at": parsed["exported_at"],
        "account": parsed["account"],
        "owner": parsed["owner"],
        "rows_seen": len(parsed["rows"]),
        "new_rows": len(new_rows),
        "duplicates": len(duplicate_rows),
    }
    data["imports"].append(import_record)
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    by_category = Counter(r["category"] or "Sin categoría" for r in new_rows if r["amount"] < 0)
    print(f"IMPORT_OK source={source.name} seen={len(parsed['rows'])} new={len(new_rows)} duplicates={len(duplicate_rows)} total={len(data['movements'])}")
    if by_category:
        print("NEW_EXPENSE_CATEGORIES " + ", ".join(f"{k}:{v}" for k, v in by_category.most_common(8)))


if __name__ == "__main__":
    main()
