"""
deadline_utils.py - Quy đổi hạn chót tương đối bằng tiếng Việt ra ngày cụ thể.

Dùng ở bước 3 (lập mục Action) và có thể dùng lại ở bước 6 (kiểm chứng).

Nguyên tắc: CHỈ quy đổi những cách nói không mơ hồ. Gặp cách nói mơ hồ hoặc chưa
hỗ trợ thì trả None (người gọi sẽ gắn cờ deadline_invalid), KHÔNG đoán.

Các dạng được hỗ trợ (so khớp không phân biệt dấu, hoa thường):
- hôm nay, ngày mai, ngày kia
- N ngày nữa/tới/sau, N tuần nữa/tới/sau
- thứ Hai..thứ Bảy, chủ nhật (hoặc "thứ 2".."thứ 7"), kèm tuỳ chọn:
    (không kèm), "tới", "sau"  -> lần xuất hiện tiếp theo SAU ngày họp
    "này", "tuần này"          -> trong tuần chứa ngày họp (tuần bắt đầu thứ Hai)
    "tuần sau", "tuần tới"     -> trong tuần kế tiếp
  Riêng trường hợp "thứ X" trần trùng đúng thứ của ngày họp thì mơ hồ -> None.
- dd/mm, dd/mm/yyyy, "ngày dd tháng mm [năm yyyy]": không ghi năm thì lấy năm của
  ngày họp; kết quả sớm hơn ngày họp thì -> None.
- cuối tháng, cuối tháng này, cuối tháng sau/tới.
Không hỗ trợ (trả None): "tuần sau" trần, "cuối tuần", "sớm", "càng sớm càng tốt"...
"""

import calendar
import re
from datetime import date, timedelta
from typing import Optional

from s1_preprocess import chuan_hoa_ten

# Số thứ trong tuần theo chuẩn Python: thứ Hai = 0 ... Chủ nhật = 6.
_THU = {
    "thu hai": 0, "thu ba": 1, "thu tu": 2, "thu nam": 3, "thu sau": 4, "thu bay": 5,
    "chu nhat": 6,
    "thu 2": 0, "thu 3": 1, "thu 4": 2, "thu 5": 3, "thu 6": 4, "thu 7": 5,
}
_DS_THU = "|".join(re.escape(k) for k in sorted(_THU, key=len, reverse=True))
_MAU_THU = re.compile(rf"\b({_DS_THU})\b(?:\s+(tuan nay|tuan sau|tuan toi|nay|toi|sau))?")
_MAU_NGAY_THANG_GACH = re.compile(
    r"(?:\bngay\s+)?\b(\d{1,2})\s*[/\-.]\s*(\d{1,2})(?:\s*[/\-.]\s*(\d{2,4}))?\b"
)
_MAU_NGAY_THANG_CHU = re.compile(r"\bngay\s+(\d{1,2})\s+thang\s+(\d{1,2})(?:\s+nam\s+(\d{4}))?\b")
_MAU_SO_NGAY_TUAN = re.compile(r"\b(\d{1,3})\s*(ngay|tuan)\s*(?:nua|toi|sau)\b")
_MAU_CUOI_THANG = re.compile(r"\bcuoi thang(?:\s+(nay|sau|toi))?\b")


def _tao_ngay(ngay: int, thang: int, nam: int, ngay_hop: date) -> Optional[date]:
    """Tạo ngày hợp lệ và không sớm hơn ngày họp, ngược lại trả None."""
    try:
        kq = date(nam, thang, ngay)
    except ValueError:
        return None
    return kq if kq >= ngay_hop else None


def quy_doi_han_chot(han_chot: str, ngay_hop: date) -> Optional[date]:
    """Quy đổi cụm từ chỉ hạn chót ra ngày cụ thể, hoặc None nếu mơ hồ/chưa hỗ trợ."""
    t = chuan_hoa_ten(han_chot).replace(",", " ").replace(";", " ")
    t = " ".join(t.split())
    if not t:
        return None

    # 1. Ngày tháng cụ thể.
    khop = _MAU_NGAY_THANG_CHU.search(t) or _MAU_NGAY_THANG_GACH.search(t)
    if khop:
        ngay, thang, nam = khop.group(1), khop.group(2), khop.group(3)
        if nam is None:
            nam_so = ngay_hop.year
        else:
            nam_so = int(nam) + (2000 if len(nam) == 2 else 0)
        return _tao_ngay(int(ngay), int(thang), nam_so, ngay_hop)

    # 2. Hôm nay / ngày mai / ngày kia.
    if re.search(r"\bhom nay\b", t):
        return ngay_hop
    if re.search(r"\bngay mai\b", t) or t == "mai":
        return ngay_hop + timedelta(days=1)
    if re.search(r"\bngay kia\b", t):
        return ngay_hop + timedelta(days=2)

    # 3. N ngày/tuần nữa.
    khop = _MAU_SO_NGAY_TUAN.search(t)
    if khop:
        so = int(khop.group(1))
        return ngay_hop + timedelta(days=so * (7 if khop.group(2) == "tuan" else 1))

    # 4. Thứ trong tuần.
    khop = _MAU_THU.search(t)
    if khop:
        thu = _THU[khop.group(1)]
        hau_to = khop.group(2)
        thu_hai_tuan_nay = ngay_hop - timedelta(days=ngay_hop.weekday())
        if hau_to in ("nay", "tuan nay"):
            kq = thu_hai_tuan_nay + timedelta(days=thu)
            return kq if kq >= ngay_hop else None
        if hau_to in ("tuan sau", "tuan toi"):
            return thu_hai_tuan_nay + timedelta(days=7 + thu)
        # Không hậu tố, hoặc "tới"/"sau": lần xuất hiện tiếp theo sau ngày họp.
        cach = (thu - ngay_hop.weekday()) % 7
        if cach == 0:
            if hau_to is None:
                return None  # cùng thứ với ngày họp: "hôm nay" hay "tuần sau" thì không rõ
            cach = 7
        return ngay_hop + timedelta(days=cach)

    # 5. Cuối tháng.
    khop = _MAU_CUOI_THANG.search(t)
    if khop:
        nam, thang = ngay_hop.year, ngay_hop.month
        if khop.group(1) in ("sau", "toi"):
            thang += 1
            if thang > 12:
                nam, thang = nam + 1, 1
        return date(nam, thang, calendar.monthrange(nam, thang)[1])

    return None