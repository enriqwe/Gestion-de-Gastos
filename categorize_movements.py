#!/usr/bin/env python3
import argparse
import json
import re
import unicodedata
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "gastos-repository" / "movements.json"


def _fold(value):
    text = " ".join(str(value or "").split()).lower()
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )


def _matches(text, patterns):
    return any(re.search(pattern, text) for pattern in patterns)


CATEGORY_RULES = [
    {
        "name": "streaming",
        "category": "Streaming",
        "subcategory": "Suscripciones",
        "patterns": [
            r"\bdisney\s*plus\b",
            r"\bnetflix(?:\.com)?\b",
            r"\bskyshowtime\b",
            r"\bspotify(?:es)?\b",
            r"\bamazon prime\b",
            r"\bprime video\b",
            r"\bcompra de prime video\b",
            r"\byoutube\b",
            r"\bhbo\b",
            r"\bmax\.com\b",
            r"\bdazn\b",
            r"\bgoogle one\b",
        ],
    },
    {
        "name": "inversion",
        "category": "Inversión",
        "subcategory": "Aportaciones",
        "patterns": [
            r"\bmyinvestor\b",
            r"\bmy investor\b",
            r"\bindexa\b",
            r"\binteractive brokers\b",
            r"\binteractivebrokers\b",
            r"\bibkr\b",
        ],
    },
    {
        "name": "seguros",
        "category": "Seguros",
        "subcategory": "Primas",
        "patterns": [
            r"\blinea directa\b",
            r"\baseguradora\b",
            r"\bseguro\b",
        ],
    },
    {
        "name": "tarjetas_financiacion",
        "category": "Tarjetas y financiación",
        "subcategory": "Liquidaciones",
        "patterns": [
            r"\bbanco cetelem\b",
            r"\bamerican express\b",
        ],
    },
    {
        "name": "educacion_actividades",
        "category": "Educación y salud",
        "subcategory": "Colegio y actividades",
        "patterns": [
            r"\bclub deportivo gredos\b",
            r"\bmenudos delfines\b",
            r"\bcomedores blanco\b",
            r"\bsobre8ruedas\b",
            r"\bliceo europeo\b",
            r"\bschoolandsports\b",
            r"\bsport club campus\b",
            r"\bgymcampus\b",
            r"\bnuria espert\b",
            r"\bfundacion gsd\b",
            r"\bkitchen academy\b",
            r"\bblue valley beach\b",
            r"\bsaludsavia\b",
        ],
    },
    {
        "name": "viajes",
        "category": "Ocio y viajes",
        "subcategory": "Viajes",
        "patterns": [
            r"\bviajes acipiter\b",
        ],
    },
    {
        "name": "efectivo_cajeros",
        "category": "Efectivo y cajeros",
        "subcategory": "Retiradas y comisiones",
        "patterns": [
            r"\breintegro efectivo\b",
            r"\bcomision cajero\b",
        ],
    },
    {
        "name": "impuestos_tasas",
        "category": "Impuestos y tasas",
        "subcategory": "Administraciones públicas",
        "patterns": [
            r"\bpago de impuestos\b",
            r"\bayuntamiento de madrid\b",
        ],
    },
    {
        "name": "donaciones",
        "category": "Donaciones",
        "subcategory": "ONG y fundaciones",
        "patterns": [
            r"\bgreenpeace\b",
            r"\bfundacion carmen pardo\b",
        ],
    },
]


def classify_movement(movement):
    if movement.get("amount", 0) >= 0:
        return None

    text = _fold(f"{movement.get('description', '')} {movement.get('comment', '')}")
    for rule in CATEGORY_RULES:
        if _matches(text, rule["patterns"]):
            return {
                "category": rule["category"],
                "subcategory": rule["subcategory"],
                "classification_rule": rule["name"],
            }
    return None


def apply_category_rules(movement):
    classification = classify_movement(movement)
    if not classification:
        return False

    movement.setdefault("original_category", movement.get("category", ""))
    movement.setdefault("original_subcategory", movement.get("subcategory", ""))

    changed = (
        movement.get("category") != classification["category"]
        or movement.get("subcategory") != classification["subcategory"]
        or movement.get("classification_rule") != classification["classification_rule"]
    )
    movement.update(classification)
    return changed


def main():
    parser = argparse.ArgumentParser(description="Reclasifica movimientos existentes con reglas deterministas.")
    parser.add_argument("--dry-run", action="store_true", help="Muestra el impacto sin escribir movements.json")
    args = parser.parse_args()

    if not DATA_PATH.exists():
        raise SystemExit("No existe movements.json.")

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    changes = []
    for movement in data.get("movements", []):
        before = (movement.get("category", ""), movement.get("subcategory", ""))
        if apply_category_rules(movement):
            after = (movement.get("category", ""), movement.get("subcategory", ""))
            changes.append((movement.get("id"), movement.get("date"), movement.get("description"), before, after))

    print(f"CATEGORIZE_OK changes={len(changes)} dry_run={args.dry_run}")
    summary = {}
    for _, _, _, _, after in changes:
        summary[after[0]] = summary.get(after[0], 0) + 1
    for category, count in sorted(summary.items(), key=lambda item: (-item[1], item[0])):
        print(f"{category}: {count}")

    if not args.dry_run:
        DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
