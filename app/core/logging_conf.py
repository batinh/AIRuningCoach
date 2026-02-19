import logging
from collections import deque

# Bộ đệm lưu 50 dòng log cuối cùng để hiển thị lên Web Admin
log_capture_string = deque(maxlen=50)

class ListHandler(logging.Handler):
    """Custom Handler để đẩy log vào deque"""
    def emit(self, record):
        try:
            msg = self.format(record)
            log_capture_string.append(msg)
        except Exception:
            self.handleError(record)

def setup_logging():
    """Khởi tạo logging cho toàn bộ ứng dụng"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    logger = logging.getLogger("AI_COACH")
    
    # Thêm ListHandler để capture log cho Admin UI
    list_handler = ListHandler()
    list_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(list_handler)
    
    return logger