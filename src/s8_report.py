"""
s8_report.py - Bước 8 [Code, KHÔNG gọi LLM]: xuất báo cáo HTML cho người duyệt.

Vai trò: như tờ tóm tắt đặt trên bìa hồ sơ. Người duyệt mở một trang duy nhất, thấy ngay
(1) mục nào cần xem lại và vì sao, (2) đủ 7 nhóm nghiệp vụ (nhóm rỗng vẫn hiện, để biết
hệ thống có tìm mà không thấy), (3) bằng chứng gốc của từng mục, (4) các phát hiện của bước 6.

Đầu ra là MỘT file HTML tự chứa (CSS nằm trong file, không tải gì từ ngoài), nên mở thẳng
bằng trình duyệt hoặc đưa lên hosting tĩnh (ví dụ Vercel) được ngay. Mọi chuỗi từ dữ liệu
đều được escape để nội dung transcript không phá được trang.

Đầu vào: s7_record.json. Đầu ra: s8_report.html (hoặc index.html với --index).

Chạy riêng (đứng trong thư mục src):
    python s8_report.py <thu_muc_run>
    python s8_report.py <thu_muc_run> --index     # ghi thành index.html để đưa lên hosting
Mã thoát: 0 = xong; 1 = đầu vào lỗi; 2 = thiếu file.
"""

import argparse
import sys
from datetime import date, datetime
from enum import Enum
from html import escape
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

CSS = """
:root{--bg:#fafaf7;--card:#fff;--text:#1f2328;--muted:#656d76;--line:#d8dce0;--accent:#2f5d8a;
--ok:#1a7f4b;--warn:#9a6700;--err:#b42318;--okbg:#e6f4ec;--warnbg:#fdf3d8;--errbg:#fde8e6;--neutralbg:#eef1f4}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#16181c;--card:#1e2126;--text:#e6e8eb;
--muted:#9aa3ad;--line:#343a42;--accent:#7fb0e0;--ok:#5fd19a;--warn:#e3b341;--err:#ff8f85;--okbg:#17332a;
--warnbg:#3a2f12;--errbg:#3d1c1a;--neutralbg:#262b31}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
padding:env(safe-area-inset-top,0) 0 env(safe-area-inset-bottom,0)}
main{max-width:920px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:1.6rem;margin:0 0 4px}h2{font-size:1.2rem;margin:32px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.muted{color:var(--muted);font-size:.9rem}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin:16px 0}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px;min-width:120px}
.stat b{display:block;font-size:1.4rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}
.card.review{border-left:4px solid var(--err)}
.card h3{font-size:1rem;margin:0 0 6px}
.badge{display:inline-block;border-radius:999px;padding:1px 9px;font-size:.78rem;margin:0 4px 4px 0;
background:var(--neutralbg);color:var(--text);white-space:nowrap}
.badge.confirmed{background:var(--okbg);color:var(--ok)}.badge.rejected,.badge.err{background:var(--errbg);color:var(--err)}
.badge.warn{background:var(--warnbg);color:var(--warn)}.badge.superseded{background:var(--neutralbg);color:var(--muted)}
dl{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px;margin:8px 0;font-size:.92rem}
dt{color:var(--muted)}dd{margin:0}
details{margin-top:6px}summary{cursor:pointer;color:var(--accent);font-size:.9rem}
blockquote{margin:6px 0;padding:4px 10px;border-left:3px solid var(--line);font-size:.92rem}
blockquote .meta{display:block;color:var(--muted);font-size:.8rem}
.empty{color:var(--muted);font-style:italic}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.9rem}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
ul.find{padding-left:18px;margin:6px 0}ul.find li{margin:4px 0}
a{color:var(--accent)}
"""


# ---------------------------------------------------------------------------
# Hàm nhỏ
# ---------------------------------------------------------------------------


def _e(x: Any) -> str:
    """Escape một giá trị bất kỳ thành chuỗi HTML an toàn."""
    return escape(str(x))


def _hien_thi(gia_tri: Any) -> Optional[str]:
    """Đổi giá trị thành chuỗi hiển thị (đã escape). None/rỗng -> None (bỏ qua dòng)."""
    if gia_tri is None or gia_tri == "" or gia_tri == []:
        return None
    if isinstance(gia_tri, bool):
        return "Có" if gia_tri else "Không"
    if isinstance(gia_tri, Enum):
        return _e(gia_tri.value)
    if isinstance(gia_tri, (date, datetime)):
        return _e(gia_tri.isoformat())
    if isinstance(gia_tri, list):
        return _e(", ".join(str(g) for g in gia_tri))
    return _e(gia_tri)


def _huy_hieu(van_ban: str, lop: str = "") -> str:
    return f'<span class="badge {lop}">{_e(van_ban)}</span>'


# ---------------------------------------------------------------------------
# Các khối HTML
# ---------------------------------------------------------------------------


def _khoi_muc(it) -> str:
    """Một thẻ cho một mục nghiệp vụ."""
    lop_the = "card review" if it.needs_review else "card"
    badge = _huy_hieu(TEN_TRANG_THAI[it.status], it.status.value)
    if it.needs_review:
        badge += _huy_hieu("Cần xem lại", "err")

    dong: list[str] = []
    for ten, nhan in TRUONG_THEO_LOAI[it.type]:
        gia_tri = _hien_thi(getattr(it, ten, None))
        if ten == "deadline" and gia_tri and getattr(it, "deadline_raw", None):
            gia_tri += f' <span class="muted">(nói: “{_e(it.deadline_raw)}”)</span>'
        if gia_tri:
            dong.append(f"<dt>{_e(nhan)}</dt><dd>{gia_tri}</dd>")
    if it.superseded_by:
        dong.append(f'<dt>Bị thay bởi</dt><dd><a href="#{_e(it.superseded_by)}">{_e(it.superseded_by)}</a></dd>')
    if it.supersedes:
        dong.append(f'<dt>Thay thế</dt><dd><a href="#{_e(it.supersedes)}">{_e(it.supersedes)}</a></dd>')
    dong.append(f"<dt>Luồng</dt><dd>{_e(it.thread_id)}</dd>")

    ly_do = ""
    if it.review_reasons:
        ly_do = "<div>" + "".join(_huy_hieu(TEN_LY_DO.get(r, r.value), "err") for r in it.review_reasons) + "</div>"

    if it.evidence:
        bc = "".join(
            f'<blockquote>“{_e(ev.quote)}”<span class="meta">{_e(ev.turn_id)} · {_e(ev.speaker)} · '
            f"{_e(ev.timestamp)}</span></blockquote>"
            for ev in it.evidence
        )
        bang_chung = f"<details><summary>Bằng chứng ({len(it.evidence)})</summary>{bc}</details>"
    else:
        bang_chung = '<p class="empty">Không có bằng chứng.</p>'

    return (
        f'<div class="{lop_the}" id="{_e(it.item_id)}">'
        f"<h3>{_e(it.item_id)} · {_e(it.summary)}</h3>"
        f"<div>{badge}</div>{ly_do}<dl>{''.join(dong)}</dl>{bang_chung}</div>"
    )


def _khoi_can_xem_lai(items: list) -> str:
    """Danh sách mục cần xem lại, đặt đầu trang để người duyệt xử lý trước."""
    can = sorted((i for i in items if i.needs_review), key=lambda x: x.item_id)
    if not can:
        return '<p class="empty">Không có mục nào cần xem lại.</p>'
    hang = []
    for it in can:
        ly_do = "".join(_huy_hieu(TEN_LY_DO.get(r, r.value), "err") for r in it.review_reasons)
        hang.append(
            f'<tr><td><a href="#{_e(it.item_id)}">{_e(it.item_id)}</a></td><td>{_e(it.summary)}</td><td>{ly_do}</td></tr>'
        )
    return (
        '<div class="scroll"><table><tr><th>Mục</th><th>Nội dung</th><th>Lý do</th></tr>'
        + "".join(hang) + "</table></div>"
    )


def _khoi_nhom(items: list) -> str:
    nhom = nhom_theo_loai(sorted(items, key=lambda x: x.item_id))
    ket = []
    for loai, ten in THU_TU_NHOM:
        ds = nhom[loai]
        noi_dung = "".join(_khoi_muc(i) for i in ds) if ds else '<p class="empty">Không có mục nào.</p>'
        ket.append(f"<h2>{_e(ten)} ({len(ds)})</h2>{noi_dung}")
    return "".join(ket)


def _khoi_luong(threads: list) -> str:
    if not threads:
        return '<p class="empty">Không có luồng nào.</p>'
    hang = [
        f"<tr><td>{_e(t.thread_id)}</td><td>{_e(t.topic)}</td>"
        f"<td>{_huy_hieu(TEN_TRANG_THAI[t.status], t.status.value)}</td>"
        f"<td>{len(t.event_ids)}</td><td>{_e(t.note or '')}</td></tr>"
        for t in sorted(threads, key=lambda x: x.thread_id)
    ]
    return (
        '<div class="scroll"><table><tr><th>Luồng</th><th>Chủ đề</th><th>Trạng thái</th><th>Số sự kiện</th>'
        "<th>Ghi chú</th></tr>" + "".join(hang) + "</table></div>"
    )


def _khoi_finding(findings: list) -> str:
    if not findings:
        return '<p class="empty">Bước kiểm chứng không có phát hiện nào.</p>'
    ket = []
    for muc_do, ten, lop in (
        (FindingSeverity.ERROR, "Lỗi (đã gắn cờ mục liên quan)", "err"),
        (FindingSeverity.WARNING, "Cảnh báo (chỉ ghi lại, không gắn cờ)", "warn"),
    ):
        ds = [f for f in findings if f.severity == muc_do]
        if not ds:
            continue
        li = "".join(
            f"<li>{_huy_hieu(f.finding_id, lop)}<b>{_e(f.kind.value)}</b>: {_e(f.message)}</li>" for f in ds
        )
        ket.append(f"<h3>{_e(ten)}: {len(ds)}</h3><ul class='find'>{li}</ul>")
    return "".join(ket)


# ---------------------------------------------------------------------------
# Hàm chính
# ---------------------------------------------------------------------------


def tao_html(record: MeetingRecord) -> str:
    """Dựng toàn bộ trang HTML từ MeetingRecord."""
    m = record.meeting
    so_can = sum(1 for i in record.items if i.needs_review)
    so_loi = sum(1 for f in record.findings if f.severity == FindingSeverity.ERROR)
    so_canh_bao = sum(1 for f in record.findings if f.severity == FindingSeverity.WARNING)
    nguoi = ", ".join(p.name for p in m.participants) or "(không có danh sách)"
    tieu_de = m.title or m.meeting_id

    thong_ke = "".join(
        f'<div class="stat"><b>{n}</b>{_e(nhan)}</div>'
        for n, nhan in (
            (len(record.items), "mục"), (len(record.threads), "luồng"), (so_can, "mục cần xem lại"),
            (so_loi, "finding lỗi"), (so_canh_bao, "finding cảnh báo"),
        )
    )
    return (
        '<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        f"<title>Báo cáo cuộc họp: {_e(tieu_de)}</title><style>{CSS}</style></head><body><main>"
        f"<h1>{_e(tieu_de)}</h1>"
        f'<p class="muted">Ngày họp {_e(m.meeting_date.isoformat())} · Người tham gia: {_e(nguoi)}<br>'
        f"Bản ghi {_e(record.record_id)} · tạo lúc {_e(record.created_at.isoformat())}</p>"
        f'<div class="stats">{thong_ke}</div>'
        f"<h2>Cần xem lại ({so_can})</h2>{_khoi_can_xem_lai(record.items)}"
        f"{_khoi_nhom(record.items)}"
        f"<h2>Các luồng vấn đề</h2>{_khoi_luong(record.threads)}"
        f"<h2>Phát hiện của bước kiểm chứng</h2>{_khoi_finding(record.findings)}"
        "</main></body></html>"
    )


def luu_ket_qua(record: MeetingRecord, thu_muc_run: str | Path, ten_file: str = "s8_report.html") -> Path:
    """Ghi file HTML vào thư mục run."""
    thu_muc_run = Path(thu_muc_run)
    thu_muc_run.mkdir(parents=True, exist_ok=True)
    duong_dan = thu_muc_run / ten_file
    duong_dan.write_text(tao_html(record), encoding="utf-8")
    return duong_dan


def _chay_rieng(argv: Optional[list[str]] = None) -> int:
    """Chạy riêng bước 8 từ command line."""
    parser = argparse.ArgumentParser(description="Chạy riêng bước 8: xuất báo cáo HTML (không gọi LLM)")
    parser.add_argument("thu_muc_run", help="thư mục đã có s7_record.json")
    parser.add_argument("--index", action="store_true", help="ghi thành index.html (để đưa lên hosting tĩnh)")
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

    duong_dan = luu_ket_qua(record, thu_muc_run, "index.html" if args.index else "s8_report.html")
    print(f"Đã ghi: {duong_dan}")
    return 0


if __name__ == "__main__":
    sys.exit(_chay_rieng())