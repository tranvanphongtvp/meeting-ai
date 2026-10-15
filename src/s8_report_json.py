"""
s8_report.py - Bước 8 [Code, KHÔNG gọi LLM]: xuất báo cáo JSON cho người duyệt / hệ thống phía sau.

Vai trò: như tờ tóm tắt đặt trên bìa hồ sơ. File JSON chứa đủ
(1) mục nào cần xem lại và vì sao, (2) đủ 7 nhóm nghiệp vụ (nhóm rỗng vẫn có mặt, để biết
hệ thống có tìm mà không thấy), (3) bằng chứng gốc của từng mục, (4) các phát hiện của bước 6.

Đầu ra là MỘT file JSON (UTF-8, giữ nguyên tiếng Việt có dấu, không escape \\uXXXX).
Cấu trúc và logic giữ nguyên như bản HTML cũ, chỉ đổi cách trình bày.

Đầu vào: s7_record.json. Đầu ra: s8_report.json (hoặc index.json với --index).

Chạy riêng (đứng trong thư mục src):
    python s8_report.py <thu_muc_run>
    python s8_report.py <thu_muc_run> --index     # ghi thành index.json
Mã thoát: 0 = xong; 1 = đầu vào lỗi; 2 = thiếu file.
"""

import argparse
import json
import sys
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from schemas import FindingSeverity, ItemStatus, MeetingRecord, ReviewReason, nhom_theo_loai

# Thứ tự và tên hiển thị của 7 nhóm (nhóm rỗng vẫn hiện).
THU_TU_NHOM: list[tuple[str, str]] = [
    ("decision", "Quyết định"),
    ("action", "Công việc cần làm"),
    ("goal", "Mục tiêu"),
    ("issue", "Vướng mắc"),
    ("requirement_feedback", "Yêu cầu và phản hồi"),
    ("open_question", "Nội dung chưa chốt"),
    ("proposal", "Đề xuất chưa được chốt"),
]

TEN_TRANG_THAI = {
    ItemStatus.PROPOSED: "Đề xuất",
    ItemStatus.CONFIRMED: "Đã chốt",
    ItemStatus.REJECTED: "Bị bác",
    ItemStatus.SUPERSEDED: "Bị thay thế",
    ItemStatus.OPEN: "Còn mở",
}

TEN_LY_DO = {
    ReviewReason.NO_EVIDENCE: "Không có bằng chứng",
    ReviewReason.EVIDENCE_MISMATCH: "Bằng chứng không khớp lượt nói gốc",
    ReviewReason.SPEAKER_UNKNOWN: "Người nói/phụ trách không có trong danh sách họp",
    ReviewReason.DEADLINE_INVALID: "Hạn chót không hợp lệ",
    ReviewReason.DEADLINE_AMBIGUITY: "Hạn chót được diễn đạt không thống nhất",
    ReviewReason.RULE_CONFLICT: "Kết quả mâu thuẫn với luật trạng thái",
    ReviewReason.IMPLICIT_SIGNAL: "Chốt ngầm, tín hiệu không rõ",
    ReviewReason.AUTHORITY_UNCLEAR: "Người chốt chưa rõ có thẩm quyền",
    ReviewReason.NO_OWNER: "Chưa có người phụ trách",
    ReviewReason.CONTRADICTION: "Mâu thuẫn với mục khác",
    ReviewReason.INVALID_REFERENCE: "Tham chiếu hỏng",
}

# Trường riêng của từng loại mục: (tên trường, nhãn hiển thị).
TRUONG_THEO_LOAI: dict[str, list[tuple[str, str]]] = {
    "decision": [("decided_by", "Người chốt"), ("rejected_options", "Phương án bị loại"), ("rationale", "Lý do")],
    "proposal": [("proposed_by", "Người đề xuất"), ("rejected_options", "Phương án bị loại"), ("rationale", "Lý do")],
    "action": [("owner", "Người phụ trách"), ("deadline", "Hạn"), ("assignment_clarity", "Mức rõ ràng khi giao")],
    "goal": [("deadline", "Hạn"), ("scope", "Phạm vi")],
    "issue": [("raised_by", "Người nêu"), ("blocked_what", "Đang cản"), ("cause", "Nguyên nhân"),
              ("can_unblock", "Người có thể gỡ")],
    "requirement_feedback": [("kind", "Loại"), ("raised_by", "Bên nêu"), ("directed_to", "Gửi tới"),
                             ("sentiment", "Sắc thái"), ("is_group_conclusion", "Là kết luận chung")],
    "open_question": [("raised_by", "Người nêu"), ("awaiting", "Đang chờ")],
}


# ---------------------------------------------------------------------------
# Hàm nhỏ
# ---------------------------------------------------------------------------


def _chuan(x: Any) -> Any:
    """Đổi một giá trị bất kỳ thành kiểu JSON-an-toàn (Enum -> value, ngày -> ISO, còn lại -> str nếu lạ)."""
    if x is None or isinstance(x, (bool, int, float, str)):
        return x
    if isinstance(x, Enum):
        return x.value
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    return str(x)


def _hien_thi(gia_tri: Any) -> Any:
    """Đổi giá trị thành dạng xuất ra JSON. None/rỗng -> None (bỏ qua trường)."""
    if gia_tri is None or gia_tri == "" or gia_tri == []:
        return None
    if isinstance(gia_tri, bool):
        return "Có" if gia_tri else "Không"
    if isinstance(gia_tri, list):
        return [_chuan(g) for g in gia_tri]
    return _chuan(gia_tri)


def _trang_thai(st: ItemStatus) -> dict[str, str]:
    return {"ma": st.value, "ten": TEN_TRANG_THAI[st]}


def _ly_do(r: ReviewReason) -> dict[str, str]:
    return {"ma": r.value, "ten": TEN_LY_DO.get(r, r.value)}


# ---------------------------------------------------------------------------
# Các khối JSON
# ---------------------------------------------------------------------------


def _khoi_muc(it) -> dict[str, Any]:
    """Một object cho một mục nghiệp vụ."""
    truong: list[dict[str, Any]] = []
    for ten, nhan in TRUONG_THEO_LOAI[it.type]:
        gia_tri = _hien_thi(getattr(it, ten, None))
        if gia_tri is None:
            continue
        muc: dict[str, Any] = {"ten": ten, "nhan": nhan, "gia_tri": gia_tri}
        if ten == "deadline" and getattr(it, "deadline_raw", None):
            muc["loi_noi_goc"] = _chuan(it.deadline_raw)
        truong.append(muc)

    return {
        "item_id": it.item_id,
        "loai": _chuan(it.type),
        "summary": it.summary,
        "trang_thai": _trang_thai(it.status),
        "needs_review": bool(it.needs_review),
        "ly_do_xem_lai": [_ly_do(r) for r in it.review_reasons] if it.review_reasons else [],
        "truong": truong,
        "bi_thay_boi": it.superseded_by or None,
        "thay_the": it.supersedes or None,
        "thread_id": it.thread_id,
        "bang_chung": [
            {
                "quote": ev.quote,
                "turn_id": _chuan(ev.turn_id),
                "speaker": _chuan(ev.speaker),
                "timestamp": _chuan(ev.timestamp),
            }
            for ev in (it.evidence or [])
        ],
    }


def _khoi_can_xem_lai(items: list) -> list[dict[str, Any]]:
    """Danh sách mục cần xem lại (sắp theo item_id). Rỗng nếu không có mục nào."""
    can = sorted((i for i in items if i.needs_review), key=lambda x: x.item_id)
    return [
        {
            "item_id": it.item_id,
            "summary": it.summary,
            "ly_do": [_ly_do(r) for r in it.review_reasons],
        }
        for it in can
    ]


def _khoi_nhom(items: list) -> list[dict[str, Any]]:
    nhom = nhom_theo_loai(sorted(items, key=lambda x: x.item_id))
    ket = []
    for loai, ten in THU_TU_NHOM:
        ds = nhom[loai]
        ket.append({"loai": loai, "ten": ten, "so_luong": len(ds), "items": [_khoi_muc(i) for i in ds]})
    return ket


def _khoi_luong(threads: list) -> list[dict[str, Any]]:
    return [
        {
            "thread_id": t.thread_id,
            "topic": t.topic,
            "trang_thai": _trang_thai(t.status),
            "so_su_kien": len(t.event_ids),
            "note": t.note or "",
        }
        for t in sorted(threads, key=lambda x: x.thread_id)
    ]


def _khoi_finding(findings: list) -> dict[str, Any]:
    ket: dict[str, Any] = {}
    for muc_do, khoa, ten in (
        (FindingSeverity.ERROR, "loi", "Lỗi (đã gắn cờ mục liên quan)"),
        (FindingSeverity.WARNING, "canh_bao", "Cảnh báo (chỉ ghi lại, không gắn cờ)"),
    ):
        ds = [f for f in findings if f.severity == muc_do]
        ket[khoa] = {
            "ten": ten,
            "so_luong": len(ds),
            "findings": [{"finding_id": f.finding_id, "kind": f.kind.value, "message": f.message} for f in ds],
        }
    return ket


# ---------------------------------------------------------------------------
# Hàm chính
# ---------------------------------------------------------------------------


def tao_json(record: MeetingRecord) -> dict[str, Any]:
    """Dựng toàn bộ báo cáo (dict) từ MeetingRecord."""
    m = record.meeting
    so_can = sum(1 for i in record.items if i.needs_review)
    so_loi = sum(1 for f in record.findings if f.severity == FindingSeverity.ERROR)
    so_canh_bao = sum(1 for f in record.findings if f.severity == FindingSeverity.WARNING)
    tieu_de = m.title or m.meeting_id

    return {
        "tieu_de": tieu_de,
        "cuoc_hop": {
            "meeting_id": m.meeting_id,
            "title": m.title,
            "meeting_date": m.meeting_date.isoformat(),
            "participants": [p.name for p in m.participants],
        },
        "ban_ghi": {
            "record_id": record.record_id,
            "created_at": record.created_at.isoformat(),
        },
        "thong_ke": {
            "so_muc": len(record.items),
            "so_luong": len(record.threads),
            "so_muc_can_xem_lai": so_can,
            "so_finding_loi": so_loi,
            "so_finding_canh_bao": so_canh_bao,
        },
        "can_xem_lai": _khoi_can_xem_lai(record.items),
        "nhom": _khoi_nhom(record.items),
        "luong": _khoi_luong(record.threads),
        "findings": _khoi_finding(record.findings),
    }


def luu_ket_qua(record: MeetingRecord, thu_muc_run: str | Path, ten_file: str = "s8_report.json") -> Path:
    """Ghi file JSON vào thư mục run."""
    thu_muc_run = Path(thu_muc_run)
    thu_muc_run.mkdir(parents=True, exist_ok=True)
    duong_dan = thu_muc_run / ten_file
    duong_dan.write_text(
        json.dumps(tao_json(record), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return duong_dan


def _chay_rieng(argv: Optional[list[str]] = None) -> int:
    """Chạy riêng bước 8 từ command line."""
    parser = argparse.ArgumentParser(description="Chạy riêng bước 8: xuất báo cáo JSON (không gọi LLM)")
    parser.add_argument("thu_muc_run", help="thư mục đã có s7_record.json")
    parser.add_argument("--index", action="store_true", help="ghi thành index.json")
    args = parser.parse_args(argv)
    thu_muc_run = Path(args.thu_muc_run)

    file_s7 = thu_muc_run / "s7_record.json"
    if not file_s7.exists():
        print(f"LỖI: không thấy {file_s7}. Chạy bước 7 (s7_assemble.py) trước.")
        return 2
    try:
        record = MeetingRecord.model_validate_json(file_s7.read_text(encoding="utf-8"))
    except ValueError as loi:
        print(f"LỖI: s7_record.json không đọc được: {loi}")
        return 1

    duong_dan = luu_ket_qua(record, thu_muc_run, "index.json" if args.index else "s8_report.json")
    print(f"Đã ghi: {duong_dan}")
    return 0


if __name__ == "__main__":
    sys.exit(_chay_rieng())