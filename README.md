# Boardroom

**The Multi-Agent Executive War Room for M&A Due Diligence.**

Boardroom is a collaborative multi-agent system designed to assist executives in making high-stakes decisions, specifically focused on M&A (Mergers and Acquisitions) target evaluation. Instead of a single AI response, Boardroom assembles a "war room" of specialized agents that research, analyze, and debate a deal in real-time.

## The Agent Team
- **Orchestrator:** Plans the workflow and manages state.
- **Researcher:** Pulls public data, news, and filings.
- **Analyst:** Ingests financials and pitch decks for deep analysis.
- **Red Team:** Actively argues the opposing case to surface risks.
- **Synthesizer:** Produces a board-ready executive brief.

## Tech Stack
- **Backend:** Python (FastAPI, Asyncio)
- **Frontend:** Next.js (Tailwind, shadcn/ui)
- **AI:** Google Gemini (Pro & Flash) via Vertex AI
- **Deployment:** Vultr (Docker, Caddy)

## Project Structure
- `/backend`: FastAPI application and agent logic.
- `/frontend`: Next.js web application.
- `/infra`: Deployment configurations (Docker, Caddy).
- `/demo-assets`: Sample pitch decks, images, and data for demos.

## Getting Started
(Detailed setup instructions to follow in Phase 1)
# agent-olympics
