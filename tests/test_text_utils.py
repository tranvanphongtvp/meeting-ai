"""test_text_utils.py - Kiểm thử hàm chuỗi dùng cho bước 6. Không gọi mạng.

Chạy: cd src && python ../tests/test_text_utils.py
"""

import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from text_utils import chuan_hoa_bo_dau, chuan_hoa_giu_dau, do_giong  # noqa: E402
from schemas import Finding, FindingKind, FindingSeverity, ReviewReason  # noqa: E402


def test_giu_dau_nfd_va_nfc_cung_ket_qua():
    nfc = unicodedata.normalize("NFC", "Chốt phương án B")
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd and chuan_hoa_giu_dau(nfc) == chuan_hoa_giu_dau(nfd) == "chốt phương án b"


def test_giu_dau_phan_biet_dau_thanh():
    assert chuan_hoa_giu_dau("ma") != chuan_hoa_giu_dau("má")


def test_giu_dau_bo_dau_cau_va_gop_khoang_trang():
    assert chuan_hoa_giu_dau("  Ok,  chốt   nhé! ") == "ok chốt nhé"


def test_bo_dau_gop_cac_dau_va_chu_d():
    assert chuan_hoa_bo_dau("Đặt máy, Á!") == "dat may a"


def test_do_giong_cac_moc():
    assert do_giong("làm báo cáo", "Làm báo cáo!") == 1.0
    assert do_giong("làm báo cáo", "gửi hợp đồng") == 0.0
    assert do_giong("", "x") == 0.0 and do_giong("", "") == 0.0
    assert 0.0 < do_giong("làm báo cáo tuần", "làm báo cáo tháng") < 1.0


def test_do_giong_doi_xung_va_bo_dau():
    assert do_giong("gửi báo cáo", "gui bao cao") == 1.0
    assert do_giong("a b c", "b c d") == do_giong("b c d", "a b c") == 0.5


def test_enum_moi_cua_schema():
    assert ReviewReason("contradiction") and ReviewReason("invalid_reference")
    f = Finding(finding_id="F001", severity=FindingSeverity.ERROR,
                kind=FindingKind.OWNER_CONFLICT, message="x", item_ids=["I001", "I002"])
    assert f.event_ids == [] and f.thread_ids == []


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