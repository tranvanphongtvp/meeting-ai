"""
s1_preprocess.py - Bước 1 [Code, không dùng LLM]: Tiền xử lý và chuẩn hoá transcript.

Làm gì: biến transcript thô thành danh sách lượt nói sạch, có mã định danh, để
các bước sau tham chiếu chính xác ("xem lượt T037").

Định dạng transcript đầu vào (mỗi lượt nói bắt đầu một dòng):
    [00:12:05] Nam: Mình dùng phương án A nhé.
    [00:12:40] Lan: A tốn chi phí quá,
    B ổn hơn.                          <- dòng không có timestamp = nói tiếp lượt trước

Thư mục một cuộc họp (dùng với hàm doc_cuoc_hop):
    transcript.txt   nội dung transcript theo định dạng trên
    meeting.json     thông tin cuộc họp, ví dụ:
        {
          "meeting_id": "case1",
          "meeting_date": "2026-10-13",
          "title": "Họp chọn nhà cung cấp",
          "participants": [
            {"name": "Nam", "aliases": ["anh Nam", "N."], "role": "Dev", "can_decide": false},
            {"name": "Lan", "aliases": [], "role": "Trưởng nhóm", "can_decide": true}
          ],
          "glossary": {"NCC": "nhà cung cấp"}
        }

Nguyên tắc:
- KHÔNG đoán. Tên người nói không khớp roster thì giữ nguyên tên gốc, gắn
  speaker_known=False và cảnh báo. Không tự "sửa" thành người gần giống nhất.
- Dữ liệu đầu vào sai định dạng thì báo LỖI (không chạy tiếp một cách im lặng).
  Pipeline phải kiểm tra ket_qua.ok trước khi sang bước 2.
- Nội dung lượt nói được giữ nguyên. Chỉ cắt khoảng trắng đầu/cuối dòng và nối
  các dòng nói tiếp bằng một dấu cách.

Chạy thử riêng bước này:
    python s1_preprocess.py <thu_muc_cuoc_hop> [--out <thu_muc_run>]
"""

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Optional

from pydantic import Field

from schemas import Base, Meeting, Turn

# Dòng lượt nói hợp lệ: [HH:MM:SS] hoặc [MM:SS], rồi "Tên người nói:", rồi nội dung.
# Tên người nói là phần đứng trước dấu ":" đầu tiên, nên nội dung được phép chứa dấu ":".
MAU_LUOT_NOI = re.compile(
    r"^\[(?P<ts>\d{1,2}:\d{2}(?::\d{2})?)\]\s*(?P<speaker>[^:\[\]]+?)\s*:\s*(?P<text>.*)$"
)
# Dòng bắt đầu bằng "[" nhưng không khớp mẫu trên: nhiều khả năng là lượt nói bị sai
# định dạng, nên báo lỗi thay vì nuốt vào lượt trước (nuốt vào sẽ làm hỏng nội dung).
MAU_BAT_DAU_NGOAC = re.compile(r"^\s*\[")

# Ước lượng thô số token từ số ký tự. Chỉ để CẢNH BÁO sớm, không phải số đo chính xác.
# Hệ số này chưa được kiểm chứng với tiếng Việt và mô hình cụ thể, cần đo lại khi chọn mô hình.
KY_TU_MOI_TOKEN_UOC_LUONG = 3


class KetQuaTienXuLy(Base):
    """Đầu ra bước 1: danh sách lượt nói + thông tin đi kèm + cảnh báo/lỗi."""

    meeting: Meeting
    turns: list[Turn]
    thong_ke: dict[str, int]
    canh_bao: list[str] = Field(default_factory=list)  # có thể chạy tiếp, nhưng nên xem
    loi: list[str] = Field(default_factory=list)       # phải sửa đầu vào trước khi chạy tiếp

    @property
    def ok(self) -> bool:
        """True nếu không có lỗi nghiêm trọng, có thể chuyển sang bước 2."""
        return not self.loi


# ---------------------------------------------------------------------------
# Hàm phụ
# ---------------------------------------------------------------------------


def chuan_hoa_ten(ten: str) -> str:
    """Chuẩn hoá tên để so khớp: bỏ dấu, thường hoá, gộp khoảng trắng.

    Ví dụ: "Anh  Nam" và "anh nam" cho cùng một khoá. CHỈ dùng để so khớp với roster,
    không dùng để hiển thị. Không so khớp mờ ở bước này (tránh gán nhầm người).
    """
    ten = ten.replace("đ", "d").replace("Đ", "D")  # "đ" không tách dấu được bằng NFD
    ten = unicodedata.normalize("NFD", ten)
    ten = "".join(c for c in ten if unicodedata.category(c) != "Mn")  # bỏ dấu thanh/mũ
    return " ".join(ten.lower().split())


def _ra_giay(ts: str) -> Optional[int]:
    """Đổi "HH:MM:SS" hoặc "MM:SS" ra số giây. None nếu phút/giây vượt 59."""
    phan = [int(x) for x in ts.split(":")]
    if len(phan) == 2:
        phan = [0] + phan
    gio, phut, giay = phan
    if phut >= 60 or giay >= 60:
        return None
    return gio * 3600 + phut * 60 + giay


def _xay_dung_ban_do_ten(meeting: Meeting) -> tuple[dict[str, str], list[str]]:
    """Tạo bảng tra: tên/biệt danh đã chuẩn hoá -> tên chính thức trong roster.

    Nếu cùng một cách gọi trỏ tới hai người khác nhau thì báo lỗi, vì như vậy
    không thể biết ai đang nói và việc đoán sẽ gây giao việc nhầm người.
    """
    ban_do: dict[str, str] = {}
    loi: list[str] = []
    for nguoi in meeting.participants:
        for ten in [nguoi.name, *nguoi.aliases]:
            khoa = chuan_hoa_ten(ten)
            if not khoa:
                continue
            if khoa in ban_do and ban_do[khoa] != nguoi.name:
                loi.append(
                    f"Roster mơ hồ: cách gọi '{ten}' trùng giữa '{ban_do[khoa]}' và '{nguoi.name}'."
                )
            else:
                ban_do[khoa] = nguoi.name
    return ban_do, loi


def tach_luot_noi(noi_dung: str) -> tuple[list[dict], list[str]]:
    """Tách văn bản transcript thành các lượt nói thô.

    Trả về (danh sách lượt nói thô, danh sách lỗi). Mỗi lượt nói thô là dict gồm:
    ts, speaker_raw, text, dong (số dòng bắt đầu, để báo lỗi chính xác).
    """
    luot_noi: list[dict] = []
    loi: list[str] = []

    noi_dung = noi_dung.lstrip("﻿")  # bỏ BOM nếu file lưu từ Notepad/Excel
    for so_dong, dong in enumerate(noi_dung.splitlines(), start=1):
        dong = dong.strip()
        if not dong:
            continue

        khop = MAU_LUOT_NOI.match(dong)
        if khop:
            ts = khop.group("ts")
            if _ra_giay(ts) is None:
                loi.append(f"Dòng {so_dong}: timestamp '{ts}' không hợp lệ (phút/giây phải < 60).")
            luot_noi.append(
                {
                    "ts": ts,
                    "speaker_raw": khop.group("speaker").strip(),
                    "text": khop.group("text").strip(),
                    "dong": so_dong,
                }
            )
        elif MAU_BAT_DAU_NGOAC.match(dong):
            loi.append(
                f"Dòng {so_dong}: nghi là lượt nói nhưng sai định dạng "
                f"(cần '[HH:MM:SS] Tên: nội dung'): {dong[:60]}"
            )
        elif luot_noi:
            # Dòng không có timestamp: coi là người nói đó nói tiếp.
            luot_noi[-1]["text"] = (luot_noi[-1]["text"] + " " + dong).strip()
        else:
            loi.append(f"Dòng {so_dong}: nội dung xuất hiện trước lượt nói đầu tiên: {dong[:60]}")

    return luot_noi, loi


# ---------------------------------------------------------------------------
# Hàm chính của bước 1
# ---------------------------------------------------------------------------


def tien_xu_ly(
    noi_dung_transcript: str,
    meeting: Meeting,
    gioi_han_ky_tu: Optional[int] = None,
) -> KetQuaTienXuLy:
    """Chuẩn hoá transcript thành danh sách Turn.

    gioi_han_ky_tu: nếu truyền vào và transcript dài hơn thì cảnh báo. Đây là chỗ
    duy nhất kiểm soát giả định "cả transcript vừa với giới hạn đầu vào của mô
    hình" (vì MVP đã bỏ bước chia cửa sổ). Chưa đặt giá trị mặc định, vì giới hạn
    thật phụ thuộc mô hình bạn chọn.
    """
    loi: list[str] = []
    canh_bao: list[str] = []

    ban_do_ten, loi_roster = _xay_dung_ban_do_ten(meeting)
    loi += loi_roster
    if not meeting.participants:
        canh_bao.append("Roster rỗng: mọi người nói sẽ bị đánh dấu không xác định.")

    luot_noi_tho, loi_tach = tach_luot_noi(noi_dung_transcript)
    loi += loi_tach
    if not luot_noi_tho and not loi_tach:
        loi.append("Transcript rỗng hoặc không có lượt nói nào hợp lệ.")

    turns: list[Turn] = []
    giay_truoc: Optional[int] = None
    nguoi_la: set[str] = set()

    for thu_tu, tho in enumerate(luot_noi_tho, start=1):
        turn_id = f"T{thu_tu:03d}"

        # Tìm người nói trong roster. Không khớp thì giữ tên gốc, KHÔNG đoán.
        ten_chuan = ban_do_ten.get(chuan_hoa_ten(tho["speaker_raw"]))
        speaker_known = ten_chuan is not None
        if not speaker_known:
            nguoi_la.add(tho["speaker_raw"])

        # Timestamp lùi lại thường là lỗi của bản ghi, cảnh báo để người dùng biết.
        giay = _ra_giay(tho["ts"])
        if giay is not None and giay_truoc is not None and giay < giay_truoc:
            canh_bao.append(f"{turn_id} (dòng {tho['dong']}): timestamp {tho['ts']} lùi so với lượt trước.")
        if giay is not None:
            giay_truoc = giay

        if not tho["text"]:
            canh_bao.append(f"{turn_id} (dòng {tho['dong']}): lượt nói không có nội dung.")

        turns.append(
            Turn(
                turn_id=turn_id,
                speaker=ten_chuan if speaker_known else tho["speaker_raw"],
                speaker_raw=tho["speaker_raw"],
                speaker_known=speaker_known,
                timestamp=tho["ts"],
                text=tho["text"],
            )
        )

    for ten in sorted(nguoi_la):
        canh_bao.append(f"Người nói '{ten}' không có trong roster (gắn speaker_known=False).")

    # Thống kê độ dài: dùng để biết transcript có vượt giới hạn mô hình không.
    so_ky_tu = sum(len(t.text) for t in turns)
    thong_ke = {
        "so_luot": len(turns),
        "so_nguoi_noi": len({t.speaker for t in turns}),
        "so_luot_khong_xac_dinh": sum(1 for t in turns if not t.speaker_known),
        "so_ky_tu": so_ky_tu,
        "uoc_luong_token_tho": so_ky_tu // KY_TU_MOI_TOKEN_UOC_LUONG,
    }
    if gioi_han_ky_tu is not None and so_ky_tu > gioi_han_ky_tu:
        canh_bao.append(
            f"Transcript dài {so_ky_tu} ký tự, vượt giới hạn đã đặt ({gioi_han_ky_tu}). "
            "Cân nhắc lại việc bỏ bước chia cửa sổ."
        )

    return KetQuaTienXuLy(
        meeting=meeting, turns=turns, thong_ke=thong_ke, canh_bao=canh_bao, loi=loi
    )


# ---------------------------------------------------------------------------
# Đọc/ghi file
# ---------------------------------------------------------------------------


def doc_cuoc_hop(thu_muc: str | Path) -> tuple[str, Meeting]:
    """Đọc transcript.txt và meeting.json trong thư mục một cuộc họp."""
    thu_muc = Path(thu_muc)
    file_transcript = thu_muc / "transcript.txt"
    file_meeting = thu_muc / "meeting.json"
    for f in (file_transcript, file_meeting):
        if not f.exists():
            raise FileNotFoundError(f"Thiếu file đầu vào: {f}")

    noi_dung = file_transcript.read_text(encoding="utf-8-sig")
    meeting = Meeting.model_validate_json(file_meeting.read_text(encoding="utf-8-sig"))
    return noi_dung, meeting


def luu_ket_qua(ket_qua: KetQuaTienXuLy, thu_muc_run: str | Path) -> Path:
    """Ghi đầu ra bước 1 ra s1_turns.json để các bước sau đọc và để lần lỗi."""
    thu_muc_run = Path(thu_muc_run)
    thu_muc_run.mkdir(parents=True, exist_ok=True)
    duong_dan = thu_muc_run / "s1_turns.json"
    duong_dan.write_text(
        json.dumps(ket_qua.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return duong_dan


def _chay_rieng() -> int:
    """Chạy riêng bước 1 để kiểm tra một cuộc họp, in tóm tắt ra màn hình."""
    parser = argparse.ArgumentParser(description="Chạy riêng bước 1: tiền xử lý transcript")
    parser.add_argument("thu_muc", help="thư mục chứa transcript.txt và meeting.json")
    parser.add_argument("--out", help="thư mục ghi s1_turns.json (bỏ qua thì không ghi file)")
    parser.add_argument("--gioi-han-ky-tu", type=int, help="cảnh báo nếu transcript dài hơn mức này")
    args = parser.parse_args()

    noi_dung, meeting = doc_cuoc_hop(args.thu_muc)
    ket_qua = tien_xu_ly(noi_dung, meeting, gioi_han_ky_tu=args.gioi_han_ky_tu)

    print(f"Thống kê: {ket_qua.thong_ke}")
    for c in ket_qua.canh_bao:
        print(f"CẢNH BÁO: {c}")
    for e in ket_qua.loi:
        print(f"LỖI: {e}")
    if args.out:
        print(f"Đã ghi: {luu_ket_qua(ket_qua, args.out)}")
    return 0 if ket_qua.ok else 1


if __name__ == "__main__":
    sys.exit(_chay_rieng())