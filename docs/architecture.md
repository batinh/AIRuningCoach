
## 🏗️ 2. System Architecture

The system utilizes a decoupled infrastructure where networking (Nginx/SSL) is isolated from the application logic.

```mermaid
graph TD
    %% External Inputs
    User(("🏃 Runner")) -->|"Telegram Chat"| Telegram["Telegram Webhook"]
    StravaCloud["Strava Cloud"] -->|"Activity Webhook"| Nginx

    %% Infra
    subgraph "INFRASTRUCTURE (runner-net)"
        Nginx["Nginx Proxy Manager"]
        SSL["Let's Encrypt"]
    end

    %% Application
    subgraph "MODULAR MONOLITH (FastAPI)"
        Gateway["main.py Gateway"]
        
        subgraph "Routers (API Layer)"
            HookRouter["Webhooks"]
            AdminRouter["Admin UI"]
        end
        
        subgraph "Services & Core"
            Cron["APScheduler"]
            State["Global App State"]
            DB[("SQLite Memory DB")]
        end
        
        subgraph "Domain Logic (Agents)"
            Coach["Coach Agent"]
            StravaAPI["Strava Integration"]
        end
    end

    %% External LLM
    Gemini["Google Gemini 2.0 API"]

    %% Connections
    Telegram --> Nginx
    Nginx -->|"Reverse Proxy :8000"| Gateway
    Gateway --> HookRouter
    Gateway --> AdminRouter
    
    HookRouter --> Coach
    Cron -->|"Trigger Harvest/Briefing"| Coach
    Coach <-->|"Context/History"| DB
    Coach <-->|"Fetch Raw Data"| StravaAPI
    Coach <-->|"Prompt Reasoning"| Gemini

```

---

## 📂 3. Project Structure

The project has been refactored from a flat-script structure into a scalable **Modular Monolith**:

```text
Personal_AI_OS/
├── app/                        # Main Application Package
│   ├── main.py                 # Lightweight Entry Point & FastAPI Init
│   ├── core/                   # ⚙️ SHARED INFRASTRUCTURE
│   │   ├── config.py           # Centralized Configuration Loader
│   │   ├── database.py         # SQLite Memory Manager
│   │   ├── logging_conf.py     # Centralized Logging Buffer
│   │   ├── notification.py     # Telegram & Email senders
│   │   └── state.py            # Global App State (Pause/Resume)
│   ├── services/               # 🔄 BACKGROUND SERVICES
│   │   └── scheduler.py        # APScheduler (Cron jobs)
│   ├── routers/                # 🌐 API ENDPOINTS
│   │   ├── admin.py            # Admin Dashboard UI Controller
│   │   └── webhooks.py         # Strava & Telegram event listeners
│   └── agents/                 # 🧠 DOMAIN LOGIC
│       └── coach/              # Coach Agent Enclave
│           ├── agent.py        # AI Reasoning & Prompt Engineering
│           ├── harvest.py      # Automated Data Harvester
│           ├── strava_client.py# Strava API Wrapper
│           └── utils.py        # Running metrics math (TRIMP, EF)
├── data/                       # Local Storage (SQLite, JSON Configs)
├── infra/                      # Independent Nginx & DuckDNS Configs
├── templates/                  # HTML Templates for Admin UI
├── docker-compose.yml          # Container Orchestration
└── .env                        # [SECRET] Environment Variables

```
