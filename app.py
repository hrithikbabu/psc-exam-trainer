from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from dotenv import load_dotenv
import os
import cloudinary
import cloudinary.uploader
from groq import Groq
import PyPDF2
import firebase_admin
from firebase_admin import credentials, firestore, auth
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

# ── Firebase Setup ────────────────────────────────────────
if not firebase_admin._apps:
    cred = credentials.Certificate("firebase-service-account.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

FIREBASE_API_KEY = os.getenv("FIREBASE_API_KEY")

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

# ── Helper: Check login ───────────────────────────────────
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

# ── Register ──────────────────────────────────────────────
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name  = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")
        try:
            user = auth.create_user(email=email, password=password, display_name=name)
            db.collection("users").document(user.uid).set({
                "name": name,
                "email": email,
                "role": "student",
                "score": 0,
                "streak": 0,
                "joined": firestore.SERVER_TIMESTAMP
            })
            return redirect(url_for("login", msg="Registration successful! Please login."))
        except Exception as e:
            return render_template("register.html", error=str(e))
    return render_template("register.html")

# ── Login ─────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    msg = request.args.get("msg", "")
    if request.method == "POST":
        email    = request.form.get("email")
        password = request.form.get("password")
        # Firebase REST API login
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
        payload = {"email": email, "password": password, "returnSecureToken": True}
        res = requests.post(url, json=payload)
        data = res.json()
        if "idToken" in data:
            uid = data["localId"]
            user_doc = db.collection("users").document(uid).get()
            user_data = user_doc.to_dict()
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

# ── Logout ────────────────────────────────────────────────
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
    user_doc = db.collection("users").document(session["user_id"]).get().to_dict()
    return render_template("student/dashboard.html", user=user_doc)

@app.route("/student/quiz")
def quiz():
    if not is_logged_in():
        return redirect(url_for("login"))
    questions = []
    docs = db.collection("questions").limit(10).stream()
    for doc in docs:
        q = doc.to_dict()
        q["id"] = doc.id
        questions.append(q)
    return render_template("student/quiz.html", questions=questions)

@app.route("/student/submit_quiz", methods=["POST"])
def submit_quiz():
    if not is_logged_in():
        return redirect(url_for("login"))
    data = request.get_json()
    answers = data.get("answers", {})
    score = 0
    total = len(answers)
    for qid, selected in answers.items():
        doc = db.collection("questions").document(qid).get()
        if doc.exists:
            correct = doc.to_dict().get("answer")
            if selected == correct:
                score += 1
    db.collection("results").add({
        "user_id": session["user_id"],
        "score": score,
        "total": total,
        "timestamp": firestore.SERVER_TIMESTAMP
    })
    return jsonify({"score": score, "total": total})

@app.route("/student/notes")
def notes():
    if not is_logged_in():
        return redirect(url_for("login"))
    notes_list = []
    docs = db.collection("notes").stream()
    for doc in docs:
        n = doc.to_dict()
        n["id"] = doc.id
        notes_list.append(n)
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
    answer = ask_ai(f"PSC Exam question: {question}")
    return jsonify({"answer": answer})

@app.route("/student/leaderboard")
def leaderboard():
    if not is_logged_in():
        return redirect(url_for("login"))
    users = []
    docs = db.collection("users").order_by("score", direction=firestore.Query.DESCENDING).limit(10).stream()
    for doc in docs:
        u = doc.to_dict()
        u["id"] = doc.id
        users.append(u)
    return render_template("student/leaderboard.html", users=users)

@app.route("/student/evaluate_answer", methods=["POST"])
def evaluate_answer():
    if not is_logged_in():
        return jsonify({"error": "Not logged in"})
    data = request.get_json()
    question = data.get("question", "")
    student_answer = data.get("answer", "")
    prompt = f"""
    PSC Exam Question: {question}
    Student's Answer: {student_answer}
    
    Evaluate this answer out of 10. Give:
    1. Score (X/10)
    2. What was correct
    3. What was missing
    4. The ideal answer
    """
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
    text = ""
    for page in reader.pages:
        text += page.extract_text()
    prompt = f"""
    Analyze this Kerala PSC previous year question paper:
    {text[:3000]}
    
    Provide:
    1. Most repeated topics
    2. Important subjects
    3. Question patterns
    4. Predictions for upcoming exams
    """
    analysis = ask_ai(prompt, system="You are a Kerala PSC exam expert analyst.")
    return jsonify({"analysis": analysis})

# ══════════════════════════════════════════════════════════
# ADMIN ROUTES
# ══════════════════════════════════════════════════════════

@app.route("/admin/dashboard")
def admin_dashboard():
    if not is_admin():
        return redirect(url_for("login"))
    users_count = len(list(db.collection("users").stream()))
    questions_count = len(list(db.collection("questions").stream()))
    notes_count = len(list(db.collection("notes").stream()))
    results_count = len(list(db.collection("results").stream()))
    return render_template("admin/dashboard.html",
        users=users_count, questions=questions_count,
        notes=notes_count, results=results_count)

@app.route("/admin/add_question", methods=["GET", "POST"])
def add_question():
    if not is_admin():
        return redirect(url_for("login"))
    if request.method == "POST":
        db.collection("questions").add({
            "question": request.form.get("question"),
            "options": [
                request.form.get("option_a"),
                request.form.get("option_b"),
                request.form.get("option_c"),
                request.form.get("option_d"),
            ],
            "answer": request.form.get("answer"),
            "subject": request.form.get("subject"),
            "difficulty": request.form.get("difficulty"),
        })
        return redirect(url_for("add_question", msg="Question added!"))
    return render_template("admin/add_question.html", msg=request.args.get("msg",""))

@app.route("/admin/upload_notes", methods=["GET", "POST"])
def upload_notes():
    if not is_admin():
        return redirect(url_for("login"))
    if request.method == "POST":
        file  = request.files.get("file")
        title = request.form.get("title")
        subject = request.form.get("subject")
        if file:
            result = cloudinary.uploader.upload(file,
                resource_type="raw",
                folder="psc-notes")
            db.collection("notes").add({
                "title": title,
                "subject": subject,
                "url": result["secure_url"],
                "uploaded_by": session["user_name"],
                "timestamp": firestore.SERVER_TIMESTAMP
            })
            return redirect(url_for("upload_notes", msg="Notes uploaded successfully!"))
    return render_template("admin/upload_notes.html", msg=request.args.get("msg",""))

@app.route("/admin/generate_ai_questions", methods=["GET", "POST"])
def generate_ai_questions():
    if not is_admin():
        return redirect(url_for("login"))
    if request.method == "POST":
        subject    = request.form.get("subject")
        difficulty = request.form.get("difficulty")
        count      = int(request.form.get("count", 5))
        prompt = f"""Generate {count} Kerala PSC multiple choice questions on '{subject}' at '{difficulty}' difficulty.
Return ONLY a JSON array like this:
[
  {{
    "question": "...",
    "options": ["A. ...", "B. ...", "C. ...", "D. ..."],
    "answer": "A. ...",
    "subject": "{subject}",
    "difficulty": "{difficulty}"
  }}
]"""
        raw = ask_ai(prompt, system="You are a Kerala PSC question paper setter. Return only valid JSON.")
        try:
            start = raw.index("[")
            end   = raw.rindex("]") + 1
            questions = json.loads(raw[start:end])
            for q in questions:
                db.collection("questions").add(q)
            return render_template("admin/generate_questions.html",
                msg=f"{len(questions)} questions generated and saved!", questions=questions)
        except Exception as e:
            return render_template("admin/generate_questions.html", error=str(e))
    return render_template("admin/generate_questions.html")

@app.route("/admin/users")
def manage_users():
    if not is_admin():
        return redirect(url_for("login"))
    users = []
    docs = db.collection("users").stream()
    for doc in docs:
        u = doc.to_dict()
        u["id"] = doc.id
        users.append(u)
    return render_template("admin/users.html", users=users)

if __name__ == "__main__":
    app.run(debug=True)
