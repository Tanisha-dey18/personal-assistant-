# JARVIS
> *Your mind, extended.*

JARVIS is a personal AI companion with **long-term memory**, a **personal knowledge graph**, **voice**, **tools** and a **life dashboard**. It remembers your background, projects, goals and past conversations, so each conversation picks up where the last one left off.

```
┌──────────────────────── Frontend (React + TS + Vite + Tailwind + Framer Motion) ────────────────────────┐
│ Animated orb · streaming chat · voice (mic → STT, TTS playback) · dashboard · memory · graph · settings  │
└───────────────▲ REST (JWT) ─────────────────────────────── WebSocket /api/chat/ws (streaming) ▲─────────┘
                │                                                                                │
┌───────────────┴──────────────────────────── Backend (FastAPI) ────────────────────────────────┴─────────┐
│ auth · rate limits · AI engine (modes, prompt, tool loop) · memory engine · tools · voice · importers    │
│ proactive engine (background loop) · integrations (Google OAuth, GitHub PAT, Tavily) · export/wipe       │
└──────┬───────────────────────────────┬──────────────────────────────┬──────────────────────┬────────────┘
  PostgreSQL / SQLite            Qdrant (vectors)               Redis (optional)     OpenAI-compatible API
  memories, graph, chats,        memory / document /            rate limits, cache   chat, embeddings,
  tasks, projects, career…       conversation embeddings                             STT, TTS
```

---

## 1. What's built (and working)

| Area | What you get |
|---|---|
| **AI brain** | Streaming chat over WebSocket, tool calling loop, multi-turn context, rolling conversation summaries, usage tracking. You can swap providers: any OpenAI-compatible API works via `OPENAI_BASE_URL`, and there is one `LLMProvider` interface for adding others. |
| **Personality & 7 modes** | Companion, Professor, Career Mentor, Developer, Research, Executive and Reality Check. **Auto mode** picks one from what you write; you can also switch manually. Sarcasm, verbosity, Hinglish and custom instructions are adjustable in settings. |
| **Long-term memory** | After every message a fast model pulls out facts, which are categorised, marked **confirmed / assumption / temporary** and scored for importance. Near-duplicates are merged and existing memories are updated when facts change. **Sensitive facts wait for your approval** and are **encrypted at rest**. |
| **Semantic retrieval** | Each reply gets only the relevant slice of memory: similarity + importance + recency ranking, core identity facts, knowledge-graph links, relevant past conversations, document excerpts, open tasks. You can open *"N memories used"* on any reply to see exactly what was sent. |
| **Knowledge graph** | Entities (people, events, projects, technologies, skills, goals, achievements…) and relations are built automatically and shown as an interactive force graph. Click a node to see its memories. |
| **"What JARVIS knows about me"** | A live profile built from the memory database, an AI-written portrait, and queues for pending sensitive items and assumptions to confirm. You can edit anything. |
| **Timeline** | Dated memories, career milestones and projects in one timeline. |
| **Voice** | Push-to-talk with automatic end-of-speech detection, speech-to-text that handles Hinglish, natural TTS with 10 voices, interruptible playback, a **hands-free** loop, and an orb that reacts to your mic and to JARVIS's voice. The mic is never on in the background. |
| **Tools** | Memory search/save/update/forget, tasks, reminders, projects, career tracker, document search, daily briefing, weather (no key needed), web search (Tavily), read webpage (SSRF-protected), Google Calendar + Gmail, GitHub. |
| **Human-in-the-loop** | Sending email, creating calendar events and deleting memories only **prepare** an action. A confirmation card appears and nothing happens until you click Confirm. |
| **Dashboard** | Home (greeting, clock, AI status, quick chat, priorities, reminders, weekly chart, projects, recent chats), Career (pipeline kanban, roadmap, skills, internships, achievements), Projects, Productivity (tasks, week planner, reminders, calendar), Memory, Import, Integrations, AI Settings. |
| **Proactive engine** | Due reminders, task deadlines, stale projects, project deadlines, follow-ups on job applications, and a weekly AI report. Each one can be turned off in settings. Shown in the bell menu and as optional browser notifications. |
| **Onboarding & imports** | An 8-question onboarding, uploads of CV/PDF/DOCX/MD/TXT, the **ChatGPT export** (.zip or conversations.json), and pasted free text. JARVIS extracts facts and queues clarifying questions when something is ambiguous. |
| **Security & privacy** | bcrypt passwords, JWT, every query filtered by `user_id` (tested), Fernet encryption for sensitive memories and all stored credentials, API keys only on the server, rate limiting, input validation, SSRF guard, security headers, full **JSON export**, scoped **data wipe**, account deletion. |

---

## 2. Quick start (local, no Docker) — about 5 minutes

You need **Python 3.11+** and **Node 18+**.

### Backend
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env
```
Open `backend/.env` and set:
* `OPENAI_API_KEY` — from https://platform.openai.com/api-keys (needed for chat, memory, voice)
* `SECRET_KEY` — any long random string: `python -c "import secrets;print(secrets.token_urlsafe(48))"`
* `ENCRYPTION_KEY` — `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"`
  **Back this key up.** If you lose it, encrypted memories can't be read.

```bash
uvicorn app.main:app --reload --port 8000
```
With no database URLs set, JARVIS uses a **SQLite file + embedded Qdrant** in `backend/data/`, so you don't need to install any databases.
API docs: http://localhost:8000/api/docs

### Frontend
```bash
cd frontend
npm install
npm run dev
```
Open **http://localhost:5173**, create your account and run the onboarding. Then say *"Hey Jarvis, what's going on?"*

> **Tip:** once your account exists, set `ALLOW_REGISTRATION=false` in `backend/.env` so nobody else can sign up on your instance.

> **Free option (Google Gemini):** get a free key at https://aistudio.google.com/apikey and use the Gemini block in `backend/.env.example`. Chat, tools, memory and embeddings all work; spoken replies use the browser voice.

> **No server key?** You can also paste an OpenAI key (or an OpenRouter/Groq key plus base URL) in **Integrations → AI brain**. It's verified, stored encrypted, and used only for your account.

---

## 3. Full stack with Docker (Postgres + Qdrant + Redis)
```bash
cp backend/.env.example backend/.env     # fill in OPENAI_API_KEY, SECRET_KEY, ENCRYPTION_KEY
docker compose up --build
```
Open **http://localhost:8080**. Compose wires up the database, vector store and cache automatically, and nginx serves the frontend and proxies `/api` (including the WebSocket).

---

## 4. Optional integrations

| Integration | Setup |
|---|---|
| **Web search** | Free key at https://tavily.com, then put it in `TAVILY_API_KEY` or paste it in Integrations. |
| **Weather** | Works out of the box (Open-Meteo). |
| **GitHub** | GitHub → Settings → Developer settings → **Fine-grained token**, read-only access to Contents/Issues/Metadata. Paste it in Integrations. |
| **Google Calendar + Gmail** | See below. |

### Google setup
1. https://console.cloud.google.com → create a project.
2. **APIs & Services → Library**: enable **Gmail API** and **Google Calendar API**.
3. **OAuth consent screen**: choose External, add your email as a **Test user** (testing mode is fine for personal use), and add the scopes `calendar.events`, `gmail.readonly` and `gmail.send`.
4. **Credentials → Create OAuth client ID → Web application**. Add this authorised redirect URI:
   `http://localhost:8000/api/integrations/google/callback` (in production use `https://YOUR-BACKEND/api/integrations/google/callback`; it must match `BACKEND_PUBLIC_URL`).
5. Put `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in `backend/.env`, restart, and click **Connect Google** in Integrations.

---

## 5. Deploying

**Free setup:** backend on **Render's free plan**, Postgres on **Neon** (free and permanent), vectors on **Qdrant Cloud** (free 1 GB), frontend on **Vercel** (free). Only OpenAI usage costs money.

> Why not Render's own Postgres? Render's free database is **deleted after 30 days**, which would wipe JARVIS's memory. Neon's free tier doesn't expire.

1. **Neon:** https://console.neon.tech → create a project and copy the connection string (`postgresql://…?sslmode=require`). JARVIS converts it for its async driver automatically.
2. **Qdrant Cloud:** create a free cluster and copy its URL and API key.
3. **Backend on Render:** *New → Blueprint*, point it at this repo (it uses `render.yaml`, which sets `plan: free`). If Render shows a price, check the instance type says **Free**. Set these env vars:
   `OPENAI_API_KEY`, `ENCRYPTION_KEY`, `DATABASE_URL` (Neon), `QDRANT_URL`, `QDRANT_API_KEY`,
   `FRONTEND_URL=https://your-app.vercel.app`, `BACKEND_PUBLIC_URL=https://astra-api.onrender.com`,
   `CORS_ORIGINS=https://your-app.vercel.app`. `SECRET_KEY` is generated for you.
   Free instances sleep after about 15 minutes idle, so the first message after a break takes 30–60 seconds.
   *Railway:* create a service from `backend/` (it has a Dockerfile) and set the same variables. Railway gives a one-time trial credit, then it's paid.
4. **Frontend on Vercel:** import the repo, set the root directory to `frontend`, add the env var `VITE_API_URL=https://astra-api.onrender.com`, and deploy (`vercel.json` handles SPA routes).
5. Create your account, then set `ALLOW_REGISTRATION=false` on the backend.

> Run **one** backend process when using embedded Qdrant (local file mode). With Qdrant server/Cloud plus Postgres you can scale out. Free Render instances sleep when idle, so proactive nudges only fire while the instance is awake.

---

## 6. How the memory engine works (simple version)

1. **You talk** → JARVIS replies (streamed).
2. **In the background**, a small, cheap model reads your message and answers one question: *"What here is worth remembering about this person?"* It gets the most similar **existing** memories alongside, so it can **update** an old fact instead of making a duplicate.
3. Each fact becomes a row in Postgres (text, category, type, importance, source) **plus** a vector in Qdrant. The vector is a list of numbers that captures meaning, so *"that drone hackathon"* still finds *"won 2nd place at SIH with a crop-monitoring drone"*. As a second safety net, anything ≥ 92% similar to an existing memory is merged.
4. People, projects and technologies mentioned in the fact become **graph nodes**, and the links between them become **edges**.
5. **Next message:** JARVIS embeds what you said, pulls the top matches (ranked by similarity, importance and recency), adds a few always-relevant identity facts, 1-hop graph links, related older conversations and open tasks, and puts **only that** in the prompt.

Qdrant payloads contain only IDs (no text), so the vector DB holds nothing readable about you.

---

## 7. Project structure
```
backend/
  app/main.py                 FastAPI app, lifespan (DB, vectors, proactive loop)
  app/core/                   config, db, security (JWT/bcrypt/Fernet), cache, deps (auth + rate limit)
  app/models.py               all tables
  app/ai/provider.py          LLM provider abstraction (chat stream, complete, embed, STT, TTS)
  app/ai/modes.py             identity prompt, 7 modes, auto-mode classifier
  app/ai/engine.py            the chat turn orchestrator (retrieve → prompt → stream → tools → save → learn)
  app/memory/                 vectors (Qdrant), store (CRUD/dedupe/encryption), extractor, retriever, graph
  app/tools/                  registry (+ confirmation flow), builtin tools, google, github
  app/services/               conversations, documents, importer, proactive, profile, usage, settings
  app/api/                    auth, chat (WebSocket), memory, productivity, content, system
  tests/                      20 end-to-end tests with a deterministic fake LLM
frontend/
  src/lib/                    api client, websocket client, voice (recorder/player), store, types
  src/components/             Orb (canvas), Layout, Markdown, ActionCard, MemoryCard, KnowledgeGraph, ui kit
  src/pages/                  Home, Chat, Profile, Memory, Career, Projects, Productivity, Import, Integrations, Settings, Login, Onboarding
docker-compose.yml · render.yaml · frontend/vercel.json
```

---

## 8. Testing
```bash
cd backend
pip install -r requirements-dev.txt
pytest -q
```
The tests run the real app (DB, vectors, WebSocket, tool loop, extraction, graph) against a **deterministic fake LLM**, so they need no API key. They cover auth, streaming chat, auto-mode, memory extraction → retrieval, dedupe, sensitive-memory approval + encryption at rest, **cross-user isolation**, tool calls, confirmation-gated actions, documents, ChatGPT import, voice endpoints, settings/export/wipe and proactive reminders. The fake LLM is used only by tests; the app never falls back to fake responses.

Frontend: `npm run build` (type-checks + production build).

---

## 9. Key decisions, explained simply
* **SQLite + embedded Qdrant by default:** you can run JARVIS today without installing databases. The same code switches to Postgres/Qdrant server/Redis just by setting URLs.
* **Keyword auto-mode, not an extra AI call:** choosing the mode costs zero latency and zero money. You can always override it.
* **Memory extraction after the reply:** you never wait for it. Its result shows up as a toast ("🧠 Remembered…").
* **Separate fast model for extraction/summaries:** it's cheaper, and the main model can be anything you like.
* **Confirmation cards instead of "are you sure?" in chat:** an LLM can misunderstand, but a button can't. Consequential actions literally cannot run without your click.
* **`create_all` instead of migrations (for now):** tables are created automatically on startup. If you change models later, add Alembic (`alembic init`) before deploying schema changes to real data.

## 10. Honest limitations / next steps
* Proactive nudges appear in-app and as browser notifications while JARVIS is open. There's no mobile push yet; a PWA + Web Push or a Telegram bot would be the next step.
* Voice is push-to-talk with auto-stop (plus an optional hands-free loop). There's no wake word ("Hey Jarvis") yet.
* Scanned (image-only) PDFs need OCR first.
* Weekly reports and stale-project checks run only while the backend is running.
* Changing `EMBEDDING_MODEL`/`EMBEDDING_DIM` after data exists requires re-creating the Qdrant collections (re-embedding).
