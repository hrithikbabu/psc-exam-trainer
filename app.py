from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from dotenv import load_dotenv
import os
import cloudinary
import cloudinary.uploader
from groq import Groq
import PyPDF2
import requests
import json
from datetime import datetime, timezone, timedelta

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "psc-trainer-secret-2026")

@app.template_filter("ist")
def format_ist(start_time_str):
    """Displays a stored (UTC) start_time back in IST, since that's the timezone
    everyone using this app is actually in. Handles old naive-format data too."""
    try:
        dt = datetime.fromisoformat(start_time_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
        ist = dt.astimezone(timezone(timedelta(hours=5, minutes=30)))
        return ist.strftime("%d %b %Y, %I:%M %p")
    except (ValueError, TypeError):
        return start_time_str

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
    """Partial update — merges the given fields into the existing document instead of
    replacing it. Without updateMask, Firestore's PATCH endpoint wipes every field not
    included in this call, which would silently delete data on every status update."""
    url = f"{FIRESTORE_URL}/{collection}/{doc_id}"
    mask_params = "&".join(f"updateMask.fieldPaths={k}" for k in data.keys())
    url = f"{url}?{mask_params}"
    body = {"fields": to_firestore(data)}
    requests.patch(url, json=body)

def firestore_add(collection, data):
    url = f"{FIRESTORE_URL}/{collection}"
    body = {"fields": to_firestore(data)}
    res = requests.post(url, json=body)
    if res.status_code == 200:
        return res.json()["name"].split("/")[-1]
    return None

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

def firestore_query(collection, field, op, value, limit=200):
    """Query a collection by a single field using Firestore's structured query API.
    op is one of: EQUAL, LESS_THAN, GREATER_THAN, LESS_THAN_OR_EQUAL, GREATER_THAN_OR_EQUAL."""
    url = f"{FIRESTORE_URL}:runQuery"
    if isinstance(value, bool):
        value_obj = {"booleanValue": value}
    elif isinstance(value, int):
        value_obj = {"integerValue": str(value)}
    else:
        value_obj = {"stringValue": str(value)}
    body = {
        "structuredQuery": {
            "from": [{"collectionId": collection}],
            "where": {
                "fieldFilter": {
                    "field": {"fieldPath": field},
                    "op": op,
                    "value": value_obj
                }
            },
            "limit": limit
        }
    }
    res = requests.post(url, json=body)
    result = []
    if res.status_code == 200:
        for entry in res.json():
            doc = entry.get("document")
            if not doc:
                continue
            d = parse_firestore(doc)
            d["id"] = doc["name"].split("/")[-1]
            result.append(d)
    return result

def firestore_delete(collection, doc_id):
    url = f"{FIRESTORE_URL}/{collection}/{doc_id}"
    requests.delete(url)

def to_firestore(data):
    fields = {}
    for k, v in data.items():
        fields[k] = _to_firestore_value(v)
    return fields

def _to_firestore_value(v):
    if isinstance(v, bool):
        return {"booleanValue": v}
    elif isinstance(v, str):
        return {"stringValue": v}
    elif isinstance(v, int):
        return {"integerValue": str(v)}
    elif isinstance(v, float):
        return {"doubleValue": v}
    elif isinstance(v, list):
        return {"arrayValue": {"values": [_to_firestore_value(i) for i in v]}}
    elif isinstance(v, dict):
        return {"mapValue": {"fields": {k2: _to_firestore_value(v2) for k2, v2 in v.items()}}}
    elif v is None:
        return {"nullValue": None}
    else:
        return {"stringValue": str(v)}

def parse_firestore(doc):
    result = {}
    for k, v in doc.get("fields", {}).items():
        result[k] = _parse_firestore_value(v)
    return result

def _parse_firestore_value(v):
    if "stringValue" in v:
        return v["stringValue"]
    elif "integerValue" in v:
        return int(v["integerValue"])
    elif "doubleValue" in v:
        return v["doubleValue"]
    elif "booleanValue" in v:
        return v["booleanValue"]
    elif "arrayValue" in v:
        return [_parse_firestore_value(i) for i in v["arrayValue"].get("values", [])]
    elif "mapValue" in v:
        return {k2: _parse_firestore_value(v2) for k2, v2 in v["mapValue"].get("fields", {}).items()}
    elif "nullValue" in v:
        return None
    return None

# ── Firebase Auth REST ────────────────────────────────────
def firebase_register(email, password, name):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={FIREBASE_API_KEY}"
    res = requests.post(url, json={"email": email, "password": password, "displayName": name, "returnSecureToken": True})
    return res.json()

def firebase_login(email, password):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}"
    res = requests.post(url, json={"email": email, "password": password, "returnSecureToken": True})
    return res.json()

def firebase_send_password_reset(email):
    """Asks Firebase to email the user a password reset link. Works for both
    students and admins since they're all stored in the same Firebase Auth project."""
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key={FIREBASE_API_KEY}"
    res = requests.post(url, json={"requestType": "PASSWORD_RESET", "email": email})
    return res.json()

# ── Helper: Ask Groq AI ───────────────────────────────────
def ask_ai(prompt, system="You are a helpful Kerala PSC exam tutor. Answer clearly and concisely."):
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
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
        name       = request.form.get("name")
        email      = request.form.get("email")
        password   = request.form.get("password")
        admin_code = request.form.get("admin_code", "").strip()
        data = firebase_register(email, password, name)
        if "idToken" in data:
            uid = data["localId"]
            # An account becomes admin ONLY if the correct secret code was entered.
            # Set ADMIN_SECRET_CODE in your .env / Render environment variables.
            role = "admin" if admin_code and admin_code == os.getenv("ADMIN_SECRET_CODE") else "student"
            firestore_set("users", uid, {
                "name": name, "email": email,
                "role": role, "score": 0, "streak": 0
            })
            if role == "admin":
                return redirect(url_for("login", msg="Admin account created! Please login."))
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

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        firebase_send_password_reset(email)
        # Always show the same message whether or not the email exists —
        # this stops people from being able to guess which emails are registered.
        return render_template("forgot_password.html",
            msg="If that email is registered, a password reset link has been sent. Check your inbox (and spam folder).")
    return render_template("forgot_password.html")

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
# STUDENT — TIMED EXAM SYSTEM
# ══════════════════════════════════════════════════════════

def _parse_exam_start(start_time_str):
    """Parses a stored start_time string into a UTC-aware datetime. Handles both the
    correct new format (timezone-aware, e.g. '...+00:00') and older naive strings that
    were saved before the IST-conversion fix — naive strings are assumed IST, same as
    the create_exam form originally intended."""
    dt = datetime.fromisoformat(start_time_str)
    if dt.tzinfo is None:
        IST_OFFSET = timedelta(hours=5, minutes=30)
        dt = dt.replace(tzinfo=timezone(IST_OFFSET))
    return dt.astimezone(timezone.utc)

def _exam_status(exam):
    """Returns 'scheduled', 'live', or 'ended' based on server clock vs stored start_time + duration."""
    now = datetime.now(timezone.utc).timestamp()
    try:
        start = _parse_exam_start(exam.get("start_time", "")).timestamp()
    except ValueError:
        return "ended"
    end = start + exam.get("duration_minutes", 0) * 60
    if now < start:
        return "scheduled"
    elif now < end:
        return "live"
    return "ended"

def _exam_seconds_left(exam):
    now = datetime.now(timezone.utc).timestamp()
    start = _parse_exam_start(exam["start_time"]).timestamp()
    end = start + exam.get("duration_minutes", 0) * 60
    return max(0, int(end - now))

def _exam_start_epoch_ms(exam):
    """Unix epoch milliseconds — handed to client-side JS so the browser never has to
    parse a date string itself. This sidesteps all cross-browser ISO-parsing quirks
    (the '--:--:--' freeze bug) since `new Date(ms)` with a plain number always works."""
    return int(_parse_exam_start(exam["start_time"]).timestamp() * 1000)

@app.route("/student/exams")
def list_exams_student():
    if not is_logged_in():
        return redirect(url_for("login"))
    exams = firestore_list("exams")
    for e in exams:
        e["computed_status"] = _exam_status(e)
    exams.sort(key=lambda x: x.get("start_time", ""))
    return render_template("student/exams.html", exams=exams)

@app.route("/student/exams/<exam_id>/enter")
def enter_exam(exam_id):
    if not is_logged_in():
        return redirect(url_for("login"))
    exam = firestore_get("exams", exam_id)
    if not exam:
        return redirect(url_for("list_exams_student"))
    exam["id"] = exam_id
    status = _exam_status(exam)

    if status == "scheduled":
        return render_template("student/exam_wait.html", exam=exam,
            start_epoch_ms=_exam_start_epoch_ms(exam))
    if status == "ended":
        return render_template("student/exam_ended.html", exam=exam)

    # Live — check for an existing attempt (prevents re-entry after disqualification/submission)
    existing = firestore_query("exam_attempts", "exam_id", "EQUAL", exam_id)
    my_attempt = next((a for a in existing if a.get("user_id") == session["user_id"]), None)

    if my_attempt:
        if my_attempt.get("status") == "disqualified":
            return render_template("student/exam_blocked.html", exam=exam,
                reason="You were disqualified from this exam for leaving the test screen or attempting to cheat. You cannot re-enter.")
        if my_attempt.get("status") == "submitted":
            return redirect(url_for("exam_result", exam_id=exam_id))
        attempt_id = my_attempt["id"]
    else:
        attempt_id = firestore_add("exam_attempts", {
            "exam_id": exam_id,
            "user_id": session["user_id"],
            "user_name": session.get("user_name", "Student"),
            "status": "in_progress",
            "joined_at": datetime.now(timezone.utc).isoformat(),
        })

    questions = []
    for qid in exam.get("question_ids", []):
        q = firestore_get("questions", qid)
        if q:
            q["id"] = qid
            questions.append(q)

    seconds_left = _exam_seconds_left(exam)
    return render_template("student/exam_room.html", exam=exam, questions=questions,
        attempt_id=attempt_id, seconds_left=seconds_left)

@app.route("/student/exams/<exam_id>/heartbeat", methods=["POST"])
def exam_heartbeat(exam_id):
    """Called periodically and on suspicious client events (tab switch, blur, devtools,
    right-click, copy/paste, page close) by exam_room.html's anti-cheat JS.
    A 'violation' payload immediately disqualifies the attempt."""
    if not is_logged_in():
        return jsonify({"error": "Not logged in"}), 401
    data = request.get_json(silent=True) or {}
    attempt_id = data.get("attempt_id")
    violation  = data.get("violation")
    if not attempt_id:
        return jsonify({"error": "Missing attempt_id"}), 400

    attempt = firestore_get("exam_attempts", attempt_id)
    if not attempt or attempt.get("user_id") != session["user_id"]:
        return jsonify({"error": "Not authorized"}), 403
    if attempt.get("status") != "in_progress":
        return jsonify({"status": attempt.get("status")})

    if violation:
        firestore_set("exam_attempts", attempt_id, {
            "status": "disqualified",
            "disqualified_reason": violation,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        })
        return jsonify({"status": "disqualified"})

    return jsonify({"status": "ok"})

@app.route("/student/exams/<exam_id>/submit", methods=["POST"])
def submit_exam(exam_id):
    if not is_logged_in():
        return jsonify({"error": "Not logged in"}), 401
    data = request.get_json(silent=True) or {}
    attempt_id = data.get("attempt_id")
    answers    = data.get("answers", {})

    attempt = firestore_get("exam_attempts", attempt_id)
    if not attempt or attempt.get("user_id") != session["user_id"]:
        return jsonify({"error": "Not authorized"}), 403
    if attempt.get("status") != "in_progress":
        return jsonify({"status": attempt.get("status")})

    exam = firestore_get("exams", exam_id) or {}
    score = 0
    total = len(exam.get("question_ids", []))
    breakdown = {}

    for qid in exam.get("question_ids", []):
        q = firestore_get("questions", qid)
        if not q:
            continue
        selected = answers.get(qid, "")
        correct  = q.get("answer", "")
        is_correct = selected == correct
        if is_correct:
            score += 1
        breakdown[qid] = {
            "question": q.get("question", ""),
            "selected": selected,
            "correct_answer": correct,
            "is_correct": is_correct,
        }

    # AI evaluation pass — a short written summary of performance, not per-question grading
    # (grading itself is exact-match above; this is the "AI evaluates" feel you asked for).
    summary_prompt = f"""A Kerala PSC student just completed a mock test titled "{exam.get('title','')}" on subject "{exam.get('subject','')}".
They scored {score} out of {total}.
Write a short (3-4 sentence) encouraging but honest evaluation of this performance, and one specific tip for improvement."""
    ai_feedback = ask_ai(summary_prompt, system="You are a supportive but honest Kerala PSC exam coach.")

    firestore_set("exam_attempts", attempt_id, {
        "status": "submitted",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "answers": answers,
        "score": score,
        "total": total,
        "ai_feedback": ai_feedback,
    })

    # Also feed the leaderboard/score system used elsewhere in the app
    firestore_add("results", {"user_id": session["user_id"], "score": score, "total": total})

    return jsonify({"status": "submitted", "redirect": url_for("exam_result", exam_id=exam_id)})

@app.route("/student/exams/<exam_id>/result")
def exam_result(exam_id):
    if not is_logged_in():
        return redirect(url_for("login"))
    exam = firestore_get("exams", exam_id)
    if not exam:
        return redirect(url_for("list_exams_student"))
    exam["id"] = exam_id

    attempts = firestore_query("exam_attempts", "exam_id", "EQUAL", exam_id)
    my_attempt = next((a for a in attempts if a.get("user_id") == session["user_id"]), None)
    if not my_attempt or my_attempt.get("status") != "submitted":
        return redirect(url_for("list_exams_student"))

    breakdown = []
    for qid in exam.get("question_ids", []):
        q = firestore_get("questions", qid)
        if not q:
            continue
        selected = my_attempt.get("answers", {}).get(qid, "")
        breakdown.append({
            "question": q.get("question", ""),
            "option_a": q.get("option_a", ""), "option_b": q.get("option_b", ""),
            "option_c": q.get("option_c", ""), "option_d": q.get("option_d", ""),
            "selected": selected,
            "correct_answer": q.get("answer", ""),
            "is_correct": selected == q.get("answer", ""),
        })

    return render_template("student/exam_result.html", exam=exam, attempt=my_attempt, breakdown=breakdown)

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

    # ── Exam widget data ──────────────────────────────────────
    all_exams = firestore_list("exams")
    live_exams = []
    upcoming_exams = []
    for e in all_exams:
        e["computed_status"] = _exam_status(e)
        if e["computed_status"] == "live":
            live_exams.append(e)
        elif e["computed_status"] == "scheduled":
            upcoming_exams.append(e)

    # Attendee counts for live exams only (keeps this cheap — we don't query attempts
    # for every exam ever created, just the ones currently in progress).
    for e in live_exams:
        attempts = firestore_query("exam_attempts", "exam_id", "EQUAL", e["id"])
        e["live_count"] = sum(1 for a in attempts if a.get("status") == "in_progress")
        e["submitted_count"] = sum(1 for a in attempts if a.get("status") == "submitted")

    upcoming_exams.sort(key=lambda e: e.get("start_time", ""))
    upcoming_exams = upcoming_exams[:5]

    # Recent results — last 5 submitted exam attempts across all exams, newest first.
    # firestore_list has no orderBy, so we pull a reasonable batch and sort client-side.
    recent_attempts = firestore_list("exam_attempts", limit=50)
    recent_attempts = [a for a in recent_attempts if a.get("status") == "submitted"]
    recent_attempts.sort(key=lambda a: a.get("submitted_at", ""), reverse=True)
    recent_attempts = recent_attempts[:5]
    # Attach exam title to each for display
    exam_titles = {e["id"]: e.get("title", "Untitled Exam") for e in all_exams}
    for a in recent_attempts:
        a["exam_title"] = exam_titles.get(a.get("exam_id"), "Unknown Exam")

    return render_template("admin/dashboard.html",
        users=len(users), questions=len(questions),
        notes=len(notes), results=len(results),
        live_exams=live_exams, upcoming_exams=upcoming_exams,
        recent_attempts=recent_attempts)

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

# ══════════════════════════════════════════════════════════
# ADMIN — TIMED EXAM SYSTEM
# ══════════════════════════════════════════════════════════

@app.route("/admin/exams")
def list_exams():
    if not is_admin():
        return redirect(url_for("login"))
    exams = firestore_list("exams")
    now = datetime.now(timezone.utc)
    for e in exams:
        try:
            start = datetime.fromisoformat(e.get("start_time", ""))
        except ValueError:
            start = now
        end = start.timestamp() + e.get("duration_minutes", 0) * 60
        if now.timestamp() >= end:
            e["computed_status"] = "ended"
        elif now.timestamp() >= start.timestamp():
            e["computed_status"] = "live"
        else:
            e["computed_status"] = "scheduled"
    exams.sort(key=lambda x: x.get("start_time", ""), reverse=True)
    return render_template("admin/exams.html", exams=exams)

@app.route("/admin/exams/create", methods=["GET", "POST"])
def create_exam():
    if not is_admin():
        return redirect(url_for("login"))
    if request.method == "POST":
        title       = request.form.get("title", "").strip()
        subject     = request.form.get("subject", "").strip()
        difficulty  = request.form.get("difficulty", "medium")
        duration    = int(request.form.get("duration_minutes", 30))
        start_time  = request.form.get("start_time", "")  # datetime-local input, e.g. 2026-06-20T14:30
        question_source = request.form.get("question_source", "bank")
        count       = int(request.form.get("count", 10))

        try:
            # datetime-local input has no timezone info. Kerala PSC students/admins are in
            # IST (UTC+5:30), so we treat the typed value as IST and convert to true UTC
            # before storing. Storing naive datetimes and comparing against timezone.utc
            # was the bug — it silently assumed the typed time was already UTC, making
            # exams start 5.5 hours later than intended.
            IST_OFFSET = timedelta(hours=5, minutes=30)
            naive_dt = datetime.fromisoformat(start_time)
            start_dt = naive_dt.replace(tzinfo=timezone(IST_OFFSET)).astimezone(timezone.utc)
        except ValueError:
            return render_template("admin/create_exam.html", error="Invalid start time.")

        question_ids = []
        if question_source == "ai":
            prompt = f"""Generate {count} Kerala PSC MCQ questions on '{subject}' at '{difficulty}' difficulty.
Return ONLY a JSON array:
[{{"question":"...","option_a":"...","option_b":"...","option_c":"...","option_d":"...","answer":"A","subject":"{subject}","difficulty":"{difficulty}"}}]"""
            raw = ask_ai(prompt, system="You are a Kerala PSC question paper setter. Return only valid JSON array.")
            try:
                start = raw.index("[")
                end   = raw.rindex("]") + 1
                questions = json.loads(raw[start:end])
                for q in questions:
                    qid = firestore_add("questions", q)
                    if qid:
                        question_ids.append(qid)
            except Exception as e:
                return render_template("admin/create_exam.html", error=f"AI question generation failed: {e}")
        else:
            bank = firestore_list("questions", limit=200)
            if subject:
                bank = [q for q in bank if q.get("subject", "").lower() == subject.lower()]
            question_ids = [q["id"] for q in bank[:count]]

        if not question_ids:
            return render_template("admin/create_exam.html",
                error="No questions available — try AI generation or add questions to the bank first.")

        exam_id = firestore_add("exams", {
            "title": title,
            "subject": subject,
            "difficulty": difficulty,
            "duration_minutes": duration,
            "start_time": start_dt.isoformat(),
            "question_ids": question_ids,
            "created_by": session["user_name"],
        })
        return redirect(url_for("exam_live_view", exam_id=exam_id))
    return render_template("admin/create_exam.html")

@app.route("/admin/exams/<exam_id>")
def exam_live_view(exam_id):
    if not is_admin():
        return redirect(url_for("login"))
    exam = firestore_get("exams", exam_id)
    if not exam:
        return redirect(url_for("list_exams"))
    exam["id"] = exam_id
    attempts = firestore_query("exam_attempts", "exam_id", "EQUAL", exam_id)
    attempts.sort(key=lambda a: a.get("joined_at", ""))
    counts = {
        "in_progress": sum(1 for a in attempts if a.get("status") == "in_progress"),
        "submitted":   sum(1 for a in attempts if a.get("status") == "submitted"),
        "disqualified": sum(1 for a in attempts if a.get("status") == "disqualified"),
    }
    return render_template("admin/exam_live.html", exam=exam, attempts=attempts, counts=counts)

@app.route("/admin/exams/<exam_id>/attempts.json")
def exam_attempts_json(exam_id):
    """Polled by the admin live view to refresh attendance without a full page reload."""
    if not is_admin():
        return jsonify({"error": "Not authorized"}), 403
    attempts = firestore_query("exam_attempts", "exam_id", "EQUAL", exam_id)
    attempts.sort(key=lambda a: a.get("joined_at", ""))
    counts = {
        "in_progress": sum(1 for a in attempts if a.get("status") == "in_progress"),
        "submitted":   sum(1 for a in attempts if a.get("status") == "submitted"),
        "disqualified": sum(1 for a in attempts if a.get("status") == "disqualified"),
    }
    return jsonify({"attempts": attempts, "counts": counts})

@app.route("/admin/exams/<exam_id>/edit_time", methods=["POST"])
def edit_exam_time(exam_id):
    if not is_admin():
        return jsonify({"error": "Not authorized"}), 403
    start_time = request.form.get("start_time", "")
    duration   = request.form.get("duration_minutes", "")
    updates = {}
    if start_time:
        try:
            IST_OFFSET = timedelta(hours=5, minutes=30)
            naive_dt = datetime.fromisoformat(start_time)
            updates["start_time"] = naive_dt.replace(tzinfo=timezone(IST_OFFSET)).astimezone(timezone.utc).isoformat()
        except ValueError:
            return jsonify({"error": "Invalid start time"}), 400
    if duration:
        updates["duration_minutes"] = int(duration)
    if updates:
        firestore_set("exams", exam_id, updates)
    return redirect(url_for("exam_live_view", exam_id=exam_id))

@app.route("/admin/exams/<exam_id>/delete", methods=["POST"])
def delete_exam(exam_id):
    if not is_admin():
        return redirect(url_for("login"))
    firestore_delete("exams", exam_id)
    return redirect(url_for("list_exams"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
