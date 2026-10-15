"""
web_app.py - Giao diện web đơn giản cho Meeting AI Pipeline.

Tính năng:
1. Tải lên file transcript (.txt) và meeting (.json) hoặc chọn case mẫu có sẵn.
2. Tự động chạy toàn bộ pipeline (Bước 1 -> Bước 8).
3. Trả về trực tiếp giao diện báo cáo HTML của bước 8 (s8_report.html).
4. KHÔNG can thiệp hay sửa đổi bất kỳ file mã nguồn nào đã có trong hệ thống.
5. Sử dụng thư viện chuẩn của Python (Zero dependency, không cần cài thêm framework).

Chạy ứng dụng:
    python web_app.py
    (hoặc: .\\.venv\\Scripts\\python.exe web_app.py)

Mở trình duyệt:
    http://localhost:8080
"""

import email
from email.policy import default
import json
import os
from pathlib import Path
import sys
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# Thêm thư mục src vào đường dẫn tìm kiếm module
THU_MUC_GOC = Path(__file__).resolve().parent
THU_MUC_SRC = THU_MUC_GOC / "src"
if str(THU_MUC_SRC) not in sys.path:
    sys.path.insert(0, str(THU_MUC_SRC))

from pipeline import chay_pipeline  # noqa: E402


PORT = 8080
THU_MUC_RUNS = THU_MUC_GOC / "data" / "runs"
THU_MUC_SAMPLES = THU_MUC_GOC / "data" / "samples"


def lay_danh_sach_mau() -> list[str]:
    """Lấy danh sách các case mẫu có sẵn trong data/samples."""
    if not THU_MUC_SAMPLES.exists():
        return []
    return sorted(
        d.name for d in THU_MUC_SAMPLES.iterdir()
        if d.is_dir() and (d / "transcript.txt").exists() and (d / "meeting.json").exists()
    )


HTML_TRANG_CHU = """<!DOCTYPE html>
<html lang="vi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Meeting AI — Phân Tích & Kiểm Chứng Cuộc Họp</title>
    <style>
        :root {
            --primary: #2563eb;
            --primary-hover: #1d4ed8;
            --bg: #f8fafc;
            --card-bg: #ffffff;
            --text: #1e293b;
            --muted: #64748b;
            --border: #e2e8f0;
            --success: #16a34a;
            --danger: #dc2626;
        }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            padding: 40px 20px;
        }
        .container {
            max-width: 800px;
            margin: 0 auto;
        }
        .header {
            text-align: center;
            margin-bottom: 30px;
        }
        .header h1 {
            font-size: 28px;
            color: #0f172a;
            margin-bottom: 8px;
        }
        .header p {
            color: var(--muted);
            font-size: 15px;
        }
        .card {
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 32px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
            margin-bottom: 24px;
        }
        .section-title {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 16px;
            color: #334155;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            font-size: 14px;
            font-weight: 500;
            margin-bottom: 6px;
            color: #334155;
        }
        .hint {
            font-size: 12px;
            color: var(--muted);
            margin-top: 4px;
        }
        .file-drop {
            border: 2px dashed var(--border);
            border-radius: 8px;
            padding: 20px;
            text-align: center;
            background: #fdfdfd;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        .file-drop:hover {
            border-color: var(--primary);
            background: #f8faff;
        }
        input[type="file"] {
            display: none;
        }
        .file-name {
            margin-top: 8px;
            font-size: 13px;
            font-weight: 600;
            color: var(--primary);
        }
        .divider {
            display: flex;
            align-items: center;
            text-align: center;
            margin: 24px 0;
            color: var(--muted);
            font-size: 13px;
        }
        .divider::before, .divider::after {
            content: '';
            flex: 1;
            border-bottom: 1px solid var(--border);
        }
        .divider:not(:empty)::before { margin-right: 15px; }
        .divider:not(:empty)::after { margin-left: 15px; }
        select {
            width: 100%;
            padding: 10px 14px;
            border: 1px solid var(--border);
            border-radius: 8px;
            background: #ffffff;
            font-size: 14px;
            color: var(--text);
            outline: none;
        }
        select:focus {
            border-color: var(--primary);
        }
        .options {
            background: #f1f5f9;
            padding: 16px;
            border-radius: 8px;
            margin-bottom: 24px;
        }
        .option-item {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 14px;
            cursor: pointer;
        }
        button.btn-submit {
            width: 100%;
            padding: 14px;
            background: var(--primary);
            color: #ffffff;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            transition: background 0.2s;
        }
        button.btn-submit:hover {
            background: var(--primary-hover);
        }
        button.btn-submit:disabled {
            background: #94a3b8;
            cursor: not-allowed;
        }
        /* Loading Overlay */
        #loading-overlay {
            display: none;
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background: rgba(255, 255, 255, 0.92);
            z-index: 9999;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            text-align: center;
            padding: 20px;
        }
        .spinner {
            width: 50px;
            height: 50px;
            border: 4px solid #e2e8f0;
            border-top: 4px solid var(--primary);
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-bottom: 20px;
        }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        .steps-box {
            background: #ffffff;
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 20px;
            max-width: 480px;
            width: 100%;
            margin-top: 15px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
            text-align: left;
            font-size: 13px;
            color: var(--muted);
        }
        .step-item {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 8px;
        }
        .step-item.active {
            color: var(--primary);
            font-weight: 600;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Meeting AI Pipeline</h1>
            <p>Trích xuất, phân luồng, kiểm chứng độc lập & tạo báo cáo cuộc họp tự động</p>
        </div>

        <form id="pipeline-form" action="/run" method="POST" enctype="multipart/form-data">
            <div class="card">
                <div class="section-title">📁 Tùy chọn 1: Tải lên dữ liệu cuộc họp</div>
                
                <div class="form-group">
                    <label>1. Transcript cuộc họp (.txt)</label>
                    <div class="file-drop" onclick="document.getElementById('transcript-file').click()">
                        <span>📄 Kéo thả hoặc click để chọn file <strong>transcript.txt</strong></span>
                        <div id="transcript-name" class="file-name"></div>
                    </div>
                    <input type="file" id="transcript-file" name="transcript" accept=".txt">
                    <div class="hint">Định dạng mỗi dòng: [HH:MM:SS] Tên người nói: Lời nói...</div>
                </div>

                <div class="form-group">
                    <label>2. Thông tin cuộc họp (.json)</label>
                    <div class="file-drop" onclick="document.getElementById('meeting-file').click()">
                        <span>⚙️ Kéo thả hoặc click để chọn file <strong>meeting.json</strong></span>
                        <div id="meeting-name" class="file-name"></div>
                    </div>
                    <input type="file" id="meeting-file" name="meeting" accept=".json">
                    <div class="hint">Chứa meeting_id, meeting_date, danh sách người tham gia (roster), quyền chốt...</div>
                </div>

                <div class="divider">HOẶC DÙNG DỮ LIỆU CÓ SẴN</div>

                <div class="form-group">
                    <label>📂 Tùy chọn 2: Chọn cuộc họp mẫu để thử nhanh</label>
                    <select name="sample_case" id="sample-case">
                        <option value="">-- Chọn một case mẫu trong data/samples/ --</option>
                        {SAMPLE_OPTIONS}
                    </select>
                </div>
            </div>

            <div class="card options">
                <div class="section-title">⚙️ Chế độ xử lý</div>
                <label class="option-item">
                    <input type="checkbox" name="dry_run" value="true">
                    <span><strong>Chế độ thử nghiệm (Dry-run):</strong> Chỉ xử lý transcript và sinh prompt xem trước, KHÔNG gọi Gemini API (không tốn token).</span>
                </label>
            </div>

            <button type="submit" id="submit-btn" class="btn-submit">
                <span>🚀 Chạy Pipeline & Xem Báo Cáo</span>
            </button>
        </form>
    </div>

    <!-- Loading Overlay -->
    <div id="loading-overlay">
        <div class="spinner"></div>
        <h2 style="font-size: 20px; color: #0f172a; margin-bottom: 8px;">Đang xử lý cuộc họp...</h2>
        <p style="color: #64748b; font-size: 14px;">Hệ thống đang thực hiện quy trình tự động từ Bước 1 đến Bước 8.</p>
        <div class="steps-box">
            <div class="step-item active">▶ [1] Tiền xử lý & chuẩn hoá transcript</div>
            <div class="step-item">▶ [2] Gọi Gemini AI trích xuất hành động lời nói</div>
            <div class="step-item">▶ [3] Phân luồng nghị sự & chốt mục nghiệp vụ</div>
            <div class="step-item">▶ [6] Kiểm toán viên kiểm chứng mâu thuẫn & bằng chứng</div>
            <div class="step-item">▶ [7-8] Ghép bản ghi & sinh báo cáo trực quan</div>
        </div>
        <p style="margin-top: 15px; font-size: 12px; color: #94a3b8;">Thời gian xử lý trung bình từ 10 - 25 giây...</p>
    </div>

    <script>
        const transcriptInput = document.getElementById('transcript-file');
        const meetingInput = document.getElementById('meeting-file');
        const sampleSelect = document.getElementById('sample-case');
        const form = document.getElementById('pipeline-form');
        const submitBtn = document.getElementById('submit-btn');
        const loadingOverlay = document.getElementById('loading-overlay');

        transcriptInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                document.getElementById('transcript-name').textContent = '✓ Đã chọn: ' + e.target.files[0].name;
                sampleSelect.value = '';
            }
        });

        meetingInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) {
                document.getElementById('meeting-name').textContent = '✓ Đã chọn: ' + e.target.files[0].name;
                sampleSelect.value = '';
            }
        });

        sampleSelect.addEventListener('change', () => {
            if (sampleSelect.value) {
                transcriptInput.value = '';
                meetingInput.value = '';
                document.getElementById('transcript-name').textContent = '';
                document.getElementById('meeting-name').textContent = '';
            }
        });

        form.addEventListener('submit', (e) => {
            const hasFiles = transcriptInput.files.length > 0 && meetingInput.files.length > 0;
            const hasSample = sampleSelect.value !== '';

            if (!hasFiles && !hasSample) {
                e.preventDefault();
                alert('Vui lòng chọn đủ 2 file (transcript.txt & meeting.json) HOẶC chọn một case mẫu có sẵn.');
                return;
            }

            if (hasFiles && (transcriptInput.files.length === 0 || meetingInput.files.length === 0)) {
                e.preventDefault();
                alert('Bạn cần tải lên ĐỦ CẢ HAI file: transcript.txt VÀ meeting.json.');
                return;
            }

            loadingOverlay.style.display = 'flex';
            submitBtn.disabled = true;
        });
    </script>
</body>
</html>
"""


BAR_DIEU_HUONG = """
<div id="web-toolbar" style="
    position: sticky; top: 0; left: 0; right: 0; z-index: 10000;
    background: #0f172a; color: #f8fafc; padding: 10px 20px;
    display: flex; align-items: center; justify-content: space-between;
    box-shadow: 0 2px 8px rgba(0,0,0,0.25); font-family: sans-serif; font-size: 14px;
">
    <div style="display: flex; align-items: center; gap: 12px;">
        <a href="/" style="
            background: #2563eb; color: #fff; text-decoration: none;
            padding: 6px 14px; border-radius: 6px; font-weight: 600; font-size: 13px;
        ">⬅️ Phân tích cuộc họp khác</a>
        <span style="color: #94a3b8; font-size: 13px;">Thư mục kết quả: <strong style="color: #cbd5e1;">{RUN_DIR}</strong></span>
    </div>
    <div>
        <button onclick="window.print()" style="
            background: #334155; color: #f8fafc; border: 1px solid #475569;
            padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 13px;
        ">🖨️ In / Lưu PDF</button>
    </div>
</div>
"""


class WebHandler(BaseHTTPRequestHandler):
    """Xử lý các HTTP request."""

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/" or parsed.path == "/index.html":
            self._gui_trang_chu()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Trang không tồn tại.")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/run":
            self._xu_ly_chay_pipeline()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Đường dẫn không hợp lệ.")

    def _gui_trang_chu(self) -> None:
        samples = lay_danh_sach_mau()
        options_html = "\n".join(
            f'<option value="{s}">{s}</option>' for s in samples
        )
        noi_dung = HTML_TRANG_CHU.replace("{SAMPLE_OPTIONS}", options_html)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(noi_dung.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(noi_dung.encode("utf-8"))

    def _xu_ly_chay_pipeline(self) -> None:
        """Đọc file upload, chạy pipeline và trả về kết quả s8_report.html."""
        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", 0))

        if not content_type.startswith("multipart/form-data") or content_length == 0:
            self._gui_loi("Yêu cầu không hợp lệ: Cần gửi form dạng multipart/form-data.")
            return

        body = self.rfile.read(content_length)

        # Parse multipart form data bằng email parser chuẩn của Python
        header_bytes = f"Content-Type: {content_type}\r\n\r\n".encode("utf-8")
        msg = email.message_from_bytes(header_bytes + body, policy=default)

        transcript_bytes = b""
        meeting_bytes = b""
        sample_case = ""
        is_dry_run = False

        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if name == "transcript":
                transcript_bytes = part.get_payload(decode=True) or b""
            elif name == "meeting":
                meeting_bytes = part.get_payload(decode=True) or b""
            elif name == "sample_case":
                sample_case = (part.get_payload(decode=True) or b"").decode("utf-8", errors="ignore").strip()
            elif name == "dry_run":
                val = (part.get_payload(decode=True) or b"").decode("utf-8", errors="ignore").strip()
                if val == "true":
                    is_dry_run = True

        # Chuẩn bị thư mục cuộc họp đầu vào
        ma_run = f"web_{int(time.time())}"
        thu_muc_run = THU_MUC_RUNS / ma_run
        thu_muc_cuoc_hop: Path

        if sample_case:
            thu_muc_cuoc_hop = THU_MUC_SAMPLES / sample_case
            if not thu_muc_cuoc_hop.exists():
                self._gui_loi(f"Case mẫu '{sample_case}' không tồn tại trong data/samples.")
                return
        else:
            if not transcript_bytes or not meeting_bytes:
                self._gui_loi("Vui lòng tải lên cả 2 file: transcript.txt VÀ meeting.json.")
                return

            # Kiểm tra định dạng JSON
            try:
                json.loads(meeting_bytes.decode("utf-8"))
            except Exception as e:
                self._gui_loi(f"File meeting.json không đúng định dạng JSON hợp lệ: {e}")
                return

            # Lưu vào thư mục input
            thu_muc_cuoc_hop = thu_muc_run / "input"
            thu_muc_cuoc_hop.mkdir(parents=True, exist_ok=True)
            (thu_muc_cuoc_hop / "transcript.txt").write_bytes(transcript_bytes)
            (thu_muc_cuoc_hop / "meeting.json").write_bytes(meeting_bytes)

        # Chạy pipeline
        try:
            thu_muc_run.mkdir(parents=True, exist_ok=True)
            ket_qua = chay_pipeline(
                thu_muc_cuoc_hop=thu_muc_cuoc_hop,
                thu_muc_run=thu_muc_run,
                dry_run=is_dry_run,
            )
        except Exception as e:
            self._gui_loi(f"Có lỗi xảy ra trong quá trình chạy pipeline: {e}")
            return

        if not ket_qua.ok and not is_dry_run:
            ds_loi = "<br>".join(f"• {l}" for l in ket_qua.loi)
            self._gui_loi(f"Pipeline dừng vì có lỗi dữ liệu:<br>{ds_loi}")
            return

        # Trả về kết quả
        if is_dry_run:
            # Hiển thị prompt đã sinh
            prompt_file = thu_muc_run / "s2_prompt.txt"
            prompt_text = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else "(Không thấy file prompt)"
            html = f"""<!DOCTYPE html>
            <html lang="vi">
            <head><meta charset="utf-8"><title>Kết Quả Dry-run</title>
            <style>
                body {{ font-family: sans-serif; padding: 30px; background: #f8fafc; color: #1e293b; }}
                .box {{ background: #fff; padding: 24px; border-radius: 8px; border: 1px solid #e2e8f0; }}
                pre {{ background: #0f172a; color: #f8fafc; padding: 16px; border-radius: 6px; overflow: auto; max-height: 500px; }}
                a {{ display: inline-block; margin-bottom: 16px; color: #2563eb; font-weight: 600; text-decoration: none; }}
            </style>
            </head>
            <body>
                <a href="/">⬅️ Quay lại trang chủ</a>
                <div class="box">
                    <h2>✓ Chế độ Dry-run thành công</h2>
                    <p style="margin: 8px 0 16px; color: #64748b;">Hệ thống đã hoàn tất tiền xử lý và tạo nội dung prompt (chưa gọi LLM):</p>
                    <pre>{prompt_text}</pre>
                </div>
            </body></html>"""
            self._tra_ve_html(html)
            return

        # Kết quả chạy thật: trả về file s8_report.html
        file_html = thu_muc_run / "s8_report.html"
        if not file_html.exists():
            self._gui_loi(f"Không tìm thấy file báo cáo kết quả tại: {file_html}")
            return

        noi_dung_html = file_html.read_text(encoding="utf-8")

        # Chèn thanh điều hướng lên đầu trang báo cáo
        toolbar = BAR_DIEU_HUONG.replace("{RUN_DIR}", str(thu_muc_run))
        if "<body" in noi_dung_html:
            parts = noi_dung_html.split("<body", 1)
            body_tag, rest = parts[1].split(">", 1)
            noi_dung_html = parts[0] + "<body" + body_tag + ">" + toolbar + rest
        else:
            noi_dung_html = toolbar + noi_dung_html

        self._tra_ve_html(noi_dung_html)

    def _tra_ve_html(self, html_text: str) -> None:
        encoded = html_text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _gui_loi(self, thong_diep: str) -> None:
        html = f"""<!DOCTYPE html>
        <html lang="vi">
        <head><meta charset="utf-8"><title>Lỗi Pipeline</title>
        <style>
            body {{ font-family: sans-serif; padding: 40px 20px; background: #fef2f2; color: #991b1b; text-align: center; }}
            .box {{ max-width: 600px; margin: 0 auto; background: #fff; padding: 30px; border-radius: 10px; border: 1px solid #fecaca; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }}
            h2 {{ margin-bottom: 15px; color: #dc2626; }}
            p {{ color: #475569; font-size: 15px; line-height: 1.6; margin-bottom: 24px; text-align: left; }}
            a {{ display: inline-block; background: #dc2626; color: #fff; padding: 10px 20px; border-radius: 6px; text-decoration: none; font-weight: 600; }}
        </style>
        </head>
        <body>
            <div class="box">
                <h2>⚠️ Thông Báo Lỗi</h2>
                <p>{thong_diep}</p>
                <a href="/">⬅️ Quay lại trang chủ</a>
            </div>
        </body></html>"""
        encoded = html.encode("utf-8")
        self.send_response(HTTPStatus.BAD_REQUEST)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def chay_server() -> None:
    server_address = ("127.0.0.1", PORT)
    httpd = ThreadingHTTPServer(server_address, WebHandler)
    print("=" * 60)
    print(f"🚀 Meeting AI Web Server đang chạy tại: http://localhost:{PORT}")
    print(f"   (hoặc http://127.0.0.1:{PORT})")
    print("   Nhấn Ctrl + C để dừng máy chủ.")
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nĐang tắt máy chủ...")
        httpd.server_close()
        print("Đã dừng.")


if __name__ == "__main__":
    chay_server()
