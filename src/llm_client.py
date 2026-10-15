"""
llm_client.py - Lớp bọc mỏng gọi LLM (hiện dùng Gemini qua gói miễn phí).

Vì sao tách riêng: gói miễn phí hay đổi hạn mức, tên mô hình, chính sách. Mọi bước
LLM trong pipeline chỉ gọi `generate_json(system_prompt, user_content)`, nên đổi
nhà cung cấp chỉ cần viết lại file này.

Cấu hình (đặt trong file .env, KHÔNG commit khoá thật):
    GEMINI_API_KEY=...        khoá lấy tại aistudio.google.com/apikey
    GEMINI_MODEL=...          tên mô hình (không đặt thì dùng MODEL_MAC_DINH)

Cách ép đầu ra: dùng "JSON mode" (response_mime_type = application/json) và mô tả
định dạng ngay trong prompt. KHÔNG gửi schema Pydantic lên API, vì chưa kiểm chứng
được mô hình có nhận mọi cấu trúc schema hay không. Đổi lại, phía code tự kiểm tra
kết quả và thử lại khi sai (xem s2_extract_acts.py).

LƯU Ý QUYỀN RIÊNG TƯ: dữ liệu gửi lên gói miễn phí có thể được nhà cung cấp dùng để
cải thiện sản phẩm. Chỉ dùng dữ liệu tự dựng, KHÔNG dùng transcript thật của doanh nghiệp.
"""

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

# Tên mô hình mặc định theo yêu cầu "Gemini 3.5 Flash Lite". Tên này lấy từ các trang
# bên thứ ba, CHƯA đối chiếu với trang chính thức. Hãy kiểm tra trong Google AI Studio
# trước khi chạy thật, hoặc ghi đè bằng biến môi trường GEMINI_MODEL.
MODEL_MAC_DINH = "gemini-3.5-flash-lite"

# Mã lỗi tạm thời đáng thử lại (quá tải, vượt hạn mức theo phút, lỗi máy chủ).
MA_LOI_THU_LAI = {429, 500, 502, 503, 504}


class LoiLLM(Exception):
    """Gọi LLM thất bại (sau khi đã thử lại nếu là lỗi tạm thời)."""


class LoiCauHinh(LoiLLM):
    """Thiếu khoá API, thiếu thư viện... cần người dùng sửa cấu hình."""


@dataclass
class KetQuaLLM:
    """Kết quả một lần gọi LLM, kèm số token để theo dõi chi phí/hạn mức."""

    text: str
    model: str
    prompt_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    thinking_tokens: Optional[int] = None  # token "suy nghĩ" nếu mô hình có tính riêng
    finish_reason: Optional[str] = None    # lý do dừng, ví dụ hết token đầu ra


class GeminiClient:
    """Gọi Gemini bằng thư viện google-genai."""

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        api_key: Optional[str] = None,
        so_lan_goi_toi_da: int = 3,
        giay_cho_co_so: float = 5.0,
    ):
        # Đọc .env nếu có python-dotenv. Không có thì chỉ dùng biến môi trường hệ thống.
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass

        self.model = model or os.environ.get("GEMINI_MODEL") or MODEL_MAC_DINH
        # temperature=None nghĩa là KHÔNG gửi tham số, dùng mặc định của API.
        # Chưa kiểm chứng giá trị nào tốt nhất cho mô hình này, cần thử khi đánh giá.
        self.temperature = temperature
        self.so_lan_goi_toi_da = so_lan_goi_toi_da
        self.giay_cho_co_so = giay_cho_co_so

        khoa = api_key or os.environ.get("GEMINI_API_KEY")
        if not khoa:
            raise LoiCauHinh(
                "Thiếu GEMINI_API_KEY. Đặt trong file .env (cần cài python-dotenv) "
                "hoặc biến môi trường. Lấy khoá tại aistudio.google.com/apikey."
            )
        try:
            from google import genai  # nhập tại đây để chế độ --dry-run không cần cài SDK
        except ImportError as loi:
            raise LoiCauHinh("Chưa cài thư viện google-genai. Chạy: pip install google-genai") from loi
        self._client = genai.Client(api_key=khoa)

    def generate_json(self, system_prompt: str, user_content: str) -> KetQuaLLM:
        """Gọi mô hình ở chế độ JSON. Lỗi tạm thời (quá tải, hạn mức) được thử lại có chờ."""
        from google.genai import types

        tham_so = {
            "system_instruction": system_prompt,
            "response_mime_type": "application/json",
        }
        if self.temperature is not None:
            tham_so["temperature"] = self.temperature
        cau_hinh = types.GenerateContentConfig(**tham_so)

        phan_hoi = None
        for lan in range(1, self.so_lan_goi_toi_da + 1):
            try:
                phan_hoi = self._client.models.generate_content(
                    model=self.model, contents=user_content, config=cau_hinh
                )
                break
            except Exception as loi:  # SDK có nhiều loại lỗi, chuyển hết sang LoiLLM kèm mã
                ma = getattr(loi, "code", None)
                if ma in MA_LOI_THU_LAI and lan < self.so_lan_goi_toi_da:
                    time.sleep(self.giay_cho_co_so * lan)  # chờ lâu dần: 5s, 10s...
                    continue
                raise LoiLLM(f"Gọi Gemini thất bại ({type(loi).__name__}, mã {ma}): {loi}") from loi

        text = getattr(phan_hoi, "text", None)
        ung_vien = getattr(phan_hoi, "candidates", None) or []
        ly_do_dung = getattr(ung_vien[0], "finish_reason", None) if ung_vien else None
        if not text:
            raise LoiLLM(
                f"Phản hồi rỗng (lý do dừng: {ly_do_dung}). Có thể bị chặn nội dung hoặc hết token đầu ra."
            )

        thong_ke = getattr(phan_hoi, "usage_metadata", None)
        return KetQuaLLM(
            text=text,
            model=self.model,
            prompt_tokens=getattr(thong_ke, "prompt_token_count", None),
            output_tokens=getattr(thong_ke, "candidates_token_count", None),
            thinking_tokens=getattr(thong_ke, "thoughts_token_count", None),
            finish_reason=str(ly_do_dung) if ly_do_dung is not None else None,
        )


def goi_json_co_thu_lai(
    client,
    system_prompt: str,
    noi_dung_goc: str,
    doc_json: Callable[[str], dict],
    so_lan_thu_lai: int = 2,
) -> tuple[Optional[dict], str, list[dict], dict[str, Any]]:
    """Gọi LLM, đọc JSON bằng `doc_json`; đầu ra sai dạng thì thử lại kèm lý do lỗi.

    Dùng chung cho mọi bước LLM (DRY). Lỗi gọi API KHÔNG thử lại ở đây vì
    GeminiClient đã tự thử lại các lỗi tạm thời.
    doc_json: nhận chuỗi, trả dict, ném json.JSONDecodeError hoặc ValueError nếu sai dạng.
    Trả về (dữ_liệu | None, lỗi_cuối, nhật_ký_thô, thống_kê_sử_dụng).
    """
    nhat_ky: list[dict] = []
    cac_lan_goi: list[KetQuaLLM] = []
    du_lieu: Optional[dict] = None
    loi_cuoi = ""
    noi_dung_gui = noi_dung_goc

    for lan in range(1, so_lan_thu_lai + 2):
        try:
            kq = client.generate_json(system_prompt, noi_dung_gui)
        except LoiLLM as loi:
            nhat_ky.append({"lan": lan, "loi_api": str(loi)})
            loi_cuoi = str(loi)
            break
        cac_lan_goi.append(kq)
        nhat_ky.append(
            {
                "lan": lan,
                "text": kq.text,
                "prompt_tokens": kq.prompt_tokens,
                "output_tokens": kq.output_tokens,
                "thinking_tokens": kq.thinking_tokens,
                "finish_reason": kq.finish_reason,
            }
        )
        try:
            du_lieu = doc_json(kq.text)
            break
        except (json.JSONDecodeError, ValueError) as loi:
            loi_cuoi = f"Đầu ra LLM không hợp lệ: {loi} (lý do dừng: {kq.finish_reason})"
            noi_dung_gui = (
                noi_dung_goc
                + "\n\n# Lưu ý\nLần trả lời trước không hợp lệ ("
                + str(loi)
                + "). Hãy trả lại DUY NHẤT một JSON đúng định dạng đã nêu, không kèm giải thích."
            )

    def _tong(truong: str) -> Optional[int]:
        gia_tri = [getattr(k, truong) for k in cac_lan_goi if getattr(k, truong) is not None]
        return sum(gia_tri) if gia_tri else None

    su_dung = {
        "model": cac_lan_goi[-1].model if cac_lan_goi else None,
        "so_lan_goi": len(nhat_ky),
        "prompt_tokens": _tong("prompt_tokens"),
        "output_tokens": _tong("output_tokens"),
        "thinking_tokens": _tong("thinking_tokens"),
    }
    return du_lieu, ("" if du_lieu is not None else loi_cuoi), nhat_ky, su_dung