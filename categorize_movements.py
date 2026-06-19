#!/usr/bin/env python3
import argparse
import json
import re
import unicodedata
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_PATH = BASE_DIR / "gastos-repository" / "movements.json"
CUSTOM_RULES_PATH = BASE_DIR / "category_rules.json"
ORANGE_SAVINGS_IBAN = "ES57 1465 0100 92 2039535408"


def _fold(value):
    text = " ".join(str(value or "").split()).lower()
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(ch)
    )


def _matches(text, patterns):
    return any(re.search(pattern, text) for pattern in patterns)


def _rule_matches_amount(rule, movement):
    if rule.get("kind") == "income":
        return movement.get("amount", 0) > 0
    if rule.get("kind") == "expense":
        return movement.get("amount", 0) < 0
    return True


def movement_text(movement):
    return _fold(f"{movement.get('description', '')} {movement.get('comment', '')}")


def load_custom_rules():
    if not CUSTOM_RULES_PATH.exists():
        return []
    try:
        rules = json.loads(CUSTOM_RULES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(rules, list):
        return []
    return rules


ALWAYS_RULES = [
    {
        "name": "sueldo_enrique_movimiento_ing",
        "category": "Sueldo Enrique",
        "subcategory": "Sueldo",
        "kind": "income",
        "patterns": [
            r"\bmovimiento ing\b",
        ],
    },
    {
        "name": "orange_savings_transfer",
        "category": "Movimientos excluidos",
        "subcategory": "Traspaso entre cuentas",
        "patterns": [
            r"\bes57\s*1465\s*0100\s*92\s*2039535408\b",
            r"\b1465\s*0100\s*92\s*2039535408\b",
            r"\bmovimiento ing\b",
            r"\bfondo de emergencia\b",
        ],
    },
    {
        "name": "sueldo_enrique",
        "category": "Sueldo Enrique",
        "subcategory": "Sueldo",
        "kind": "income",
        "patterns": [
            r"\bsueldo\s+enri\b",
            r"\bsueldo\b.*\benri\b",
        ],
    },
    {
        "name": "sueldo_gabi",
        "category": "Sueldo Gabi",
        "subcategory": "Sueldo",
        "kind": "income",
        "patterns": [
            r"\bsueldo\s+gabi\b",
            r"\bsueldo\s+\w+\s+gabi\b",
            r"\bnomina\s+gabi\b",
            r"\bpaga\s+extra\b.*\bgabi\b",
            r"\b(?:aguinaldo|dietas|gastos)\b.*\bgabi\b",
            r"\bgabi\b.*\b(?:aguinaldo|dietas|gastos)\b",
        ],
    },
]


EXPENSE_RULES = [
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
    text = movement_text(movement)
    for rule in load_custom_rules():
        if (
            rule.get("text")
            and rule.get("category")
            and _rule_matches_amount(rule, movement)
            and text == rule["text"]
        ):
            return {
                "category": rule["category"],
                "subcategory": rule.get("subcategory", ""),
                "classification_rule": rule.get("name", "manual_rule"),
            }

    for rule in ALWAYS_RULES:
        if _rule_matches_amount(rule, movement) and _matches(text, rule["patterns"]):
            return {
                "category": rule["category"],
                "subcategory": rule["subcategory"],
                "classification_rule": rule["name"],
            }

    if movement.get("amount", 0) >= 0:
        return None

    for rule in EXPENSE_RULES:
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
