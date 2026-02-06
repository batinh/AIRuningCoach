# System Architecture

## Overview
The system operates as an event-driven middleware. It bypasses local network restrictions (NAT) using SSH Reverse Tunneling to receive real-time updates from Strava.

## Architecture Diagram

```mermaid
graph TD
    subgraph "External Cloud"
        User((User / Garmin)) -- 1. Sync --> STRAVA[Strava API]
        GEMINI[Google Gemini AI]
        Tunnel_Host["Tunnel Service (localhost.run)"]
    end

    subgraph "Secure Tunnel"
        STRAVA -- 2. Webhook Event --> Tunnel_Host
        Tunnel_Host == 3. Forward Traffic ==> SSH_Client
    end

    subgraph "Home Server (OMV)"
        SSH_Client["SSH Client Process"] -- 4. Localhost:8000 --> APP["Python Application (FastAPI)"]
        
        APP -- 5. Fetch Streams --> STRAVA
        APP -- 6. Send Context + Data --> GEMINI
        GEMINI -- 7. Return Analysis --> APP
        APP -- 8. Update Description --> STRAVA
    end

    %% Styles
    style STRAVA fill:#fc4c02,stroke:#333,color:white
    style GEMINI fill:#4285F4,stroke:#333,color:white
    style APP fill:#00C853,stroke:#333,color:white