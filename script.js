// ── Chatbot ───────────────────────────────────────────────
function sendMessage() {
  const input = document.getElementById("chat-input");
  const messages = document.getElementById("chat-messages");
  const question = input.value.trim();
  if (!question) return;

  // User message
  messages.innerHTML += `<div class="message user">${question}</div>`;
  input.value = "";
  messages.scrollTop = messages.scrollHeight;

  // Typing indicator
  messages.innerHTML += `<div class="message ai" id="typing"><i>Thinking...</i></div>`;
  messages.scrollTop = messages.scrollHeight;

  fetch("/student/ask_doubt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question })
  })
  .then(res => res.json())
  .then(data => {
    document.getElementById("typing").remove();
    messages.innerHTML += `<div class="message ai">${data.answer}</div>`;
    messages.scrollTop = messages.scrollHeight;
  })
  .catch(() => {
    document.getElementById("typing").remove();
    messages.innerHTML += `<div class="message ai">Sorry, something went wrong. Please try again.</div>`;
  });
}

// Send on Enter key
document.addEventListener("DOMContentLoaded", () => {
  const chatInput = document.getElementById("chat-input");
  if (chatInput) {
    chatInput.addEventListener("keypress", (e) => {
      if (e.key === "Enter") sendMessage();
    });
  }
});

// ── Quiz Timer ────────────────────────────────────────────
function startTimer(seconds) {
  const timerEl = document.getElementById("timer");
  if (!timerEl) return;
  let remaining = seconds;
  const interval = setInterval(() => {
    remaining--;
    const mins = Math.floor(remaining / 60).toString().padStart(2, "0");
    const secs = (remaining % 60).toString().padStart(2, "0");
    timerEl.textContent = `${mins}:${secs}`;
    if (remaining <= 60) timerEl.classList.add("urgent");
    if (remaining <= 0) {
      clearInterval(interval);
      submitQuiz();
    }
  }, 1000);
}

// ── Quiz Submission ───────────────────────────────────────
function submitQuiz() {
  const answers = {};
  document.querySelectorAll(".option-btn.selected").forEach(btn => {
    answers[btn.dataset.qid] = btn.dataset.option;
  });

  fetch("/student/submit_quiz", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answers })
  })
  .then(res => res.json())
  .then(data => {
    document.getElementById("quiz-area").innerHTML = `
      <div class="card" style="max-width:400px;margin:2rem auto;text-align:center;">
        <div class="card-body">
          <i class="fas fa-trophy" style="font-size:3rem;color:var(--warning);margin-bottom:1rem;display:block;"></i>
          <h2 style="font-family:var(--font-display);font-size:2rem;margin-bottom:0.5rem;">
            ${data.score} / ${data.total}
          </h2>
          <p style="color:var(--gray-500);margin-bottom:1.5rem;">
            ${data.score >= data.total * 0.8 ? "Excellent! 🎉" : data.score >= data.total * 0.5 ? "Good job! Keep practicing." : "Keep going! You'll do better next time."}
          </p>
          <a href="/student/quiz" class="btn btn-primary">Try Again</a>
          &nbsp;
          <a href="/student/dashboard" class="btn btn-outline">Dashboard</a>
        </div>
      </div>`;
  });
}

// ── Option Select ─────────────────────────────────────────
document.addEventListener("click", (e) => {
  if (e.target.classList.contains("option-btn")) {
    const qid = e.target.dataset.qid;
    document.querySelectorAll(`[data-qid="${qid}"]`).forEach(btn => btn.classList.remove("selected"));
    e.target.classList.add("selected");
  }
});

// ── Answer Evaluator ──────────────────────────────────────
function evaluateAnswer() {
  const question = document.getElementById("eval-question")?.value.trim();
  const answer   = document.getElementById("eval-answer")?.value.trim();
  const resultEl = document.getElementById("eval-result");
  if (!question || !answer) return alert("Please enter both question and your answer.");

  resultEl.innerHTML = "<i>Evaluating your answer...</i>";

  fetch("/student/evaluate_answer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, answer })
  })
  .then(res => res.json())
  .then(data => {
    resultEl.innerHTML = `<pre style="white-space:pre-wrap;font-family:inherit;">${data.feedback}</pre>`;
  });
}

// ── Past Paper Analyzer ───────────────────────────────────
function analyzePaper() {
  const fileInput = document.getElementById("paper-file");
  const resultEl  = document.getElementById("analysis-result");
  if (!fileInput?.files[0]) return alert("Please select a PDF file.");

  const formData = new FormData();
  formData.append("paper", fileInput.files[0]);
  resultEl.innerHTML = "<i>Analyzing paper with AI... this may take a moment.</i>";

  fetch("/student/analyze_paper", { method: "POST", body: formData })
  .then(res => res.json())
  .then(data => {
    resultEl.innerHTML = `<pre style="white-space:pre-wrap;font-family:inherit;">${data.analysis}</pre>`;
  });
}

// ── Global Scroll-Reveal ──────────────────────────────────
// Adds a quick fade+rise entrance to cards/stat-cards/etc as they
// scroll into view, on every page, without needing new HTML classes.
document.addEventListener("DOMContentLoaded", () => {
  const targets = document.querySelectorAll(
    ".stat-card, .card, .feature-card, .note-card, .question-card, .file-card"
  );
  if (!("IntersectionObserver" in window) || !targets.length) return;

  targets.forEach((el) => {
    el.classList.add("reveal-ready");
  });

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add("reveal-visible");
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });

  targets.forEach((el) => observer.observe(el));
});

// ── Confetti burst on a great score ───────────────────────
// Call celebrate() from a result page when the score is high.
function celebrate() {
  if (typeof confetti !== "function") return;
  const colors = ["#FFE65C", "#FF6FA6", "#7CF29C", "#5CDFFF", "#A6791F"];
  confetti({ particleCount: 90, spread: 70, origin: { y: 0.6 }, colors });
  setTimeout(() => confetti({ particleCount: 60, spread: 100, origin: { y: 0.4 }, colors }), 250);
}
