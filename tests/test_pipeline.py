"""Test pipeline.py và run.py bằng LLM giả (không gọi mạng). Chạy: pytest tests/test_pipeline.py"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import run  # noqa: E402
from llm_client import KetQuaLLM  # noqa: E402
from pipeline import chay_pipeline  # noqa: E402

TRANSCRIPT = (
    "[00:01:00] Nam: Mình sẽ làm báo cáo doanh thu trước thứ Sáu.\n"
    "[00:02:00] Lan: Ok, chốt vậy nhé.\n"
)
MEETING = {
    "meeting_id": "case_test",
    "meeting_date": "2026-10-14",
    "title": "Họp thử",
    "participants": [
        {"name": "Nam", "aliases": [], "role": "Dev", "can_decide": False},
        {"name": "Lan", "aliases": [], "role": "Trưởng nhóm", "can_decide": True},
    ],
}
S2_JSON = {
    "events": [
        {"turn_id": "T001", "act": "assign", "topic_label": "báo cáo", "quote": "sẽ làm báo cáo doanh thu"},
        {"turn_id": "T002", "act": "confirm", "topic_label": "báo cáo", "quote": "chốt vậy nhé"},
    ]
}
S3_JSON = {
    "threads": [{"thread_id": "TH1", "topic": "Báo cáo doanh thu", "event_ids": ["E001", "E002"]}],
    "items": [
        {"item_id": "A1", "type": "action", "summary": "Làm báo cáo doanh thu", "thread_id": "TH1",
         "event_ids": ["E001", "E002"], "status": "confirmed", "owner": "Nam"}
    ],
}


class LLMGia:
    """Client giả: trả một chuỗi cố định, đếm số lần gọi."""

    model = "gia"

    def __init__(self, tra_ve):
        self.tra_ve = tra_ve
        self.so_lan = 0

    def generate_json(self, system_prompt, user_content):
        self.so_lan += 1
        text = self.tra_ve if isinstance(self.tra_ve, str) else json.dumps(self.tra_ve, ensure_ascii=False)
        return KetQuaLLM(text=text, model=self.model)


class LLMCam:
    """Client nổ ngay nếu bị gọi: dùng để chứng minh một lượt chạy KHÔNG gọi LLM."""

    model = "cam"

    def generate_json(self, *a, **k):
        raise AssertionError("Không được gọi LLM ở lượt chạy này")


@pytest.fixture
def cuoc_hop(tmp_path):
    thu_muc = tmp_path / "case_test"
    thu_muc.mkdir()
    (thu_muc / "transcript.txt").write_text(TRANSCRIPT, encoding="utf-8")
    (thu_muc / "meeting.json").write_text(json.dumps(MEETING), encoding="utf-8")
    return thu_muc


def _chay(cuoc_hop, ra, **kw):
    kw.setdefault("client_s2", LLMGia(S2_JSON))
    kw.setdefault("client_s3", LLMGia(S3_JSON))
    return chay_pipeline(cuoc_hop, ra, ghi=lambda s: None, **kw)


def test_chay_tron_1_den_8(cuoc_hop, tmp_path):
    ra = tmp_path / "run"
    kq = _chay(cuoc_hop, ra)
    assert kq.ok, kq.loi
    assert kq.buoc_da_chay == [1, 2, 3, 6, 7, 8]
    for ten in ("s1_turns.json", "s2_events.json", "s3_threads.json", "s6_verified.json",
                "s7_record.json", "s8_report.html", "run_info.json"):
        assert (ra / ten).exists(), ten
    assert "Làm báo cáo doanh thu" in (ra / "s8_report.html").read_text(encoding="utf-8")
    info = json.loads((ra / "run_info.json").read_text(encoding="utf-8"))
    assert info["ma_thoat"] == 0 and info["buoc_da_chay"] == [1, 2, 3, 6, 7, 8]


def test_dry_run_khong_goi_llm(cuoc_hop, tmp_path):
    ra = tmp_path / "run"
    kq = chay_pipeline(cuoc_hop, ra, dry_run=True, client_s2=LLMCam(), client_s3=LLMCam(), ghi=lambda s: None)
    assert kq.ok
    assert (ra / "s2_prompt.txt").exists() and not (ra / "s2_events.json").exists()
    assert kq.buoc_da_chay == [1, 2]


def test_chay_lai_tu_buoc_6_khong_goi_llm(cuoc_hop, tmp_path):
    ra = tmp_path / "run"
    assert _chay(cuoc_hop, ra).ok
    for ten in ("s6_verified.json", "s7_record.json", "s8_report.html"):
        (ra / ten).unlink()
    kq = chay_pipeline(None, ra, tu_buoc=6, client_s2=LLMCam(), client_s3=LLMCam(), ghi=lambda s: None)
    assert kq.ok and kq.buoc_da_chay == [6, 7, 8]
    assert (ra / "s8_report.html").exists()


def test_den_buoc_dung_som(cuoc_hop, tmp_path):
    ra = tmp_path / "run"
    kq = _chay(cuoc_hop, ra, den_buoc=2)
    assert kq.buoc_da_chay == [1, 2] and not (ra / "s3_threads.json").exists()


def test_ten_file_html_index(cuoc_hop, tmp_path):
    ra = tmp_path / "run"
    assert _chay(cuoc_hop, ra, ten_file_html="index.html").ok
    assert (ra / "index.html").exists() and not (ra / "s8_report.html").exists()


def test_thieu_thu_muc_cuoc_hop_exit_2(tmp_path):
    kq = chay_pipeline(tmp_path / "khong_co", tmp_path / "run", ghi=lambda s: None)
    assert kq.ma_thoat == 2


def test_chay_lai_thieu_file_exit_2(tmp_path):
    kq = chay_pipeline(None, tmp_path / "run_rong", tu_buoc=6, ghi=lambda s: None)
    assert kq.ma_thoat == 2 and "bước" in kq.loi[0]


def test_buoc_khong_hop_le_exit_2(tmp_path):
    assert chay_pipeline(None, tmp_path, tu_buoc=4, ghi=lambda s: None).ma_thoat == 2
    assert chay_pipeline(None, tmp_path, tu_buoc=7, den_buoc=3, ghi=lambda s: None).ma_thoat == 2


def test_s1_loi_dung_ngay_exit_1(cuoc_hop, tmp_path):
    (cuoc_hop / "transcript.txt").write_text("[00:01:00] sai dinh dang khong co dau hai cham\n", encoding="utf-8")
    ra = tmp_path / "run"
    kq = _chay(cuoc_hop, ra)
    assert kq.ma_thoat == 1 and kq.buoc_da_chay == []
    assert (ra / "s1_turns.json").exists() and not (ra / "s2_events.json").exists()


def test_llm_tra_rac_dung_o_buoc_2_exit_1(cuoc_hop, tmp_path):
    ra = tmp_path / "run"
    kq = _chay(cuoc_hop, ra, client_s2=LLMGia("khong phai json"))
    assert kq.ma_thoat == 1 and "Bước 2" in kq.loi[0]
    assert not (ra / "s3_threads.json").exists()


def test_s3_khong_lap_duoc_muc_nao_exit_1(cuoc_hop, tmp_path):
    kq = _chay(cuoc_hop, tmp_path / "run", client_s3=LLMGia({"threads": [], "items": [{"item_id": "X"}]}))
    assert kq.ma_thoat == 1 and "Bước 3" in kq.loi[0]


def test_file_ket_qua_cu_sai_dinh_dang_exit_1(cuoc_hop, tmp_path):
    ra = tmp_path / "run"
    assert _chay(cuoc_hop, ra).ok
    (ra / "s3_threads.json").write_text('{"threads": 5}', encoding="utf-8")
    kq = chay_pipeline(None, ra, tu_buoc=6, ghi=lambda s: None)
    assert kq.ma_thoat == 1


# ---------------------------------------------------------------------------
# run.py
# ---------------------------------------------------------------------------


def test_run_duong_dan_mac_dinh_va_tu_buoc():
    hop, ra = run.xac_dinh_duong_dan("../data/case0_test", None, 1)
    assert hop == Path("../data/case0_test") and ra == run.THU_MUC_RUN_MAC_DINH / "case0_test"
    hop, ra = run.xac_dinh_duong_dan("x/runs/case0", None, 6)
    assert hop is None and ra == Path("x/runs/case0")
    hop, ra = run.xac_dinh_duong_dan("../data/case0_test", "tuy_chon", 1)
    assert ra == Path("tuy_chon")


def test_run_tu_buoc_lon_hon_den_buoc_exit_2(tmp_path):
    assert run.main([str(tmp_path), "--tu-buoc", "6", "--den-buoc", "2"]) == 2


def test_run_main_dry_run(cuoc_hop, tmp_path):
    ra = tmp_path / "ra"
    assert run.main([str(cuoc_hop), "--ra", str(ra), "--dry-run"]) == 0
    assert (ra / "s2_prompt.txt").exists()