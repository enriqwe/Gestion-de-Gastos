#!/usr/bin/env python3
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR / "gastos-repository"
DATA_PATH = REPO_DIR / "movements.json"
HTML_PATH = REPO_DIR / "index.html"
DIRECT_DEBIT_ALERTS_PATH = BASE_DIR / "state" / "direct_debit_alerts.json"


def money(value):
    return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def month_label(month):
    try:
        return datetime.strptime(month, "%Y-%m").strftime("%m/%Y")
    except Exception:
        return month or "-"


def pct_delta(now, prev):
    if not prev:
        return None
    return (now - prev) / prev * 100


def month_key(date_text):
    return (date_text or "")[:7]


def normalize_text(text):
    return re.sub(r"\s+", " ", (text or "")).strip()


def merchant(description):
    original = normalize_text(description)
    folded = (
        original.lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )
    if "myinvestor" in folded or "my investor" in folded:
        return "MyInvestor"
    if "movimiento ing" in folded and "enrique" in folded:
        return "Movimiento ING"
    if folded.startswith("cargo mensual tarjeta credito"):
        return "Tarjeta crédito ING"
    if folded.startswith("recibo "):
        return normalize_text(re.sub(r"^recibo\s+(?:de\s+)?", "", original, flags=re.IGNORECASE))[:80] or "Recibo"
    text = original
    prefixes = [
        "Pago en ",
        "Compra en ",
        "Bizum enviado a ",
        "Bizum recibido de ",
        "Transferencia de ",
        "Transferencia a ",
        "Transferencia emitida a ",
        "Abono por campaña ",
    ]
    for prefix in prefixes:
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text[:80] or "Sin descripción"


def direct_debit_name(movement):
    text = " ".join((movement.get("description") or "").split())
    text = re.sub(r"^recibo\s+(?:de\s+)?", "", text, flags=re.IGNORECASE).strip()
    return text[:120] or "Sin descripción"


def direct_debit_key(name):
    return " ".join(name.lower().split())


def is_direct_debit(movement):
    return movement.get("amount", 0) < 0 and (movement.get("description") or "").strip().lower().startswith("recibo")


def load_direct_debit_alerts():
    if not DIRECT_DEBIT_ALERTS_PATH.exists():
        return []
    try:
        alerts = json.loads(DIRECT_DEBIT_ALERTS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return alerts if isinstance(alerts, list) else []


def direct_debit_rows(movements):
    groups = {}
    for movement in movements:
        if not is_direct_debit(movement):
            continue
        name = direct_debit_name(movement)
        key = direct_debit_key(name)
        group = groups.setdefault(key, {"key": key, "name": name, "movements": []})
        group["movements"].append(movement)

    rows = []
    for group in groups.values():
        rows_for_group = group["movements"]
        amounts = [abs(m["amount"]) for m in rows_for_group]
        last = max(rows_for_group, key=lambda m: (m["date"], m["id"]))
        first_date = min(m["date"] for m in rows_for_group)
        last_date = last["date"]
        rows.append({
            "key": group["key"],
            "name": group["name"],
            "count": len(rows_for_group),
            "avgAmount": round(sum(amounts) / len(amounts), 2),
            "minAmount": round(min(amounts), 2),
            "maxAmount": round(max(amounts), 2),
            "firstDate": first_date,
            "lastDate": last_date,
            "lastAmount": round(abs(last["amount"]), 2),
            "category": last.get("category") or "Sin categoría",
            "subcategory": last.get("subcategory") or "Sin subcategoría",
        })
    return sorted(rows, key=lambda row: (row["lastDate"], row["avgAmount"]), reverse=True)


def school_year(month):
    if not month:
        return ""
    year = int(month[:4])
    mo = int(month[5:7])
    start = year if mo >= 9 else year - 1
    return f"{start}-{str(start + 1)[-2:]}"


def main():
    if not DATA_PATH.exists():
        raise SystemExit("No existe movements.json. Importa primero un Excel.")

    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    movements = raw.get("movements", [])
    for m in movements:
        m["month"] = month_key(m["date"])
        m["year"] = (m["date"] or "")[:4]
        m["kind"] = "expense" if m["amount"] < 0 else "income"
        m["absAmount"] = round(abs(m["amount"]), 2)
        m["merchant"] = merchant(m["description"])
        m["schoolYear"] = school_year(m["month"])

    expenses = [m for m in movements if m["amount"] < 0]
    income = [m for m in movements if m["amount"] > 0]
    months = sorted({m["month"] for m in movements if m["month"]})
    accounts = sorted({m["account"] for m in movements if m.get("account")})
    categories = sorted({m["category"] or "Sin categoría" for m in movements})
    subcategories = sorted({m["subcategory"] or "Sin subcategoría" for m in movements})

    monthly_expense = defaultdict(float)
    monthly_income = defaultdict(float)
    monthly_net = defaultdict(float)
    monthly_cat = defaultdict(lambda: defaultdict(float))
    by_category = defaultdict(float)
    by_subcategory = defaultdict(float)
    by_merchant = defaultdict(float)
    merchant_count = Counter()
    by_year = defaultdict(float)
    by_school_year = defaultdict(float)

    for m in movements:
        amount = m["amount"]
        monthly_net[m["month"]] += amount
        if amount < 0:
            value = abs(amount)
            monthly_expense[m["month"]] += value
            by_category[m["category"] or "Sin categoría"] += value
            by_subcategory[f'{m["category"] or "Sin categoría"} / {m["subcategory"] or "Sin subcategoría"}'] += value
            by_merchant[m["merchant"]] += value
            merchant_count[m["merchant"]] += 1
            monthly_cat[m["month"]][m["category"] or "Sin categoría"] += value
            by_year[m["year"]] += value
            by_school_year[m["schoolYear"]] += value
        elif amount > 0:
            monthly_income[m["month"]] += amount

    expense_total = sum(abs(m["amount"]) for m in expenses)
    income_total = sum(m["amount"] for m in income)
    net_total = income_total - expense_total
    expense_values = [monthly_expense[m] for m in months if monthly_expense[m] > 0]
    avg_month = expense_total / len(expense_values) if expense_values else 0
    median_month = statistics.median(expense_values) if expense_values else 0
    latest_month = months[-1] if months else ""
    previous_month = months[-2] if len(months) > 1 else ""
    max_month = max(months, key=lambda m: monthly_expense[m]) if months else ""
    latest_delta = pct_delta(monthly_expense[latest_month], monthly_expense[previous_month]) if latest_month and previous_month else None

    sorted_categories = sorted(by_category.items(), key=lambda item: item[1], reverse=True)
    sorted_subcategories = sorted(by_subcategory.items(), key=lambda item: item[1], reverse=True)
    sorted_merchants = sorted(by_merchant.items(), key=lambda item: item[1], reverse=True)
    top_category = sorted_categories[0] if sorted_categories else ("-", 0)
    top_merchant = sorted_merchants[0] if sorted_merchants else ("-", 0)
    direct_debits = direct_debit_rows(movements)
    direct_debit_alerts = load_direct_debit_alerts()

    insights = []

    payload = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "period": {
            "first": min((m["date"] for m in movements), default=""),
            "last": max((m["date"] for m in movements), default=""),
        },
        "imports": raw.get("imports", []),
        "accounts": accounts,
        "categories": [{"name": name, "total": round(total, 2), "share": total / expense_total * 100 if expense_total else 0} for name, total in sorted_categories],
        "subcategories": [{"name": name, "total": round(total, 2)} for name, total in sorted_subcategories],
        "merchants": [{"name": name, "total": round(total, 2), "count": merchant_count[name]} for name, total in sorted_merchants],
        "months": [{
            "month": month,
            "expense": round(monthly_expense[month], 2),
            "income": round(monthly_income[month], 2),
            "net": round(monthly_net[month], 2),
            "cats": dict(monthly_cat[month]),
        } for month in months],
        "years": [{"year": year, "total": round(total, 2)} for year, total in sorted(by_year.items())],
        "schoolYears": [{"year": year, "total": round(total, 2)} for year, total in sorted(by_school_year.items())],
        "directDebits": direct_debits,
        "directDebitAlerts": direct_debit_alerts,
        "movements": sorted(movements, key=lambda m: (m["date"], m["description"], m["amount"]), reverse=True),
        "insights": insights,
        "kpis": {
            "expenseTotal": round(expense_total, 2),
            "incomeTotal": round(income_total, 2),
            "netTotal": round(net_total, 2),
            "movementCount": len(movements),
            "expenseCount": len(expenses),
            "incomeCount": len(income),
            "monthCount": len(expense_values),
            "avgMonth": round(avg_month, 2),
            "medianMonth": round(median_month, 2),
            "latestMonth": latest_month,
            "latestMonthExpense": round(monthly_expense[latest_month], 2) if latest_month else 0,
            "latestDeltaPct": latest_delta,
            "maxMonth": max_month,
            "maxMonthExpense": round(monthly_expense[max_month], 2) if max_month else 0,
            "topCategory": top_category[0],
            "topCategoryTotal": round(top_category[1], 2),
            "topMerchant": top_merchant[0],
            "topMerchantTotal": round(top_merchant[1], 2),
        },
    }
    payload_json = json.dumps(payload, ensure_ascii=False).replace("</script>", "<\\/script>")

    html = r'''<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Centro de mando · Gastos personales</title>
<style>
:root{--bg:#080d1a;--panel:#111a2e;--panel2:#16233e;--line:#263655;--text:#eef4ff;--muted:#95a5c7;--soft:#c7d4f2;--accent:#7c5cff;--accent2:#18c7a7;--warn:#ffb020;--bad:#ff5d73;--good:#45d483;--blue:#4dabf7}*{box-sizing:border-box}body{margin:0;font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:radial-gradient(circle at 0 0,#203365 0,#080d1a 44%);color:var(--text)}a{color:#9cc8ff}.wrap{width:min(1480px,100%);margin:0 auto;padding:22px}.hero{display:grid;grid-template-columns:1fr auto;gap:18px;align-items:start;margin-bottom:18px}.hero-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:14px}.filter-toggle{display:inline-flex;align-items:center;gap:8px;font-weight:800;background:linear-gradient(180deg,#121d34,#0d1426);border-color:#344568}.filter-toggle span{font-size:15px}.filter-panel{display:none;margin-top:10px}.filter-panel.open{display:block}h1{margin:0;font-size:clamp(29px,4vw,50px);letter-spacing:0}.sub{color:var(--muted);margin-top:8px;line-height:1.45;max-width:900px}.badge,.pill{display:inline-block;border:1px solid #334360;background:#101a30;border-radius:999px;color:#c8d5f5}.badge{padding:9px 12px;white-space:nowrap}.pill{padding:3px 8px;font-size:12px}.grid{display:grid;gap:16px}.kpis{grid-template-columns:repeat(auto-fit,minmax(240px,1fr))}.card{background:linear-gradient(180deg,rgba(255,255,255,.052),rgba(255,255,255,.022));border:1px solid rgba(255,255,255,.09);box-shadow:0 18px 50px #0006;border-radius:22px;padding:18px;overflow:hidden}.card.tight{padding:14px}.kpi .label{color:var(--muted);font-size:13px}.kpi .value{font-size:clamp(22px,2.2vw,29px);font-weight:850;margin-top:8px;letter-spacing:0}.kpi .hint{color:#b8c4df;margin-top:8px;font-size:13px}.delta{font-weight:800}.delta.good{color:var(--good)}.delta.bad{color:var(--bad)}.delta.neutral{color:var(--muted)}.main{grid-template-columns:1.42fr .9fr;align-items:stretch;margin-top:16px}.two{grid-template-columns:1fr 1fr;margin-top:16px}.three{grid-template-columns:1.1fr 1fr 1fr;margin-top:16px}.distribution-stack{display:grid;grid-template-columns:1fr;gap:16px}h2{margin:0 0 13px;font-size:20px;letter-spacing:0}.section-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px}.chart{width:100%;height:370px}.chart.flow{height:650px;min-height:650px}.donut-split{display:grid;grid-template-columns:1fr 1fr;gap:12px}.donut-box{min-width:0}.donut-title{color:#c7d4f2;font-size:13px;font-weight:800;margin:0 0 6px}.donut-split .chart{height:330px}.controls,.upload-form{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0 0}.upload-form{align-items:center;padding:10px;border:1px solid #2f3d60;background:#0d1528;border-radius:14px;width:fit-content;max-width:100%}.upload-form input[type=file]{min-width:280px}.upload-form button{background:linear-gradient(180deg,#1e8f7d,#126f62);border-color:#25b99f}.statusline{color:var(--muted);font-size:13px}.insights,.mini-list{display:grid;gap:10px}.insight,.mini-item,.answer{border:1px solid #2b3a5c;background:#0d1528;border-radius:16px;padding:13px}.insight strong,.mini-item strong{display:block;margin-bottom:5px}.insight.good,.mini-item.good{border-color:#27684a}.insight.warn,.mini-item.warn{border-color:#70551d}.insight.bad,.mini-item.bad{border-color:#713043}.quick{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.answer .small{color:var(--muted);font-size:12px}.answer .big{font-weight:850;font-size:22px;margin-top:4px}.metric-row{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:center;border-bottom:1px solid rgba(255,255,255,.07);padding:8px 0}.metric-row:last-child{border-bottom:0}.meter{height:9px;background:#20304f;border-radius:999px;overflow:hidden;margin-top:7px}.meter span{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,var(--accent2),var(--accent))}.multi{position:relative;min-width:260px}.multi-btn{width:100%;min-height:42px;display:flex;align-items:center;justify-content:space-between;gap:10px;background:linear-gradient(180deg,#121d34,#0d1426);border-color:#344568}.multi-btn.active{border-color:var(--accent);box-shadow:0 0 0 3px rgba(124,92,255,.16)}.multi-btn-text{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.multi-menu{display:none;position:absolute;z-index:50;top:calc(100% + 8px);left:0;width:min(380px,92vw);max-height:430px;overflow:auto;padding:10px;background:linear-gradient(180deg,#121d34,#0b1222);border:1px solid #35486e;border-radius:18px;box-shadow:0 24px 70px #000b}.multi.open .multi-menu{display:block}.multi-actions{display:flex;gap:8px;margin-bottom:8px}.multi-actions button{flex:1;padding:8px 10px;border-radius:10px;font-size:12px}.multi-option{display:grid;grid-template-columns:22px 10px 1fr;gap:10px;align-items:center;padding:9px 10px;border-radius:13px;color:#dbe6ff;cursor:pointer}.multi-option:hover{background:rgba(255,255,255,.055)}.multi-option input{min-width:auto;accent-color:var(--accent)}.multi-option .swatch{width:10px;height:10px;border-radius:999px}.multi-option .count{color:var(--muted);font-size:12px}select,input,button{background:#0d1426;color:var(--text);border:1px solid #2f3d60;border-radius:12px;padding:10px 12px;outline:none}button{cursor:pointer}button:hover{border-color:#5870aa}input{min-width:220px;flex:1}.multi-option input{min-width:auto;flex:0;padding:0}table{width:100%;border-collapse:collapse;font-size:14px}th,td{border-bottom:1px solid rgba(255,255,255,.08);padding:10px 8px;text-align:left;vertical-align:top}th{color:#b9c6e4;font-size:12px;text-transform:uppercase;letter-spacing:.05em}.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}.negative{color:var(--bad)}.positive{color:var(--good)}.dot{width:10px;height:10px;border-radius:99px;display:inline-block}.footer{color:var(--muted);margin:24px 0 8px;font-size:13px}.mobile-note{display:none;color:var(--muted);font-size:13px}.money-map{display:grid;grid-template-columns:260px 1fr;gap:18px;align-items:stretch}.money-total{background:linear-gradient(180deg,#18c7a7,#0b927c);color:#06131b;border-radius:22px;padding:22px;display:flex;flex-direction:column;justify-content:center;min-height:220px}.money-total .label{font-size:13px;font-weight:800;text-transform:uppercase;opacity:.75}.money-total .value{font-size:33px;font-weight:950;margin-top:10px;letter-spacing:0}.money-total .meta{font-size:13px;margin-top:8px;opacity:.8}.money-cats{display:grid;gap:12px}.money-cat{background:#0d1528;border:1px solid #2b3a5c;border-radius:18px;padding:14px}.money-cat-head{display:grid;grid-template-columns:minmax(130px,1fr) auto auto;gap:12px;align-items:center}.money-bar{height:12px;background:#20304f;border-radius:999px;overflow:hidden;margin-top:10px}.money-fill{height:100%;border-radius:999px}.money-concepts{display:grid;gap:7px;margin-top:12px}.money-concept{display:grid;grid-template-columns:minmax(160px,1fr) minmax(90px,30%) 82px;gap:8px;align-items:center;color:#d8e2f6;font-size:12px}.money-concept-track{height:8px;background:#1e2c49;border-radius:99px;overflow:hidden}.money-concept-fill{height:100%;border-radius:99px}.explain-text{border-top:1px solid rgba(255,255,255,.08);margin-top:10px;padding-top:10px;color:#b9c6e4;font-size:13px;line-height:1.45}.explain-text strong{color:#eef4ff}@media(max-width:1050px){.wrap{padding:14px}.hero{display:block}.badge{margin-top:12px}.kpis,.main,.two,.three,.money-map,.donut-split{grid-template-columns:1fr}.quick{grid-template-columns:1fr}.chart{height:300px}.chart.flow{height:560px;min-height:560px}.donut-split .chart{height:300px}table{font-size:13px}.mobile-note{display:block}}@media(max-width:560px){th:nth-child(4),td:nth-child(4){display:none}.card{border-radius:18px;padding:14px}.hero-actions{width:100%}.filter-toggle{width:100%;justify-content:space-between}}
@media(max-width:560px){
  .wrap{padding:14px;overflow:hidden}
  h1{font-size:24px;line-height:1.12;overflow-wrap:anywhere;word-break:break-word}
  .controls{display:grid;grid-template-columns:1fr;width:100%}
  .controls>*{width:100%;min-width:0;max-width:100%}
  .multi{min-width:0;width:100%}
  .badge{display:block;white-space:normal;width:100%;overflow-wrap:anywhere}
  .sub,.statusline{white-space:normal;overflow-wrap:anywhere;word-break:break-word}
  .sub,#filterStatus{display:none}
}
.flow-legend{display:none}
@media(max-width:700px){
  .section-head{display:block}
  .section-head .statusline{display:block;margin-top:6px}
  h2{font-size:18px;line-height:1.22;overflow-wrap:anywhere}
  .chart.flow{height:380px;min-height:380px}
  .flow-legend{display:grid;gap:10px;margin-top:12px}
  .flow-legend-item{display:grid;grid-template-columns:12px minmax(0,1fr);gap:6px 8px;align-items:start;padding:10px;border:1px solid #273757;background:#0d1528;border-radius:14px}
  .flow-legend-swatch{width:12px;height:12px;border-radius:4px;margin-top:3px}
  .flow-legend-name{font-weight:800;color:#eef4ff;overflow-wrap:anywhere}
  .flow-legend-detail{grid-column:2;color:#b9c6e4;font-size:12px;line-height:1.35;overflow-wrap:anywhere}
  .flow-legend-amount{grid-column:2;font-variant-numeric:tabular-nums;color:#dbe6ff;font-size:12px}
}
.date-range{position:relative;min-width:230px}
.date-range-btn{width:100%;min-height:42px;display:flex;align-items:center;justify-content:space-between;gap:10px;background:linear-gradient(180deg,#121d34,#0d1426);border-color:#344568}
.date-range-btn.active{border-color:var(--accent);box-shadow:0 0 0 3px rgba(124,92,255,.16)}
.date-range-menu{display:none;position:absolute;z-index:60;top:calc(100% + 8px);left:0;width:min(330px,92vw);padding:12px;background:linear-gradient(180deg,#121d34,#0b1222);border:1px solid #35486e;border-radius:18px;box-shadow:0 24px 70px #000b}
.date-range.open .date-range-menu{display:grid;gap:10px}
.date-range-row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.date-range label{display:grid;gap:6px;color:#b9c6e4;font-size:12px}
.date-range input{min-width:0;width:100%}
.date-range-actions{display:flex;gap:8px}
.date-range-actions button{flex:1;padding:8px 10px;border-radius:10px;font-size:12px}
.row-action{padding:7px 10px;border-radius:10px;font-size:12px;white-space:nowrap}
.modal-backdrop{display:none;position:fixed;inset:0;z-index:100;background:rgba(3,7,15,.72);padding:18px;align-items:center;justify-content:center}
.modal-backdrop.open{display:flex}
.modal{width:min(560px,100%);background:linear-gradient(180deg,#121d34,#0b1222);border:1px solid #35486e;border-radius:18px;box-shadow:0 28px 90px #000c;padding:18px}
.modal h2{margin-bottom:8px}
.modal-form{display:grid;gap:12px;margin-top:14px}
.modal-form label{display:grid;gap:6px;color:#b9c6e4;font-size:12px}
.modal-form input[type=text],.modal-form select{width:100%;min-width:0}
.new-value-wrap{display:none!important}
.new-value-wrap.open{display:grid!important}
.modal-check{display:flex;gap:10px;align-items:flex-start;color:#dbe6ff;font-size:13px;line-height:1.35}
.modal-check input{min-width:auto;margin-top:2px}
.modal-actions{display:flex;gap:10px;justify-content:flex-end;margin-top:14px}
.modal-actions button{min-width:110px}
.modal-primary{background:linear-gradient(180deg,#1e8f7d,#126f62);border-color:#25b99f}
.modal-danger{color:#ffb8c4}
.desc-chip{min-width:150px}
.desc-chip summary{display:inline-flex;align-items:center;width:max-content;max-width:100%;padding:6px 9px;border:1px solid #334360;border-radius:999px;background:#101a30;color:#c8d5f5;font-size:12px;cursor:pointer}
.desc-chip div{margin-top:8px;max-width:520px;color:#dbe6ff;line-height:1.35;white-space:normal}
details.disclosure>summary{list-style:none;display:flex;justify-content:space-between;align-items:center;gap:12px;cursor:pointer}
details.disclosure>summary::-webkit-details-marker{display:none}
.disclosure-icon{font-size:18px;color:#c7d4f2}
details.disclosure[open] .disclosure-icon{transform:rotate(180deg)}
.disclosure-body{margin-top:14px}
.debit-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:14px 0}
.debit-alerts{display:grid;gap:10px;margin:10px 0 14px}
.debit-alert{border:1px solid #70551d;background:#19140b;border-radius:14px;padding:12px}
.debit-table-wrap{overflow:auto}
.debit-table td:first-child,.debit-table th:first-child{min-width:260px}
</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <div>
      <h1>Centro de mando de gastos personales</h1>
      <div class="sub">Movimientos bancarios importados con deduplicación. Vista preparada para cargar nuevos Excel periódicamente y explotar gasto, ingresos, categorías, comercios y meses anómalos.</div>
      <div class="hero-actions"><button id="toggleFilters" class="filter-toggle" type="button">Filtros y acciones <span>⌄</span></button></div>
      <div id="filtersPanel" class="filter-panel">
        <div class="controls">
        <input id="search" placeholder="Buscar descripción, comercio, categoría…">
        <div class="date-range" id="dateRangeFilter">
          <button id="dateRangeButton" class="date-range-btn" type="button"><span id="dateRangeText">Desde / hasta</span><span>⌄</span></button>
          <div class="date-range-menu" id="dateRangeMenu">
            <div class="date-range-row">
              <label>Desde<input id="dateFromPicker" type="date"></label>
              <label>Hasta<input id="dateToPicker" type="date"></label>
            </div>
            <div class="date-range-actions"><button id="dateRangeApply" type="button">Aplicar</button><button id="dateRangeClear" type="button">Limpiar fechas</button></div>
          </div>
          <input id="dateFrom" type="hidden">
          <input id="dateTo" type="hidden">
        </div>
        <select id="kindFilter"><option value="">Gastos e ingresos</option><option value="expense">Solo gastos</option><option value="income">Solo ingresos</option></select>
        <select id="accountFilter"><option value="">Todas las cuentas</option></select>
        <div class="multi" id="categoryFilter">
          <button id="categoryButton" class="multi-btn" type="button"><span id="categoryButtonText" class="multi-btn-text">Todas las categorías</span><span>⌄</span></button>
          <div class="multi-menu" id="categoryMenu">
            <div class="multi-actions"><button id="selectAllCategories" type="button">Seleccionar todas</button><button id="clearCategories" type="button">Limpiar</button></div>
            <div id="categoryOptions"></div>
          </div>
        </div>
        <select id="monthFilter"><option value="">Todos los meses</option></select>
        <button id="currentYear">Año actual</button><button id="lastMonth">Último mes</button><button id="last12">Últimos 12 meses</button><button id="allDates">Todo</button><button id="resetView">Limpiar filtros</button><button id="exportCsv">Exportar CSV</button>
      </div>
      <form class="upload-form" action="/upload" method="post" enctype="multipart/form-data">
        <select name="bank" required>
          <option value="">Banco</option>
          <option value="ing">ING</option>
          <option value="bankinter" disabled>Bankinter: pendiente</option>
          <option value="caixa" disabled>CaixaBank: pendiente</option>
        </select>
        <input type="file" name="movement_file" accept=".xls" required>
        <button type="submit">Incluir movimientos</button>
      </form>
      <div class="statusline" id="filterStatus" style="margin-top:8px"></div>
      </div>
    </div>
    <div class="badge" id="generated"></div>
  </header>

  <section class="card priority-card">
    <div class="section-head"><h2>Evolución mensual</h2><span class="statusline">gasto, ingresos y neto</span></div>
    <div id="monthlyChart" class="chart"></div>
  </section>

  <section class="card" style="margin-top:16px">
    <div class="section-head"><h2>Sankey: cómo se ha ido el dinero</h2><span class="statusline">total → categorías → comercios principales</span></div>
    <div id="moneyFlow" class="chart flow"></div>
    <div id="moneyFlowLegend" class="flow-legend"></div>
  </section>

  <section class="card" style="margin-top:16px">
    <details class="disclosure" id="summaryDetails" open>
      <summary><div><h2>KPIs y lecturas rápidas</h2><div class="statusline">totales, medias y señales del periodo filtrado</div></div><span class="disclosure-icon">⌄</span></summary>
      <section class="grid kpis disclosure-body">
        <div class="card tight kpi"><div class="label">Gastos</div><div class="value negative" id="kExpenses"></div><div class="hint" id="kExpensesHint"></div></div>
        <div class="card tight kpi"><div class="label">Ingresos / abonos</div><div class="value positive" id="kIncome"></div><div class="hint" id="kIncomeHint"></div></div>
        <div class="card tight kpi"><div class="label">Neto</div><div class="value" id="kNet"></div><div class="hint">ingresos menos gastos</div></div>
        <div class="card tight kpi"><div class="label">Gastos mensuales</div><div class="value negative" id="kAvgExpense"></div><div class="hint" id="kAvgExpenseHint"></div></div>
        <div class="card tight kpi"><div class="label">Ingresos mensuales</div><div class="value positive" id="kAvgIncome"></div><div class="hint" id="kAvgIncomeHint"></div></div>
      </section>
      <div class="insights" id="insights"></div>
    </details>
  </section>

  <section class="card" style="margin-top:16px">
    <details class="disclosure" id="distributionDetails">
      <summary><div><h2>Distribución y comercios</h2><div class="statusline">categorías, ingresos y ranking de conceptos</div></div><span class="disclosure-icon">⌄</span></summary>
      <section class="distribution-stack disclosure-body">
        <div class="card tight"><div class="section-head"><h2>Reparto por categoría</h2><span class="statusline">click para filtrar</span></div><div class="donut-split"><div class="donut-box"><div class="donut-title">Gastos</div><div id="expenseDonutChart" class="chart"></div></div><div class="donut-box"><div class="donut-title">Ingresos</div><div id="incomeDonutChart" class="chart"></div></div></div></div>
        <div class="card tight"><div class="section-head"><h2>Ranking de comercios y conceptos</h2><span class="statusline">click para filtrar</span></div><div class="statusline" style="margin:-4px 0 10px">Excluye las transferencias de inversión a MyInvestor y los traspasos a Enrique con concepto Movimiento ING para que no tapen el gasto operativo.</div><div id="merchantChart" class="chart"></div></div>
      </section>
    </details>
  </section>

  <section class="card" style="margin-top:16px">
    <details class="disclosure" id="analysisDetails">
      <summary><div><h2>Análisis financiero</h2><div class="statusline">alertas, concentración y calidad de clasificación</div></div><span class="disclosure-icon">⌄</span></summary>
      <section class="grid three disclosure-body">
        <div class="card tight"><div class="section-head"><h2>Respuestas rápidas</h2></div><div class="quick">
          <div class="answer"><div class="small">¿Dónde se va más?</div><div class="big" id="qWhere"></div><div class="small" id="qWhere2"></div></div>
          <div class="answer"><div class="small">¿Qué mes vigilar?</div><div class="big" id="qWatch"></div><div class="small" id="qWatch2"></div></div>
          <div class="answer"><div class="small">Movimiento medio</div><div class="big" id="qAvgMove"></div><div class="small">solo gastos</div></div>
          <div class="answer"><div class="small">Comercio dominante</div><div class="big" id="qMerchant"></div><div class="small" id="qMerchant2"></div></div>
        </div></div>
        <div class="card tight"><div class="section-head"><h2>Alertas explicadas</h2></div><div id="anomalyChart" class="chart" style="height:260px"></div><div id="anomalyPanel" class="explain-text"></div></div>
        <div class="card tight"><div class="section-head"><h2>Calidad de clasificación</h2></div><div id="qualityChart" class="chart" style="height:260px"></div><div id="qualityPanel" class="explain-text"></div></div>
      </section>
    </details>
  </section>

  <section class="card" style="margin-top:16px">
    <details class="disclosure" id="directDebitDetails">
      <summary><div><h2>Domiciliaciones</h2><div class="statusline">recibos detectados, importes medios y últimas cargas</div></div><span class="disclosure-icon">⌄</span></summary>
      <div id="directDebitAlerts" class="debit-alerts"></div>
      <div class="debit-summary">
        <div class="answer"><div class="small">Domiciliaciones activas</div><div class="big" id="ddCount"></div><div class="small">conceptos únicos</div></div>
        <div class="answer"><div class="small">Gasto medio mensual</div><div class="big" id="ddMonthlyAvg"></div><div class="small">sobre meses con recibos</div></div>
        <div class="answer"><div class="small">Último recibo</div><div class="big" id="ddLatest"></div><div class="small" id="ddLatestName"></div></div>
      </div>
      <div class="debit-table-wrap"><table class="debit-table" id="directDebitTable"><thead><tr><th>Domiciliación</th><th class="num">Importe medio</th><th>Activa desde</th><th>Último recibo</th><th class="num">Último importe</th><th class="num">Recibos</th></tr></thead><tbody></tbody></table></div>
    </details>
  </section>

  <section class="card" style="margin-top:16px">
    <details class="disclosure" id="historyDetails">
      <summary><div><h2>Histórico y subcategorías</h2><div class="statusline">comparativa anual y concentración</div></div><span class="disclosure-icon">⌄</span></summary>
      <section class="grid two disclosure-body">
        <div><div class="section-head"><h2>Año en curso vs año anterior</h2><span class="statusline">comparativa fija, independiente de los filtros</span></div><div id="yearCompareChart" class="chart"></div></div>
        <div><div class="section-head"><h2>Comparativa anual</h2><span class="statusline">por año natural</span></div><div id="yearChart" class="chart"></div></div>
        <div><div class="section-head"><h2>Concentración por subcategoría</h2><span class="statusline">top 12</span></div><div id="subcatChart" class="chart"></div></div>
      </section>
    </details>
  </section>

  <section class="card" style="margin-top:16px">
    <details class="disclosure" id="detailDetails">
      <summary><div><h2>Detalle y exploración</h2><div class="statusline">tabla de movimientos filtrados</div></div><span class="disclosure-icon">⌄</span></summary>
      <div class="mobile-note">En móvil se ocultan algunas columnas.</div>
      <div class="statusline" id="tableStatus"></div>
      <div style="overflow:auto"><table id="movementTable"><thead><tr><th>Fecha</th><th>Categoría</th><th>Concepto genérico</th><th>Descripción completa</th><th class="num">Importe</th><th class="num">Saldo</th><th>Acción</th></tr></thead><tbody></tbody></table></div>
    </details>
  </section>

  <div class="footer">Nota: las categorías y subcategorías son las que vienen en la exportación bancaria. El importador conserva el fichero original y evita duplicados por huella del movimiento.</div>
</div>
<div class="modal-backdrop" id="recategorizeModal">
  <div class="modal">
    <div class="section-head"><h2>Recategorizar movimiento</h2><button id="recatClose" type="button">Cerrar</button></div>
    <div class="statusline" id="recatMovementText"></div>
    <div class="modal-form">
      <label>Categoría<select id="recatCategory"></select></label>
      <label id="recatNewCategoryWrap" class="new-value-wrap">Nueva categoría<input id="recatNewCategory" type="text" autocomplete="off"></label>
      <label>Subcategoría<select id="recatSubcategory"></select></label>
      <label id="recatNewSubcategoryWrap" class="new-value-wrap">Nueva subcategoría<input id="recatNewSubcategory" type="text" autocomplete="off"></label>
      <label class="modal-check"><input id="recatApplySimilar" type="checkbox" checked><span>Aplicar también a movimientos con la misma descripción y guardar regla para futuras importaciones</span></label>
      <div class="statusline modal-danger" id="recatStatus"></div>
      <div class="modal-actions"><button id="recatCancel" type="button">Cancelar</button><button id="recatSave" class="modal-primary" type="button">Guardar</button></div>
    </div>
  </div>
</div>
<script src="vendor/echarts.min.js"></script>
<script id="data" type="application/json">__PAYLOAD__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
let activeCategories = [];
let activeMerchant = '';
const colors = ['#7c5cff','#18c7a7','#ffb020','#ff5d73','#4dabf7','#45d483','#d67cff','#8aa4ff','#ff8f5a','#5de4ff'];
const fmt = v => new Intl.NumberFormat('es-ES',{style:'currency',currency:'EUR'}).format(v || 0);
const fmt0 = v => new Intl.NumberFormat('es-ES',{style:'currency',currency:'EUR',maximumFractionDigits:0}).format(Math.round(v || 0));
const pct = v => v == null || !isFinite(v) ? '—' : `${v>0?'+':''}${v.toFixed(1)}%`;
const monthLabel = m => { if(!m) return '—'; const [y,mo]=m.split('-'); return `${mo}/${y}`; };
const el = id => document.getElementById(id);
const sum = (arr, fn) => arr.reduce((a,x)=>a+(fn?fn(x):x),0);
const uniq = arr => [...new Set(arr)].filter(Boolean);
const truncate = (s,n) => (s||'').length>n ? s.slice(0,n-1)+'…' : (s||'');
const esc = s => String(s??'').replace(/[&<>"']/g, ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
function descriptionChip(text){
  return `<details class="desc-chip"><summary>Ver descripción</summary><div>${esc(text||'')}</div></details>`;
}
function isExcludedMerchantRankingConcept(name){
  const text=(name||'').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/\s+/g,' ').trim();
  if(text==='myinvestor' || text==='movimiento ing') return true;
  const isMyInvestorTransfer=text.includes('transferencia emitida') && text.includes('enrique salas alvaro') && (text.includes('myinvestor') || text.includes('my investor'));
  const isOwnIngTransfer=text.includes('traspaso emitido') && text.includes('enrique') && text.includes('movimiento ing');
  const isEnriqueIngTransfer=text.includes('transferencia emitida') && text.includes('enrique') && text.includes(' ing');
  return isMyInvestorTransfer || isOwnIngTransfer || isEnriqueIngTransfer;
}
function isInvestmentCategory(name){
  return (name||'').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').trim()==='inversion';
}
let recatMovement = null;
function deltaClass(v){return v == null || Math.abs(v)<8 ? 'neutral' : v>0 ? 'bad' : 'good'}
function formatIsoDate(value){if(!value) return ''; const [y,m,d]=value.split('-'); return `${d}/${m}/${y}`}
function currentFilters(){return {search:el('search').value,dateFrom:el('dateFrom').value,dateTo:el('dateTo').value,kind:el('kindFilter').value,account:el('accountFilter').value,categories:activeCategories,merchant:activeMerchant,month:el('monthFilter').value}}
function normalizeFilters(){if(el('dateFrom').value && el('dateTo').value && el('dateFrom').value > el('dateTo').value){const a=el('dateFrom').value; el('dateFrom').value=el('dateTo').value; el('dateTo').value=a; syncDateRangeControls()}}
function categoryLabel(){return activeCategories.length ? activeCategories.length===1 ? activeCategories[0] : `${activeCategories.length} categorías seleccionadas` : 'Todas las categorías'}
function setCategories(values){activeCategories=[...new Set(values||[])].filter(Boolean)}
function toggleCategory(category){if(!category) return; const set=new Set(activeCategories); set.has(category)?set.delete(category):set.add(category); activeCategories=[...set]; renderAll()}
function toggleMerchant(merchant){if(!merchant) return; activeMerchant = activeMerchant===merchant ? '' : merchant; renderAll()}
function toggleCategoryChartFilter(category, kind=''){
  if(!category) return;
  const sameCategory=activeCategories.length===1 && activeCategories[0]===category && !activeMerchant && el('kindFilter').value===(kind||'');
  activeCategories=sameCategory ? [] : [category];
  el('kindFilter').value=sameCategory ? '' : (kind||'');
  activeMerchant='';
  renderAll();
}
function toggleMerchantChartFilter(merchant){
  if(!merchant) return;
  const sameMerchant=activeMerchant===merchant && activeCategories.length===0;
  activeMerchant=sameMerchant ? '' : merchant;
  activeCategories=[];
  renderAll();
}
function toggleMonthChartFilter(month){
  if(!month) return;
  el('monthFilter').value = el('monthFilter').value === month ? '' : month;
  renderAll();
}
function monthEndDate(month){
  if(!month) return '';
  const [year, monthNumber]=month.split('-').map(Number);
  const lastDay=new Date(year, monthNumber, 0).getDate();
  return `${month}-${String(lastDay).padStart(2,'0')}`;
}
function last12Range(){
  const months=DATA.months.map(m=>m.month), from=months.at(-12), to=months.at(-1);
  return {from: from ? from+'-01' : '', to: monthEndDate(to)};
}
function lastMonthRange(){
  const month=DATA.months.map(m=>m.month).at(-1);
  return {from: month ? month+'-01' : '', to: monthEndDate(month)};
}
function setDateRange(from='', to='', shouldRender=true){
  el('dateFrom').value=from || '';
  el('dateTo').value=to || '';
  syncDateRangeControls();
  if(shouldRender) renderAll();
}
function applyLast12(shouldRender=true){const r=last12Range(); setDateRange(r.from, r.to, shouldRender)}
function applyLastMonth(shouldRender=true){const r=lastMonthRange(); setDateRange(r.from, r.to, shouldRender)}
function syncDateRangeControls(){
  const from=el('dateFrom').value, to=el('dateTo').value;
  el('dateFromPicker').value=from;
  el('dateToPicker').value=to;
  el('dateRangeText').textContent=from || to ? `${formatIsoDate(from)||'inicio'} → ${formatIsoDate(to)||'fin'}` : 'Desde / hasta';
  el('dateRangeButton').classList.toggle('active', Boolean(from || to));
}
function filteredMovements(){
  normalizeFilters();
  const f=currentFilters(), q=f.search.toLowerCase();
  return DATA.movements.filter(m=>{
    const cat=m.category||'Sin categoría';
    const hay=(m.date+' '+m.category+' '+m.subcategory+' '+m.description+' '+m.comment+' '+m.merchant+' '+m.account).toLowerCase();
    if(f.dateFrom && m.date < f.dateFrom) return false;
    if(f.dateTo && m.date > f.dateTo) return false;
    if(f.kind && m.kind !== f.kind) return false;
    if(f.account && m.account !== f.account) return false;
    if(f.month && m.month !== f.month) return false;
    if(f.categories.length && !f.categories.includes(cat)) return false;
    if(f.merchant && m.merchant !== f.merchant) return false;
    if(q && !hay.includes(q)) return false;
    return true;
  }).sort((a,b)=>b.date.localeCompare(a.date) || b.id.localeCompare(a.id));
}
function expenseAmount(m){return m.amount < 0 ? Math.abs(m.amount) : 0}
function computeView(rows){
  const expenses=rows.filter(m=>m.amount<0), income=rows.filter(m=>m.amount>0);
  const monthly={}, cats={}, incomeCats={}, subcats={}, merchants={}, merchantCount={}, years={};
  rows.forEach(m=>{
    monthly[m.month] ||= {month:m.month,expense:0,income:0,net:0,cats:{}};
    monthly[m.month].net += m.amount;
    if(m.amount<0){
      const v=Math.abs(m.amount), cat=m.category||'Sin categoría', sub=`${cat} / ${m.subcategory||'Sin subcategoría'}`;
      monthly[m.month].expense += v; monthly[m.month].cats[cat]=(monthly[m.month].cats[cat]||0)+v;
      cats[cat]=(cats[cat]||0)+v; subcats[sub]=(subcats[sub]||0)+v; merchants[m.merchant]=(merchants[m.merchant]||0)+v; merchantCount[m.merchant]=(merchantCount[m.merchant]||0)+1; years[m.year]=(years[m.year]||0)+v;
    } else if(m.amount>0) {
      const cat=m.category||'Sin categoría';
      monthly[m.month].income += m.amount;
      incomeCats[cat]=(incomeCats[cat]||0)+m.amount;
    }
  });
  const months=Object.values(monthly).sort((a,b)=>a.month.localeCompare(b.month));
  const expenseTotal=sum(expenses, m=>Math.abs(m.amount)), incomeTotal=sum(income,m=>m.amount), netTotal=incomeTotal-expenseTotal;
  const expenseMonths=months.filter(m=>m.expense>0), incomeMonths=months.filter(m=>m.income>0), vals=expenseMonths.map(m=>m.expense), sortedVals=[...vals].sort((a,b)=>a-b), mid=Math.floor(sortedVals.length/2);
  const median=sortedVals.length ? (sortedVals.length%2 ? sortedVals[mid] : (sortedVals[mid-1]+sortedVals[mid])/2) : 0;
  const latest=months.at(-1), prev=months.at(-2), maxMonth=expenseMonths.length ? expenseMonths.reduce((a,b)=>a.expense>b.expense?a:b) : null;
  const catRows=Object.entries(cats).sort((a,b)=>b[1]-a[1]).map(([name,total])=>({name,total,share:expenseTotal?total/expenseTotal*100:0}));
  const analysisCatRows=catRows.filter(row=>!isInvestmentCategory(row.name));
  const analysisExpenseTotal=sum(analysisCatRows, row=>row.total);
  const incomeCatRows=Object.entries(incomeCats).sort((a,b)=>b[1]-a[1]).map(([name,total])=>({name,total,share:incomeTotal?total/incomeTotal*100:0}));
  const merchantRows=Object.entries(merchants).filter(([name])=>!isExcludedMerchantRankingConcept(name)).sort((a,b)=>b[1]-a[1]).map(([name,total])=>({name,total,count:merchantCount[name]}));
  const v={rows,expenses,income,months,categories:catRows,incomeCategories:incomeCatRows,subcategories:Object.entries(subcats).sort((a,b)=>b[1]-a[1]).map(([name,total])=>({name,total})),merchants:merchantRows,years:Object.entries(years).sort().map(([year,total])=>({year,total})),kpis:{expenseTotal,incomeTotal,netTotal,movementCount:rows.length,expenseCount:expenses.length,incomeCount:income.length,monthCount:expenseMonths.length,incomeMonthCount:incomeMonths.length,avgMonth:expenseMonths.length?expenseTotal/expenseMonths.length:0,avgIncomeMonth:incomeMonths.length?incomeTotal/incomeMonths.length:0,medianMonth:median,latestMonth:latest?.month||'',latestMonthExpense:latest?.expense||0,latestMonthIncome:latest?.income||0,latestDeltaPct:latest&&prev&&prev.expense?(latest.expense-prev.expense)/prev.expense*100:null,maxMonth:maxMonth?.month||'',maxMonthExpense:maxMonth?.expense||0,topCategory:analysisCatRows[0]?.name||'—',topCategoryTotal:analysisCatRows[0]?.total||0,topCategoryBaseTotal:analysisExpenseTotal,topMerchant:merchantRows[0]?.name||'—',topMerchantTotal:merchantRows[0]?.total||0}};
  v.insights=makeInsights(v);
  return v;
}
function makeInsights(v){
  if(!v.rows.length) return [{title:'Sin datos para estos filtros',body:'Amplía fechas o elimina filtros para recuperar la vista.',tone:'warn'}];
  return [];
}
function cleanChartText(option){
  const font='Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif', clean={fontFamily:font,color:'#c7d4f2',textBorderWidth:0,textShadowBlur:0};
  const apply=o=>{if(o&&typeof o==='object') Object.assign(o,clean)};
  apply(option.textStyle ||= {});
  ['xAxis','yAxis'].forEach(axis=>(Array.isArray(option[axis])?option[axis]:[option[axis]].filter(Boolean)).forEach(a=>{apply(a.axisLabel ||= {}); apply(a.nameTextStyle ||= {})}));
  (Array.isArray(option.series)?option.series:[option.series].filter(Boolean)).forEach(s=>{apply(s.label ||= {}); if(s.emphasis) apply(s.emphasis.label ||= {})});
  if(option.legend) apply(option.legend.textStyle ||= {});
  return option;
}
function setChart(id, option){
  if(!window.echarts){el(id).innerHTML='<div class="statusline" style="padding:28px">No se ha podido cargar ECharts.</div>'; return null}
  const key='_'+id; if(window[key]?.dispose) window[key].dispose();
  const chart=window[key]=echarts.init(el(id), null, {renderer:'svg'});
  chart.setOption(cleanChartText({backgroundColor:'transparent', textStyle:{color:'#c7d4f2'}, ...option}));
  requestAnimationFrame(()=>chart.resize());
  window.addEventListener('resize', ()=>chart.resize(), {passive:true});
  return chart;
}
function resizeCharts(){
  Object.keys(window).filter(k=>k.startsWith('_')).forEach(k=>{
    const chart=window[k];
    if(chart && typeof chart.resize==='function') requestAnimationFrame(()=>chart.resize());
  });
}
function noData(id,msg='Sin datos con estos filtros'){el(id).innerHTML=`<div class="statusline" style="padding:28px">${msg}</div>`}
function renderKpis(v){
  const k=v.kpis;
  el('generated').textContent='Última generación: '+DATA.generatedAt.replace('T',' ');
  el('kExpenses').textContent=fmt0(k.expenseTotal); el('kExpensesHint').textContent=`${k.expenseCount} gastos · ${k.monthCount} meses`;
  el('kIncome').textContent=fmt0(k.incomeTotal); el('kIncomeHint').textContent=`${k.incomeCount} ingresos o abonos · ${k.incomeMonthCount} meses`;
  el('kNet').textContent=fmt0(k.netTotal); el('kNet').className='value '+(k.netTotal>=0?'positive':'negative');
  el('kAvgExpense').textContent=fmt0(k.avgMonth); el('kAvgExpenseHint').innerHTML=`media de ${k.monthCount} meses · último mes ${fmt0(k.latestMonthExpense)} (${monthLabel(k.latestMonth)}, <span class="delta ${deltaClass(k.latestDeltaPct)}">${pct(k.latestDeltaPct)}</span>)`;
  el('kAvgIncome').textContent=fmt0(k.avgIncomeMonth); el('kAvgIncomeHint').textContent=`media de ${k.incomeMonthCount} meses · último mes ${fmt0(k.latestMonthIncome)} (${monthLabel(k.latestMonth)})`;
  el('qWhere').textContent=k.topCategory; el('qWhere2').textContent=`${fmt(k.topCategoryTotal)} · ${k.topCategoryBaseTotal?(k.topCategoryTotal/k.topCategoryBaseTotal*100).toFixed(1):0}% sin inversión`;
  el('qWatch').textContent=monthLabel(k.maxMonth); el('qWatch2').textContent=`máximo del periodo: ${fmt(k.maxMonthExpense)}`;
  el('qAvgMove').textContent=fmt(k.expenseCount?k.expenseTotal/k.expenseCount:0);
  el('qMerchant').textContent=truncate(k.topMerchant,28); el('qMerchant2').textContent=fmt(k.topMerchantTotal);
}
function renderInsights(v){el('insights').innerHTML=v.insights.map(i=>`<div class="insight ${i.tone||''}"><strong>${i.title}</strong><div class="statusline">${i.body}</div></div>`).join('')}
function renderMonthly(v){
  if(!v.months.length) return noData('monthlyChart');
  const activeMonth=el('monthFilter').value;
  const monthItem=(m,value,color)=>({value,month:m.month,itemStyle:{color,opacity:activeMonth && activeMonth!==m.month ? .36 : 1,borderColor:activeMonth===m.month ? '#eef4ff' : 'transparent',borderWidth:activeMonth===m.month ? 2 : 0}});
  const chart=setChart('monthlyChart',{tooltip:{trigger:'axis'},legend:{top:0},grid:{left:70,right:28,top:42,bottom:42},xAxis:{type:'category',data:v.months.map(m=>monthLabel(m.month))},yAxis:{type:'value',axisLabel:{formatter:x=>fmt(x).replace(',00 €','')}},series:[{name:'Gasto',type:'bar',data:v.months.map(m=>monthItem(m,m.expense,'#ff5d73'))},{name:'Ingresos',type:'bar',data:v.months.map(m=>monthItem(m,m.income,'#45d483'))},{name:'Neto',type:'line',data:v.months.map(m=>({value:m.net,month:m.month,symbolSize:activeMonth===m.month ? 11 : 7})),smooth:true,itemStyle:{color:'#4dabf7'}}]});
  chart?.on('click', p=>toggleMonthChartFilter(p?.data?.month || v.months[p?.dataIndex]?.month));
  chart?.getZr?.().setCursorStyle('pointer');
}
function renderYearComparison(){
  const latestDataYear=Math.max(...DATA.months.map(m=>Number(m.month.slice(0,4))).filter(Boolean));
  const calendarYear=new Date().getFullYear();
  const currentYear=DATA.months.some(m=>m.month.startsWith(String(calendarYear))) ? calendarYear : latestDataYear;
  if(!currentYear) return noData('yearCompareChart');
  const previousYear=currentYear-1;
  const currentCalendarYear=new Date().getFullYear();
  const monthLimit=currentYear===currentCalendarYear ? new Date().getMonth()+1 : 12;
  const months=Array.from({length:monthLimit},(_,i)=>String(i+1).padStart(2,'0'));
  const base=months.reduce((acc,mo)=>({ ...acc, [`${currentYear}-${mo}`]:{expense:0,income:0}, [`${previousYear}-${mo}`]:{expense:0,income:0} }), {});
  DATA.movements.forEach(m=>{
    if(!base[m.month]) return;
    if(m.amount<0) base[m.month].expense += Math.abs(m.amount);
    if(m.amount>0) base[m.month].income += m.amount;
  });
  setChart('yearCompareChart',{
    tooltip:{trigger:'axis',axisPointer:{type:'shadow'},formatter:items=>items.map(p=>`${p.marker}${p.seriesName}: <b>${fmt(p.value)}</b>`).join('<br>')},
    legend:{top:0,type:'scroll'},
    grid:{left:70,right:24,top:52,bottom:42},
    xAxis:{type:'category',data:months.map(mo=>monthLabel(`${currentYear}-${mo}`))},
    yAxis:{type:'value',axisLabel:{formatter:x=>fmt(x).replace(',00 €','')}},
    series:[
      {name:`Gasto ${currentYear}`,type:'bar',data:months.map(mo=>Math.round(base[`${currentYear}-${mo}`].expense*100)/100),itemStyle:{color:'#ff5d73'}},
      {name:`Gasto ${previousYear}`,type:'bar',data:months.map(mo=>Math.round(base[`${previousYear}-${mo}`].expense*100)/100),itemStyle:{color:'#9b3242'}},
      {name:`Ingresos ${currentYear}`,type:'bar',data:months.map(mo=>Math.round(base[`${currentYear}-${mo}`].income*100)/100),itemStyle:{color:'#45d483'}},
      {name:`Ingresos ${previousYear}`,type:'bar',data:months.map(mo=>Math.round(base[`${previousYear}-${mo}`].income*100)/100),itemStyle:{color:'#217d57'}}
    ]
  });
}
function renderDonut(v){
  renderPie('expenseDonutChart', v.categories, 'No hay gastos con estos filtros', 'expense');
  renderPie('incomeDonutChart', v.incomeCategories, 'No hay ingresos con estos filtros', 'income');
}
function renderPie(id, rows, emptyMsg, kind=''){
  if(!rows.length) return noData(id, emptyMsg);
  const activeKind=el('kindFilter').value;
  const chart=setChart(id,{tooltip:{trigger:'item',formatter:p=>`${p.name}<br><b>${fmt(p.value)}</b> · ${p.percent}%`},legend:{bottom:0,type:'scroll'},series:[{type:'pie',radius:['42%','72%'],center:['50%','43%'],data:rows.slice(0,12).map((c,i)=>({name:c.name,value:c.total,itemStyle:{color:colors[i%colors.length],opacity:activeCategories.length && !activeCategories.includes(c.name) ? .38 : 1,borderColor:activeCategories.length===1 && activeCategories[0]===c.name && activeKind===(kind||'') ? '#eef4ff' : 'transparent',borderWidth:activeCategories.length===1 && activeCategories[0]===c.name && activeKind===(kind||'') ? 2 : 0}})),label:{formatter:p=>truncate(p.name,16)}}]});
  chart?.on('click', p=>toggleCategoryChartFilter(p?.name, kind));
  chart?.getZr?.().setCursorStyle('pointer');
}
function renderMerchantChart(v){
  const rows=v.merchants.slice(0,15).reverse();
  if(!rows.length) return noData('merchantChart');
  const chart=setChart('merchantChart',{tooltip:{trigger:'item',formatter:p=>`${esc(p.data?.merchant||p.name)}<br><b>${fmt(p.value)}</b>`},grid:{left:160,right:24,top:18,bottom:28},xAxis:{type:'value',axisLabel:{formatter:x=>fmt(x).replace(',00 €','')}},yAxis:{type:'category',data:rows.map(r=>truncate(r.name,25)),axisTick:{show:false}},series:[{type:'bar',data:rows.map((r,i)=>({name:r.name,merchant:r.name,value:r.total,itemStyle:{color:colors[i%colors.length],opacity:activeMerchant && activeMerchant!==r.name ? .38 : 1,borderColor:activeMerchant===r.name ? '#eef4ff' : 'transparent',borderWidth:activeMerchant===r.name ? 2 : 0}})),label:{show:true,position:'right',formatter:p=>fmt(p.value).replace(',00 €','')}}]});
  chart?.on('click', p=>toggleMerchantChartFilter(p?.data?.merchant || p?.name));
  chart?.getZr?.().setCursorStyle('pointer');
}
function renderMoneyFlow(v){
  try{
    if(!v.categories.length || !v.kpis.expenseTotal) return noData('moneyFlow');
    if(!window.echarts){el('moneyFlow').innerHTML='<div class="statusline" style="padding:28px">No se ha podido cargar ECharts.</div>'; return}
    const container=el('moneyFlow');
    const isMobile=container.clientWidth < 620 || window.matchMedia('(max-width: 700px)').matches;
    const catLimit=isMobile ? 3 : 4;
    const merchantLimit=isMobile ? 2 : 3;
    const topCats=v.categories.slice(0,catLimit), catNames=new Set(topCats.map(c=>c.name));
    const restTotal=sum(v.categories.slice(catLimit), c=>c.total);
    const cats=restTotal>1 ? [...topCats,{name:'Resto de categorías',total:restTotal,share:restTotal/v.kpis.expenseTotal*100,rest:true}] : topCats;
    const totalNode='total';
    const nodes=[{name:totalNode,labelName:`Gasto filtrado\n${fmt(v.kpis.expenseTotal)}`,desktopLabel:`${fmt(v.kpis.expenseTotal)}`,mobileLabel:`${fmt(v.kpis.expenseTotal)}`,value:v.kpis.expenseTotal,share:100,depth:0,itemStyle:{color:'#18c7a7'}}];
    const links=[];
    const labelByName={total:nodes[0].labelName};
    cats.forEach((cat,idx)=>{
      const catNode=`cat:${idx}`;
      const catLabel=`${truncate(cat.name,30)}\n${cat.share.toFixed(1)}%`;
      nodes.push({name:catNode,labelName:catLabel,desktopLabel:catLabel,mobileLabel:catLabel,value:cat.total,share:cat.share,depth:1,itemStyle:{color:colors[idx%colors.length]}});
      labelByName[catNode]=nodes.at(-1).labelName;
      links.push({source:totalNode,target:catNode,value:Math.max(0.01,cat.total)});

      const merchantTotals={};
      v.expenses.forEach(m=>{
        const name=m.category||'Sin categoría';
        const belongs=cat.rest ? !catNames.has(name) : name===cat.name;
        if(belongs) merchantTotals[m.merchant]=(merchantTotals[m.merchant]||0)+Math.abs(m.amount);
      });
      const merchants=Object.entries(merchantTotals).sort((a,b)=>b[1]-a[1]);
      const topMerchants=merchants.slice(0,merchantLimit);
      const other=sum(merchants.slice(merchantLimit), row=>row[1]);
      const rows=other>1 ? [...topMerchants,['Otros conceptos',other]] : topMerchants;
      rows.forEach(([name,total],j)=>{
        const merchantNode=`merchant:${idx}:${j}`;
        const merchantShare=v.kpis.expenseTotal ? total/v.kpis.expenseTotal*100 : 0;
        const merchantLabel=`${truncate(name,34)}\n${fmt(total)}`;
        const mobileMerchantLabel=merchantShare >= 6 || total >= v.kpis.expenseTotal*.12 ? truncate(name,24) : '';
        nodes.push({name:merchantNode,labelName:merchantLabel,desktopLabel:merchantLabel,mobileLabel:mobileMerchantLabel,value:total,share:merchantShare,depth:2,itemStyle:{color:colors[idx%colors.length]}});
        labelByName[merchantNode]=nodes.at(-1).labelName;
        links.push({source:catNode,target:merchantNode,value:Math.max(0.01,total)});
      });
    });
    const legend=el('moneyFlowLegend');
    if(legend){
      legend.innerHTML=cats.map((cat,idx)=>{
        const related=links.filter(link=>link.source===`cat:${idx}`).slice(0,3).map(link=>{
          const target=nodes.find(node=>node.name===link.target);
          return `${esc((target?.labelName||'').split('\n')[0])} · ${fmt(link.value)}`;
        }).join('<br>');
        return `<div class="flow-legend-item"><span class="flow-legend-swatch" style="background:${colors[idx%colors.length]}"></span><div class="flow-legend-name">${esc(cat.name)}</div><div class="flow-legend-amount">${fmt(cat.total)}</div><div class="flow-legend-detail">${related}</div></div>`;
      }).join('');
    }
    if(window._moneyFlow && typeof window._moneyFlow.dispose==='function') window._moneyFlow.dispose();
    const chart=window._moneyFlow=echarts.init(container, null, {renderer:'svg'});
    chart.setOption(cleanChartText({
      tooltip:{trigger:'item',triggerOn:'mousemove',formatter:p=>{
        if(p.dataType==='edge') return `${(labelByName[p.data.source]||p.data.source).replaceAll('\n',' ')} → ${(labelByName[p.data.target]||p.data.target).replaceAll('\n',' ')}<br><b>${fmt(p.data.value)}</b>`;
        return `${(p.data.labelName||p.name).replaceAll('\n','<br>')}<br><b>${fmt(p.data.value||0)}</b>`;
      }},
      series:[{
        type:'sankey',
        left:isMobile?8:28,right:isMobile?8:310,top:isMobile?16:30,bottom:isMobile?16:30,
        nodeWidth:isMobile?12:22,nodeGap:isMobile?22:34,nodeAlign:'justify',layoutIterations:isMobile?32:0,draggable:false,
        emphasis:{focus:'adjacency'},
        label:{show:true,color:'#eef4ff',fontSize:isMobile?11:12,lineHeight:isMobile?14:15,formatter:p=>isMobile ? (p.data.mobileLabel||'') : (p.data.desktopLabel||p.data.labelName||p.name),overflow:'break',width:isMobile?112:220},
        levels:[
          {depth:0,label:{position:'right',width:isMobile?104:170,fontWeight:800}},
          {depth:1,label:{position:'right',width:isMobile?126:190,fontWeight:isMobile?800:500}},
          {depth:2,label:{position:'right',width:isMobile?112:260,fontSize:isMobile?10:11}}
        ],
        lineStyle:{color:'gradient',opacity:.34,curveness:.5},
        itemStyle:{borderWidth:0,borderRadius:5},
        data:nodes,
        links
      }]
    }));
    requestAnimationFrame(()=>chart.resize());
    window.addEventListener('resize',()=>chart.resize(),{passive:true});
  }catch(err){
    console.error('Error renderizando Sankey', err);
    el('moneyFlow').innerHTML='<div class="statusline" style="padding:28px">No he podido renderizar el Sankey con estos filtros.</div>';
  }
}
function renderAnalysis(v){
  const deltas=[]; for(let i=1;i<v.months.length;i++){const prev=v.months[i-1], cur=v.months[i]; if(prev.expense) deltas.push({month:cur.month,delta:cur.expense-prev.expense,pct:(cur.expense-prev.expense)/prev.expense*100})}
  const anomalies=deltas.filter(d=>Math.abs(d.delta)>500 && Math.abs(d.pct)>20).sort((a,b)=>Math.abs(b.delta)-Math.abs(a.delta)).slice(0,6).reverse();
  if(anomalies.length){
    setChart('anomalyChart',{grid:{left:78,right:20,top:14,bottom:24},tooltip:{trigger:'axis'},xAxis:{type:'value',axisLabel:{formatter:x=>fmt(Math.abs(x)).replace(',00 €','')}},yAxis:{type:'category',data:anomalies.map(d=>monthLabel(d.month))},series:[{type:'bar',data:anomalies.map(d=>({value:d.delta,itemStyle:{color:d.delta>0?'#ffb020':'#45d483'}})),label:{show:true,position:'right',formatter:p=>fmt(Math.abs(p.value)).replace(',00 €','')}}]});
    const main=anomalies.at(-1); el('anomalyPanel').innerHTML=`<strong>Qué muestra:</strong> meses con cambios fuertes respecto al mes anterior visible.<br><strong>Lectura:</strong> ${monthLabel(main.month)} tuvo ${main.delta>0?'una subida':'una bajada'} de ${fmt(Math.abs(main.delta))} (${pct(main.pct)}).`;
  } else {noData('anomalyChart','Sin anomalías relevantes'); el('anomalyPanel').textContent='No hay saltos mensuales fuertes con estos filtros.'}
  const total=v.kpis.expenseTotal, excluded=v.categories.find(c=>c.name==='Movimientos excluidos')?.total||0, uncategorized=v.categories.find(c=>c.name==='Sin categoría')?.total||0, other=v.categories.find(c=>c.name==='Otros gastos')?.total||0;
  const quality=[{name:'Mov. excluidos',value:total?excluded/total*100:0,color:excluded?'#ffb020':'#18c7a7'},{name:'Otros gastos',value:total?other/total*100:0,color:other/total>.2?'#ffb020':'#4dabf7'},{name:'Sin categoría',value:total?uncategorized/total*100:0,color:uncategorized?'#ff5d73':'#18c7a7'}];
  setChart('qualityChart',{grid:{left:110,right:28,top:18,bottom:24},tooltip:{trigger:'axis',formatter:ps=>ps.map(p=>`${p.name}: <b>${p.value.toFixed(1)}%</b>`).join('<br>')},xAxis:{type:'value',axisLabel:{formatter:x=>`${x}%`}},yAxis:{type:'category',data:quality.map(x=>x.name)},series:[{type:'bar',data:quality.map(x=>({value:x.value,itemStyle:{color:x.color}})),label:{show:true,position:'right',formatter:p=>`${p.value.toFixed(1)}%`}}]});
  el('qualityPanel').innerHTML=`<strong>Qué muestra:</strong> cuánto gasto queda en bolsas poco explicativas.<br><strong>Lectura:</strong> “Otros gastos” pesa ${(total?other/total*100:0).toFixed(1)}% (${fmt(other)}). Si pesa demasiado, conviene crear reglas propias sobre descripción/comercio.`;
}
function renderYears(v){
  if(!v.years.length) return noData('yearChart');
  setChart('yearChart',{tooltip:{trigger:'axis'},grid:{left:70,right:24,top:18,bottom:34},xAxis:{type:'category',data:v.years.map(r=>r.year)},yAxis:{type:'value',axisLabel:{formatter:x=>fmt(x).replace(',00 €','')}},series:[{type:'bar',data:v.years.map((r,i)=>({value:r.total,itemStyle:{color:colors[i%colors.length]}})),label:{show:true,position:'top',formatter:p=>fmt(p.value).replace(',00 €','')}}]});
}
function renderSubcats(v){
  const rows=v.subcategories.slice(0,12).reverse();
  if(!rows.length) return noData('subcatChart');
  setChart('subcatChart',{tooltip:{trigger:'axis'},grid:{left:190,right:24,top:18,bottom:28},xAxis:{type:'value',axisLabel:{formatter:x=>fmt(x).replace(',00 €','')}},yAxis:{type:'category',data:rows.map(r=>truncate(r.name,32))},series:[{type:'bar',data:rows.map((r,i)=>({value:r.total,itemStyle:{color:colors[i%colors.length]}})),label:{show:true,position:'right',formatter:p=>fmt(p.value).replace(',00 €','')}}]});
}
function renderDirectDebits(){
  const rows=[...(DATA.directDebits||[])].sort((a,b)=>b.lastDate.localeCompare(a.lastDate) || b.avgAmount-a.avgAmount);
  const alerts=(DATA.directDebitAlerts||[]).filter(a=>a.status!=='reviewed').slice().sort((a,b)=>(b.detected_at||'').localeCompare(a.detected_at||''));
  const months=new Set(DATA.movements.filter(m=>m.description?.toLowerCase().startsWith('recibo')).map(m=>m.month).filter(Boolean));
  const latest=rows[0];
  el('ddCount').textContent=rows.length;
  el('ddMonthlyAvg').textContent=fmt(months.size ? sum(rows, r=>r.avgAmount*r.count)/months.size : 0);
  el('ddLatest').textContent=latest ? formatIsoDate(latest.lastDate) : '—';
  el('ddLatestName').textContent=latest ? `${truncate(latest.name,36)} · ${fmt(latest.lastAmount)}` : 'sin recibos detectados';
  el('directDebitAlerts').innerHTML=alerts.length ? alerts.map(a=>`<div class="debit-alert"><strong>Nueva domiciliación pendiente de revisar</strong><div class="statusline">${esc(a.name)} · ${fmt(a.first_amount)} · ${formatIsoDate(a.first_date)} · ${esc(a.source_file||'')}</div></div>`).join('') : '';
  el('directDebitDetails').open = alerts.length > 0;
  el('directDebitTable').querySelector('tbody').innerHTML=rows.map(r=>`<tr><td>${esc(r.name)}<br><span class="statusline">${esc(r.category)} / ${esc(r.subcategory)}</span></td><td class="num">${fmt(r.avgAmount)}<br><span class="statusline">${fmt(r.minAmount)}–${fmt(r.maxAmount)}</span></td><td>${formatIsoDate(r.firstDate)}</td><td>${formatIsoDate(r.lastDate)}</td><td class="num negative">${fmt(r.lastAmount)}</td><td class="num">${r.count}</td></tr>`).join('');
}
function renderTable(v){
  const rows=v.rows.slice(0,300);
  el('tableStatus').textContent=`${v.rows.length} movimientos · ${fmt(v.kpis.expenseTotal)} en gastos · ${fmt(v.kpis.incomeTotal)} en ingresos · mostrando ${rows.length}`;
  el('movementTable').querySelector('tbody').innerHTML=rows.map(m=>`<tr><td>${esc(m.date)}</td><td>${esc(m.category)}<br><span class="statusline">${esc(m.subcategory||'')}</span></td><td><strong>${esc(m.merchant||'')}</strong></td><td>${descriptionChip(m.description)}</td><td class="num ${m.amount<0?'negative':'positive'}">${fmt(m.amount)}</td><td class="num">${m.balance==null?'':fmt(m.balance)}</td><td><button class="row-action" type="button" data-recat="${esc(m.id)}">Recategorizar</button></td></tr>`).join('');
  el('movementTable').querySelectorAll('[data-recat]').forEach(btn=>btn.addEventListener('click',()=>openRecategorize(btn.dataset.recat)));
}
function renderCategoryFilter(){
  const cats=uniq(DATA.movements.map(m=>m.category||'Sin categoría')).sort();
  el('categoryButtonText').textContent=categoryLabel();
  el('categoryButton').classList.toggle('active', activeCategories.length>0);
  el('categoryOptions').innerHTML=cats.map((c,i)=>`<label class="multi-option"><input type="checkbox" value="${c.replaceAll('"','&quot;')}" ${activeCategories.includes(c)?'checked':''}><span class="swatch" style="background:${colors[i%colors.length]}"></span><span>${c}<br><span class="count">${DATA.movements.filter(m=>(m.category||'Sin categoría')===c).length} movimientos</span></span></label>`).join('');
  el('categoryOptions').querySelectorAll('input').forEach(input=>input.addEventListener('change',()=>toggleCategory(input.value)));
}
function setupFilters(){
  setupRecategorizeOptions();
  DATA.accounts.forEach(a=>el('accountFilter').insertAdjacentHTML('beforeend',`<option value="${a}">${a}</option>`));
  DATA.months.slice().sort((a,b)=>b.month.localeCompare(a.month)).forEach(m=>el('monthFilter').insertAdjacentHTML('beforeend',`<option value="${m.month}">${monthLabel(m.month)}</option>`));
  el('toggleFilters').addEventListener('click',()=>{
    const panel=el('filtersPanel'), open=!panel.classList.contains('open');
    panel.classList.toggle('open', open);
    el('toggleFilters').innerHTML=`Filtros y acciones <span>${open?'⌃':'⌄'}</span>`;
  });
  ['search','kindFilter','accountFilter','monthFilter'].forEach(id=>el(id).addEventListener('input',renderAll));
  el('dateRangeButton').addEventListener('click',()=>el('dateRangeFilter').classList.toggle('open'));
  document.addEventListener('click',e=>{if(!el('dateRangeFilter').contains(e.target)) el('dateRangeFilter').classList.remove('open')});
  ['dateFromPicker','dateToPicker'].forEach(id=>el(id).addEventListener('input',()=>{
    el('dateFrom').value=el('dateFromPicker').value;
    el('dateTo').value=el('dateToPicker').value;
    syncDateRangeControls();
    renderAll();
  }));
  el('dateRangeApply').addEventListener('click',()=>{el('dateRangeFilter').classList.remove('open'); renderAll()});
  el('dateRangeClear').addEventListener('click',()=>{setDateRange('', ''); el('dateRangeFilter').classList.remove('open')});
  el('categoryButton').addEventListener('click',()=>el('categoryFilter').classList.toggle('open'));
  document.addEventListener('click',e=>{if(!el('categoryFilter').contains(e.target)) el('categoryFilter').classList.remove('open')});
  el('selectAllCategories').addEventListener('click',()=>{setCategories(uniq(DATA.movements.map(m=>m.category||'Sin categoría')).sort()); renderAll()});
  el('clearCategories').addEventListener('click',()=>{setCategories([]); renderAll()});
  el('resetView').addEventListener('click',()=>{['search','kindFilter','accountFilter','monthFilter'].forEach(id=>el(id).value=''); setCategories([]); activeMerchant=''; applyLast12()});
  el('allDates').addEventListener('click',()=>{el('monthFilter').value=''; setDateRange('', '')});
  el('currentYear').addEventListener('click',()=>{el('monthFilter').value=''; const y=new Date().getFullYear(); setDateRange(`${y}-01-01`, `${y}-12-31`)});
  el('lastMonth').addEventListener('click',()=>{el('monthFilter').value=''; applyLastMonth()});
  el('last12').addEventListener('click',()=>{el('monthFilter').value=''; applyLast12()});
  el('exportCsv').addEventListener('click',exportCsv);
  document.querySelectorAll('details.disclosure').forEach(details=>details.addEventListener('toggle',()=>{if(details.open) setTimeout(resizeCharts, 80)}));
  setupRecategorizeModal();
  applyLast12(false);
}
function setupRecategorizeOptions(){
  const categories=uniq(DATA.movements.map(m=>m.category||'Sin categoría')).sort();
  const subcategories=uniq(DATA.movements.map(m=>m.subcategory).filter(Boolean)).sort();
  el('recatCategory').innerHTML=categories.map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('')+'<option value="__new__">Nueva categoría...</option>';
  el('recatSubcategory').innerHTML='<option value="">Sin subcategoría</option>'+subcategories.map(c=>`<option value="${esc(c)}">${esc(c)}</option>`).join('')+'<option value="__new__">Nueva subcategoría...</option>';
}
function setSelectValue(select, value){
  if(value && ![...select.options].some(option=>option.value===value)){
    select.insertAdjacentHTML('beforeend', `<option value="${esc(value)}">${esc(value)}</option>`);
  }
  select.value=value||'';
}
function syncNewValueControls(){
  const newCategory=el('recatCategory').value==='__new__';
  const newSubcategory=el('recatSubcategory').value==='__new__';
  el('recatNewCategoryWrap').classList.toggle('open', newCategory);
  el('recatNewSubcategoryWrap').classList.toggle('open', newSubcategory);
  if(newCategory) el('recatNewCategory').focus();
  if(newSubcategory) el('recatNewSubcategory').focus();
}
function recategorizeValue(selectId, inputId){
  const select=el(selectId);
  return select.value==='__new__' ? el(inputId).value.trim() : select.value.trim();
}
function setupRecategorizeModal(){
  el('recatClose').addEventListener('click',closeRecategorize);
  el('recatCancel').addEventListener('click',closeRecategorize);
  el('recategorizeModal').addEventListener('click',e=>{if(e.target.id==='recategorizeModal') closeRecategorize()});
  el('recatCategory').addEventListener('change',syncNewValueControls);
  el('recatSubcategory').addEventListener('change',syncNewValueControls);
  el('recatSave').addEventListener('click',saveRecategorize);
}
function openRecategorize(id){
  recatMovement=DATA.movements.find(m=>m.id===id);
  if(!recatMovement) return;
  setSelectValue(el('recatCategory'), recatMovement.category||'Sin categoría');
  setSelectValue(el('recatSubcategory'), recatMovement.subcategory||'');
  el('recatNewCategory').value='';
  el('recatNewSubcategory').value='';
  syncNewValueControls();
  el('recatApplySimilar').checked=true;
  el('recatStatus').textContent='';
  el('recatMovementText').innerHTML=`${esc(recatMovement.date)} · ${fmt(recatMovement.amount)}<br>${esc(recatMovement.description)}${recatMovement.comment?'<br>'+esc(recatMovement.comment):''}`;
  el('recategorizeModal').classList.add('open');
  el('recatCategory').focus();
}
function closeRecategorize(){
  recatMovement=null;
  el('recategorizeModal').classList.remove('open');
}
async function saveRecategorize(){
  if(!recatMovement) return;
  const category=recategorizeValue('recatCategory','recatNewCategory'), subcategory=recategorizeValue('recatSubcategory','recatNewSubcategory');
  if(!category){el('recatStatus').textContent='La categoría es obligatoria.'; return}
  el('recatSave').disabled=true;
  el('recatStatus').textContent='Guardando...';
  try{
    const endpoint=new URL('recategorize', window.location.href);
    const res=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:recatMovement.id,category,subcategory,applySimilar:el('recatApplySimilar').checked})});
    const contentType=res.headers.get('content-type')||'';
    const data=contentType.includes('application/json') ? await res.json() : {ok:false,error:'Esta vista no está conectada al servidor editable. Abre el dashboard en http://192.168.1.139:8081/ e inicia sesión.'};
    if(!res.ok || !data.ok) throw new Error(data.error||'No se ha podido guardar.');
    el('recatStatus').textContent=`Guardado: ${data.changed} movimiento(s) actualizados${data.ruleSaved?' y regla futura creada.':'.'} Recargando...`;
    setTimeout(()=>window.location.reload(),650);
  }catch(err){
    el('recatStatus').textContent=err.message||String(err);
    el('recatSave').disabled=false;
  }
}
function exportCsv(){
  const rows=filteredMovements();
  const cols=['date','category','subcategory','merchant','description','amount','balance'];
  const csv=[cols.join(',')].concat(rows.map(r=>cols.map(c=>`"${String(r[c]??'').replaceAll('"','""')}"`).join(','))).join('\n');
  const blob=new Blob([csv],{type:'text/csv;charset=utf-8'}), url=URL.createObjectURL(blob), a=document.createElement('a');
  a.href=url; a.download='gastos-filtrados.csv'; a.click(); URL.revokeObjectURL(url);
}
function renderAll(){
  const view=computeView(filteredMovements());
  renderCategoryFilter(); renderKpis(view); renderInsights(view); renderMonthly(view); renderYearComparison(); renderMoneyFlow(view); renderDonut(view); renderMerchantChart(view); renderAnalysis(view); renderDirectDebits(); renderYears(view); renderSubcats(view); renderTable(view);
  const f=currentFilters();
  const merchantText = f.merchant ? ` · comercio: ${f.merchant}` : '';
  el('filterStatus').textContent=view.rows.length ? `Vista filtrada: ${f.dateFrom||'inicio'} → ${f.dateTo||'fin'} · ${view.rows.length} movimientos · gastos ${fmt(view.kpis.expenseTotal)} · ${activeCategories.length ? 'categorías: '+activeCategories.join(', ') : 'todas las categorías'}${merchantText}` : 'Sin movimientos con estos filtros. Pulsa “Todo” o limpia filtros.';
}
setupFilters();
renderAll();
</script>
</body>
</html>
'''
    HTML_PATH.write_text(html.replace("__PAYLOAD__", payload_json), encoding="utf-8")
    print(f"DASHBOARD_OK {HTML_PATH}")
    print(f"Movements: {len(movements)}")
    print(f"Expense total: {money(expense_total)}")
    print(f"Income total: {money(income_total)}")


if __name__ == "__main__":
    main()
