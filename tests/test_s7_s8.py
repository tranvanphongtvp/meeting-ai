"""Test bước 7 (ghép bản ghi) và bước 8 (báo cáo HTML). Chạy: pytest tests/test_s7_s8.py"""

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import s7_assemble  # noqa: E402
import s8_report  # noqa: E402
from s6_verify import kiem_chung  # noqa: E402
from schemas import (  # noqa: E402
    Action,
    ActType,
    Evidence,
    ItemStatus,
    Meeting,
    MeetingRecord,
    Participant,
    SpeechEvent,
    Thread,
    Turn,
)

THOI_DIEM = datetime(2026, 10, 14, 9, 30, 5, tzinfo=timezone.utc)


def _du_lieu(quote="sẽ làm báo cáo", summary="Làm báo cáo <b>doanh thu</b>"):
    meeting = Meeting(meeting_id="M01", meeting_date=date(2026, 10, 14), title="Họp tuần",
                      participants=[Participant(name="Nam")])
    turn = Turn(turn_id="T001", speaker="Nam", speaker_raw="Nam", timestamp="00:01:00",
                text="Mình sẽ làm báo cáo trước thứ Sáu")
    ev = SpeechEvent(event_id="E001", turn_id="T001", speaker="Nam", act=ActType.ASSIGN, topic_label="x", quote="q")
    it = Action(item_id="I001", summary=summary, status=ItemStatus.CONFIRMED, thread_id="TH01", owner="Nam",
                deadline=date(2026, 10, 17), deadline_raw="thứ Sáu", event_ids=["E001"],
                evidence=[Evidence(turn_id="T001", speaker="Nam", timestamp="00:01:00", quote=quote)])
    th = Thread(thread_id="TH01", topic="Báo cáo", event_ids=["E001"], status=ItemStatus.CONFIRMED)
    s1 = SimpleNamespace(meeting=meeting, turns=[turn])
    s2 = SimpleNamespace(events=[ev])
    s3 = SimpleNamespace(threads=[th], items=[it], loi=[])
    return s1, s2, s3


def _record(**kw):
    s1, s2, s3 = _du_lieu(**kw)
    s6 = kiem_chung(s1, s2, s3)
    return s7_assemble.ghep_ban_ghi(s1, s6, THOI_DIEM), s6


# ---------------------------------------------------------------------------
# Bước 7
# ---------------------------------------------------------------------------


def test_s7_record_id_va_truong():
    rec, s6 = _record()
    assert rec.record_id == "M01-20261014-093005"
    assert rec.created_at == THOI_DIEM
    assert rec.meeting.meeting_id == "M01"
    assert len(rec.items) == 1 and len(rec.threads) == 1


def test_s7_giu_nguyen_co_va_finding_tu_s6():
    rec, s6 = _record(quote="bịa hoàn toàn")
    assert rec.items[0].needs_review and rec.findings == s6.findings and rec.findings


def test_s7_khong_sua_dau_vao():
    s1, s2, s3 = _du_lieu()
    s6 = kiem_chung(s1, s2, s3)
    truoc = s6.model_dump()
    rec = s7_assemble.ghep_ban_ghi(s1, s6, THOI_DIEM)
    rec.items[0].summary = "đã sửa"
    assert s6.model_dump() == truoc


def test_s7_ghi_file_doc_lai_duoc(tmp_path):
    rec, _ = _record()
    p = s7_assemble.luu_ket_qua(rec, tmp_path)
    assert MeetingRecord.model_validate_json(p.read_text(encoding="utf-8")) == rec


# ---------------------------------------------------------------------------
# Bước 8
# ---------------------------------------------------------------------------


def test_s8_du_7_nhom_ke_ca_rong():
    rec, _ = _record()
    html = s8_report.tao_html(rec)
    for _, ten in s8_report.THU_TU_NHOM:
        assert ten in html
    assert "Không có mục nào." in html  # các nhóm rỗng vẫn hiện


def test_s8_escape_noi_dung_tu_du_lieu():
    rec, _ = _record(summary='<script>alert("x")</script>')
    html = s8_report.tao_html(rec)
    assert "<script>alert" not in html and "&lt;script&gt;" in html


def test_s8_hien_thi_bang_chung_han_va_co_review():
    rec, _ = _record()
    html = s8_report.tao_html(rec)
    assert "sẽ làm báo cáo" in html and "2026-10-17" in html and "thứ Sáu" in html
    rec2, _ = _record(quote="bịa hoàn toàn")
    html2 = s8_report.tao_html(rec2)
    assert "Cần xem lại (1)" in html2 and "Bằng chứng không khớp lượt nói gốc" in html2
    assert "Cần xem lại (0)" in html


def test_s8_tu_chua_khong_tai_tai_nguyen_ngoai():
    html = s8_report.tao_html(_record()[0])
    assert "http://" not in html and "https://" not in html and "<link" not in html


def test_s8_ghi_index(tmp_path):
    rec, _ = _record()
    s7_assemble.luu_ket_qua(rec, tmp_path)
    assert s8_report._chay_rieng([str(tmp_path), "--index"]) == 0
    assert (tmp_path / "index.html").exists()


def test_s8_thieu_file_exit_2(tmp_path):
    assert s8_report._chay_rieng([str(tmp_path)]) == 2


def test_s8_file_hong_exit_1(tmp_path):
    (tmp_path / "s7_record.json").write_text("{}", encoding="utf-8")
    assert s8_report._chay_rieng([str(tmp_path)]) == 1


def test_s7_cli_thieu_file_exit_2(tmp_path):
    assert s7_assemble._chay_rieng([str(tmp_path)]) == 2