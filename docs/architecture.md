graph TD
    User((User)) <-->|Chat/Query| Interface[Telegram/Web UI]
    Strava[Strava Webhook] -->|Data| AgentCore
    Weather[Weather API] -->|Context| AgentCore
    
    subgraph "The AI AGENT (Brain)"
        AgentCore{Orchestrator (Gemini)}
        
        subgraph "Memory (RAG)"
            ShortTerm[Log bài tập tuần này]
            LongTerm[Lịch sử chấn thương, PR cũ]
            Knowledge[Sách/Giáo án chạy bộ]
        end
        
        subgraph "Tools (Tay chân)"
            Tool_Analysis[Phân tích CSV (Code hiện tại)]
            Tool_Plan[Lập lịch tập (Google Calendar)]
            Tool_Weather[Check thời tiết]
            Tool_Search[Search Google (Kiến thức mới)]
        end
    end

    AgentCore <--> Memory
    AgentCore --> Tools
    
    Tools -->|Update| StravaOutput[Strava Activity]
    Tools -->|Notify| Email_Telegram[Alert]