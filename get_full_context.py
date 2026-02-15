import os

# --- CẤU HÌNH NGƯỜI DÙNG ---
# Tự động lấy đường dẫn Home của user hiện tại (ví dụ: /home/tinhn)
USER_HOME = os.path.expanduser("~")

# Danh sách các thư mục quan trọng cần quét
TARGET_DIRS = [
    os.path.join(USER_HOME, "repo", "AIRuningCoach"),  # Source Code
    os.path.join(USER_HOME, "nginx-proxy")             # Docker Infra
]

OUTPUT_FILE = "full_system_context.txt"

# --- BỘ LỌC (FILTER) ---
IGNORE_DIRS = {
    ".git", "__pycache__", "venv", "env", ".idea", ".vscode", 
    "node_modules", "site-packages", "data", "letsencrypt", "mysql" 
    # Bỏ qua data/mysql để tránh file nặng
}

IGNORE_FILES = {
    ".DS_Store", "package-lock.json", "yarn.lock", 
    "full_system_context.txt", "get_full_context.py", 
    "zwift-offline", # Nếu có file binary
}

# Các đuôi file cần đọc nội dung
INCLUDE_EXTENSIONS = {
    ".py", ".js", ".html", ".css", ".json", ".md", ".txt", 
    ".yml", ".yaml", ".sh", ".conf", ".env", "Dockerfile", "Makefile"
}

def scan_directory(path, output_file):
    if not os.path.exists(path):
        output_file.write(f"\n[!] WARNING: Directory not found: {path}\n")
        return

    output_file.write(f"\n{'='*20} SCANNING: {path} {'='*20}\n")

    # 1. TREE STRUCTURE
    output_file.write(f"--- STRUCTURE: {os.path.basename(path)} ---\n")
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        level = root.replace(path, "").count(os.sep)
        indent = " " * 4 * (level)
        output_file.write(f"{indent}{os.path.basename(root)}/\n")
        subindent = " " * 4 * (level + 1)
        for f in files:
            if f not in IGNORE_FILES:
                output_file.write(f"{subindent}{f}\n")
    
    output_file.write("\n")

    # 2. FILE CONTENTS
    output_file.write(f"--- CONTENTS: {os.path.basename(path)} ---\n")
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        for file in files:
            if file in IGNORE_FILES: continue
            
            _, ext = os.path.splitext(file)
            # Logic: Đọc nếu đúng đuôi file HOẶC là file không có đuôi (như Dockerfile)
            is_valid = (ext in INCLUDE_EXTENSIONS) or (file in INCLUDE_EXTENSIONS)
            
            if is_valid:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, USER_HOME) # Show path từ Home cho dễ nhìn
                
                output_file.write(f"\n>>> START FILE: ~/{rel_path}\n")
                
                # Xử lý bảo mật file .env
                if file == ".env":
                    output_file.write("# [SECURED] Content hidden. Structure only.\n")
                    output_file.write("# KEY=******\n")
                else:
                    try:
                        with open(file_path, "r", encoding="utf-8", errors='ignore') as f:
                            output_file.write(f.read())
                    except Exception as e:
                        output_file.write(f"[Error reading file: {e}]\n")
                
                output_file.write(f"\n<<< END FILE: ~/{rel_path}\n")

if __name__ == "__main__":
    print(f"Bắt đầu quét hệ thống của: {USER_HOME}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"REPORT GENERATED FOR USER: {os.environ.get('USER', 'Unknown')}\n")
        for target in TARGET_DIRS:
            print(f"-> Đang xử lý: {target}")
            scan_directory(target, f)
            
    print(f"\n✅ Xong! Toàn bộ context đã lưu vào: {OUTPUT_FILE}")
    print("👉 Hãy upload file này lên để tôi phân tích.")