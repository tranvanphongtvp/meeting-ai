"""
s2_extract_acts.py - Bước 2 [LLM #1]: Trích xuất HÀNH ĐỘNG LỜI NÓI kèm trích dẫn gốc.

Làm gì: với mỗi lượt nói, xác định người nói đang LÀM GÌ (đề xuất, phản đối, chốt,
giao việc, hoãn...). CHƯA kết luận gì. Ưu tiên không bỏ sót (recall), phần thừa sẽ
được lọc ở các bước sau.

Phân công giữa LLM và code (để giảm lỗi):
- LLM chỉ trả: turn_id, act, topic_label, quote, certainty.
- Code tự điền: event_id (tuần tự) và speaker (lấy từ lượt nói gốc, không để LLM tự viết).
- Code kiểm tra từng sự kiện: turn_id có thật, act hợp lệ, trích dẫn có nằm trong lượt
  nói không. Sự kiện hỏng bị bỏ kèm cảnh báo, không làm hỏng cả lượt chạy.
- Nếu cả đầu ra không phải JSON đúng dạng thì thử lại (kèm lý do lỗi), tối đa
  SO_LAN_THU_LAI_JSON lần.

Chạy riêng bước này (đứng trong thư mục src):
    python s2_extract_acts.py <thu_muc_run> --dry-run   # chỉ dựng prompt, KHÔNG gọi LLM
    python s2_extract_acts.py <thu_muc_run>             # gọi LLM thật (cần GEMINI_API_KEY)
Trong đó <thu_muc_run> là thư mục đã có s1_turns.json (đầu ra bước 1).
Kết quả ghi cùng thư mục: s2_events.json và s2_raw_llm.json (nhật ký thô để lần lỗi).
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field, ValidationError, field_validator

from llm_client import GeminiClient, LoiCauHinh, goi_json_co_thu_lai
from s1_preprocess import KetQuaTienXuLy, chuan_hoa_ten
from schemas import ActType, Base, Certainty, SpeechEvent

THU_MUC_GOC = Path(__file__).resolve().parent.parent
FILE_PROMPT = THU_MUC_GOC / "configs" / "prompts" / "extract_acts.md"

# Số lần thử lại khi đầu ra không phải JSON đúng dạng (không tính lỗi gọi API,
# lỗi API đã được llm_client tự thử lại).
SO_LAN_THU_LAI_JSON = 2


# ---------------------------------------------------------------------------
# Dữ liệu
# ---------------------------------------------------------------------------


class SuKienTho(Base):
    """Một sự kiện đúng như LLM trả về, trước khi code bổ sung event_id và speaker.

    Khác các mẫu trong schemas.py: bỏ qua trường lạ (extra=ignore) vì LLM có thể thêm
    trường thừa, nhưng vẫn bắt buộc các trường cốt lõi.
    """

    model_config = ConfigDict(extra="ignore")

    turn_id: str
    act: ActType
    topic_label: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    certainty: Certainty = Certainty.FIRM

    @field_validator("turn_id", "act", "certainty", "topic_label", "quote", mode="before")
    @classmethod
    def _lam_sach(cls, gia_tri: Any, info) -> Any:
        """Cắt khoảng trắng; act và certainty đưa về chữ thường ("Propose" -> "propose")."""
        if isinstance(gia_tri, str):
            gia_tri = gia_tri.strip()
            if info.field_name in ("act", "certainty"):
                gia_tri = gia_tri.lower()
        return gia_tri


class KetQuaTrichXuat(Base):
    """Đầu ra bước 2."""

    events: list[SpeechEvent]
    thong_ke: dict[str, int]
    theo_hanh_dong: dict[str, int]
    canh_bao: list[str] = Field(default_factory=list)  # chạy tiếp được nhưng nên xem
    loi: list[str] = Field(default_factory=list)       # không có kết quả dùng được
    su_dung_llm: dict[str, Any] = Field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.loi


# ---------------------------------------------------------------------------
# Dựng đầu vào cho LLM
# ---------------------------------------------------------------------------


def xay_dung_noi_dung_nguoi_dung(s1: KetQuaTienXuLy) -> str:
    """Ghép thông tin cuộc họp và transcript thành nội dung gửi cho LLM.

    Cố ý KHÔNG gửi can_decide (ai có quyền chốt): bước này chưa xét thẩm quyền,
    gửi vào dễ khiến LLM tự kết luận.
    """
    m = s1.meeting
    dong = ["# Thông tin cuộc họp", f"Ngày họp: {m.meeting_date.isoformat()}"]
    if m.title:
        dong.append(f"Tiêu đề: {m.title}")
    dong.append("Người tham gia:")
    if not m.participants:
        dong.append("- (không có danh sách)")
    for nguoi in m.participants:
        chi_tiet = []
        if nguoi.role:
            chi_tiet.append(nguoi.role)
        if nguoi.aliases:
            chi_tiet.append("còn được gọi: " + ", ".join(nguoi.aliases))
        hau_to = f" ({'; '.join(chi_tiet)})" if chi_tiet else ""
        dong.append(f"- {nguoi.name}{hau_to}")
    if m.glossary:
        dong.append("Thuật ngữ nội bộ:")
        dong += [f"- {tu}: {nghia}" for tu, nghia in m.glossary.items()]
    dong += ["", "# Transcript"]
    dong += [f"{t.turn_id} [{t.timestamp}] {t.speaker}: {t.text}" for t in s1.turns]
    return "\n".join(dong)


# ---------------------------------------------------------------------------
# Kiểm tra đầu ra của LLM
# ---------------------------------------------------------------------------


def _chuan_hoa_so_khop(s: str) -> str:
    """Chuẩn hoá để so trích dẫn: bỏ dấu, thường hoá, bỏ dấu câu, gộp khoảng trắng.

    Cố ý dễ tính (bỏ dấu, bỏ dấu câu) vì transcript từ nhận dạng giọng nói hay lệch
    chút ít. Đổi lại KHÔNG phát hiện được việc LLM đổi dấu thanh hay thêm bớt dấu câu.
    """
    s = chuan_hoa_ten(s)
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def _trich_dan_co_trong_luot(quote: str, noi_dung_luot: str) -> bool:
    q = _chuan_hoa_so_khop(quote)
    return bool(q) and q in _chuan_hoa_so_khop(noi_dung_luot)


def _doc_json(text: str) -> dict:
    """Đọc JSON từ đầu ra LLM. Chịu được trường hợp bị bọc trong khối mã ```json."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    du_lieu = json.loads(t)
    if not isinstance(du_lieu, dict) or not isinstance(du_lieu.get("events"), list):
        raise ValueError('JSON phải là một đối tượng có khoá "events" là danh sách.')
    return du_lieu


def _tom_tat_loi(loi: ValidationError) -> str:
    """Rút gọn lỗi Pydantic thành một dòng dễ đọc."""
    return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in loi.errors()[:3])


# ---------------------------------------------------------------------------
# Hàm chính của bước 2
# ---------------------------------------------------------------------------


def trich_xuat(
    s1: KetQuaTienXuLy,
    client,
    system_prompt: str,
    so_lan_thu_lai: int = SO_LAN_THU_LAI_JSON,
) -> tuple[KetQuaTrichXuat, list[dict]]:
    """Gọi LLM #1 và biến đầu ra thành danh sách SpeechEvent đã kiểm tra.

    client: đối tượng có phương thức generate_json(system_prompt, user_content) -> KetQuaLLM
    (xem llm_client.py). Tách ra như vậy để kiểm thử mà không cần gọi mạng.
    Trả về (kết quả, nhật_ký_thô). Nhật ký thô lưu toàn bộ lần gọi để lần lỗi.
    """
    noi_dung_goc = xay_dung_noi_dung_nguoi_dung(s1)
    du_lieu, loi_cuoi, nhat_ky, su_dung_llm = goi_json_co_thu_lai(
        client, system_prompt, noi_dung_goc, _doc_json, so_lan_thu_lai
    )

    if du_lieu is None:
        ket_qua = KetQuaTrichXuat(
            events=[], thong_ke={}, theo_hanh_dong={}, loi=[loi_cuoi], su_dung_llm=su_dung_llm
        )
        return ket_qua, nhat_ky

    # Kiểm tra và làm sạch từng sự kiện.
    luot_theo_id = {t.turn_id: t for t in s1.turns}
    vi_tri_luot = {t.turn_id: i for i, t in enumerate(s1.turns)}
    canh_bao: list[str] = []
    hop_le: list[tuple[int, int, SuKienTho]] = []
    da_thay: set[tuple[str, str, str]] = set()
    so_bo = so_trung = so_trich_dan_sai = 0

    for stt, tho in enumerate(du_lieu["events"], start=1):
        try:
            sk = SuKienTho.model_validate(tho)
        except ValidationError as loi:
            canh_bao.append(f"Bỏ sự kiện #{stt}: sai định dạng ({_tom_tat_loi(loi)}).")
            so_bo += 1
            continue

        luot = luot_theo_id.get(sk.turn_id)
        if luot is None:
            canh_bao.append(f"Bỏ sự kiện #{stt}: turn_id '{sk.turn_id}' không có trong transcript.")
            so_bo += 1
            continue

        khoa = (sk.turn_id, sk.act.value, _chuan_hoa_so_khop(sk.quote))
        if khoa in da_thay:
            so_trung += 1
            continue
        da_thay.add(khoa)

        # Giữ sự kiện nhưng cảnh báo nếu trích dẫn không nằm trong lượt nói được dẫn.
        if not _trich_dan_co_trong_luot(sk.quote, luot.text):
            so_trich_dan_sai += 1
            canh_bao.append(
                f"{sk.turn_id} ({sk.act.value}): trích dẫn không khớp lượt nói gốc: '{sk.quote[:60]}'."
            )
        hop_le.append((vi_tri_luot[sk.turn_id], stt, sk))

    # Sắp theo thứ tự lượt nói (giữ thứ tự LLM trả nếu cùng lượt), rồi đánh mã E001...
    hop_le.sort(key=lambda x: (x[0], x[1]))
    events = [
        SpeechEvent(
            event_id=f"E{thu_tu:03d}",
            turn_id=sk.turn_id,
            speaker=luot_theo_id[sk.turn_id].speaker,  # lấy từ lượt nói gốc, không tin LLM
            act=sk.act,
            topic_label=sk.topic_label,
            quote=sk.quote,
            certainty=sk.certainty,
        )
        for thu_tu, (_, _, sk) in enumerate(hop_le, start=1)
    ]

    theo_hanh_dong: dict[str, int] = {}
    for e in events:
        theo_hanh_dong[e.act.value] = theo_hanh_dong.get(e.act.value, 0) + 1

    if not events:
        canh_bao.append("Không có sự kiện nào được ghi nhận. Cần xem lại nhật ký thô s2_raw_llm.json.")

    thong_ke = {
        "so_su_kien": len(events),
        "so_luot_co_su_kien": len({e.turn_id for e in events}),
        "so_luot_tong": len(s1.turns),
        "so_su_kien_bi_bo": so_bo,
        "so_su_kien_trung": so_trung,
        "so_trich_dan_khong_khop": so_trich_dan_sai,
    }
    return (
        KetQuaTrichXuat(
            events=events,
            thong_ke=thong_ke,
            theo_hanh_dong=theo_hanh_dong,
            canh_bao=canh_bao,
            su_dung_llm=su_dung_llm,
        ),
        nhat_ky,
    )


# ---------------------------------------------------------------------------
# Đọc/ghi file và chạy riêng
# ---------------------------------------------------------------------------


def luu_ket_qua(ket_qua: KetQuaTrichXuat, nhat_ky: list[dict], thu_muc_run: str | Path) -> Path:
    """Ghi s2_events.json (kết quả) và s2_raw_llm.json (nhật ký thô các lần gọi)."""
    thu_muc_run = Path(thu_muc_run)
    thu_muc_run.mkdir(parents=True, exist_ok=True)
    duong_dan = thu_muc_run / "s2_events.json"
    duong_dan.write_text(
        json.dumps(ket_qua.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (thu_muc_run / "s2_raw_llm.json").write_text(
        json.dumps(nhat_ky, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return duong_dan


def _chay_rieng() -> int:
    parser = argparse.ArgumentParser(description="Chạy riêng bước 2: trích xuất hành động lời nói")
    parser.add_argument("thu_muc_run", help="thư mục đã có s1_turns.json")
    parser.add_argument("--dry-run", action="store_true", help="chỉ dựng prompt, KHÔNG gọi LLM")
    parser.add_argument("--model", help="ghi đè tên mô hình (mặc định lấy từ GEMINI_MODEL)")
    parser.add_argument("--temperature", type=float, help="nhiệt độ lấy mẫu (bỏ qua = mặc định của API)")
    args = parser.parse_args()

    thu_muc_run = Path(args.thu_muc_run)
    file_s1 = thu_muc_run / "s1_turns.json"
    if not file_s1.exists():
        print(f"LỖI: không thấy {file_s1}. Chạy bước 1 trước (s1_preprocess.py --out ...).")
        return 2
    s1 = KetQuaTienXuLy.model_validate_json(file_s1.read_text(encoding="utf-8"))
    if not s1.ok:
        print("LỖI: bước 1 còn lỗi, sửa transcript trước khi chạy bước 2:")
        for loi in s1.loi:
            print(f"  - {loi}")
        return 1

    system_prompt = FILE_PROMPT.read_text(encoding="utf-8")
    noi_dung = xay_dung_noi_dung_nguoi_dung(s1)

    if args.dry_run:
        duong_dan = thu_muc_run / "s2_prompt.txt"
        duong_dan.write_text(
            "=== SYSTEM PROMPT ===\n" + system_prompt + "\n\n=== NỘI DUNG GỬI ===\n" + noi_dung,
            encoding="utf-8",
        )
        print("Chế độ dry-run: KHÔNG gọi LLM.")
        print(f"Độ dài: system prompt {len(system_prompt)} ký tự, nội dung gửi {len(noi_dung)} ký tự.")
        print(f"Đã ghi toàn bộ nội dung sẽ gửi để bạn kiểm tra: {duong_dan}")
        return 0

    try:
        client = GeminiClient(model=args.model, temperature=args.temperature)
    except LoiCauHinh as loi:
        print(f"LỖI CẤU HÌNH: {loi}")
        return 2

    print(f"Đang gọi mô hình '{client.model}' ...")
    ket_qua, nhat_ky = trich_xuat(s1, client, system_prompt)
    duong_dan = luu_ket_qua(ket_qua, nhat_ky, thu_muc_run)

    print(f"Thống kê: {ket_qua.thong_ke}")
    print(f"Theo hành động: {ket_qua.theo_hanh_dong}")
    print(f"LLM: {ket_qua.su_dung_llm}")
    for c in ket_qua.canh_bao:
        print(f"CẢNH BÁO: {c}")
    for e in ket_qua.loi:
        print(f"LỖI: {e}")
    print(f"Đã ghi: {duong_dan}")
    return 0 if ket_qua.ok else 1


if __name__ == "__main__":
    sys.exit(_chay_rieng())