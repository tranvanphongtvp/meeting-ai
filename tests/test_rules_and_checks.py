"""
test_rules_and_checks.py - Kiểm thử bước 3 sau khi dựng lại (LLM chỉ trả event_ids).

Không gọi mạng. Chạy được cả bằng pytest lẫn chạy thẳng (không cần cài pytest):
    cd src && python ../tests/test_rules_and_checks.py
"""

import json
import re
import sys
from datetime import date
from pathlib import Path

GOC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GOC / "src"))

from llm_client import KetQuaLLM  # noqa: E402
from s1_preprocess import tien_xu_ly  # noqa: E402
from s2_extract_acts import KetQuaTrichXuat  # noqa: E402
from deadline_utils import quy_doi_han_chot  # noqa: E402
from s3_resolve import phan_giai, xu_ly_dau_ra  # noqa: E402
from schemas import (  # noqa: E402
    TRANG_THAI_THEO_LOAI,
    ActType,
    AssignmentClarity,
    Goal,
    ItemStatus,
    Meeting,
    Participant,
    Proposal,
    ResolutionOutput,
    ReviewReason,
    SpeechEvent,
    nhom_theo_loai,
    trang_thai_hop_le_cho_loai,
)

R = ReviewReason
NGAY_HOP = date(2026, 10, 13)  # thứ Ba


# ---------------------------------------------------------------------------
# Hàm dựng dữ liệu thử
# ---------------------------------------------------------------------------


def dung(transcript: str, su_kien: list[tuple], nguoi: list[tuple], ngay=NGAY_HOP):
    """transcript: các dòng '[mm:ss] Tên: nội dung'.
    su_kien: (turn_id, act, quote) hoặc (turn_id, act, quote, certainty), đánh E001.. theo thứ tự.
    nguoi: (tên, can_decide).
    """
    meeting = Meeting(
        meeting_id="t", meeting_date=ngay,
        participants=[Participant(name=n, can_decide=q) for n, q in nguoi],
    )
    s1 = tien_xu_ly(transcript, meeting)
    assert s1.ok, s1.loi
    luot = {t.turn_id: t for t in s1.turns}
    events = []
    for i, sk in enumerate(su_kien, start=1):
        tid, act, quote = sk[:3]
        ct = sk[3] if len(sk) > 3 else "firm"
        events.append(SpeechEvent(event_id=f"E{i:03d}", turn_id=tid, speaker=luot[tid].speaker,
                                  act=act, topic_label="x", quote=quote, certainty=ct))
    return s1, KetQuaTrichXuat(events=events, thong_ke={}, theo_hanh_dong={})


def muc(item_id, loai, status, event_ids, thread="TH01", **kw):
    d = {"item_id": item_id, "type": loai, "summary": f"muc {item_id}", "thread_id": thread,
         "event_ids": event_ids, "status": status}
    d.update(kw)
    return d


def luong(ids, thread="TH01"):
    return {"thread_id": thread, "topic": "chu de", "event_ids": ids, "note": None}


def chay(s1, s2, threads, items):
    return xu_ly_dau_ra(s1, s2, {"threads": threads, "items": items})


def theo_loai(kq, loai):
    return [i for i in kq.items if i.type == loai]


# Bối cảnh dùng chung: Minh có quyền chốt, Nam và Lan thì không.
NGUOI = [("Minh", True), ("Nam", False), ("Lan", False)]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_schema_proposal_goal_va_bang_trang_thai():
    p = Proposal(item_id="I1", summary="A", status=ItemStatus.SUPERSEDED, thread_id="TH01", proposed_by="Nam")
    assert trang_thai_hop_le_cho_loai(p)
    assert not trang_thai_hop_le_cho_loai(
        Proposal(item_id="I1", summary="A", status=ItemStatus.CONFIRMED, thread_id="TH01"))
    assert TRANG_THAI_THEO_LOAI["goal"] == {ItemStatus.PROPOSED, ItemStatus.CONFIRMED, ItemStatus.SUPERSEDED}
    out = ResolutionOutput.model_validate({"threads": [], "items": [
        {"item_id": "I1", "type": "goal", "summary": "b", "status": "confirmed", "thread_id": "TH01"}]})
    assert isinstance(out.items[0], Goal)
    assert len(nhom_theo_loai([])) == 7
    assert R("deadline_ambiguity") is R.DEADLINE_AMBIGUITY


# ---------------------------------------------------------------------------
# Ví dụ trong prompt phải chạy qua code ra đúng kết quả mong đợi
# ---------------------------------------------------------------------------


def _lay_vi_du_tu_prompt():
    prompt = (GOC / "configs" / "prompts" / "resolve_threads.md").read_text(encoding="utf-8")
    json_vi_du = json.loads(re.findall(r"```json\n(.*?)```", prompt, re.S)[-1])
    su_kien = []
    for dong in prompt.splitlines():
        c = [x.strip() for x in dong.strip().strip("|").split("|")]
        if len(c) == 7 and re.fullmatch(r"E\d{3}", c[0]):
            su_kien.append((c[1], c[3], c[5], c[6]))
    return json_vi_du, su_kien


def test_vi_du_trong_prompt_chay_dung():
    json_vi_du, su_kien = _lay_vi_du_tu_prompt()
    assert len(su_kien) == 9
    transcript = (
        "[00:01:10] Hà: Tôi đề xuất làm báo cáo bằng Excel cho nhanh.\n"
        "[00:01:40] Tùng: Excel khó cập nhật tự động. Dùng Power BI thì hơn.\n"
        "[00:02:20] Hà: Ừ, Power BI cũng được, nhưng hạn là cuối tháng nhé.\n"
        "[00:02:50] Sơn: Vậy thống nhất Power BI. Tùng phụ trách.\n"
        "[00:03:15] Tùng: Để em lo. Mà em chưa có license, chắc phải chờ IT."
    )
    s1, s2 = dung(transcript, su_kien, [("Hà", False), ("Tùng", False), ("Sơn", True)], date(2026, 10, 1))
    kq = xu_ly_dau_ra(s1, s2, json_vi_du)
    assert kq.ok and not kq.canh_bao, kq.canh_bao
    de_xuat, quyet_dinh = theo_loai(kq, "proposal")[0], theo_loai(kq, "decision")[0]
    assert quyet_dinh.status == ItemStatus.CONFIRMED and quyet_dinh.decided_by == "Sơn"
    assert quyet_dinh.supersedes == de_xuat.item_id and not quyet_dinh.needs_review
    assert quyet_dinh.rejected_options == ["Excel"]
    assert de_xuat.status == ItemStatus.SUPERSEDED and de_xuat.superseded_by == quyet_dinh.item_id
    assert de_xuat.proposed_by == "Hà" and not de_xuat.needs_review
    viec = theo_loai(kq, "action")[0]
    assert (viec.owner, viec.deadline, viec.assignment_clarity) == (
        "Tùng", date(2026, 10, 31), AssignmentClarity.EXPLICIT)
    assert viec.status == ItemStatus.CONFIRMED and not viec.needs_review
    assert theo_loai(kq, "issue")[0].status == ItemStatus.OPEN
    th = {t.thread_id: t for t in kq.threads}
    assert (th["TH01"].status, th["TH01"].decisive_event_id) == (ItemStatus.CONFIRMED, "E006")
    assert th["TH02"].status == ItemStatus.CONFIRMED and th["TH03"].status == ItemStatus.OPEN


# ---------------------------------------------------------------------------
# Bằng chứng do code dựng
# ---------------------------------------------------------------------------

TR1 = "[00:01] Nam: Em đề xuất phương án A.\n[00:02] Minh: Vậy chốt phương án B."


def test_evidence_do_code_dung_bo_qua_evidence_llm_tu_viet():
    s1, s2 = dung(TR1, [("T001", "propose", "Em đề xuất phương án A"), ("T002", "confirm", "chốt phương án B")], NGUOI)
    kq = chay(s1, s2, [luong(["E001", "E002"])], [
        muc("A", "decision", "confirmed", ["E002"],
            evidence=[{"turn_id": "T999", "speaker": "Ma", "timestamp": "9", "quote": "bịa đặt"}])])
    ev = kq.items[0].evidence
    assert [(e.turn_id, e.speaker, e.timestamp, e.quote) for e in ev] == [
        ("T002", "Minh", "00:02", "chốt phương án B")]


def test_event_id_la_bi_bo_va_muc_khong_con_bang_chung_bi_co():
    s1, s2 = dung(TR1, [("T001", "propose", "Em đề xuất phương án A")], NGUOI)
    kq = chay(s1, s2, [luong(["E001", "E777"])], [muc("A", "proposal", "proposed", ["E888"], thread=None)])
    it = kq.items[0]
    assert R.NO_EVIDENCE in it.review_reasons and it.needs_review and it.evidence == []
    assert it.thread_id == "UNASSIGNED"
    assert any("E777" in c for c in kq.canh_bao) and any("E888" in c for c in kq.canh_bao)


def test_quote_khong_khop_luot_noi_bi_co_evidence_mismatch():
    s1, s2 = dung(TR1, [("T001", "propose", "câu này không có trong lượt nói")], NGUOI)
    kq = chay(s1, s2, [luong(["E001"])], [muc("A", "proposal", "proposed", ["E001"])])
    assert R.EVIDENCE_MISMATCH in kq.items[0].review_reasons


# ---------------------------------------------------------------------------
# Mục hỏng: bỏ mục đó, giữ các mục còn lại
# ---------------------------------------------------------------------------


def test_muc_hong_bi_bo_kem_canh_bao_muc_tot_van_giu():
    s1, s2 = dung(TR1, [("T001", "propose", "Em đề xuất phương án A"), ("T002", "confirm", "chốt phương án B")], NGUOI)
    kq = chay(s1, s2, [luong(["E001", "E002"])], [
        muc("X", "khong_co_loai", "proposed", ["E001"]),
        muc("Y", "proposal", "confirmed", ["E001"]),   # proposal không có confirmed
        muc("Z", "decision", "confirmed", ["E002"]),
    ])
    assert [i.type for i in kq.items] == ["decision"]
    assert kq.thong_ke["so_muc_bi_bo"] == 2 and len(kq.canh_bao) >= 2
    assert kq.ok


def test_item_id_trung_khong_lam_mat_muc():
    s1, s2 = dung(TR1, [("T001", "propose", "Em đề xuất phương án A"), ("T002", "confirm", "chốt phương án B")], NGUOI)
    kq = chay(s1, s2, [luong(["E001", "E002"])], [
        muc("A", "proposal", "proposed", ["E001"]), muc("A", "decision", "confirmed", ["E002"])])
    assert len(kq.items) == 2 and any("trùng" in c for c in kq.canh_bao)


def test_truong_la_va_gia_tri_null_chuoi_duoc_chap_nhan():
    s1, s2 = dung(TR1, [("T001", "propose", "Em đề xuất phương án A")], NGUOI)
    kq = chay(s1, s2, [luong(["E001"])], [
        muc("A", "proposal", "PROPOSED", ["E001"], proposed_by="null", truong_la="x", decided_by=None)])
    assert kq.items[0].proposed_by == "Nam"  # null -> code lấy người đề xuất


# ---------------------------------------------------------------------------
# Luật trạng thái
# ---------------------------------------------------------------------------


def test_nguoi_chot_khong_co_quyen_ha_ve_proposed_va_authority_unclear():
    tr = "[00:01] Minh: Mình có hai phương án.\n[00:02] Nam: Chốt phương án B nhé."
    s1, s2 = dung(tr, [("T001", "propose", "hai phương án"), ("T002", "confirm", "Chốt phương án B")], NGUOI)
    kq = chay(s1, s2, [luong(["E001", "E002"])], [muc("A", "decision", "confirmed", ["E001", "E002"])])
    it = kq.items[0]
    assert it.status == ItemStatus.PROPOSED and R.AUTHORITY_UNCLEAR in it.review_reasons
    assert R.RULE_CONFLICT in it.review_reasons and it.decided_by is None


def test_roster_khong_ai_co_quyen_giu_confirmed_kem_co():
    s1, s2 = dung(TR1, [("T001", "propose", "Em đề xuất phương án A"), ("T002", "confirm", "chốt phương án B")],
                  [("Minh", False), ("Nam", False)])
    kq = chay(s1, s2, [luong(["E001", "E002"])], [muc("A", "decision", "confirmed", ["E002"])])
    it = kq.items[0]
    assert it.status == ItemStatus.CONFIRMED and it.decided_by == "Minh"
    assert it.review_reasons == [R.AUTHORITY_UNCLEAR]


def test_phan_doi_sau_khi_chot_ha_ve_proposed():
    tr = "[00:01] Minh: Chốt phương án B.\n[00:02] Nam: Em không đồng ý phương án B."
    s1, s2 = dung(tr, [("T001", "confirm", "Chốt phương án B"), ("T002", "object", "không đồng ý phương án B")], NGUOI)
    kq = chay(s1, s2, [luong(["E001", "E002"])], [muc("A", "decision", "confirmed", ["E001", "E002"])])
    assert kq.items[0].status == ItemStatus.PROPOSED and R.RULE_CONFLICT in kq.items[0].review_reasons


def test_proposal_bi_decision_thay_the_hop_le_va_bi_action_thay_the_thi_khong():
    s1, s2 = dung(TR1, [("T001", "propose", "Em đề xuất phương án A"), ("T002", "confirm", "chốt phương án B")], NGUOI)
    ok = chay(s1, s2, [luong(["E001", "E002"])], [
        muc("A", "proposal", "superseded", ["E001"], superseded_by="B"),
        muc("B", "decision", "confirmed", ["E002"])])
    pr = theo_loai(ok, "proposal")[0]
    assert pr.status == ItemStatus.SUPERSEDED and pr.superseded_by and not pr.needs_review
    sai = chay(s1, s2, [luong(["E001", "E002"])], [
        muc("A", "proposal", "superseded", ["E001"], superseded_by="B"),
        muc("B", "issue", "open", ["E002"])])
    pr = theo_loai(sai, "proposal")[0]
    assert pr.status == ItemStatus.PROPOSED and R.RULE_CONFLICT in pr.review_reasons and pr.superseded_by is None


def test_llm_noi_confirmed_nhung_khong_co_confirm_thi_luat_ha_xuong():
    s1, s2 = dung(TR1, [("T001", "propose", "Em đề xuất phương án A")], NGUOI)
    kq = chay(s1, s2, [luong(["E001"])], [muc("A", "decision", "confirmed", ["E001"])])
    assert kq.items[0].status == ItemStatus.PROPOSED and R.RULE_CONFLICT in kq.items[0].review_reasons


# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------

TR_GOAL = "[00:01] {ai}: Mục tiêu là hoàn thành MVP trước ngày 23 tháng 10 năm 2026."


def test_goal_co_confirm_boi_nguoi_can_decide_la_confirmed_va_co_deadline():
    tr = TR_GOAL.format(ai="Minh") + "\n[00:02] Minh: Ok chốt mục tiêu đó."
    s1, s2 = dung(tr, [("T001", "share_info", "hoàn thành MVP trước ngày 23 tháng 10 năm 2026"),
                       ("T002", "confirm", "chốt mục tiêu đó")], NGUOI)
    kq = chay(s1, s2, [luong(["E001", "E002"])], [
        muc("G", "goal", "confirmed", ["E001", "E002"], deadline_raw="trước ngày 23 tháng 10 năm 2026")])
    g = kq.items[0]
    assert g.status == ItemStatus.CONFIRMED and g.deadline == date(2026, 10, 23) and not g.needs_review


def test_goal_chi_duoc_nguoi_co_quyen_neu_ma_chua_ai_chot_thi_la_proposed():
    # Lựa chọn đã chốt với người dùng: goal dùng luật như decision, cần sự kiện confirm.
    for ai in ("Minh", "Nam"):
        s1, s2 = dung(TR_GOAL.format(ai=ai),
                      [("T001", "share_info", "hoàn thành MVP trước ngày 23 tháng 10 năm 2026")], NGUOI)
        kq = chay(s1, s2, [luong(["E001"])], [muc("G", "goal", "confirmed", ["E001"])])
        assert kq.items[0].status == ItemStatus.PROPOSED and R.RULE_CONFLICT in kq.items[0].review_reasons


def test_goal_confirm_boi_nguoi_khong_co_quyen_ha_ve_proposed():
    tr = TR_GOAL.format(ai="Minh") + "\n[00:02] Nam: Ok chốt mục tiêu đó."
    s1, s2 = dung(tr, [("T001", "share_info", "hoàn thành MVP"), ("T002", "confirm", "chốt mục tiêu đó")], NGUOI)
    kq = chay(s1, s2, [luong(["E001", "E002"])], [muc("G", "goal", "confirmed", ["E001", "E002"])])
    g = kq.items[0]
    assert g.status == ItemStatus.PROPOSED and R.AUTHORITY_UNCLEAR in g.review_reasons


def test_goal_co_confirm_boi_nguoi_khong_co_quyen_van_confirmed_kem_co():
    tr = TR_GOAL.format(ai="Minh") + "\n[00:02] Nam: Ok chốt mục tiêu đó."
    s1, s2 = dung(tr, [("T001", "share_info", "hoàn thành MVP"), ("T002", "confirm", "chốt mục tiêu đó")],
                  [("Minh", False), ("Nam", False)])
    kq = chay(s1, s2, [luong(["E001", "E002"])], [muc("G", "goal", "confirmed", ["E001", "E002"])])
    assert kq.items[0].status == ItemStatus.CONFIRMED and R.AUTHORITY_UNCLEAR in kq.items[0].review_reasons


# ---------------------------------------------------------------------------
# Deadline và owner
# ---------------------------------------------------------------------------

TR_VIEC = (
    "[00:01] Minh: Deadline hoàn thành là ngày 16 tháng 10 năm 2026.\n"
    "[00:02] Nam: Em sẽ hoàn thành trước ngày 16 tháng 10 năm 2026."
)
EV_VIEC = [("T001", "assign", "Deadline hoàn thành là ngày 16 tháng 10 năm 2026"),
           ("T002", "accept_task", "Em sẽ hoàn thành trước ngày 16 tháng 10 năm 2026")]


def _viec(**kw):
    s1, s2 = dung(TR_VIEC, EV_VIEC, NGUOI)
    return chay(s1, s2, [luong(["E001", "E002"])], [muc("A", "action", "confirmed", ["E001", "E002"], **kw)]).items[0]


def test_deadline_nhieu_dien_dat_gan_co_mo_ho_va_quy_doi_phan_dau():
    it = _viec(owner="Nam", deadline_raw="ngày 16 tháng 10 năm 2026 (Minh, T001) | trước ngày 16 tháng 10 năm 2026 (Nam, T002)")
    assert it.deadline == date(2026, 10, 16) and R.DEADLINE_AMBIGUITY in it.review_reasons
    assert R.EVIDENCE_MISMATCH not in it.review_reasons and it.needs_review


def test_deadline_dau_gach_khong_khoang_trang():
    it = _viec(owner="Nam", deadline_raw="ngày 16 tháng 10 năm 2026|trước ngày 16 tháng 10 năm 2026")
    assert R.DEADLINE_AMBIGUITY in it.review_reasons


def test_deadline_khong_co_trong_loi_noi_la_evidence_mismatch_va_khong_quy_doi():
    it = _viec(owner="Nam", deadline_raw="thứ Sáu tới")
    assert it.deadline is None and R.EVIDENCE_MISMATCH in it.review_reasons


def test_deadline_ngay_da_qua_la_deadline_invalid():
    tr = "[00:01] Minh: Nam làm xong trước ngày 10 tháng 10 năm 2026 nhé."
    s1, s2 = dung(tr, [("T001", "assign", "Nam làm xong trước ngày 10 tháng 10 năm 2026")], NGUOI)
    it = chay(s1, s2, [luong(["E001"])], [
        muc("A", "action", "confirmed", ["E001"], owner="Nam", deadline_raw="ngày 10 tháng 10 năm 2026")]).items[0]
    assert it.deadline is None and R.DEADLINE_INVALID in it.review_reasons


def test_owner_va_assignment_clarity_do_code_tinh():
    # chỉ có accept_task, LLM không nêu owner -> owner = người nhận, implicit
    s1, s2 = dung(TR_VIEC, EV_VIEC[1:], NGUOI)
    it = chay(s1, s2, [luong(["E001"])], [muc("A", "action", "confirmed", ["E001"])]).items[0]
    assert it.owner == "Nam" and it.assignment_clarity == AssignmentClarity.IMPLICIT
    # có assign nêu tên -> explicit
    tr = "[00:01] Minh: Lan phụ trách phần này."
    s1, s2 = dung(tr, [("T001", "assign", "Lan phụ trách phần này")], NGUOI)
    it = chay(s1, s2, [luong(["E001"])], [muc("A", "action", "confirmed", ["E001"], owner="Lan")]).items[0]
    assert it.assignment_clarity == AssignmentClarity.EXPLICIT and not it.needs_review


def test_owner_khong_co_trong_roster_hoac_khong_co_ai_deu_bi_co():
    s1, s2 = dung(TR_VIEC, EV_VIEC, NGUOI)
    it = chay(s1, s2, [luong(["E001", "E002"])], [muc("A", "action", "confirmed", ["E001", "E002"], owner="Zed")]).items[0]
    assert R.SPEAKER_UNKNOWN in it.review_reasons and R.EVIDENCE_MISMATCH in it.review_reasons and it.owner == "Zed"
    tr = "[00:01] Minh: Cần làm báo cáo."
    s1, s2 = dung(tr, [("T001", "request", "Cần làm báo cáo")], NGUOI)
    it = chay(s1, s2, [luong(["E001"])], [muc("A", "action", "proposed", ["E001"])]).items[0]
    assert it.owner is None and R.NO_OWNER in it.review_reasons
    assert it.assignment_clarity == AssignmentClarity.UNASSIGNED


def test_quy_doi_han_chot_bang_chuan():
    """Ngày họp thứ Ba 2026-10-13. Gồm 4 lỗi cũ của parse_deadline (thứ Bảy, tuần sau, ngày đã qua, thứ 6)."""
    d = lambda s: date.fromisoformat(s)
    bang = {
        "thứ Sáu": "2026-10-16", "thứ Sáu tới": "2026-10-16", "thứ Ba": None, "thứ Ba tới": "2026-10-20",
        "thứ Sáu tuần sau": "2026-10-23", "thứ Sáu tuần này": "2026-10-16", "thứ Hai tuần này": None,
        "thứ Bảy": "2026-10-17", "thứ 6": "2026-10-16", "chủ nhật": "2026-10-18",
        "ngày mai": "2026-10-14", "hôm nay": "2026-10-13", "3 ngày nữa": "2026-10-16",
        "cuối tháng": "2026-10-31", "cuối tháng sau": "2026-11-30",
        "20/10": "2026-10-20", "ngày 20 tháng 10": "2026-10-20", "10/10": None,
        "trước ngày 23 tháng 10 năm 2026": "2026-10-23",  # ý "trước" nằm trong deadline_raw
        "tuần sau": None, "cuối tuần": None, "khi nào xong thì xong": None,
    }
    sai = {k: (quy_doi_han_chot(k, NGAY_HOP), v) for k, v in bang.items()
           if quy_doi_han_chot(k, NGAY_HOP) != (d(v) if v else None)}
    assert not sai, sai


# ---------------------------------------------------------------------------
# Luồng và toàn bộ lượt gọi
# ---------------------------------------------------------------------------


def test_su_kien_o_hai_luong_chi_giu_luong_dau_va_luong_rong_bi_bo():
    s1, s2 = dung(TR1, [("T001", "propose", "Em đề xuất phương án A"), ("T002", "confirm", "chốt phương án B")], NGUOI)
    kq = chay(s1, s2, [luong(["E001"], "TH01"), luong(["E001", "E002"], "TH02"), luong(["E999"], "TH03")],
              [muc("A", "proposal", "proposed", ["E001"])])
    assert [t.event_ids for t in kq.threads] == [["E001"], ["E002"]]
    assert any("TH03" in c for c in kq.canh_bao)
    assert kq.threads[1].note and "không có mục" in kq.threads[1].note


class _GiaLap:
    def __init__(self, *tra_loi):
        self.tra_loi, self.n = list(tra_loi), 0

    def generate_json(self, system_prompt, user_content):
        t = self.tra_loi[min(self.n, len(self.tra_loi) - 1)]
        self.n += 1
        return KetQuaLLM(text=t, model="gia-lap", prompt_tokens=10, output_tokens=5)


def test_phan_giai_thu_lai_khi_json_hong_roi_xu_ly_dau_ra():
    s1, s2 = dung(TR1, [("T001", "propose", "Em đề xuất phương án A")], NGUOI)
    tot = json.dumps({"threads": [luong(["E001"])], "items": [muc("A", "proposal", "proposed", ["E001"])]})
    gia = _GiaLap("không phải json", tot)
    kq, log = phan_giai(s1, s2, gia, "sys")
    assert kq.ok and len(kq.items) == 1 and kq.su_dung_llm["so_lan_goi"] == 2 and len(log) == 2
    assert kq.su_dung_llm["prompt_tokens"] == 20


def test_phan_giai_that_bai_hoan_toan_tra_loi():
    s1, s2 = dung(TR1, [("T001", "propose", "Em đề xuất phương án A")], NGUOI)
    kq, _ = phan_giai(s1, s2, _GiaLap("hỏng"), "sys")
    assert not kq.ok and kq.items == []


def test_s2_tro_toi_turn_khong_co_trong_s1_la_loi():
    s1, s2 = dung(TR1, [("T001", "propose", "Em đề xuất phương án A")], NGUOI)
    s2.events[0] = s2.events[0].model_copy(update={"turn_id": "T099"})
    kq = chay(s1, s2, [], [])
    assert not kq.ok


if __name__ == "__main__":
    ds = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    loi = 0
    for ten, ham in ds:
        try:
            ham()
            print(f"OK   {ten}")
        except Exception as e:  # noqa: BLE001
            loi += 1
            print(f"FAIL {ten}: {type(e).__name__}: {e}")
    print(f"\n{len(ds) - loi}/{len(ds)} đạt")
    sys.exit(1 if loi else 0)