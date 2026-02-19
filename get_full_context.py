import os

# --- CẤU HÌNH NGƯỜI DÙNG ---
USER_HOME = os.path.expanduser("~")

# Tên thư mục Repository mới
REPO_NAME = "Personal_AI_OS"

# Danh sách các thư mục cần quét
# Vì nginx-proxy đã nằm trong infra của repo này, chỉ cần quét root repo là đủ
TARGET_DIRS = [
    os.path.join(USER_HOME, "repo", REPO_NAME)
]

OUTPUT_FILE = "full_system_context.txt"

# --- BỘ LỌC (FILTER) ---
# Các thư mục cần bỏ qua để file không bị quá nặng
IGNORE_DIRS = {
    ".git", "__pycache__", "venv", "env", ".idea", ".vscode", 
    "node_modules", "site-packages", "data", "letsencrypt", "mysql",
    "certs", "vhost.d", "html" # Bỏ qua các folder data của nginx nếu không cần thiết
}

# Các file cần bỏ qua
IGNORE_FILES = {
    ".DS_Store", "package-lock.json", "yarn.lock", 
    "full_system_context.txt", "get_full_context.py", 
    "zwift-offline", ".gitignore"
}

# Các đuôi file code & config quan trọng cần đọc nội dung
INCLUDE_EXTENSIONS = {
    # Code & Web
    ".py", ".js", ".html", ".css", ".json", ".md", ".txt", 
    # Config & Infra
    ".yml", ".yaml", ".sh", ".conf", ".env", "Dockerfile", "Makefile",
    ".ini", ".toml"
}

def scan_directory(path, output_file):
    if not os.path.exists(path):
        output_file.write(f"\n[!] WARNING: Directory not found: {path}\n")
        print(f"❌ Lỗi: Không tìm thấy thư mục {path}")
        return

    output_file.write(f"\n{'='*20} SCANNING: {path} {'='*20}\n")

    # 1. CẤU TRÚC THƯ MỤC (TREE STRUCTURE)
    # Giúp AI hình dung sơ đồ tổ chức file
    output_file.write(f"--- STRUCTURE: {os.path.basename(path)} ---\n")
    for root, dirs, files in os.walk(path):
        # Lọc bỏ các thư mục ignore
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        level = root.replace(path, "").count(os.sep)
        indent = " " * 4 * (level)
        output_file.write(f"{indent}{os.path.basename(root)}/\n")
        
        subindent = " " * 4 * (level + 1)
        for f in files:
            if f not in IGNORE_FILES:
                output_file.write(f"{subindent}{f}\n")
    
    output_file.write("\n")

    # 2. NỘI DUNG FILE (FILE CONTENTS)
    output_file.write(f"--- CONTENTS: {os.path.basename(path)} ---\n")
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        for file in files:
            if file in IGNORE_FILES: continue
            
            # Lấy đuôi file
            _, ext = os.path.splitext(file)
            
            # Logic: Đọc nếu đúng đuôi file HOẶC tên file chính xác (như Dockerfile)
            is_valid = (ext in INCLUDE_EXTENSIONS) or (file in INCLUDE_EXTENSIONS)
            
            if is_valid:
                file_path = os.path.join(root, file)
                # Tạo đường dẫn tương đối để AI dễ nhìn (VD: app/main.py thay vì /home/tinhn/...)
                rel_path = os.path.relpath(file_path, path)
                
                output_file.write(f"\n>>> START FILE: {rel_path}\n")
                
                # Xử lý bảo mật file .env (chỉ hiện tên biến, che giá trị)
                if file == ".env":
                    output_file.write("# [SECURED] Content hidden for security.\n")
                    try:
                        with open(file_path, "r", encoding="utf-8", errors='ignore') as f:
                            for line in f:
                                if "=" in line and not line.strip().startswith("#"):
                                    key = line.split("=")[0]
                                    output_file.write(f"{key}=******\n")
                                else:
                                    output_file.write(line)
                    except:
                        output_file.write("# Error reading .env\n")
                else:
                    try:
                        with open(file_path, "r", encoding="utf-8", errors='ignore') as f:
                            output_file.write(f.read())
                    except Exception as e:
                        output_file.write(f"[Error reading file: {e}]\n")
                
                output_file.write(f"\n<<< END FILE: {rel_path}\n")

if __name__ == "__main__":
    print(f"🚀 Bắt đầu quét hệ thống tại: {USER_HOME}/repo/{REPO_NAME}...")
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(f"REPORT GENERATED FOR USER: {os.environ.get('USER', 'Unknown')}\n")
        f.write(f"REPO ROOT: {REPO_NAME}\n")
        
        for target in TARGET_DIRS:
            print(f"-> Đang xử lý: {target}")
            scan_directory(target, f)
            
    print(f"\n✅ Xong! File context đã được tạo tại: {os.path.abspath(OUTPUT_FILE)}")
    print("👉 Hãy upload file này lên để tôi phân tích kiến trúc mới.")