from flask import Flask, request, render_template
import os
import json
import re
import pandas as pd
from dotenv import load_dotenv

import google.generativeai as genai

load_dotenv()

app = Flask(__name__)

UPLOAD_FOLDER = "./uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER


def _safe_filename(name: str) -> str:
    name = os.path.basename(name)
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    return name[:120] if name else "upload.xlsx"

def normalize_keys(g: dict) -> dict:
    """
    Convert Gemini output keys (whatever they are) into stable keys used by results.html
    """
    if not isinstance(g, dict):
        return {}

    def pick(*keys):
        for k in keys:
            if k in g and g[k] is not None and g[k] != "":
                return g[k]
        return None

    out = {}

    # Gross overall
    out["avg_gross_wage_overall"] = pick(
    "Average Gross Wage (overall)",
    "Average Gross Wage",
    "average_gross_wage",
    "avg_gross_wage"
)
    out["min_gross_wage_overall"] = pick(
    "Lowest Gross Wage (overall)",
    "Lowest Gross Wage",
    "lowest_gross_wage",
    "min_gross_wage"
)

    # Basic by categories
    out["avg_basic_wage_production"] = pick(
        "Average Basic Wage (Production Workers)", "avg_basic_wage_production", "average_basic_wage_production"
    )
    out["min_basic_wage_production"] = pick(
        "Lowest Basic Wage (Production Workers)", "min_basic_wage_production", "lowest_basic_wage_production"
    )

    out["avg_basic_wage_non_production"] = pick(
        "Average Basic Wage (Non-Production Workers)", "avg_basic_wage_non_production", "average_basic_wage_non_production"
    )
    out["min_basic_wage_non_production"] = pick(
        "Lowest Basic Wage (Non-Production Workers)", "min_basic_wage_non_production", "lowest_basic_wage_non_production"
    )

    out["avg_basic_wage_admin_management"] = pick(
        "Average Basic Wage (Admin & Management)", "avg_basic_wage_admin_management", "average_basic_wage_admin_management"
    )
    out["min_basic_wage_admin_management"] = pick(
        "Lowest Basic Wage (Admin & Management)", "min_basic_wage_admin_management", "lowest_basic_wage_admin_management"
    )

    out["avg_basic_wage_prod_nonprod"] = pick(
        "Average Basic Wage (Production & Non-Production Workers)", "avg_basic_wage_prod_nonprod"
    )
    out["min_basic_wage_prod_nonprod"] = pick(
        "Lowest Basic Wage (Production & Non-Production Workers)", "min_basic_wage_prod_nonprod"
    )

    out["avg_basic_wage_cutting"] = pick("Average Basic Wage (Cutting)", "avg_basic_wage_cutting")
    out["min_basic_wage_cutting"] = pick("Lowest Basic Wage (Cutting)", "min_basic_wage_cutting")

    out["avg_basic_wage_sewing"] = pick("Average Basic Wage (Sewing)", "avg_basic_wage_sewing")
    out["min_basic_wage_sewing"] = pick("Lowest Basic Wage (Sewing)", "min_basic_wage_sewing")

    # totals
    out["total_production_workers"] = pick("total_production_workers", "production_workers_total")
    out["total_non_production_workers"] = pick("total_non_production_workers", "non_production_workers_total")
    out["total_admin_management"] = pick("total_admin_management", "admin_management_total")

    return out


def read_file_to_text_tables(file_path: str) -> dict:
    """
    Returns: {"sheets": [{"name": "...", "preview": "...", "csv": "..."}]}
    - Reads all sheets (Excel) or CSV into text Gemini can understand.
    """
    ext = os.path.splitext(file_path.lower())[1]

    sheets = []

    if ext in [".csv"]:
        df = pd.read_csv(file_path)
        sheets.append({
            "name": "CSV",
            "preview": df.head(20).to_string(index=False),
            "csv": df.to_csv(index=False)
        })
        return {"sheets": sheets}

    # Excel: read all sheets
    xls = pd.ExcelFile(file_path)
    for sname in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sname)

        # Drop fully empty columns/rows to reduce noise
        df = df.dropna(axis=1, how="all")
        df = df.dropna(axis=0, how="all")

        sheets.append({
            "name": sname,
            "preview": df.head(20).to_string(index=False),
            "csv": df.to_csv(index=False)
        })

    return {"sheets": sheets}


def gemini_calculate(payload: dict) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing. Add it to .env or environment variables.")

    genai.configure(api_key=api_key)

    model = genai.GenerativeModel("gemini-2.5-pro")

    # Your definitions + exact outputs you need
    system_rules = """
You are a payroll calculation engine.
You MUST output ONLY valid JSON. No markdown. No backticks.

Goal:
Compute wage statistics and headcounts by worker categories and sub-roles.

Definitions:
- Gross Wage = gross wage/cash/total wage INCLUDING fixed allowances listed below, EXCLUDING overtime and deductions.
- Basic Wage = base wage/basic wage only (no allowances).
- Fixed allowances to include in gross wage:
  house_all, attendance (if earned during normal hours), fixed special_reward / role premiums (only if NOT performance/OT linked),
  other_benef (if fixed cash allowance), any other fixed non-OT, non-deduction cash payments.
- Exclude: overtime, OT-linked bonuses, deductions, tax, social security deductions.

Worker categories:
A) Production Workers (non-managerial, floor-based): Cutting, Sewing, Ironing, Quality, Assembly, Packing, Warehouse, Loading.
B) Non-Production Workers (non-managerial support): Cleaning, Maintenance, Catering, Security, Drivers.
C) Admin & Management: office/admin/supervisors/managers/management (anything managerial/admin not in A/B).

Also compute combined:
- Production & Non-Production (A+B)
- Cutting only
- Sewing only

Part-time:
If there is any column indicating part_time / working days / hours, convert to full-time equivalent (FTE) by pro-rating.
If no part-time signal exists, assume all are full-time.

Output required fields (numbers):
1 Average Gross Wage (overall)
2 Lowest Gross Wage (overall)
3 Average Basic Wage (Production Workers)
4 Lowest Basic Wage (Production Workers)
5 Average Basic Wage (Non-Production Workers)
6 Lowest Basic Wage (Non-Production Workers)
7 Average Basic Wage (Admin & Management)
8 Lowest Basic Wage (Admin & Management)
9 Average Basic Wage (Production & Non-Production Workers)
10 Lowest Basic Wage (Production & Non-Production Workers)
11 Average Basic Wage (Cutting)
12 Lowest Basic Wage (Cutting)
13 Average Basic Wage (Sewing)
14 Lowest Basic Wage (Sewing)

Also totals:
total_production_workers
total_non_production_workers
total_admin_management

Also add:
- assumptions: array of strings (only if needed, keep short)
- mapping_used: short explanation of which columns you used for role, basic wage, allowances, overtime, deductions

If columns are unclear:
- Detect them from headers and values.
- Use best match. If still ambiguous, make reasonable assumption and mention in assumptions.

IMPORTANT:
- Return numeric values (float ok).
- If a category has zero workers, return null for averages/lows and 0 for total.
"""

    user_content = {
        "instruction": "Use the uploaded payroll sheets below. Choose the sheet(s) containing payroll rows. Ignore README/mapping sheets.",
        "sheets": payload["sheets"]
    }

    resp = model.generate_content(
        [
            {"role": "user", "parts": [{"text": system_rules}]},
            {"role": "user", "parts": [{"text": json.dumps(user_content)}]},
        ],
        generation_config={
            "temperature": 0,
            "response_mime_type": "application/json",
        }
    )

    # Gemini returns a JSON string in resp.text (most of the time). Parse safely.
    text = (resp.text or "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON object if model wrapped extra text
        m = re.search(r"\{.*\}", text, flags=re.S)
        if not m:
            raise RuntimeError(f"Gemini did not return valid JSON. Raw response: {text[:500]}")
        return json.loads(m.group(0))


@app.route("/")
def index():
    return render_template("upload.html")


@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return "No file provided", 400

    file = request.files["file"]
    if file.filename == "":
        return "No selected file", 400

    file_path = os.path.join(app.config["UPLOAD_FOLDER"], file.filename)
    file.save(file_path)

    error = None
    raw_json = ""
    results = {}

    try:
        payload = read_file_to_text_tables(file_path)
        gemini_raw = gemini_calculate(payload)

        raw_json = json.dumps(gemini_raw, indent=2, ensure_ascii=False)
        results = normalize_keys(gemini_raw)

    except Exception as e:
        error = str(e)

    return render_template("results.html", results=results, raw_json=raw_json, error=error)



if __name__ == "__main__":
    app.run(debug=True)
