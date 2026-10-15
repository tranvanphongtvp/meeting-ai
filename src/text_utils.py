"""Hàm xử lý chuỗi dùng chung cho bước kiểm chứng (bước 6).

Ví dụ đời thường: như hai cách so chữ ký. Cách chặt đòi đúng từng nét (giữ dấu tiếng
Việt); cách lỏng chỉ đòi giống dáng (bỏ dấu). Khớp chặt là chắc chắn đúng; chỉ khớp
lỏng thì đáng nghi LLM đã đổi dấu.
"""

import re
import unicodedata

from s1_preprocess import chuan_hoa_ten


def chuan_hoa_giu_dau(s: str) -> str:
    """Chuẩn hoá NFC, thường hoá, bỏ dấu câu, gộp khoảng trắng. GIỮ dấu thanh tiếng Việt.

    NFC trước để chuỗi gõ kiểu tổ hợp (NFD) và dựng sẵn (NFC) cho cùng kết quả.
    """
    s = unicodedata.normalize("NFC", s).lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def chuan_hoa_bo_dau(s: str) -> str:
    """Như chuan_hoa_giu_dau nhưng bỏ cả dấu thanh/mũ (dùng chuan_hoa_ten của s1)."""
    s = chuan_hoa_ten(s)
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def do_giong(a: str, b: str) -> float:
    """Độ giống 0..1 giữa hai câu: Jaccard trên tập từ đã bỏ dấu. Rỗng thì 0.0.

    Chỉ là xấp xỉ rẻ, không hiểu nghĩa. Ngưỡng dùng nó phải chỉnh bằng dữ liệu thật.
    """
    ta, tb = set(chuan_hoa_bo_dau(a).split()), set(chuan_hoa_bo_dau(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)