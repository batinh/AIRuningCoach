import os
import secrets
import logging
from typing import Optional

from fastapi import APIRouter, Request, Form, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import load_config, save_config
from app.core.notification import send_html_email
from app.core.logging_conf import log_capture_string 
from app.core.state import state
from app.services.scheduler import reload_scheduler

router = APIRouter()
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger("AI_COACH")

# ==========================================
# 🔐 AUTHENTICATION SETUP
# ==========================================
security = HTTPBasic()

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """Kiểm tra Username và Password từ file .env"""
    env_user = os.getenv("ADMIN_USERNAME", "admin")
    env_pass = os.getenv("ADMIN_PASSWORD", "123456")
    
    # Sử dụng secrets.compare_digest để chống lỗi Timing Attacks (Bảo mật nâng cao)
    is_user_ok = secrets.compare_digest(credentials.username, env_user)
    is_pass_ok = secrets.compare_digest(credentials.password, env_pass)
    
    if not (is_user_ok and is_pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sai tài khoản hoặc mật khẩu!",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# ==========================================
# 🌐 ADMIN ROUTES
# ==========================================

@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, username: str = Depends(verify_credentials)):
    """Hiển thị giao diện Admin Dashboard."""
    logs_text = "\n".join(list(log_capture_string))
    
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "config": load_config(),
        "logs": logs_text,
        "service_active": state.service_active
    })

@router.post("/admin/save")
async def save_settings(
    request: Request,
    system_instruction: str = Form(...),
    user_profile: str = Form(...),
    task_description: str = Form(...),
    analysis_requirements: str = Form(...),
    output_format: str = Form(...),
    max_hr: int = Form(185),
    rest_hr: int = Form(55),
    race_date: Optional[str] = Form(None),
    current_goal: str = Form(""),
    briefing_time: str = Form("06:00"),
    backup_time: str = Form("02:00"),
    harvest_hours: str = Form("0,6,12,18"),
    harvest_minute: str = Form("15"),
    email_enabled: Optional[str] = Form(None),
    debug_mode: Optional[str] = Form(None),
    model_name: str = Form("models/gemini-2.0-flash"),
    username: str = Depends(verify_credentials)
):
    """Xử lý form lưu cấu hình từ Admin UI."""
    config = load_config()
    
    # 1. Cập nhật thông tin AI Persona
    config["system_instruction"] = system_instruction
    config["user_profile"] = user_profile
    config["task_description"] = task_description
    config["analysis_requirements"] = analysis_requirements
    config["output_format"] = output_format
    
    # 2. Cập nhật thông số Sinh lý học & Mục tiêu (Sports Science)
    config["max_hr"] = max_hr
    config["rest_hr"] = rest_hr
    config["race_date"] = race_date
    config["current_goal"] = current_goal
    
    # 3. Cập nhật Lịch trình (Scheduler)
    config["scheduler"] = {
        "briefing_time": briefing_time,
        "backup_time": backup_time,
        "harvest_hours": harvest_hours,
        "harvest_minute": harvest_minute
    }
    
    # 4. Cập nhật Email config
    if "email_config" not in config:
        config["email_config"] = {}
    config["email_config"]["enabled"] = True if email_enabled == "on" else False
    config["email_config"]["smtp_server"] = config.get("email_config", {}).get("smtp_server", "smtp.gmail.com")
    config["email_config"]["smtp_port"] = config.get("email_config", {}).get("smtp_port", 587)
    
    # 5. Cập nhật System settings
    config["debug_mode"] = True if debug_mode == "on" else False
    config["model_name"] = model_name
    
    save_config(config)
    reload_scheduler()
    
    logger.info(f"[ADMIN] Auth User '{username}' saved configuration.")
    return RedirectResponse(url="/admin", status_code=303)

@router.get("/admin/save", include_in_schema=False)
async def catch_accidental_get_save(username: str = Depends(verify_credentials)):
    """
    Bẫy lỗi 405: Nếu user vô tình F5 hoặc gõ thẳng /admin/save lên thanh địa chỉ (GET),
    hệ thống sẽ nhẹ nhàng chuyển hướng họ về lại trang chủ Admin thay vì báo lỗi.
    """
    logger.info(f"[ADMIN] Bắt được request GET đi lạc vào /admin/save từ user '{username}'. Đang đưa về trang chủ...")
    return RedirectResponse(url="/admin", status_code=303)

@router.get("/admin/test-email")
async def test_email_route(username: str = Depends(verify_credentials)):
    """Gửi email test để kiểm tra kết nối SMTP."""
    try:
        cfg = load_config()
        send_html_email(
            "Test Email from AI Coach", 
            "<h1>It Works!</h1><p>Hệ thống gửi email của bạn đang hoạt động tốt.</p>", 
            cfg
        )
        return {"status": "success"}
    except Exception as e:
        logger.error(f"[ADMIN] Test email failed: {e}")
        return {"status": "error", "message": str(e)}

@router.post("/admin/toggle")
async def toggle_service(username: str = Depends(verify_credentials)):
    """Bật/Tắt dịch vụ AI (Pause/Resume)."""
    state.service_active = not state.service_active
    status = "RESUMED" if state.service_active else "PAUSED"
    logger.info(f"[ADMIN] User '{username}' triggered Service {status}")
    return RedirectResponse(url="/admin", status_code=303)