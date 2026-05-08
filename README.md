# Boardroom

**The Multi-Agent Executive War Room for M&A Due Diligence.**

Boardroom is a collaborative multi-agent system designed to assist executives in making high-stakes decisions, specifically focused on M&A (Mergers and Acquisitions) target evaluation. Instead of a single AI response, Boardroom assembles a "war room" of specialized agents that research, analyze, and debate a deal in real-time.

## 🚀 Deployment & Demo
- **Frontend (Vercel):** [https://boardroom-agent-olympics-demo.vercel.app](https://boardroom-agent-olympics-demo.vercel.app)
- **Backend (FastAPI):** Docker-ready for persistent hosting (Railway, Fly.io, etc.)

### Vercel Deployment Note
To connect the frontend to a backend on Vercel:
1. Set the `BACKEND_URL` environment variable in your Vercel project to your public FastAPI URL.
2. If the backend is unavailable, the UI will automatically fall back to **Demo Mode** when you click "Load Demo Scenario".

### Demo Mode
Append `?demo=true` to the URL to run a bulletproof offline demo. The app now also automatically detects if the backend is offline and offers to switch to Demo Mode for a seamless presentation experience.

## 🧠 The Agent Team
- **Orchestrator:** Plans the workflow, extracts facts, and manages state using a **Blackboard Architecture**.
- **Researcher:** Pulls public data, news, and filings (via Tavily Search).
- **Analyst:** Deep analysis of business models, unit economics, and market fit.
- **Red Team:** Actively argues the opposing case to surface risks and challenge the Analyst.
- **Synthesizer:** Produces a board-ready executive brief with confidence scores and clickable citations.

## 🏗️ Architecture: The Blackboard Pattern
Boardroom uses a "Blackboard" architecture where agents read from and write to a shared session workspace.
1. **Inputs:** PDFs, Whiteboard Photos, and URLs are parsed and added to the Blackboard.
2. **Parallel Execution:** Researcher and Analyst run simultaneously.
3. **Adversarial Feedback:** Red Team critiques the analysis once initial work is done.
4. **Conflict Detection:** Orchestrator identifies material disagreements (e.g., "Analyst found strong growth; Red Team flagged customer concentration").
5. **Synthesis:** All findings are distilled into a final briefing document.

## 🛠️ Tech Stack
- **Frontend:** Next.js 15, Tailwind CSS, shadcn/ui, Lucide Icons. Deployed on **Vercel**.
- **Backend:** Python 3.11, FastAPI, Asyncio, Google GenAI SDK (Gemini 2.5 Flash/Pro).
- **Deployment:** Docker Compose ready, Caddy for HTTPS.

## 🏃 Getting Started

### Local Development
1. **Backend:**
   ```bash
   cd backend
   pip install -r requirements.txt
   # Set environment variables in .env
   python -m uvicorn main:app --reload
   ```
2. **Frontend:**
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

### Demoing
1. Open the frontend.
2. Click **"Load Demo Scenario"** to pre-populate TargetCo data.
3. Click **"Run Analysis"** and watch the agents collaborate in real-time.
4. If the backend is unavailable, add `?demo=true` to the URL for a simulated run.

## 🛡️ Hardening
- **Demo Mode:** Query-param driven fallback for offline demos.
- **Health Checks:** Real-time backend status monitoring in the UI.
- **Conflict Highlighting:** Visual markers for agent disagreements.
- **Streaming:** Server-Sent Events (SSE) for low-latency token-by-token reasoning.

---
Built for the **AI Agent Olympics Hackathon**.
