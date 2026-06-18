from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from dotenv import load_dotenv
import os
import cloudinary
import cloudinary.uploader
from groq import Groq
import PyPDF2
import requests
import json

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "psc-trainer-secret-2026")

# ── Cloudinary Setup ──────────────────────────────────────
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

# ── Groq AI Setup ─────────────────────────────────────────
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ── Firebase Config ───────────────────────────────────────
FIREBASE_API_KEY    = os.getenv("FIREBASE_API_KEY")
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
FIRESTORE_URL       = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/databases/(default)/documents"

# ── Firebase REST Helpers ─────────────────────────────────
def firestore_get(collection, doc_id):
    url = f"{FIRESTORE_URL}/{collection}/{doc_id}"
    res = requests.get(url)
    if res.status_code == 200:
        return parse_firestore(res.json())
    return None

def firestore_set(collection, doc_id, data):
    url = f"{FIRESTORE_URL}/{collection}/{doc_id}"
    body = {"fields": to_firestore(data)}
    requests.patch(url, json=body)

def firestore_add(collection, data):
    url = f"{FIRESTORE_URL}/{collection}"
    body = {"fields": to_firestore(data)}
    requests.post(url, json=body)

def firestore_list(collection, limit=100):
    url = f"{FIRESTORE_URL}/{collection}?pageSize={limit}"
    res = requests.get(url)
    if res.status_code == 200:
        docs = res.json().get("documents", [])
        result = []
        for doc in docs:
            d = parse_firestore(doc)
            d["id"] = doc["name"].split("/")[-1]
            result.append(d)
        return result
    return []

def to_firestore(data):
    fields = {}
    for k, v in data.items():
        if isinstance(v, str):
            fields[k] = {"stringValue": v}
        elif isinstance(v, int):
            fields[k] = {"integerValue": str(v)}
        elif isinstance(v, float):
            fields[k] = {"doubleValue": v}
        elif isinstance(v, bool):
            fields[k] = {"booleanValue": v}
        elif isinstance(v, list):
            fields[k] = {"arrayValue": {"values": [{"stringValue": str(i)} for i in v]}}
    return fields

def parse_firestore(doc):
    result = {}
    for k, v in doc.get("fields", {}).items():
        if "stringValue" in v:
            result[k] = v["stringValue"]
        elif "integerValue" in v:
            result[k] = int(v["integerValue"])
        elif "doubleValue" in v:
            result[k] = v["doubleValue"]
        elif "booleanValue" in v:
            result[k] = v["booleanValue"]
        elif "arrayValue" in v:
            result[k] = [i.get("stringValue", "") for i in v["arrayValue"].get("values", [])]
    return result

# ── Firebase Auth REST ────────────────────────────────────
def firebase_register(email, password, name):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FIREBASE_API_KEY}"
    res = requests.post(url, json={"email": email, "password": password, "displayName": name, "returnSecureToken": True})
    return res.json()

def firebase_login(email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
    res = requests.post(url, json={"email": email, "password": password, "returnSecureToken": True})
    return res.json()

# ── Helper: Ask Groq AI ───────────────────────────────────
def ask_ai(prompt, system="You are a helpful Kerala PSC exam tutor. Answer clearly and concisely."):
    response = groq_client.chat.completions.create(
        model="llama3-8b-8192",
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content

def is_logged_in():
    return "user_id" in session

def is_admin():
    return session.get("role") == "admin"

# ══════════════════════════════════════════════════════════
# PUBLIC ROUTES
# ══════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name     = request.form.get("name")
        email    = request.form.get("email")
        password = request.form.get("password")
        data = firebase_register(email, password, name)
        if "idToken" in data:
            uid = data["localId"]
            firestore_set("users", uid, {
                "name": name, "email": email,
                "role": "student", "score": 0, "streak": 0
            })
            return redirect(url_for("login", msg="Registration successful! Please login."))
        else:
            error = data.get("error", {}).get("message", "Registration failed")
            return render_template("register.html", error=error)
    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    msg = request.args.get("msg", "")
    if request.method == "POST":
        email    = request.form.get("email")
        password = request.form.get("password")
        data = firebase_login(email, password)
        if "idToken" in data:
            uid       = data["localId"]
            user_data = firestore_get("users", uid) or {}
            session["user_id"]   = uid
            session["user_name"] = user_data.get("name", email)
            session["email"]     = email
            session["role"]      = user_data.get("role", "student")
            if session["role"] == "admin":
                return redirect(url_for("admin_dashboard"))
            return redirect(url_for("student_dashboard"))
        else:
            error = data.get("error", {}).get("message", "Login failed")
            return render_template("login.html", error=error)
    return render_template("login.html", msg=msg)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# ══════════════════════════════════════════════════════════
# STUDENT ROUTES
# ══════════════════════════════════════════════════════════

@app.route("/student/dashboard")
def student_dashboard():
    if not is_logged_in():
        return redirect(url_for("login"))
    user = firestore_get("users", session["user_id"]) or {}
    return render_template("student/dashboard.html", user=user)

@app.route("/student/quiz")
def quiz():
    if not is_logged_in():
        return redirect(url_for("login"))
    questions = firestore_list("questions", limit=10)
    return render_template("student/quiz.html", questions=questions)

@app.route("/student/submit_quiz", methods=["POST"])
def submit_quiz():
    if not is_logged_in():
        return redirect(url_for("login"))
    data    = request.get_json()
    answers = data.get("answers", {})
    score   = 0
    total   = len(answers)
    for qid, selected in answers.items():
        q = firestore_get("questions", qid)
        if q and q.get("answer") == selected:
            score += 1
    firestore_add("results", {
        "user_id": session["user_id"],
        "score": score, "total": total
    })
    return jsonify({"score": score, "total": total})

@app.route("/student/notes")
def notes():
    if not is_logged_in():
        return redirect(url_for("login"))
    notes_list = firestore_list("notes")
    return render_template("student/notes.html", notes=notes_list)

@app.route("/student/chatbot")
def chatbot():
    if not is_logged_in():
        return redirect(url_for("login"))
    return render_template("student/chatbot.html")

@app.route("/student/ask_doubt", methods=["POST"])
def ask_doubt():
    if not is_logged_in():
        return jsonify({"error": "Not logged in"})
    question = request.get_json().get("question", "")
    answer   = ask_ai(f"Kerala PSC exam question: {question}")
    return jsonify({"answer": answer})

@app.route("/student/leaderboard")
def leaderboard():
    if not is_logged_in():
        return redirect(url_for("login"))
    users = firestore_list("users", limit=10)
    users.sort(key=lambda x: x.get("score", 0), reverse=True)
    return render_template("student/leaderboard.html", users=users)

@app.route("/student/evaluate_answer", methods=["POST"])
def evaluate_answer():
    if not is_logged_in():
        return jsonify({"error": "Not logged in"})
    data           = request.get_json()
    question       = data.get("question", "")
    student_answer = data.get("answer", "")
    prompt = f"""PSC Exam Question: {question}
Student Answer: {student_answer}
Evaluate out of 10. Give: 1) Score 2) What was correct 3) What was missing 4) Ideal answer"""
    result = ask_ai(prompt, system="You are a strict but fair Kerala PSC exam evaluator.")
    return jsonify({"feedback": result})

@app.route("/student/analyze_paper", methods=["POST"])
def analyze_paper():
    if not is_logged_in():
        return jsonify({"error": "Not logged in"})
    file = request.files.get("paper")
    if not file:
        return jsonify({"error": "No file uploaded"})
    reader = PyPDF2.PdfReader(file)
    text   = "".join([page.extract_text() for page in reader.pages])
    prompt = f"""Analyze this Kerala PSC previous year question paper:
{text[:3000]}
Give: 1) Most repeated topics 2) Important subjects 3) Question patterns 4) Predictions"""
    analysis = ask_ai(prompt, system="You are a Kerala PSC exam expert analyst.")
    return jsonify({"analysis": analysis})

# ══════════════════════════════════════════════════════════
# ADMIN ROUTES
# ══════════════════════════════════════════════════════════

@app.route("/admin/dashboard")
def admin_dashboard():
    if not is_admin():
        return redirect(url_for("login"))
    users     = firestore_list("users")
    questions = firestore_list("questions")
    notes     = firestore_list("notes")
    results   = firestore_list("results")
    return render_template("admin/dashboard.html",
        users=len(users), questions=len(questions),
        notes=len(notes), results=len(results))

@app.route("/admin/add_question", methods=["GET", "POST"])
def add_question():
    if not is_admin():
        return redirect(url_for("login"))
    if request.method == "POST":
        firestore_add("questions", {
            "question":   request.form.get("question"),
            "option_a":   request.form.get("option_a"),
            "option_b":   request.form.get("option_b"),
            "option_c":   request.form.get("option_c"),
            "option_d":   request.form.get("option_d"),
            "answer":     request.form.get("answer"),
            "subject":    request.form.get("subject"),
            "difficulty": request.form.get("difficulty"),
        })
        return redirect(url_for("add_question", msg="Question added!"))
    return render_template("admin/add_question.html", msg=request.args.get("msg", ""))

@app.route("/admin/upload_notes", methods=["GET", "POST"])
def upload_notes():
    if not is_admin():
        return redirect(url_for("login"))
    if request.method == "POST":
        file    = request.files.get("file")
        title   = request.form.get("title")
        subject = request.form.get("subject")
        if file:
            result = cloudinary.uploader.upload(file, resource_type="raw", folder="psc-notes")
            firestore_add("notes", {
                "title": title, "subject": subject,
                "url": result["secure_url"],
                "uploaded_by": session["user_name"]
            })
            return redirect(url_for("upload_notes", msg="Notes uploaded successfully!"))
    return render_template("admin/upload_notes.html", msg=request.args.get("msg", ""))

@app.route("/admin/generate_ai_questions", methods=["GET", "POST"])
def generate_ai_questions():
    if not is_admin():
        return redirect(url_for("login"))
    if request.method == "POST":
        subject    = request.form.get("subject")
        difficulty = request.form.get("difficulty")
        count      = int(request.form.get("count", 5))
        prompt = f"""Generate {count} Kerala PSC MCQ questions on '{subject}' at '{difficulty}' difficulty.
Return ONLY a JSON array:
[{{"question":"...","option_a":"...","option_b":"...","option_c":"...","option_d":"...","answer":"A","subject":"{subject}","difficulty":"{difficulty}"}}]"""
        raw = ask_ai(prompt, system="You are a Kerala PSC question paper setter. Return only valid JSON array.")
        try:
            start     = raw.index("[")
            end       = raw.rindex("]") + 1
            questions = json.loads(raw[start:end])
            for q in questions:
                firestore_add("questions", q)
            return render_template("admin/generate_questions.html",
                msg=f"{len(questions)} questions generated!", questions=questions)
        except Exception as e:
            return render_template("admin/generate_questions.html", error=str(e))
    return render_template("admin/generate_questions.html")

@app.route("/admin/users")
def manage_users():
    if not is_admin():
        return redirect(url_for("login"))
    users = firestore_list("users")
    return render_template("admin/users.html", users=users)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
