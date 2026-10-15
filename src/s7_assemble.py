"""
s7_assemble.py - Bước 7 [Code, KHÔNG gọi LLM]: ghép bản ghi cuộc họp cuối cùng.

Vai trò: như người đóng gáy hồ sơ. Các bước trước làm ra từng tờ rời (thông tin họp ở s1,
luồng và mục ở s3, finding và cờ review ở s6); bước này gom lại thành MỘT bản ghi
(MeetingRecord) có mã hồ sơ và thời điểm tạo. Không đổi nội dung, không đổi status.

Đầu vào: s1_turns.json, s6_verified.json (cùng một thư mục run).
Đầu ra:  s7_record.json (MeetingRecord).

Chạy riêng (đứng trong thư mục src):
    python s7_assemble.py <thu_muc_run>
Mã thoát: 0 = xong; 1 = đầu vào lỗi; 2 = thiếu file.
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from s1_preprocess import KetQuaTienXuLy
from s6_verify import KetQuaKiemChung
from schemas import MeetingRecord


def tao_record_id(meeting_id: str, thoi_diem: datetime) -> str:
    """Mã hồ sơ: <meeting_id>-<YYYYMMDD-HHMMSS>. Mỗi lần chạy có một mã riêng."""
    return f"{meeting_id}-{thoi_diem:%Y%m%d-%H%M%S}"


def ghep_ban_ghi(s1, s6, thoi_diem: Optional[datetime] = None) -> MeetingRecord:
    """Ghép s1 + s6 thành MeetingRecord. Dùng bản sao nên đầu vào không bị sửa.

    s1 chỉ cần có .meeting; s6 cần .threads, .items, .findings.
    thoi_diem: truyền vào khi cần kết quả lặp lại được (test); bỏ trống thì lấy giờ UTC hiện tại.
    """
    thoi_diem = thoi_diem or datetime.now(timezone.utc)
    return MeetingRecord(
        record_id=tao_record_id(s1.meeting.meeting_id, thoi_diem),
        created_at=thoi_diem,
        meeting=s1.meeting.model_copy(deep=True),
        threads=[t.model_copy(deep=True) for t in s6.threads],
        items=[i.model_copy(deep=True) for i in s6.items],
        findings=[f.model_copy(deep=True) for f in s6.findings],
    )


def luu_ket_qua(record: MeetingRecord, thu_muc_run: str | Path) -> Path:
    """Ghi s7_record.json vào thư mục run."""
    thu_muc_run = Path(thu_muc_run)
    thu_muc_run.mkdir(parents=True, exist_ok=True)
    duong_dan = thu_muc_run / "s7_record.json"
    duong_dan.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    return duong_dan


def _chay_rieng(argv: Optional[list[str]] = None) -> int:
    """Chạy riêng bước 7 từ command line."""
    parser = argparse.ArgumentParser(description="Chạy riêng bước 7: ghép bản ghi cuộc họp (không gọi LLM)")
    parser.add_argument("thu_muc_run", help="thư mục đã có s1_turns.json và s6_verified.json")
    args = parser.parse_args(argv)
    thu_muc_run = Path(args.thu_muc_run)

    file_s1 = thu_muc_run / "s1_turns.json"
    file_s6 = thu_muc_run / "s6_verified.json"
    for f, ten_buoc in ((file_s1, "bước 1 (s1_preprocess.py)"), (file_s6, "bước 6 (s6_verify.py)")):
        if not f.exists():
            print(f"LỖI: không thấy {f}. Chạy {ten_buoc} trước.")
            return 2

    s1 = KetQuaTienXuLy.model_validate_json(file_s1.read_text(encoding="utf-8"))
    s6 = KetQuaKiemChung.model_validate_json(file_s6.read_text(encoding="utf-8"))
    for ten, kq in (("1", s1), ("6", s6)):
        if not kq.ok:
            print(f"LỖI: bước {ten} còn lỗi, xem lại trước:")
            for loi in kq.loi:
                print(f"  - {loi}")
            return 1

    record = ghep_ban_ghi(s1, s6)
    duong_dan = luu_ket_qua(record, thu_muc_run)
    so_can_xem = sum(1 for i in record.items if i.needs_review)
    print(f"Bản ghi {record.record_id}: {len(record.threads)} luồng, {len(record.items)} mục "
          f"({so_can_xem} cần xem lại), {len(record.findings)} finding.")
    print(f"Đã ghi: {duong_dan}")
    return 0


if __name__ == "__main__":
    sys.exit(_chay_rieng())