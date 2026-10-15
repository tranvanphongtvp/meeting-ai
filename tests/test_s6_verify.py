"""Test bước 6 (kiểm chứng). Chạy từ thư mục gốc: pytest tests/test_s6_verify.py"""

import sys
import unicodedata
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import s6_verify  # noqa: E402
from s6_verify import kiem_chung  # noqa: E402
from schemas import (  # noqa: E402
    Action,
    ActType,
    Decision,
    Evidence,
    FindingKind,
    FindingSeverity,
    Goal,
    Issue,
    ItemStatus,
    OpenQuestion,
    Proposal,
    RequirementFeedback,
    ReviewReason,
    SpeechEvent,
    Thread,
    Turn,
    FeedbackKind,
)
from text_utils import chuan_hoa_bo_dau  # noqa: E402

# ---------------------------------------------------------------------------
# Dựng dữ liệu mẫu
# ---------------------------------------------------------------------------


def luot(tid="T001", speaker="Nam", ts="00:01:00", text="Mình sẽ làm báo cáo trước thứ Sáu"):
    return Turn(turn_id=tid, speaker=speaker, speaker_raw=speaker, timestamp=ts, text=text)


def su_kien(eid="E001", tid="T001", act=ActType.ASSIGN, speaker="Nam"):
    return SpeechEvent(event_id=eid, turn_id=tid, speaker=speaker, act=act, topic_label="x", quote="q")


def bang_chung(tid="T001", speaker="Nam", ts="00:01:00", quote="sẽ làm báo cáo"):
    return Evidence(turn_id=tid, speaker=speaker, timestamp=ts, quote=quote)


def viec(iid="I001", thread="TH01", summary="làm báo cáo doanh thu", status=ItemStatus.CONFIRMED,
         owner="Nam", deadline=None, events=("E001",), evidence=None, **kw):
    return Action(
        item_id=iid, summary=summary, status=status, thread_id=thread, owner=owner, deadline=deadline,
        event_ids=list(events), evidence=[bang_chung()] if evidence is None else evidence, **kw,
    )


def luong(tid="TH01", events=("E001",), decisive=None):
    return Thread(thread_id=tid, topic="t", event_ids=list(events), status=ItemStatus.CONFIRMED,
                  decisive_event_id=decisive)


def chay(items, threads=None, turns=None, events=None, nguong=0.5):
    s1 = SimpleNamespace(turns=turns if turns is not None else [luot()])
    s2 = SimpleNamespace(events=events if events is not None else [su_kien()])
    s3 = SimpleNamespace(threads=threads if threads is not None else [luong()], items=items, loi=[])
    return kiem_chung(s1, s2, s3, nguong), (s1, s2, s3)


def kinds(kq, severity=None):
    return [f.kind for f in kq.findings if severity is None or f.severity == severity]


def muc(kq, iid):
    return next(i for i in kq.items if i.item_id == iid)


# ---------------------------------------------------------------------------
# Kiểm tra giả định về text_utils (chạy trước để biết hàm bỏ dấu có thật sự bỏ dấu)
# ---------------------------------------------------------------------------


def test_chuan_hoa_bo_dau_thuc_su_bo_dau():
    assert chuan_hoa_bo_dau("Báo cáo Việt") == chuan_hoa_bo_dau("bao cao viet")


# ---------------------------------------------------------------------------
# V1: bằng chứng
# ---------------------------------------------------------------------------


def test_v1_turn_id_khong_co_la_error():
    kq, _ = chay([viec(evidence=[bang_chung(tid="T999")])])
    assert FindingKind.EVIDENCE_TURN_MISSING in kinds(kq, FindingSeverity.ERROR)
    assert ReviewReason.EVIDENCE_MISMATCH in muc(kq, "I001").review_reasons


def test_v1_speaker_lech():
    kq, _ = chay([viec(evidence=[bang_chung(speaker="Lan")])])
    assert FindingKind.EVIDENCE_SPEAKER_MISMATCH in kinds(kq, FindingSeverity.ERROR)


def test_v1_timestamp_lech():
    kq, _ = chay([viec(evidence=[bang_chung(ts="00:09:99")])])
    assert FindingKind.EVIDENCE_TIMESTAMP_MISMATCH in kinds(kq, FindingSeverity.ERROR)


def test_v1_quote_khop_du_dau_khong_finding():
    kq, _ = chay([viec()])
    assert not [k for k in kinds(kq) if k.value.startswith("evidence")]


def test_v1_quote_chi_khop_khi_bo_dau_la_warning_khong_co():
    kq, _ = chay([viec(evidence=[bang_chung(quote="se lam bao cao")])])
    assert kinds(kq, FindingSeverity.WARNING).count(FindingKind.EVIDENCE_QUOTE_DIACRITICS) == 1
    assert not muc(kq, "I001").needs_review


def test_v1_quote_khac_hoan_toan_la_error_va_co():
    kq, _ = chay([viec(evidence=[bang_chung(quote="điều này chưa ai nói")])])
    assert FindingKind.EVIDENCE_QUOTE_MISMATCH in kinds(kq, FindingSeverity.ERROR)
    assert muc(kq, "I001").needs_review


def test_v1_nfc_nfd_van_khop():
    nfd = unicodedata.normalize("NFD", "Mình sẽ làm báo cáo trước thứ Sáu")
    kq, _ = chay([viec(evidence=[bang_chung(quote="sẽ làm báo cáo")])], turns=[luot(text=nfd)])
    assert not [k for k in kinds(kq) if k.value.startswith("evidence")]


def test_v1_quote_rong_la_error():
    kq, _ = chay([viec(evidence=[bang_chung(quote="")])])
    assert FindingKind.EVIDENCE_QUOTE_MISMATCH in kinds(kq, FindingSeverity.ERROR)


def test_v1_muc_khong_evidence():
    kq, _ = chay([viec(evidence=[])])
    assert FindingKind.EVIDENCE_MISSING in kinds(kq, FindingSeverity.ERROR)
    assert muc(kq, "I001").review_reasons == [ReviewReason.NO_EVIDENCE]


def test_v1_event_id_khong_co_trong_s2():
    kq, _ = chay([viec(events=("E001", "E777"))])
    assert FindingKind.DANGLING_REFERENCE in kinds(kq, FindingSeverity.ERROR)
    assert ReviewReason.INVALID_REFERENCE in muc(kq, "I001").review_reasons


# ---------------------------------------------------------------------------
# V2: mâu thuẫn
# ---------------------------------------------------------------------------


def _hai_viec(**kw_b):
    a = viec("I001", events=("E001",))
    b = viec("I002", events=("E001",), **kw_b)
    return [a, b]


def test_v2_khac_owner_ca_hai_gan_co():
    kq, _ = chay(_hai_viec(owner="Lan"))
    assert FindingKind.OWNER_CONFLICT in kinds(kq, FindingSeverity.ERROR)
    assert muc(kq, "I001").needs_review and muc(kq, "I002").needs_review
    assert ReviewReason.CONTRADICTION in muc(kq, "I001").review_reasons


def test_v2_khac_han():
    a = viec("I001", deadline=date(2026, 10, 20))
    b = viec("I002", deadline=date(2026, 10, 27))
    kq, _ = chay([a, b])
    assert FindingKind.DEADLINE_CONFLICT in kinds(kq, FindingSeverity.ERROR)


def test_v2_cung_owner_cung_han_la_duplicate_khong_co():
    kq, _ = chay(_hai_viec())
    assert kinds(kq) == [FindingKind.DUPLICATE_TASK]
    assert not muc(kq, "I001").needs_review


def test_v2_thieu_owner_la_duplicate_khong_mau_thuan():
    kq, _ = chay(_hai_viec(owner=None))
    assert kinds(kq) == [FindingKind.DUPLICATE_TASK]


def test_v2_khac_luong_khong_so():
    a = viec("I001", thread="TH01")
    b = viec("I002", thread="TH02", owner="Lan")
    kq, _ = chay([a, b], threads=[luong("TH01"), luong("TH02")])
    assert not [k for k in kinds(kq) if k in (FindingKind.OWNER_CONFLICT, FindingKind.DUPLICATE_TASK)]


def test_v2_tom_tat_khac_nhau_khong_so():
    a = viec("I001", summary="làm báo cáo doanh thu")
    b = viec("I002", summary="đặt phòng họp tuần sau", owner="Lan")
    kq, _ = chay([a, b])
    assert FindingKind.OWNER_CONFLICT not in kinds(kq)


def test_v2_muc_superseded_khong_tham_gia():
    a = viec("I001", status=ItemStatus.SUPERSEDED, superseded_by="I002", owner="Lan", events=("E001",))
    b = viec("I002", events=("E001",))
    kq, _ = chay([a, b])
    assert FindingKind.OWNER_CONFLICT not in kinds(kq)


def test_v2_han_viec_muon_hon_han_goal_la_warning_khong_co():
    goal = Goal(item_id="I001", summary="ra mắt", status=ItemStatus.CONFIRMED, thread_id="TH01",
                deadline=date(2026, 10, 20), event_ids=["E001"], evidence=[bang_chung()])
    v = viec("I002", thread="TH02", deadline=date(2026, 10, 30), events=("E002",))
    events = [su_kien("E001", act=ActType.CONFIRM), su_kien("E002", act=ActType.ASSIGN)]
    kq, _ = chay([goal, v], threads=[luong("TH01"), luong("TH02", events=("E002",))], events=events)
    assert kinds(kq) == [FindingKind.DEADLINE_AFTER_GOAL]
    assert not muc(kq, "I002").needs_review


# ---------------------------------------------------------------------------
# V3: bất biến
# ---------------------------------------------------------------------------


def test_v3_id_trung():
    kq, _ = chay([viec("I001"), viec("I001", owner="Lan")])
    assert FindingKind.DUPLICATE_ID in kinds(kq, FindingSeverity.ERROR)


def test_v3_thread_id_trung():
    kq, _ = chay([viec()], threads=[luong("TH01"), luong("TH01")])
    assert FindingKind.DUPLICATE_ID in kinds(kq, FindingSeverity.ERROR)


def test_v3_item_thuoc_luong_khong_ton_tai_la_error_con_unassigned_la_warning():
    kq, _ = chay([viec(thread="TH99")])
    assert FindingKind.THREAD_INCONSISTENT in kinds(kq, FindingSeverity.ERROR)
    kq2, _ = chay([viec(thread="UNASSIGNED")])
    assert FindingKind.THREAD_INCONSISTENT in kinds(kq2, FindingSeverity.WARNING)
    assert not muc(kq2, "I001").needs_review


def test_v3_superseded_by_tro_id_khong_co():
    kq, _ = chay([viec(status=ItemStatus.SUPERSEDED, superseded_by="I099")])
    assert FindingKind.DANGLING_REFERENCE in kinds(kq, FindingSeverity.ERROR)


def test_v3_tu_tro_ve_chinh_no():
    kq, _ = chay([viec(status=ItemStatus.SUPERSEDED, superseded_by="I001")])
    assert FindingKind.DANGLING_REFERENCE in kinds(kq, FindingSeverity.ERROR)


def test_v3_vong_a_b_a():
    a = viec("I001", status=ItemStatus.SUPERSEDED, superseded_by="I002")
    b = viec("I002", status=ItemStatus.SUPERSEDED, superseded_by="I001", owner="Nam")
    kq, _ = chay([a, b])
    cycles = [f for f in kq.findings if f.kind == FindingKind.SUPERSEDE_CYCLE]
    assert len(cycles) == 1 and cycles[0].item_ids == ["I001", "I002"]


def test_v3_superseded_thieu_superseded_by():
    kq, _ = chay([viec(status=ItemStatus.SUPERSEDED)])
    assert FindingKind.SUPERSEDE_INCONSISTENT in kinds(kq, FindingSeverity.ERROR)


def test_v3_co_superseded_by_ma_status_khac():
    a = viec("I001", status=ItemStatus.CONFIRMED, superseded_by="I002")
    b = viec("I002", owner="Nam")
    kq, _ = chay([a, b])
    assert FindingKind.SUPERSEDE_INCONSISTENT in kinds(kq, FindingSeverity.ERROR)


def test_v3_muc_thay_the_khong_xay_ra_sau_hoac_chua_chot():
    events = [su_kien("E001"), su_kien("E002", act=ActType.ASSIGN)]
    cu = viec("I001", status=ItemStatus.SUPERSEDED, superseded_by="I002", events=("E002",))
    moi = viec("I002", status=ItemStatus.PROPOSED, events=("E001",))
    kq, _ = chay([cu, moi], threads=[luong(events=("E001", "E002"))], events=events)
    msgs = [f.message for f in kq.findings if f.kind == FindingKind.SUPERSEDE_INCONSISTENT]
    assert any("không xảy ra sau" in m for m in msgs)
    assert any("confirmed hoặc superseded" in m for m in msgs)


def test_v3_supersedes_khong_khop_superseded_by():
    cu = viec("I001", status=ItemStatus.CONFIRMED)
    moi = viec("I002", supersedes="I001")
    kq, _ = chay([cu, moi])
    assert FindingKind.SUPERSEDE_INCONSISTENT in kinds(kq, FindingSeverity.ERROR)


def test_v3_trang_thai_khong_thuoc_loai():
    sai = Issue(item_id="I001", summary="s", status=ItemStatus.CONFIRMED, thread_id="TH01",
                event_ids=["E001"], evidence=[bang_chung()])
    kq, _ = chay([sai])
    assert FindingKind.STATUS_NOT_ALLOWED in kinds(kq, FindingSeverity.ERROR)


def test_v3_decision_confirmed_khong_co_confirm():
    d = Decision(item_id="I001", summary="chọn A", status=ItemStatus.CONFIRMED, thread_id="TH01",
                 event_ids=["E001"], evidence=[bang_chung()])
    kq, _ = chay([d], events=[su_kien("E001", act=ActType.PROPOSE)])
    assert FindingKind.STATUS_NOT_SUPPORTED in kinds(kq, FindingSeverity.ERROR)
    assert ReviewReason.RULE_CONFLICT in muc(kq, "I001").review_reasons


def test_v3_decision_confirmed_co_confirm_thi_ok():
    d = Decision(item_id="I001", summary="chọn A", status=ItemStatus.CONFIRMED, thread_id="TH01",
                 event_ids=["E001"], evidence=[bang_chung()])
    kq, _ = chay([d], events=[su_kien("E001", act=ActType.CONFIRM)])
    assert FindingKind.STATUS_NOT_SUPPORTED not in kinds(kq)


def test_v3_action_confirmed_can_assign_hoac_accept_va_requirement_feedback():
    kq, _ = chay([viec()], events=[su_kien("E001", act=ActType.ACCEPT_TASK)])
    assert FindingKind.STATUS_NOT_SUPPORTED not in kinds(kq)
    kq, _ = chay([viec()], events=[su_kien("E001", act=ActType.ASK)])
    assert FindingKind.STATUS_NOT_SUPPORTED in kinds(kq)
    rf = RequirementFeedback(item_id="I001", summary="s", status=ItemStatus.CONFIRMED, thread_id="TH01",
                             kind=FeedbackKind.REQUIREMENT, event_ids=["E001"], evidence=[bang_chung()])
    kq, _ = chay([rf], events=[su_kien("E001", act=ActType.ACCEPT_TASK)])
    assert FindingKind.STATUS_NOT_SUPPORTED not in kinds(kq)


def test_v3_decisive_event_ngoai_luong():
    kq, _ = chay([viec()], threads=[luong(decisive="E005")])
    assert FindingKind.THREAD_INCONSISTENT in kinds(kq, FindingSeverity.ERROR)
    assert not muc(kq, "I001").needs_review  # lỗi cấp luồng, không gắn cờ mục


def test_v3_event_cua_luong_khong_co_trong_s2():
    kq, _ = chay([viec()], threads=[luong(events=("E001", "E888"))])
    assert FindingKind.THREAD_INCONSISTENT in kinds(kq, FindingSeverity.ERROR)


# ---------------------------------------------------------------------------
# V4: độ phủ
# ---------------------------------------------------------------------------


def test_v4_confirm_khong_thuoc_muc_nao_la_warning():
    events = [su_kien("E001"), su_kien("E002", act=ActType.CONFIRM)]
    kq, _ = chay([viec()], threads=[luong(events=("E001", "E002"))], events=events)
    unc = [f for f in kq.findings if f.kind == FindingKind.UNCOVERED_EVENT]
    assert len(unc) == 1 and unc[0].event_ids == ["E002"] and unc[0].thread_ids == ["TH01"]
    assert unc[0].severity == FindingSeverity.WARNING
    assert not muc(kq, "I001").needs_review


def test_v4_share_info_va_agree_khong_warning():
    events = [su_kien("E001"), su_kien("E002", act=ActType.SHARE_INFO), su_kien("E003", act=ActType.AGREE)]
    kq, _ = chay([viec()], threads=[luong(events=("E001", "E002", "E003"))], events=events)
    assert FindingKind.UNCOVERED_EVENT not in kinds(kq)


def test_v4_muc_superseded_van_tinh_la_da_phu():
    events = [su_kien("E001"), su_kien("E002", act=ActType.CONFIRM)]
    cu = viec("I001", status=ItemStatus.SUPERSEDED, superseded_by="I002", events=("E001",))
    moi = viec("I002", events=("E001", "E002"), owner="Nam")
    kq, _ = chay([cu, moi], threads=[luong(events=("E001", "E002"))], events=events)
    assert FindingKind.UNCOVERED_EVENT not in kinds(kq)


def test_s3_cu_thieu_event_ids_bo_qua_v39_v4_va_canh_bao():
    events = [su_kien("E001", act=ActType.ASK), su_kien("E002", act=ActType.CONFIRM)]
    kq, _ = chay([viec(events=())], events=events, threads=[luong(events=("E001", "E002"))])
    assert FindingKind.STATUS_NOT_SUPPORTED not in kinds(kq)
    assert FindingKind.UNCOVERED_EVENT not in kinds(kq)
    assert any("s3 cũ" in c for c in kq.canh_bao)


# ---------------------------------------------------------------------------
# Tổng hợp
# ---------------------------------------------------------------------------


def test_chi_error_gan_co():
    kq, _ = chay([viec(evidence=[bang_chung(quote="se lam bao cao")])])  # chỉ warning
    assert not muc(kq, "I001").needs_review


def test_needs_review_bang_bool_review_reasons_va_khu_trung_giu_thu_tu():
    cu = viec("I001", review_reasons=[ReviewReason.NO_OWNER], needs_review=True)
    kq, _ = chay([cu.model_copy(update={"evidence": [bang_chung(tid="T999")]})])
    it = muc(kq, "I001")
    assert it.review_reasons == [ReviewReason.NO_OWNER, ReviewReason.EVIDENCE_MISMATCH]
    for i in kq.items:
        assert i.needs_review == bool(i.review_reasons)


def test_khong_doi_status_va_noi_dung():
    a = viec("I001", status=ItemStatus.CONFIRMED, owner="Nam", evidence=[bang_chung(quote="bịa")])
    kq, (_, _, s3) = chay([a])
    it = muc(kq, "I001")
    assert it.status == ItemStatus.CONFIRMED and it.summary == a.summary and it.owner == "Nam"
    assert it.model_dump(exclude={"needs_review", "review_reasons"}) == a.model_dump(
        exclude={"needs_review", "review_reasons"}
    )


def test_hai_lan_chay_cung_finding_id_va_error_truoc():
    items = [viec("I001", evidence=[bang_chung(quote="se lam bao cao")]), viec("I002", owner="Lan")]
    kq1, _ = chay(items)
    kq2, _ = chay(items)
    assert [(f.finding_id, f.kind) for f in kq1.findings] == [(f.finding_id, f.kind) for f in kq2.findings]
    sev = [f.severity for f in kq1.findings]
    assert sev == sorted(sev, key=lambda s: 0 if s == FindingSeverity.ERROR else 1)
    assert kq1.findings[0].finding_id == "F001"


def test_ban_ghi_dau_vao_khong_bi_sua_tai_cho():
    a = viec("I001", evidence=[bang_chung(tid="T999")])
    truoc = a.model_dump()
    kq, _ = chay([a])
    assert a.model_dump() == truoc and not a.needs_review
    assert muc(kq, "I001").needs_review


def test_thong_ke():
    kq, _ = chay([viec("I001", evidence=[bang_chung(tid="T999")])])
    assert kq.thong_ke == {"error": 1, "warning": 0, "muc_can_xem_lai": 1}


def test_s3_co_loi_hoac_khong_co_muc_thi_tra_loi():
    s1 = SimpleNamespace(turns=[luot()])
    s2 = SimpleNamespace(events=[su_kien()])
    kq = kiem_chung(s1, s2, SimpleNamespace(threads=[], items=[], loi=["hỏng"]))
    assert not kq.ok
    kq = kiem_chung(s1, s2, SimpleNamespace(threads=[], items=[], loi=[]))
    assert not kq.ok


def test_cac_loai_muc_khac_chay_khong_loi():
    items = [
        Proposal(item_id="I001", summary="a", status=ItemStatus.PROPOSED, thread_id="TH01",
                 event_ids=["E001"], evidence=[bang_chung()]),
        OpenQuestion(item_id="I002", summary="b", status=ItemStatus.OPEN, thread_id="TH01",
                     event_ids=["E001"], evidence=[bang_chung()]),
    ]
    kq, _ = chay(items)
    assert kq.thong_ke["error"] == 0


# ---------------------------------------------------------------------------
# CLI (dùng file thật trong thư mục tạm)
# ---------------------------------------------------------------------------


def _ghi_run(thu_muc: Path, co_s1=True, co_s2=True, co_s3=True, s3_loi=None):
    from s3_resolve import KetQuaPhanGiai
    from s1_preprocess import KetQuaTienXuLy
    from s2_extract_acts import KetQuaTrichXuat
    from schemas import Meeting

    if co_s1:
        s1 = KetQuaTienXuLy(meeting=Meeting(meeting_id="M1", meeting_date=date(2026, 10, 14), participants=[]),
                            turns=[luot()])
        (thu_muc / "s1_turns.json").write_text(s1.model_dump_json(), encoding="utf-8")
    if co_s2:
        s2 = KetQuaTrichXuat(events=[su_kien()])
        (thu_muc / "s2_events.json").write_text(s2.model_dump_json(), encoding="utf-8")
    if co_s3:
        s3 = KetQuaPhanGiai(threads=[luong()], items=[] if s3_loi else [viec()], thong_ke={}, theo_loai={},
                            loi=[s3_loi] if s3_loi else [])
        (thu_muc / "s3_threads.json").write_text(s3.model_dump_json(), encoding="utf-8")


def test_cli_thieu_file_exit_2(tmp_path):
    _ghi_run(tmp_path, co_s3=False)
    assert s6_verify._chay_rieng([str(tmp_path)]) == 2


def test_cli_s3_loi_exit_1(tmp_path):
    _ghi_run(tmp_path, s3_loi="hỏng")
    assert s6_verify._chay_rieng([str(tmp_path)]) == 1


def test_cli_chay_thuong_exit_0_va_co_file(tmp_path, capsys):
    _ghi_run(tmp_path)
    assert s6_verify._chay_rieng([str(tmp_path), "--nguong-giong-nhau", "0.6"]) == 0
    assert (tmp_path / "s6_verified.json").exists()
    assert "Thống kê" in capsys.readouterr().out