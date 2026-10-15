# Meeting AI — Pipeline Tự Động Phân Tích & Kiểm Chứng Biên Bản Cuộc Họp

Hệ thống trích xuất và phân tích biên bản cuộc họp tiếng Việt từ transcript dạng hội thoại, tự động chuyển hoá thành các mục nghiệp vụ (Quyết định, Công việc, Mục tiêu, Vấn đề mở...) và tích hợp bước **kiểm chứng (audit/verify)** độc lập để phát hiện mâu thuẫn, sai lệch bằng chứng hoặc bỏ sót nội dung.

---

## 🏗️ Kiến trúc các bước trong Pipeline

```
Transcript thô (.txt) + Thông tin cuộc họp (.json)
  │
  ├── [Bước 1] Tiền xử lý (Code)                 ──► s1_turns.json
  ├── [Bước 2] Trích xuất hành động (LLM #1)     ──► s2_events.json
  ├── [Bước 3] Phân luồng & Lập mục (LLM #2 + Luật) ──► s3_threads.json
  ├── [Bước 6] Kiểm chứng độc lập (Code s6)      ──► s6_verified.json  (Gắn cờ needs_review)
  ├── [Bước 7] Ghép bản ghi cuộc họp (Code)       ──► s7_record.json
  └── [Bước 8] Xuất báo cáo trực quan (HTML)      ──► s8_report.html
```

---

## 🚀 Hướng Dẫn Cài Đặt & Chạy

### 1. Cài đặt thư viện & Môi trường

#### 1.1 Khởi tạo môi trường ảo (Khuyến nghị)
Mở terminal tại thư mục gốc của dự án (`meeting-ai`):

```powershell
# Tạo môi trường ảo
python -m venv .venv

# Kích hoạt môi trường ảo (Windows PowerShell)
.\.venv\Scripts\Activate.ps1
```

#### 1.2 Cài đặt các thư viện phụ thuộc
Cài đặt từ file `requirements.txt`:

```powershell
pip install -r requirements.txt
```

> Các thư viện cốt lõi gồm:
> - `pydantic>=2`: Định nghĩa schema và xác thực kiểu dữ liệu chặt chẽ.
> - `google-genai`: SDK chính thức gọi mô hình Google Gemini.
> - `python-dotenv`: Nạp biến môi trường tự động từ file `.env`.
> - `pytest`: Chạy bộ kiểm thử tự động (offline).

#### 1.3 Cấu hình API Key Gemini
Tạo hoặc mở file `.env` tại thư mục gốc và điền khóa API của bạn:

```env
# Lấy khoá API miễn phí tại: https://aistudio.google.com/apikey
GEMINI_API_KEY=your_gemini_api_key_here

# Mô hình sử dụng (mặc định gemini-2.5-flash tốc độ cao và chi phí thấp)
GEMINI_MODEL_EXTRACT=gemini-2.5-flash
GEMINI_MODEL_RESOLVE=gemini-2.5-flash
```

---

### 2. Chạy Thử Nghiệm Qua Giao Diện Web (Web Demo — Khuyến nghị)

Dự án có sẵn giao diện web trực quan, hoạt động độc lập bằng thư viện chuẩn của Python (**không cần cài thêm framework** như Flask hay FastAPI):

#### 2.1 Khởi động Web Server
Từ thư mục gốc dự án, chạy lệnh:

```powershell
python web_app.py
```

Khi màn hình hiện thông báo:
```
[Web Server] Đang chạy tại http://localhost:8080
[Web Server] Nhấn Ctrl+C để dừng server.
```

#### 2.2 Trải nghiệm trên trình duyệt
1. Mở trình duyệt và truy cập: **`http://localhost:8080`**
2. Tại giao diện web, bạn có 2 cách thực hiện:
   * **Cách 1 (Nhanh nhất):** Chọn một trong các **Case mẫu có sẵn** trong danh sách thả xuống (ví dụ `case1_dao_nguoc`, `case2_chot_ngam`...).
   * **Cách 2:** Tải lên trực tiếp 2 file của bạn: **Transcript (.txt)** và **Thông tin cuộc họp (.json)**.
3. *(Tùy chọn)* Tích chọn **"Chỉ chạy thử (Dry-run)"** nếu muốn kiểm tra prompt trước mà không tốn token API.
4. Bấm nút **"🚀 Bắt đầu phân tích cuộc họp"**.
5. Hệ thống sẽ tự động chạy toàn bộ pipeline và **hiển thị trực tiếp báo cáo HTML (Bước 8)** ngay trên trình duyệt với thanh điều hướng tiện lợi!

---

### 3. Chạy Bằng Dòng Lệnh (CLI Pipeline)

> [!IMPORTANT]
> **Lưu ý trên Windows PowerShell:** Trước khi chạy lệnh, hãy thiết lập mã hóa UTF-8 để hiển thị tiếng Việt mượt mà:
> ```powershell
> $env:PYTHONIOENCODING = "utf-8"
> ```

#### 3.1 Chạy thử nghiệm trước (Dry-run — KHÔNG tốn token)
Dùng cờ `--dry-run` để hệ thống chỉ tiền xử lý transcript và sinh prompt xem trước, **không gọi Gemini API**:

```powershell
python src/run.py data/samples/case1_dao_nguoc --dry-run
```

#### 3.2 Chạy thật từng case cụ thể
Hệ thống sẽ gọi LLM, áp dụng các luật trạng thái, chạy bước 6 kiểm chứng và tạo đầy đủ kết quả:

```powershell
# Chạy Case 1 (Đảo ngược quyết định)
python src/run.py data/samples/case1_dao_nguoc

# Chạy Case 2 (Chốt ngầm / Đồng thuận ngầm)
python src/run.py data/samples/case2_chot_ngam

# Chạy Case 3 (Để xem lại / Chưa chốt)
python src/run.py data/samples/case3_de_xem_lai

# Chạy Case 4 (Không chốt phương án)
python src/run.py data/samples/case4_khong_chot

# Chạy Case 5 (Giao việc ngầm)
python src/run.py data/samples/case5_giao_viec_ngam
```

#### 3.3 Chạy tự động TẤT CẢ các case trong 1 dòng lệnh
Duyệt qua toàn bộ các case mẫu trong `data/samples/`:

```powershell
Get-ChildItem -Directory data/samples | ForEach-Object { python src/run.py $_.FullName }
```

#### 3.4 Chạy lại từ Bước 6 (Kiểm chứng) không tốn token
Nếu bạn đã chạy trước đó và muốn thử nghiệm kiểm chứng lại mà **không gọi lại LLM**:

```powershell
python src/run.py data/runs/case1_dao_nguoc --tu-buoc 6
```

---

### 4. Đọc Kết Quả & Xem Báo Cáo HTML

Sau khi chạy xong, kết quả của từng case được lưu trong thư mục tương ứng tại `data/runs/<tên_case>/`:

```
data/runs/case1_dao_nguoc/
├── s1_turns.json       # Lượt nói chuẩn hoá
├── s2_events.json      # Danh sách sự kiện lời nói
├── s3_threads.json     # Các luồng và mục nghiệp vụ
├── s6_verified.json    # Kết quả kiểm chứng: danh sách findings + cờ review
├── s7_record.json      # Bản ghi cuộc họp hoàn chỉnh (JSON)
├── s8_report.html      # BÁO CÁO GIAO DIỆN TRỰC QUAN (HTML)
└── run_info.json       # Thống kê thời gian và số lượng token tiêu thụ
```

#### 4.1 Mở báo cáo HTML
Bạn có thể mở báo cáo trực quan bằng cách:
1. Mở thư mục `data/runs/case1_dao_nguoc/` trong File Explorer và **click đúp vào file `s8_report.html`**.
2. Hoặc mở trực tiếp từ dòng lệnh:
   ```powershell
   Start-Process data/runs/case1_dao_nguoc/s8_report.html
   ```

#### 4.2 Nội dung bạn sẽ thấy trên báo cáo `s8_report.html`:
- **Thông tin cuộc họp:** Ngày họp, tiêu đề, danh sách người tham gia và thẩm quyền chốt (`can_decide`).
- **Mục cần xem lại (Needs Review):** Các mục bị bước 6 gắn cờ nghi ngờ (ví dụ: người chốt không có thẩm quyền, trích dẫn lệch với lượt nói gốc, mâu thuẫn người phụ trách/deadline).
- **Quyết định (Decisions):** Phương án được chốt chính thức, lý do chốt và phương án bị loại/thay thế.
- **Công việc (Action Items):** Người chịu trách nhiệm (`owner`), hạn chót (`deadline`) đã được chuẩn hóa ra ngày cụ thể (YYYY-MM-DD), bằng chứng kèm theo.
- **Mục tiêu & Vướng mắc (Goals & Issues):** Mục tiêu chung của nhóm hoặc khó khăn/blocker còn tồn đọng.
- **Bảng phát hiện (Findings) từ Bước 6:** Báo cáo chi tiết của kiểm toán viên tự động (mức độ `ERROR` hoặc `WARNING`).

---

### 5. Chạy Bộ Kiểm Thử Tự Động (Unit Tests)

Bộ test chạy **offline 100%** (không cần kết nối mạng và không tốn token LLM) để đảm bảo toàn bộ logic của hệ thống luôn hoạt động chính xác:

```powershell
# Chạy toàn bộ test
pytest tests/ -v

# Hoặc chạy kiểm tra riêng bước 6 (Kiểm chứng)
pytest tests/test_s6_verify.py -v
```
#   m e e t i n g - a i  
 