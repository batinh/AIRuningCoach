### 🗄️ DATABASE ARCHITECTURE DESIGN (v2.3.0 - Multi-Tenant Ready)

**Triết lý thiết kế (Design Philosophy):**

* **Zero-Heavy:** Sử dụng SQLite và file-based DB, không yêu cầu cài đặt Docker container DB riêng biệt.
* **Multi-Tenant:** Tất cả các bảng và bản ghi (records) đều phải có `user_id` để cô lập dữ liệu giữa các Runner.
* **Separation of Concerns (Phân tách trách nhiệm):** Phân chia rõ ràng giữa Dữ liệu cấu trúc (Toán học/Logic), Dữ liệu phi cấu trúc (Ngữ nghĩa/AI) và Cấu hình hệ thống.

---

#### 🏛️ TIER 1: RELATIONAL DATABASE (Dữ liệu Cấu trúc & Tính toán)

**Công nghệ:** SQLite (`data/os_core.db`)
**Mục đích:** Lưu trữ hồ sơ người dùng, các chỉ số toán học chính xác (TRIMP, ACWR) và lịch sử hoạt động để query tốc độ cao.

**1. Table: `users` (Hồ sơ Vận động viên)**
Thay vì lưu `max_hr`, `rest_hr` trong `config.json`, chúng ta dời nó vào DB để mỗi Runner có một chỉ số riêng.

* `user_id` (TEXT, Primary Key) - *Nên dùng Strava Athlete ID hoặc Telegram Chat ID để làm ID gốc.*
* `name` (TEXT)
* `max_hr` (INTEGER)
* `rest_hr` (INTEGER)
* `race_date` (TEXT) - *Ngày thi đấu mục tiêu (YYYY-MM-DD).*
* `current_goal` (TEXT)
* `is_active` (BOOLEAN) - *Trạng thái hoạt động.*

**2. Table: `run_activities` (Lịch sử Strava)**

* `activity_id` (TEXT, Primary Key) - *ID bài chạy từ Strava.*
* `user_id` (TEXT, Foreign Key -> `users.user_id`) - **[QUAN TRỌNG] Gắn thẻ chủ nhân.**
* `name` (TEXT)
* `start_date` (DATETIME)
* `distance_km` (REAL)
* `moving_time_min` (REAL)
* `avg_hr` (INTEGER)
* `max_hr` (INTEGER)
* `suffer_score` (INTEGER) - *Mức độ nỗ lực (Từ Strava).*
* `trimp_score` (REAL) - *Điểm TRIMP hệ thống tự tính toán.*

**3. Table: `chat_history` (Lịch sử giao tiếp)**

* `id` (INTEGER, Primary Key, Auto Increment)
* `user_id` (TEXT, Foreign Key -> `users.user_id`) - **[QUAN TRỌNG] Tránh AI chat lẫn lộn nội dung giữa 2 người.**
* `role` (TEXT) - *'user' hoặc 'model'.*
* `content` (TEXT)
* `timestamp` (DATETIME)

---

#### 🧠 TIER 2: VECTOR DATABASE (Trí nhớ Dài hạn & Ngữ nghĩa)

**Công nghệ:** ChromaDB (`data/chroma_db`)
**Mục đích:** Lưu trữ Embeddings để AI tìm kiếm ngữ cảnh, so sánh chéo các bài chạy và nhớ lại lời khuyên cũ.

**Collection: `os_memory**`
Khi dùng hàm `rag_db.memorize()`, chúng ta bắt buộc phải tiêm `user_id` vào phần `metadata`.

* **`id`**: Unique ID (Ví dụ: `run_12345` hoặc `chat_9876`).
* **`document`**: Semantic Text (Văn bản chứa ngữ nghĩa).
* **`metadata`**:
```json
{
    "user_id": "telegram_id_cua_tinh",  // Bắt buộc
    "domain": "coach",                  // Phân loại: coach, finance, life
    "type": "run_analysis",             // Phân loại chi tiết
    "date": "2026-02-20"
}

```



*Khi query hồi tưởng (recall), hệ thống sẽ luôn có điều kiện `where={"user_id": current_user_id}` để AI không lấy nhầm bài chạy của người khác vào tư vấn cho bạn.*

---

#### ⚙️ TIER 3: SYSTEM CONFIGURATION (Trạng thái & Cấu hình App)

**Công nghệ:** JSON File (`config.json` & `.env`)
**Mục đích:** Chỉ lưu trữ các cấu hình mang tính chất **hệ thống (System-wide)**, không phụ thuộc vào cá nhân VĐV nào.

**Nội dung `config.json` thu gọn:**

* **`scheduler`**: Khung giờ chạy auto-sync.
* **`email_config`**: SMTP server, Port, Enable/Disable.
* **`system`**: `debug_mode`, `model_name` (Phiên bản Gemini đang dùng).
* *(Lưu ý: Các trường như `system_instruction` hay `user_profile` có thể chuyển thành mặc định (default template) và lưu biến thể riêng cho từng `user` trong SQLite sau này).*

---
