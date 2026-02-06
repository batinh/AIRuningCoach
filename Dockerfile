# Dùng Python nhẹ
FROM python:3.11-slim

# Thiết lập thư mục làm việc
WORKDIR /app

# Copy file thư viện và cài đặt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ code vào
COPY . .

# Mở cổng 8000
EXPOSE 8000

# Lệnh chạy App khi khởi động
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
