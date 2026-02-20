import logging
from fastapi import FastAPI

# --- IMPORTS (Modular Structure) ---
# Folders/Files are snake_case: app.core.database
from app.core.database import init_db
from app.routers import webhooks, admin, dashboard
from app.services.scheduler import start_scheduler, scheduler
from app.core.logging_conf import setup_logging

# 1. Setup Logging
# Function name is snake_case
logger = setup_logging()

# 2. Initialize Database
init_db()

# 3. Initialize FastAPI App
# Variable 'app' is snake_case
app = FastAPI(
    title="Personal AI OS",
    description="Modular Monolith AI Agent System (Coach Dyno)",
    version="2.0.0"
)

# 4. Register Routers
# 'webhooks' and 'admin' are module names (snake_case)
# 'router' is the APIRouter instance inside them
app.include_router(webhooks.router)
app.include_router(admin.router)
app.include_router(dashboard.router) # Đăng ký router mới

# 5. Lifecycle Events
@app.on_event("startup")
async def startup_event():
    """Executed once when the container starts."""
    logger.info("🚀 Personal AI OS is starting up...")
    
    # Start background tasks
    start_scheduler()
    
    logger.info("✅ System Ready. Scheduler Active.")

@app.on_event("shutdown")
async def shutdown_event():
    """Executed when the container stops."""
    logger.info("🛑 Personal AI OS is shutting down...")
    
    # Gracefully stop the scheduler
    if scheduler.running:
        scheduler.shutdown()
        
    logger.info("✅ Scheduler Stopped. Goodbye!")