from fastapi import APIRouter, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Optional
import logging

# Import các module từ Core
from app.core.config import load_config, save_config
from app.core.notification import send_html_email
from app.core.logging_conf import log_capture_string 

# [QUAN TRỌNG] Import State chung của toàn hệ thống
from app.core.state import state

router = APIRouter()
templates = Jinja2Templates(directory="templates")
logger = logging.getLogger("AI_COACH")

@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    """
    Hiển thị giao diện Admin Dashboard.
    Lấy logs từ bộ nhớ đệm để hiển thị thời gian thực.
    """
    # Chuyển deque logs thành string
    logs_text = "\n".join(list(log_capture_string))
    
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "config": load_config(),
        "logs": logs_text,
        # Đọc trạng thái từ state chung
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
    email_enabled: Optional[str] = Form(None),
    debug_mode: Optional[str] = Form(None),
    model_name: str = Form("models/gemini-2.0-flash")
):
    """
    Xử lý form lưu cấu hình từ Admin UI.
    """
    config = load_config()
    
    # Cập nhật logic phân tích
    config["system_instruction"] = system_instruction
    config["user_profile"] = user_profile
    config["task_description"] = task_description
    config["analysis_requirements"] = analysis_requirements
    config["output_format"] = output_format
    config["max_hr"] = max_hr
    config["rest_hr"] = rest_hr
    config["race_date"] = race_date
    config["current_goal"] = current_goal
    
    # Cập nhật Email
    if "email_config" not in config: config["email_config"] = {}
    config["email_config"]["enabled"] = True if email_enabled == "on" else False
    config["email_config"]["smtp_server"] = config.get("email_config", {}).get("smtp_server", "smtp.gmail.com")
    config["email_config"]["smtp_port"] = config.get("email_config", {}).get("smtp_port", 587)
    
    # Cập nhật System settings
    config["debug_mode"] = True if debug_mode == "on" else False
    config["model_name"] = model_name
    
    save_config(config)
    logger.info(f"[ADMIN] Configuration saved. Active Model: {config['model_name']}")
    
    return RedirectResponse(url="/admin", status_code=303)

@router.get("/admin/test-email")
async def test_email_route():
    """
    Gửi email test để kiểm tra kết nối SMTP.
    """
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
async def toggle_service():
    """
    Bật/Tắt dịch vụ AI (Pause/Resume).
    """
    # Đảo ngược trạng thái trong state chung
    state.service_active = not state.service_active
    status = "RESUMED" if state.service_active else "PAUSED"
    logger.info(f"[ADMIN] Service {status}")
    return RedirectResponse(url="/admin", status_code=303)