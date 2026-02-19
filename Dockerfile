FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ code
COPY . .

# Quan trọng: Set Python Path để nhận diện module 'app'
ENV PYTHONPATH=/app

# Lệnh chạy trỏ vào app.main:app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]