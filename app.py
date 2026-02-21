from flask import Flask, request, jsonify
from flasgger import Swagger
import os
import json
import re
import pandas as pd
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

app = Flask(__name__)
swagger = Swagger(app)

UPLOAD_FOLDER = "./uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _safe_filename(name: str) -> str:
    name = os.path.basename(name)
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    return name[:120] if name else "upload.xlsx"


def read_file_to_text_tables(file_path: str) -> dict:
    ext = os.path.splitext(file_path.lower())[1]
    sheets = []

    if ext == ".csv":
        df = pd.read_csv(file_path)
        df = df.dropna(axis=1, how="all").dropna(axis=0, how="all")
        sheets.append({
            "name": "CSV",
            "csv": df.to_csv(index=False)
        })
        return {"sheets": sheets}

    xls = pd.ExcelFile(file_path)
    for sname in xls.sheet_names:
        df = pd.read_excel(xls, sheet_name=sname)
        df = df.dropna(axis=1, how="all").dropna(axis=0, how="all")
        sheets.append({
            "name": sname,
            "csv": df.to_csv(index=False)
        })
    return {"sheets": sheets}


def gemini_calculate(payload: dict) -> dict:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY missing.")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-pro")

    system_rules = """
Return ONLY valid JSON.

Compute:
- totals (men_workers, women_workers, men_managers, women_managers)
- gross_average_wage (women, men)
- finishing_average_wage (women, men)
- cutting_and_sewing (average_wage women/men, lowest_wage women/men, overall avg & lowest)
- production_workers_average_wage (women, men)
- non_production_workers_average_wage (women, men)
- admin_and_management_average_wage (women, men)

Exclude:
- total_admin_management
- total_non_production_workers
- total_production_workers
"""

    resp = model.generate_content(
        [
            {"role": "user", "parts": [{"text": system_rules}]},
            {"role": "user", "parts": [{"text": json.dumps(payload)}]},
        ],
        generation_config={
            "temperature": 0,
            "response_mime_type": "application/json",
        }
    )

    text = resp.text.strip()
    return json.loads(text)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/api/calculate", methods=["POST"])
def calculate():
    """
    Calculate payroll statistics
    ---
    consumes:
      - multipart/form-data
    parameters:
      - name: file
        in: formData
        type: file
        required: true
        description: Payroll Excel or CSV file
    responses:
      200:
        description: Calculated payroll metrics
        schema:
          type: object
    """
    if "file" not in request.files:
        return jsonify({"error": "File missing"}), 400

    f = request.files["file"]
    filename = _safe_filename(f.filename)
    path = os.path.join(UPLOAD_FOLDER, filename)
    f.save(path)

    try:
        payload = read_file_to_text_tables(path)
        result = gemini_calculate(payload)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)