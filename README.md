# PSC Exam Trainer with Artificial Intelligence

A free, AI-powered web application for Kerala PSC exam preparation.

## Features
- 🔐 User & Admin login (Firebase Auth)
- 🔑 Forgot Password (for both Student & Admin)
- 🛡️ Admin signup via secret code
- 🧠 AI Doubt Solver (Groq AI)
- 📝 Timed Mock Tests
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

## Setup

1. Clone the repo
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in your keys (including `ADMIN_SECRET_CODE`)
4. Run: `python app.py`
