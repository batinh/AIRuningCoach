import os
import shutil
import logging
from datetime import datetime

logger = logging.getLogger("AI_COACH")

def perform_backup():
    """
    Nén toàn bộ thư mục 'data/' thành file ZIP và lưu vào thư mục 'backups/'.
    Tự động xóa các bản backup cũ, chỉ giữ lại 7 bản gần nhất (xoay vòng 1 tuần).
    """
    source_dir = "data"
    backup_dir = "backups"
    
    # Tạo thư mục backups nếu chưa có
    os.makedirs(backup_dir, exist_ok=True)
    
    # Tạo tên file theo thời gian thực
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"coach_data_{timestamp}"
    backup_path = os.path.join(backup_dir, backup_filename)
    
    try:
        # Nén thư mục data/
        shutil.make_archive(backup_path, 'zip', source_dir)
        logger.info(f"[BACKUP] Đã sao lưu thành công: {backup_filename}.zip")
        
        # Dọn dẹp: Chỉ giữ lại 7 bản backup gần nhất để đỡ tốn ổ cứng T440
        all_backups = sorted([f for f in os.listdir(backup_dir) if f.endswith('.zip')])
        while len(all_backups) > 7:
            oldest_file = all_backups.pop(0)
            os.remove(os.path.join(backup_dir, oldest_file))
            logger.info(f"[BACKUP] Đã xóa bản sao lưu cũ: {oldest_file}")
            
    except Exception as e:
        logger.error(f"[BACKUP] Lỗi khi sao lưu dữ liệu: {e}")