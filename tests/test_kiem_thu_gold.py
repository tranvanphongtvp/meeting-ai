"""Test cho eval/kiem_thu_gold.py bằng gold và record dựng tay. Chạy: pytest tests/test_kiem_thu_gold.py"""

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))

import kiem_thu_gold as kt  # noqa: E402
from kiem_thu_gold import BO_QUA, DAT, LUU_Y, TRUOT  # noqa: E402


# ---------------------------------------------------------------------------
# Dữ liệu mẫu: gold nhỏ và một record "hoàn hảo"
# ---------------------------------------------------------------------------

GOLD = {
    "meeting_id": "case_x",
    "muc_dich": "thử",
    "items": [
        {"gold_id": "G01", "type": "decision", "status": "confirmed", "summary": "Chốt B",
         "turn_ids": ["T010", "T013"], "needs_review": False, "review_reasons": []},
        {"gold_id": "G02", "type": "proposal", "status": "proposed", "status_chap_nhan": ["superseded", "rejected"],
         "optional": True, "summary": "Đề xuất A", "turn_ids": ["T002"], "needs_review": False, "review_reasons": []},
        {"gold_id": "G03", "type": "action", "status": "confirmed", "owner": "Nam", "deadline": "2026-10-16",
         "summary": "Nam làm module", "turn_ids": ["T008", "T014"], "needs_review": False, "review_reasons": []},
        {"gold_id": "G04", "type": "action", "status": "confirmed", "owner": "Lan", "deadline": "2026-10-20",
         "summary": "Lan kiểm thử", "turn_ids": ["T009", "T015"], "needs_review": True,
         "needs_review_chap_nhan": [True, False], "review_reasons": ["implicit_signal"]},
        {"gold_id": "G05", "type": "action", "status": "superseded", "owner": "Nam", "deadline": None,
         "superseded_by": "G03", "summary": "Việc cũ", "turn_ids": ["T003"], "needs_review": False,
         "review_reasons": []},
    ],
    "must_not_have": [
        {"type": "decision", "status": ["confirmed"], "turn_ids": ["T002", "T003"], "ly_do": "A chưa chốt"},
        {"type": "action", "owner": "Minh", "turn_ids": [], "ly_do": "Minh không nhận việc"},
        {"type": "action", "owner": "Lan", "deadline": "2026-10-16", "turn_ids": [], "ly_do": "hạn của Nam"},
        {"type": "action", "owner": "Nam", "status": "confirmed", "turn_ids": ["T003"], "ly_do": "việc cũ của Nam"},
    ],
    "must_share_thread": [["G01", "G02"]],
    "must_not_share_thread": [],
    "pair_labels": [
        {"items": ["G03", "G04"], "same_task": False},
        {"items": ["G05", "G03"], "same_task": True},
    ],
}


def muc(iid, typ, status, turns, summary, **kw):
    d = {"item_id": iid, "type": typ, "status": status, "summary": summary, "thread_id": "TH1",
         "evidence": [{"turn_id": t, "speaker": "x", "timestamp": "00:00:00", "quote": "q"} for t in turns],
         "needs_review": False, "review_reasons": [], "superseded_by": None}
    d.update(kw)
    return d


def record_tot():
    return {
        "items": [
            muc("I001", "decision", "confirmed", ["T010", "T013", "T004"], "Chọn B"),
            muc("I002", "proposal", "superseded", ["T002"], "Đề xuất A"),
            muc("I003", "action", "confirmed", ["T008", "T014"], "Nam xây module quản lý quyền",
                owner="Nam", deadline="2026-10-16"),
            muc("I004", "action", "confirmed", ["T009", "T015"], "Lan kiểm thử đăng nhập phân quyền",
                owner="Lan", deadline="2026-10-20"),
            muc("I005", "action", "superseded", ["T003"], "Nam xây module quản lý quyền cũ",
                owner="Nam", deadline=None, superseded_by="I003"),
        ],
        "findings": [{"severity": "warning"}],
    }


def tim(kq, gold_id=None, nhom=None):
    return [t for t in kq.kiem_tra if (gold_id is None or t.gold_id == gold_id) and (nhom is None or t.nhom == nhom)]


# ---------------------------------------------------------------------------
# Khớp mục
# ---------------------------------------------------------------------------


def test_record_hoan_hao_khong_dong_truot():
    kq = kt.kiem_thu_case(GOLD, record_tot(), nguong_giong=0.5)
    truot = [(t.gold_id, t.nhom, t.thuc_te) for t in kq.kiem_tra if t.ket_qua == TRUOT]
    assert truot == [], truot
    assert kq.so_finding == {"warning": 1}


def test_khop_theo_loai_va_luot_khong_theo_id():
    khop, sai = kt.khop_muc(GOLD["items"], record_tot()["items"])
    assert khop["G01"] == 0 and khop["G03"] == 2 and khop["G04"] == 3 and sai == {}


def test_moi_muc_du_doan_chi_khop_mot_lan():
    gold = {"items": [
        {"gold_id": "G01", "type": "action", "turn_ids": ["T001"]},
        {"gold_id": "G02", "type": "action", "turn_ids": ["T001"]},
    ]}
    pred = [muc("I1", "action", "confirmed", ["T001"], "a")]
    khop, _ = kt.khop_muc(gold["items"], pred)
    assert len(khop) == 1


def test_khong_du_trung_luot_thi_khong_khop():
    gold = [{"gold_id": "G01", "type": "action", "turn_ids": ["T001", "T002", "T003", "T004"]}]
    pred = [muc("I1", "action", "confirmed", ["T001", "T010", "T011", "T012"], "a")]
    khop, sai = kt.khop_muc(gold, pred)  # chung 1/4 = 25% cả hai phía, dưới 34%
    assert khop == {} and sai == {}


# ---------------------------------------------------------------------------
# Kiểm tra từng trường
# ---------------------------------------------------------------------------


def test_sai_owner_va_han_truot():
    r = record_tot()
    r["items"][2]["owner"] = "Lan"
    r["items"][2]["deadline"] = "2026-10-18"
    kq = kt.kiem_thu_case(GOLD, r)
    assert [t.ket_qua for t in tim(kq, "G03", "owner")] == [TRUOT]
    assert [t.ket_qua for t in tim(kq, "G03", "hạn")] == [TRUOT]


def test_owner_so_khong_phan_biet_hoa_thuong_va_dau():
    r = record_tot()
    r["items"][2]["owner"] = "nam"
    assert tim(kt.kiem_thu_case(GOLD, r), "G03", "owner")[0].ket_qua == DAT


def test_han_none_phai_none():
    r = record_tot()
    r["items"][4]["deadline"] = "2026-10-21"
    assert tim(kt.kiem_thu_case(GOLD, r), "G05", "hạn")[0].ket_qua == TRUOT


def test_trang_thai_chap_nhan_nhieu_gia_tri_va_tuy_chon_chi_luu_y():
    r = record_tot()
    r["items"][1]["status"] = "rejected"      # nằm trong status_chap_nhan
    assert tim(kt.kiem_thu_case(GOLD, r), "G02", "trạng thái")[0].ket_qua == DAT
    r["items"][1]["status"] = "confirmed"     # sai, nhưng G02 là optional nên chỉ lưu ý
    assert tim(kt.kiem_thu_case(GOLD, r), "G02", "trạng thái")[0].ket_qua == LUU_Y


def test_thieu_muc_bat_buoc_truot_con_tuy_chon_bo_qua():
    r = record_tot()
    r["items"] = [i for i in r["items"] if i["item_id"] not in ("I001", "I002")]
    kq = kt.kiem_thu_case(GOLD, r)
    assert tim(kq, "G01", "mục")[0].ket_qua == TRUOT
    assert tim(kq, "G02", "mục")[0].ket_qua == BO_QUA
    assert tim(kq, "G01", "trạng thái") == []  # mục thiếu thì không kiểm tiếp trường


def test_sai_loai_duoc_bao_rieng():
    r = record_tot()
    r["items"][0]["type"] = "proposal"  # decision bị xếp thành proposal
    kq = kt.kiem_thu_case(GOLD, r)
    dong = tim(kq, "G01", "mục")[0]
    assert dong.ket_qua == TRUOT and "SAI LOẠI" in dong.ghi_chu and "proposal" in dong.thuc_te


def test_co_xem_lai_va_ly_do():
    r = record_tot()
    # G04 chấp nhận cả có cờ lẫn không cờ; không cờ thì không có lý do để so
    assert tim(kt.kiem_thu_case(GOLD, r), "G04", "cờ xem lại")[0].ket_qua == DAT
    assert tim(kt.kiem_thu_case(GOLD, r), "G04", "lý do cờ")[0].ket_qua == BO_QUA
    r["items"][3]["needs_review"] = True
    r["items"][3]["review_reasons"] = ["implicit_signal"]
    kq = kt.kiem_thu_case(GOLD, r)
    assert tim(kq, "G04", "lý do cờ")[0].ket_qua == DAT
    r["items"][3]["review_reasons"] = ["rule_conflict"]
    assert tim(kt.kiem_thu_case(GOLD, r), "G04", "lý do cờ")[0].ket_qua == TRUOT
    # G03 gold không cờ: dự đoán có cờ thì trượt
    r["items"][2]["needs_review"] = True
    r["items"][2]["review_reasons"] = ["rule_conflict"]
    assert tim(kt.kiem_thu_case(GOLD, r), "G03", "cờ xem lại")[0].ket_qua == TRUOT


def test_thay_the_dung_va_sai():
    assert tim(kt.kiem_thu_case(GOLD, record_tot()), "G05", "thay thế")[0].ket_qua == DAT
    r = record_tot()
    r["items"][4]["superseded_by"] = "I004"
    assert tim(kt.kiem_thu_case(GOLD, r), "G05", "thay thế")[0].ket_qua == TRUOT


def test_cung_luong():
    kq = kt.kiem_thu_case(GOLD, record_tot())
    assert tim(kq, "", "luồng")[0].ket_qua == DAT
    r = record_tot()
    r["items"][1]["thread_id"] = "TH2"
    assert tim(kt.kiem_thu_case(GOLD, r), "", "luồng")[0].ket_qua == TRUOT


# ---------------------------------------------------------------------------
# Điều cấm
# ---------------------------------------------------------------------------


def test_dieu_cam_quyet_dinh_a_da_chot():
    r = record_tot()
    r["items"].append(muc("I006", "decision", "confirmed", ["T002", "T003"], "Chốt A"))
    kq = kt.kiem_thu_case(GOLD, r)
    cam = tim(kq, nhom="điều cấm")
    assert cam[0].ket_qua == TRUOT and "I006" in cam[0].thuc_te
    assert cam[1].ket_qua == DAT and cam[2].ket_qua == DAT


def test_dieu_cam_khong_nham_quyet_dinh_dung_chi_trich_them_luot_a():
    r = record_tot()
    r["items"][0]["evidence"].append({"turn_id": "T002", "speaker": "x", "timestamp": "t", "quote": "q"})
    # quyết định B có trích thêm T002 (1/4 lượt) nên không bị coi là "quyết định A"
    assert tim(kt.kiem_thu_case(GOLD, r), nhom="điều cấm")[0].ket_qua == DAT


def test_dieu_cam_theo_owner_va_han_khong_can_luot_noi():
    r = record_tot()
    r["items"][3]["deadline"] = "2026-10-16"  # Lan bị gán hạn của Nam
    kq = kt.kiem_thu_case(GOLD, r)
    assert tim(kq, nhom="điều cấm")[2].ket_qua == TRUOT
    r2 = record_tot()
    r2["items"].append(muc("I009", "action", "confirmed", ["T001"], "Minh làm gì đó", owner="Minh"))
    assert tim(kt.kiem_thu_case(GOLD, r2), nhom="điều cấm")[1].ket_qua == TRUOT


def test_dieu_cam_theo_tu_khoa_summary():
    gold = {"meeting_id": "c", "items": [], "must_not_have": [
        {"type": "decision", "status": "confirmed", "summary_chua_mot_trong": ["Phương án A"], "turn_ids": []}]}
    rec = {"items": [muc("I1", "decision", "confirmed", ["T001"], "Chọn phương án a để làm")]}
    assert kt.kiem_thu_case(gold, rec).kiem_tra[0].ket_qua == TRUOT
    rec = {"items": [muc("I1", "decision", "confirmed", ["T001"], "Chọn cấu trúc dữ liệu")]}
    assert kt.kiem_thu_case(gold, rec).kiem_tra[0].ket_qua == DAT


# ---------------------------------------------------------------------------
# Cặp việc, mục thừa
# ---------------------------------------------------------------------------


def test_cap_viec_theo_nguong():
    kq_thap = kt.kiem_thu_case(GOLD, record_tot(), nguong_giong=0.1)
    kq_cao = kt.kiem_thu_case(GOLD, record_tot(), nguong_giong=0.9)
    cap_khac = lambda kq: tim(kq, nhom="cặp việc")[0]  # noqa: E731  G03/G04 phải KHÁC việc
    cap_cung = lambda kq: tim(kq, nhom="cặp việc")[1]  # noqa: E731  G05/G03 phải CÙNG việc
    assert cap_khac(kq_cao).ket_qua == DAT and cap_cung(kq_cao).ket_qua == TRUOT  # ngưỡng cao: bỏ sót cặp cùng việc
    assert cap_cung(kq_thap).ket_qua == DAT
    assert "độ giống" in cap_khac(kq_thap).thuc_te


def test_cap_viec_thieu_muc_thi_bo_qua():
    r = record_tot()
    r["items"] = [i for i in r["items"] if i["item_id"] != "I004"]
    assert tim(kt.kiem_thu_case(GOLD, r), nhom="cặp việc")[0].ket_qua == BO_QUA


def test_muc_thua_duoc_liet_ke_khong_tinh_loi():
    r = record_tot()
    r["items"].append(muc("I007", "issue", "open", ["T006"], "Một vướng mắc lạ"))
    kq = kt.kiem_thu_case(GOLD, r)
    assert [m["item_id"] for m in kq.muc_thua] == ["I007"]
    assert not [t for t in kq.kiem_tra if t.ket_qua == TRUOT]


# ---------------------------------------------------------------------------
# Đọc file, HTML, dòng lệnh
# ---------------------------------------------------------------------------


def _dung_thu_muc(tmp_path, co_run=True):
    gold_dir, runs_dir = tmp_path / "gold", tmp_path / "runs"
    (gold_dir / "case_x").mkdir(parents=True)
    (gold_dir / "case_y").mkdir()
    (gold_dir / "case_x" / "gold.json").write_text(json.dumps(GOLD), encoding="utf-8")
    g2 = copy.deepcopy(GOLD)
    g2["meeting_id"] = "case_y"
    (gold_dir / "case_y" / "gold.json").write_text(json.dumps(g2), encoding="utf-8")
    if co_run:
        (runs_dir / "case_x").mkdir(parents=True)
        (runs_dir / "case_x" / "s7_record.json").write_text(json.dumps(record_tot()), encoding="utf-8")
        (runs_dir / "case_x" / "s8_report.html").write_text("<html></html>", encoding="utf-8")
    else:
        runs_dir.mkdir()
    return gold_dir, runs_dir


def test_case_chua_co_ket_qua_va_record_hong(tmp_path):
    gold_dir, runs_dir = _dung_thu_muc(tmp_path)
    kq = kt.kiem_thu_mot_case("case_y", gold_dir, runs_dir, 0.5)
    assert not kq.co_ket_qua and "Chưa có" in kq.thong_bao
    (runs_dir / "case_y").mkdir()
    (runs_dir / "case_y" / "s7_record.json").write_text('{"khong_co_items": 1}', encoding="utf-8")
    kq = kt.kiem_thu_mot_case("case_y", gold_dir, runs_dir, 0.5)
    assert not kq.co_ket_qua and "Không đọc được" in kq.thong_bao


def test_html_co_noi_dung_va_escape(tmp_path):
    r = record_tot()
    r["items"][0]["summary"] = "<script>alert(1)</script>"
    kq = kt.kiem_thu_case(GOLD, r)
    html = kt.tao_html([kq, kt.KetQuaCase("case_y", co_ket_qua=False, thong_bao="Chưa có")], 0.5)
    assert "<script>alert" not in html and "&lt;script&gt;" in html
    assert "case_x" in html and "case_y" in html and "Chưa có" in html
    assert "Chỉ hiện dòng trượt" in html


def test_main_ghi_html_va_ma_thoat(tmp_path, capsys):
    gold_dir, runs_dir = _dung_thu_muc(tmp_path)
    ra = tmp_path / "bao_cao.html"
    ma = kt.main(["--gold-dir", str(gold_dir), "--runs-dir", str(runs_dir), "--ra", str(ra)])
    out = capsys.readouterr().out
    assert ma == 0 and ra.exists()
    assert "case_x: đạt" in out and "case_y: CHƯA CÓ KẾT QUẢ" in out
    html = ra.read_text(encoding="utf-8")
    assert "s8_report.html" in html  # có link sang báo cáo bước 8 của case_x


def test_main_mac_dinh_ghi_vao_runs_dir_va_loc_case(tmp_path):
    gold_dir, runs_dir = _dung_thu_muc(tmp_path)
    assert kt.main(["--gold-dir", str(gold_dir), "--runs-dir", str(runs_dir), "--case", "case_x"]) == 0
    html = (runs_dir / "bao_cao_kiem_thu.html").read_text(encoding="utf-8")
    assert "case_y" not in html


def test_main_thieu_gold_exit_2(tmp_path):
    assert kt.main(["--gold-dir", str(tmp_path / "khong_co")]) == 2
    gold_dir, runs_dir = _dung_thu_muc(tmp_path)
    assert kt.main(["--gold-dir", str(gold_dir), "--runs-dir", str(runs_dir), "--case", "case_z"]) == 2


def test_chay_goi_pipeline_cho_tung_case(tmp_path, monkeypatch):
    gold_dir, runs_dir = _dung_thu_muc(tmp_path, co_run=False)
    da_chay = []
    monkeypatch.setattr(kt, "chay_pipeline_cho_case", lambda ten, *a, **k: da_chay.append((ten, k)) or True)
    kt.main(["--gold-dir", str(gold_dir), "--runs-dir", str(runs_dir), "--chay", "--temperature", "0"])
    assert [t for t, _ in da_chay] == ["case_x", "case_y"]
    assert da_chay[0][1]["temperature"] == 0.0


def test_chay_pipeline_cho_case_thieu_sample(tmp_path, capsys):
    assert kt.chay_pipeline_cho_case("case_x", tmp_path / "samples", tmp_path / "runs") is False
    assert "BỎ QUA" in capsys.readouterr().out


def test_dieu_cam_co_owner_nhung_van_loc_theo_luot():
    # Việc của Nam đã bị thay (T003) mà còn confirmed là vi phạm; các việc khác của Nam thì không.
    r = record_tot()
    assert tim(kt.kiem_thu_case(GOLD, r), nhom="điều cấm")[3].ket_qua == DAT
    r["items"][4]["status"] = "confirmed"
    assert tim(kt.kiem_thu_case(GOLD, r), nhom="điều cấm")[3].ket_qua == TRUOT
