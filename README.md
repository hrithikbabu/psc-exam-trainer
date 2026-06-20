# PSC Exam Trainer with Artificial Intelligence

A free, AI-powered web application for Kerala PSC exam preparation.

## Features
- 🔐 User & Admin login (Firebase Auth)
- 🔑 Forgot Password (for both Student & Admin)
- 🛡️ Admin signup via secret code
- 🧠 AI Doubt Solver (Groq AI)
- 📝 Practice Quiz (untimed, casual)
- ⏱️ **Proctored Timed Exams** — admin-scheduled, live attendance tracking, anti-cheat lockdown, AI evaluation on submit (see below)
- 🤖 AI Mock Test Generator
- ✍️ AI Answer Evaluator
- 📄 Previous Year Paper Analyzer
- 📚 Study Notes (Cloudinary)
- 🏆 Leaderboard & Streaks

## Tech Stack
- **Backend:** Python (Flask)
- **Frontend:** HTML, CSS, JavaScript
- **AI:** Groq API (Llama 3)
- **Database:** Firebase Firestore
- **Auth:** Firebase Authentication
- **Storage:** Cloudinary
- **Hosting:** Render.com

## How to Create an Admin Account
1. Set an `ADMIN_SECRET_CODE` value in your `.env` / Render environment variables (e.g. `psc-admin-2026`).
2. Go to the Register page and sign up like normal, but type that exact code into the "Admin Secret Code" field.
3. That account is now an admin and will land on the Admin Dashboard after login.
4. Leave the code blank for normal student accounts.

## Forgot Password
Both students and admins can click "Forgot password?" on the login page, enter their email,
and Firebase will email them a reset link automatically (no extra setup needed — Firebase
sends this by default).

## Proctored Timed Exams
Admin → "Exams" in the nav → "Schedule New Exam".

- Set title, subject, difficulty, question count, **question source** (existing bank or fresh AI-generated), exam **start time**, and **duration**.
- Students see the exam on `/student/exams`. Before start time they see a live countdown; once live, "Enter Now" unlocks.
- **Lockdown:** once inside, switching tabs, minimizing, losing window focus, closing/refreshing the tab, right-clicking, copy/paste, or common devtools shortcuts (F12, Ctrl+Shift+I/J/C, Ctrl+U) all immediately end the attempt and mark it `disqualified`. A disqualified student cannot re-enter that exam.
- The countdown timer is calculated from the **server's stored start time + duration**, not the student's local clock, so changing your system clock doesn't grant extra time.
- Admin gets a **live attendance dashboard** (auto-refreshes every 4 seconds) showing who's in progress, who's submitted, who's been disqualified, and live scores as they come in.
- Admin can adjust an exam's start time or duration after creation from the live view page.
- On submit, answers are graded instantly (exact match), and Groq AI generates a short written performance summary + one improvement tip, shown alongside the revealed correct answers.

### Notes / known limitations (worth knowing before you present this)
- Anti-cheat is enforced **client-side via JavaScript** (`visibilitychange`, `blur`, `beforeunload`, blocked key combos). This deters casual cheating but a technically determined student could bypass it (e.g. via browser devtools network tab, disabling JS). For a fully tamper-proof system you'd need a native proctoring client or browser lockdown extension — out of scope for this build, but worth mentioning as a "future work" item if this is a college project.
- Live attendance uses **polling** (the admin page re-fetches every 4 seconds), not WebSockets. Simple and reliable at small/classroom scale; wouldn't scale to thousands of concurrent test-takers without more infra.
- AI evaluation on submit is a **written summary**, not per-question AI grading — actual scoring is exact-match against the stored correct answer (MCQs only). If you want free-text/short-answer questions in timed exams with AI-graded scoring, that's a reasonable next feature to add.

## Setup

1. Clone the repo
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in your keys (including `ADMIN_SECRET_CODE`)
4. Run: `python app.py`
