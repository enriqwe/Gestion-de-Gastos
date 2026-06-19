#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
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
STATE_DIR = BASE_DIR / "state"
DIRECT_DEBIT_REGISTRY_PATH = STATE_DIR / "direct_debit_registry.json"
DIRECT_DEBIT_ALERTS_PATH = STATE_DIR / "direct_debit_alerts.json"


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


def direct_debit_name(movement):
    text = " ".join((movement.get("description") or "").split())
    text = re.sub(r"^recibo\s+(?:de\s+)?", "", text, flags=re.IGNORECASE).strip()
    return text[:120] or "Sin descripción"


def direct_debit_key(name):
    return " ".join(name.lower().split())


def is_direct_debit(movement):
    return movement.get("amount", 0) < 0 and (movement.get("description") or "").strip().lower().startswith("recibo")


def load_json(path, fallback):
    if not path.exists():
        return fallback
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return fallback
    return value


def registry_from_movements(movements):
    registry = {}
    for movement in movements:
        if not is_direct_debit(movement):
            continue
        name = direct_debit_name(movement)
        key = direct_debit_key(name)
        current = registry.get(key)
        if not current or movement["date"] < current["first_seen"]:
            registry[key] = {
                "name": name,
                "first_seen": movement["date"],
                "source_file": movement.get("source_file", ""),
            }
    return registry


def detect_new_direct_debits(new_rows, known_registry, source_name):
    alerts = []
    seen = set(known_registry)
    for movement in new_rows:
        if not is_direct_debit(movement):
            continue
        name = direct_debit_name(movement)
        key = direct_debit_key(name)
        if key in seen:
            continue
        seen.add(key)
        alerts.append({
            "amount": abs(movement["amount"]),
            "date": movement["date"],
            "description": movement.get("description", ""),
            "key": key,
            "name": name,
            "source_file": source_name,
        })
    return alerts


def persist_direct_debit_watch(data, new_rows, source_name):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if DIRECT_DEBIT_REGISTRY_PATH.exists():
        registry = load_json(DIRECT_DEBIT_REGISTRY_PATH, {})
        if not isinstance(registry, dict):
            registry = {}
    else:
        new_ids = {row["id"] for row in new_rows}
        registry = registry_from_movements([row for row in data.get("movements", []) if row.get("id") not in new_ids])

    new_alerts = detect_new_direct_debits(new_rows, registry, source_name)
    now = datetime.now().isoformat(timespec="seconds")
    existing_alerts = load_json(DIRECT_DEBIT_ALERTS_PATH, [])
    if not isinstance(existing_alerts, list):
        existing_alerts = []
    for alert in new_alerts:
        existing_alerts.append({
            "detected_at": now,
            "first_amount": alert["amount"],
            "first_date": alert["date"],
            "key": alert["key"],
            "name": alert["name"],
            "source_file": alert["source_file"],
            "status": "new",
        })

    registry = registry_from_movements(data.get("movements", []))
    DIRECT_DEBIT_REGISTRY_PATH.write_text(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    DIRECT_DEBIT_ALERTS_PATH.write_text(json.dumps(existing_alerts, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return new_alerts


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


def remove_duplicate_movements(data):
    seen = set()
    unique = []
    removed = []
    for movement in data.get("movements", []):
        movement_key = movement.get("id") or movement_id(movement)
        if movement_key in seen:
            removed.append(movement)
            continue
        seen.add(movement_key)
        unique.append(movement)
    data["movements"] = unique
    return removed


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
    cleaned_duplicates = remove_duplicate_movements(data)
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
        "cleaned_existing_duplicates": len(cleaned_duplicates),
    }
    data["imports"].append(import_record)
    direct_debit_alerts = persist_direct_debit_watch(data, new_rows, source.name)
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    by_category = Counter(r["category"] or "Sin categoría" for r in new_rows if r["amount"] < 0)
    print(f"IMPORT_OK source={source.name} seen={len(parsed['rows'])} new={len(new_rows)} duplicates={len(duplicate_rows)} cleaned_existing_duplicates={len(cleaned_duplicates)} total={len(data['movements'])}")
    if by_category:
        print("NEW_EXPENSE_CATEGORIES " + ", ".join(f"{k}:{v}" for k, v in by_category.most_common(8)))
    if direct_debit_alerts:
        print("NEW_DIRECT_DEBIT_ALERTS " + " | ".join(f"{a['name']} {money(a['amount'])} {a['date']}" for a in direct_debit_alerts))


if __name__ == "__main__":
    main()
