⚙️ Installation (VS Code)
1️⃣ Clone Repository
git clone https://github.com/AbdullahShafiq413/Wages-Calculator.git
cd EXTRACTION_CSV
2️⃣ Create Virtual Environment
Windows
    python -m venv venv
    .\venv\Scripts\activate
Mac/Linux
    python3 -m venv venv
    source venv/bin/activate
3️⃣ Install Dependencies
    pip install -r requirements.txt
4️⃣ Add Gemini API Key

Create .env file:

GEMINI_API_KEY=your_gemini_key_here

⚠️ Do NOT commit .env to GitHub.

▶️ Run the API
python app.py

Server will start at:

http://127.0.0.1:5000
📘 Swagger Interface

Open:

http://127.0.0.1:5000/apidocs

You can:

Click POST /api/calculate

Click Try it out

Upload payroll file

Execute

View JSON response
