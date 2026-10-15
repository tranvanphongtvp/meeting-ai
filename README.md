# Meeting AI — Pipeline Tự Động Phân Tích & Kiểm Chứng Biên Bản Cuộc Họp

Hệ thống trích xuất và phân tích biên bản cuộc họp tiếng Việt từ transcript dạng hội thoại, tự động chuyển hóa thành các mục nghiệp vụ như **Quyết định, Công việc, Mục tiêu, Vấn đề mở**, đồng thời tích hợp bước **kiểm chứng (Audit/Verify)** độc lập để phát hiện mâu thuẫn, sai lệch bằng chứng hoặc bỏ sót nội dung.

---

## 🏗️ Kiến trúc Pipeline

```text
Transcript thô (.txt) + Thông tin cuộc họp (.json)
  │
  ├── [Bước 1] Tiền xử lý (Code)
  │      └── s1_turns.json
  │
  ├── [Bước 2] Trích xuất hành động (LLM #1)
  │      └── s2_events.json
  │
  ├── [Bước 3] Phân luồng & Lập mục (LLM #2 + Luật)
  │      └── s3_threads.json
  │
  ├── [Bước 6] Kiểm chứng độc lập (Code)
  │      └── s6_verified.json (Gắn cờ needs_review)
  │
  ├── [Bước 7] Ghép bản ghi cuộc họp (Code)
  │      └── s7_record.json
  │
  └── [Bước 8] Xuất báo cáo trực quan (HTML)
         └── s8_report.html
```

---

## 🚀 Hướng Dẫn Cài Đặt & Chạy

### 1. Cài đặt thư viện và môi trường

#### 1.1. Khởi tạo môi trường ảo (khuyến nghị)

Mở terminal tại thư mục gốc của dự án (`meeting-ai`).

```powershell
# Tạo môi trường ảo
python -m venv .venv

# Kích hoạt môi trường ảo trên Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

#### 1.2. Cài đặt thư viện phụ thuộc

Cài đặt các thư viện từ file `requirements.txt`:

```powershell
pip install -r requirements.txt
```

Các thư viện cốt lõi gồm:

- `pydantic>=2`: Định nghĩa schema và xác thực kiểu dữ liệu.
- `google-genai`: SDK chính thức để gọi mô hình Google Gemini.
- `python-dotenv`: Nạp biến môi trường từ file `.env`.
- `pytest`: Chạy bộ kiểm thử tự động offline.

#### 1.3. Cấu hình Gemini API Key

Tạo file `.env` tại thư mục gốc dự án và điền API key của bạn.

Lấy API key tại: [Google AI Studio](https://aistudio.google.com/apikey).

```env
GEMINI_API_KEY=your_gemini_api_key_here

# Mô hình sử dụng
GEMINI_MODEL_EXTRACT=gemini-2.5-flash
GEMINI_MODEL_RESOLVE=gemini-2.5-flash
```

**Lưu ý:** Không commit file `.env` hoặc API key thật lên GitHub. Hãy thêm `.env` vào `.gitignore`.

---

### 2. Chạy thử nghiệm qua giao diện Web

Dự án có giao diện web trực quan, sử dụng thư viện chuẩn của Python nên không cần cài thêm framework như Flask hoặc FastAPI để khởi động giao diện hiện tại.

#### 2.1. Khởi động Web Server

Từ thư mục gốc dự án, chạy:

```powershell
python web_app.py
```

Khi server khởi động thành công, terminal sẽ hiển thị thông báo tương tự:

```text
[Web Server] Đang chạy tại http://localhost:8080
[Web Server] Nhấn Ctrl+C để dừng server.
```

#### 2.2. Sử dụng giao diện

1. Mở trình duyệt và truy cập [http://localhost:8080](http://localhost:8080).
2. Chọn một trong hai cách nhập dữ liệu:
   - **Cách 1 — Sử dụng case mẫu:** Chọn một case có sẵn, ví dụ `case1_dao_nguoc` hoặc `case2_chot_ngam`.
   - **Cách 2 — Tải file lên:** Upload file transcript (`.txt`) và file thông tin cuộc họp (`.json`).
3. (Tùy chọn) Chọn **Dry-run** nếu muốn kiểm tra prompt mà không gọi Gemini API.
4. Nhấn **🚀 Bắt đầu phân tích cuộc họp**.
5. Hệ thống chạy pipeline và hiển thị báo cáo HTML ở Bước 8 ngay trên trình duyệt.

---

### 3. Chạy Pipeline bằng dòng lệnh (CLI)

**Lưu ý trên Windows PowerShell:** Có thể thiết lập mã hóa UTF-8 để hiển thị tiếng Việt chính xác:

```powershell
$env:PYTHONIOENCODING = "utf-8"
```

#### 3.1. Chạy thử (Dry-run — không tốn token)

Sử dụng `--dry-run` để tiền xử lý transcript và sinh prompt xem trước mà không gọi Gemini API:

```powershell
python src/run.py data/samples/case1_dao_nguoc --dry-run
```

#### 3.2. Chạy một case cụ thể

Các lệnh dưới đây chạy pipeline cho từng case và tạo kết quả tương ứng:

```powershell
# Case 1: Đảo ngược quyết định
python src/run.py data/samples/case1_dao_nguoc

# Case 2: Chốt ngầm / Đồng thuận ngầm
python src/run.py data/samples/case2_chot_ngam

# Case 3: Để xem lại / Chưa chốt
python src/run.py data/samples/case3_de_xem_lai

# Case 4: Không chốt phương án
python src/run.py data/samples/case4_khong_chot

# Case 5: Giao việc ngầm
python src/run.py data/samples/case5_giao_viec_ngam
```

#### 3.3. Chạy tất cả các case mẫu

Duyệt qua toàn bộ thư mục `data/samples/`:

```powershell
Get-ChildItem -Directory data/samples | ForEach-Object {
    python src/run.py $_.FullName
}
```

#### 3.4. Chạy lại từ Bước 6 — Kiểm chứng

Nếu đã có kết quả từ các bước trước, bạn có thể chạy lại từ Bước 6 mà không gọi lại LLM:

```powershell
python src/run.py data/runs/case1_dao_nguoc --tu-buoc 6
```

---

### 4. Đọc kết quả và xem báo cáo HTML

Sau khi chạy xong, kết quả được lưu trong thư mục tương ứng bên trong `data/runs/`.

Ví dụ với `case1_dao_nguoc`:

```text
data/runs/case1_dao_nguoc/
├── s1_turns.json       # Các lượt nói đã chuẩn hóa
├── s2_events.json      # Danh sách sự kiện lời nói
├── s3_threads.json     # Các luồng và mục nghiệp vụ
├── s6_verified.json   # Kết quả kiểm chứng và cờ review
├── s7_record.json     # Bản ghi cuộc họp hoàn chỉnh
├── s8_report.html     # Báo cáo trực quan HTML
└── run_info.json      # Thống kê thời gian và token tiêu thụ
```

#### 4.1. Mở báo cáo HTML

**Cách 1:** Mở thư mục `data/runs/case1_dao_nguoc/` trong File Explorer và nhấp đúp vào file `s8_report.html`.

**Cách 2:** Mở trực tiếp bằng PowerShell:

```powershell
Start-Process data/runs/case1_dao_nguoc/s8_report.html
```

#### 4.2. Nội dung báo cáo HTML

Báo cáo `s8_report.html` cung cấp các thông tin sau:

- **Thông tin cuộc họp:** Ngày họp, tiêu đề, danh sách người tham gia và thẩm quyền ra quyết định (`can_decide`).
- **Mục cần xem lại (Needs Review):** Các mục được Bước 6 gắn cờ nghi ngờ, chẳng hạn người chốt không có thẩm quyền, trích dẫn không khớp với lượt nói gốc hoặc mâu thuẫn về người phụ trách và deadline.
- **Quyết định (Decisions):** Phương án được chốt chính thức, lý do lựa chọn và phương án bị loại hoặc thay thế.
- **Công việc (Action Items):** Người chịu trách nhiệm (`owner`), hạn chót (`deadline`) chuẩn hóa theo định dạng `YYYY-MM-DD` và bằng chứng liên quan.
- **Mục tiêu và vướng mắc (Goals & Issues):** Mục tiêu chung, khó khăn và các blocker còn tồn đọng.
- **Bảng phát hiện (Findings):** Các vấn đề được Bước 6 phát hiện, với mức độ nghiêm trọng như `ERROR` hoặc `WARNING`.

---

### 5. Chạy bộ kiểm thử tự động (Unit Tests)

Bộ kiểm thử được thiết kế để chạy offline, không cần kết nối API LLM và không tiêu tốn token.

#### 5.1. Chạy toàn bộ test

```powershell
pytest tests/ -v
```

#### 5.2. Chỉ kiểm thử Bước 6 — Kiểm chứng

```powershell
pytest tests/test_s6_verify.py -v
```

---

**Tên dự án:** `meeting-ai`
