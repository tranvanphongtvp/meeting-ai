"""
kiem_thu_gold.py - Kiểm thử kết quả pipeline so với gold, in ra báo cáo HTML.

Vai trò: như giáo viên chấm bài từng câu. Mỗi cuộc họp mẫu có "đáp án" (gold.json) và "bài làm"
của pipeline (s7_record.json). File này đặt từng câu hỏi nhỏ ("việc của Nam có đúng hạn
không?", "có quyết định nào không được phép xuất hiện không?") và ghi đạt/trượt kèm kỳ vọng
và thực tế, để bạn thấy NGAY chỗ nào sai. Chưa tính điểm tổng hợp (precision/recall):
hàm đánh giá viết sau, dựa trên đúng các dòng kiểm tra này.

Cách dùng (từ thư mục gốc dự án):
    python eval/kiem_thu_gold.py                       # chỉ so các kết quả ĐÃ có trong data/runs
    python eval/kiem_thu_gold.py --chay                # chạy pipeline cho mọi case có sample trước (tốn LLM)
    python eval/kiem_thu_gold.py --chay --temperature 0
    python eval/kiem_thu_gold.py --case case1_dao_nguoc case3_de_xem_lai
    python eval/kiem_thu_gold.py --nguong-giong-nhau 0.6

Cách khớp mục gold với mục dự đoán:
    Theo LOẠI mục và các lượt nói làm bằng chứng (turn_id), KHÔNG theo item_id (id đổi mỗi lần chạy).
    Cặp hợp lệ khi cùng loại, có chung ít nhất một lượt, và các lượt chung chiếm từ 34% trở lên
    của một trong hai bên. Chọn cặp có độ trùng cao nhất trước (mỗi mục chỉ khớp một lần).

Kết quả mỗi dòng kiểm tra:
    dat      đúng như gold
    truot    sai so với gold (mục bắt buộc)
    luu_y    sai nhưng mục gold là tùy chọn (optional), chỉ để bạn xem
    bo_qua   không kiểm được (ví dụ mục tùy chọn không có, hoặc thiếu mục để so)
Mã thoát: 0 = đã ghi báo cáo (kể cả có dòng trượt), 2 = thiếu thư mục gold.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Optional

THU_MUC_GOC = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(THU_MUC_GOC / "src"))

from s6_verify import NGUONG_GIONG_MAC_DINH  # noqa: E402
from text_utils import chuan_hoa_giu_dau, do_giong  # noqa: E402

DAT, TRUOT, LUU_Y, BO_QUA = "dat", "truot", "luu_y", "bo_qua"
TEN_KET_QUA = {DAT: "Đạt", TRUOT: "Trượt", LUU_Y: "Lưu ý", BO_QUA: "Bỏ qua"}

# Ngưỡng ghép mục gold với mục dự đoán (xem docstring đầu file).
NGUONG_TRUNG_LUOT = 0.34


# ---------------------------------------------------------------------------
# Dữ liệu
# ---------------------------------------------------------------------------


@dataclass
class KiemTra:
    """Một dòng kiểm tra: một câu hỏi nhỏ và câu trả lời đạt/trượt."""

    gold_id: str          # mục gold liên quan ("" nếu là kiểm tra cấp cuộc họp)
    nhom: str             # mục, trạng thái, owner, hạn, cờ xem lại, thay thế, luồng, cấm, cặp
    ket_qua: str          # DAT | TRUOT | LUU_Y | BO_QUA
    ky_vong: str
    thuc_te: str
    ghi_chu: str = ""


@dataclass
class KetQuaCase:
    """Kết quả kiểm thử một cuộc họp."""

    ten_case: str
    muc_dich: str = ""
    co_ket_qua: bool = True               # False nếu chưa có s7_record.json
    thong_bao: str = ""                   # lý do khi không kiểm được
    kiem_tra: list[KiemTra] = field(default_factory=list)
    muc_thua: list[dict] = field(default_factory=list)   # mục dự đoán không khớp mục gold nào
    so_finding: dict[str, int] = field(default_factory=dict)  # đếm finding của bước 6
    co_html_bao_cao: bool = False         # có s8_report.html cạnh kết quả để dẫn link

    def dem(self) -> dict[str, int]:
        d = {DAT: 0, TRUOT: 0, LUU_Y: 0, BO_QUA: 0}
        for k in self.kiem_tra:
            d[k.ket_qua] += 1
        return d


# ---------------------------------------------------------------------------
# Khớp mục gold với mục dự đoán
# ---------------------------------------------------------------------------


def _tap_luot(muc: dict) -> set[str]:
    """Tập lượt nói làm bằng chứng của một mục (gold dùng turn_ids, dự đoán dùng evidence)."""
    if "turn_ids" in muc:
        return set(muc["turn_ids"])
    return {e["turn_id"] for e in muc.get("evidence", [])}


def _diem_trung(a: set[str], b: set[str]) -> Optional[float]:
    """Độ trùng Dice của hai tập lượt, hoặc None nếu không đủ điều kiện ghép."""
    chung = len(a & b)
    if not chung:
        return None
    if max(chung / len(a), chung / len(b)) < NGUONG_TRUNG_LUOT:
        return None
    return 2 * chung / (len(a) + len(b))


def khop_muc(gold_items: list[dict], pred_items: list[dict]) -> tuple[dict[str, int], dict[str, int]]:
    """Ghép mục gold với mục dự đoán.

    Trả về (khop, sai_loai):
      khop[gold_id] = chỉ số mục dự đoán cùng loại, trùng lượt nói
      sai_loai[gold_id] = chỉ số mục dự đoán trùng lượt nói nhưng KHÁC loại (để báo "sai loại")
    """
    khop: dict[str, int] = {}
    da_dung: set[int] = set()

    def _ghep(cung_loai: bool, ket_qua: dict[str, int]) -> None:
        cap = []
        for gi, g in enumerate(gold_items):
            if g["gold_id"] in khop or g["gold_id"] in ket_qua:
                continue
            for pi, p in enumerate(pred_items):
                if pi in da_dung or (p["type"] == g["type"]) != cung_loai:
                    continue
                diem = _diem_trung(_tap_luot(g), _tap_luot(p))
                if diem is not None:
                    # Mục bắt buộc được ưu tiên hơn mục tùy chọn khi độ trùng bằng nhau.
                    cap.append((-round(diem, 6), bool(g.get("optional")), gi, pi))
        for _, _, gi, pi in sorted(cap):
            gid = gold_items[gi]["gold_id"]
            if gid in khop or gid in ket_qua or pi in da_dung:
                continue
            ket_qua[gid] = pi
            da_dung.add(pi)

    _ghep(True, khop)
    sai_loai: dict[str, int] = {}
    _ghep(False, sai_loai)
    return khop, sai_loai


# ---------------------------------------------------------------------------
# Các phép kiểm tra
# ---------------------------------------------------------------------------


def _chuoi(x: Any) -> str:
    return "(không có)" if x is None or x == "" else str(x)


def _so_ten(a: Any, b: Any) -> bool:
    return chuan_hoa_giu_dau(str(a or "")) == chuan_hoa_giu_dau(str(b or ""))


def _vi_pham(cam: dict, p: dict) -> bool:
    """Mục dự đoán p có vi phạm một điều cấm (must_not_have) không. Các điều kiện cùng phải đúng."""
    if p["type"] != cam["type"]:
        return False
    if "status" in cam:
        ds = cam["status"] if isinstance(cam["status"], list) else [cam["status"]]
        if p["status"] not in ds:
            return False
    if "owner" in cam and not _so_ten(p.get("owner"), cam["owner"]):
        return False
    if "deadline" in cam and p.get("deadline") != cam["deadline"]:
        return False
    tu_khoa = cam.get("summary_chua_mot_trong")
    if tu_khoa and not any(chuan_hoa_giu_dau(k) in chuan_hoa_giu_dau(p["summary"]) for k in tu_khoa):
        return False
    # Điều kiện lượt nói (khi gold ghi turn_ids): phần lớn bằng chứng của mục dự đoán phải nằm trong
    # các lượt bị cấm. Nhờ vậy mục đúng chỉ trích thêm một lượt đó làm ngữ cảnh không bị bắt oan.
    # Gold để turn_ids rỗng nghĩa là áp cho mọi mục khớp các điều kiện còn lại.
    if cam.get("turn_ids"):
        luot = _tap_luot(p)
        if not luot or len(luot & set(cam["turn_ids"])) / len(luot) < 0.5:
            return False
    return True


def kiem_thu_case(gold: dict, record: dict, nguong_giong: float = NGUONG_GIONG_MAC_DINH) -> KetQuaCase:
    """So một s7_record (dict đọc từ JSON) với gold, trả về danh sách các dòng kiểm tra."""
    kq = KetQuaCase(ten_case=gold["meeting_id"], muc_dich=gold.get("muc_dich", ""))
    gold_items: list[dict] = gold["items"]
    preds: list[dict] = record["items"]
    khop, sai_loai = khop_muc(gold_items, preds)
    ds = kq.kiem_tra

    def them(g: Optional[dict], nhom: str, ok: bool, ky_vong: str, thuc_te: str, ghi_chu: str = "") -> None:
        tuy_chon = bool(g and g.get("optional"))
        ds.append(KiemTra(g["gold_id"] if g else "", nhom, DAT if ok else (LUU_Y if tuy_chon else TRUOT),
                          ky_vong, thuc_te, ghi_chu))

    for g in gold_items:
        gid, tuy_chon = g["gold_id"], bool(g.get("optional"))
        mo_ta = f"{g['type']}: {g['summary']}" if g.get("summary") else g["type"]

        # 1. Có mục khớp không.
        if gid in sai_loai:
            p = preds[sai_loai[gid]]
            ds.append(KiemTra(gid, "mục", LUU_Y if tuy_chon else TRUOT, f"loại {g['type']}",
                              f"loại {p['type']} ({p['item_id']}): {p['summary']}",
                              "Có mục trùng lượt nói nhưng SAI LOẠI. " + g.get("ghi_chu", "")))
            continue
        if gid not in khop:
            ds.append(KiemTra(gid, "mục", BO_QUA if tuy_chon else TRUOT, mo_ta,
                              "không có mục nào khớp các lượt " + ", ".join(g["turn_ids"]),
                              ("Mục tùy chọn nên không tính thiếu. " if tuy_chon else "") + g.get("ghi_chu", "")))
            continue
        p = preds[khop[gid]]
        ds.append(KiemTra(gid, "mục", DAT, mo_ta, f"{p['item_id']}: {p['summary']}", g.get("ghi_chu", "")))

        # 2. Trạng thái.
        chap_nhan = [g["status"]] + [s for s in g.get("status_chap_nhan", []) if s != g["status"]]
        them(g, "trạng thái", p["status"] in chap_nhan, " hoặc ".join(chap_nhan), p["status"])

        # 3. Người phụ trách và hạn (chỉ khi gold có ghi).
        if "owner" in g:
            them(g, "owner", _so_ten(p.get("owner"), g["owner"]), _chuoi(g["owner"]), _chuoi(p.get("owner")))
        if "deadline" in g:
            hop_le = [g["deadline"]] + list(g.get("deadline_chap_nhan", []))
            thuc_te = p.get("deadline")
            them(g, "hạn", thuc_te in hop_le, " hoặc ".join(_chuoi(x) for x in hop_le), _chuoi(thuc_te))

        # 4. Cờ xem lại và lý do cờ.
        co_hop_le = g.get("needs_review_chap_nhan") or [bool(g.get("needs_review"))]
        co_that = bool(p.get("needs_review"))
        nhan = lambda b: "gắn cờ" if b else "không cờ"  # noqa: E731
        them(g, "cờ xem lại", co_that in co_hop_le, " hoặc ".join(nhan(b) for b in co_hop_le),
             nhan(co_that) + (f" ({', '.join(p.get('review_reasons', []))})" if co_that else ""))
        if g.get("review_reasons"):
            if not co_that and False in co_hop_le:
                # Gold chấp nhận cả không cờ: không có cờ thì không có lý do để so.
                ds.append(KiemTra(gid, "lý do cờ", BO_QUA, ", ".join(g["review_reasons"]),
                                  "không gắn cờ (gold chấp nhận không cờ)"))
            else:
                thieu = [r for r in g["review_reasons"] if r not in p.get("review_reasons", [])]
                them(g, "lý do cờ", not thieu, ", ".join(g["review_reasons"]),
                     ", ".join(p.get("review_reasons", [])) or "(không có)")

        # 5. Quan hệ thay thế.
        dich = g.get("superseded_by")
        if dich:
            if dich not in khop:
                ds.append(KiemTra(gid, "thay thế", BO_QUA, f"bị thay bởi {dich}", "không kiểm được vì thiếu mục thay thế"))
            else:
                p_dich = preds[khop[dich]]
                them(g, "thay thế", p.get("superseded_by") == p_dich["item_id"],
                     f"bị thay bởi mục khớp {dich} ({p_dich['item_id']})", _chuoi(p.get("superseded_by")))

    # 6. Các mục phải cùng luồng.
    for nhom_id in gold.get("must_share_thread", []):
        if not all(i in khop for i in nhom_id):
            ds.append(KiemTra("", "luồng", BO_QUA, "cùng luồng: " + ", ".join(nhom_id), "thiếu mục để so"))
            continue
        luong = {preds[khop[i]]["thread_id"] for i in nhom_id}
        ds.append(KiemTra("", "luồng", DAT if len(luong) == 1 else TRUOT, "cùng luồng: " + ", ".join(nhom_id),
                          ", ".join(f"{i}→{preds[khop[i]]['thread_id']}" for i in nhom_id)))
    for nhom_id in gold.get("must_not_share_thread", []):
        if not all(i in khop for i in nhom_id):
            ds.append(KiemTra("", "luồng", BO_QUA, "khác luồng: " + ", ".join(nhom_id), "thiếu mục để so"))
            continue
        luong = {preds[khop[i]]["thread_id"] for i in nhom_id}
        ds.append(KiemTra("", "luồng", DAT if len(luong) == len(nhom_id) else TRUOT, "khác luồng: " + ", ".join(nhom_id),
                          ", ".join(f"{i}→{preds[khop[i]]['thread_id']}" for i in nhom_id)))

    # 7. Điều cấm (must_not_have): không mục dự đoán nào được vi phạm.
    for k, cam in enumerate(gold.get("must_not_have", []), start=1):
        vp = [p for p in preds if _vi_pham(cam, p)]
        dieu_kien = ", ".join(f"{a}={cam[a]}" for a in ("type", "status", "owner", "deadline") if a in cam)
        ds.append(KiemTra("", "điều cấm", TRUOT if vp else DAT, f"không có mục nào: {dieu_kien}",
                          "; ".join(f"{p['item_id']} ({p['status']}): {p['summary']}" for p in vp) or "không có",
                          cam.get("ly_do", "")))

    # 8. Cặp cùng việc/khác việc: kiểm ngưỡng độ giống tóm tắt hiện tại.
    for pl in gold.get("pair_labels", []):
        a, b = pl["items"]
        if a not in khop or b not in khop:
            ds.append(KiemTra("", "cặp việc", BO_QUA, f"{a} / {b}", "thiếu mục để so", pl.get("ghi_chu", "")))
            continue
        do = do_giong(preds[khop[a]]["summary"], preds[khop[b]]["summary"])
        coi_la_cung = do >= nguong_giong
        ds.append(KiemTra(
            "", "cặp việc", DAT if coi_la_cung == pl["same_task"] else TRUOT,
            f"{a} / {b}: {'cùng việc' if pl['same_task'] else 'khác việc'}",
            f"độ giống {do:.2f}, ngưỡng {nguong_giong} → coi là {'cùng việc' if coi_la_cung else 'khác việc'}",
            pl.get("ghi_chu", "")))

    # Mục dự đoán không khớp mục gold nào: chỉ liệt kê để xem, gold có thể chưa đủ.
    da_khop = set(khop.values()) | set(sai_loai.values())
    for pi, p in enumerate(preds):
        if pi not in da_khop:
            kq.muc_thua.append({"item_id": p["item_id"], "type": p["type"], "status": p["status"],
                                "summary": p["summary"], "owner": p.get("owner"),
                                "needs_review": p.get("needs_review", False)})

    for f in record.get("findings", []):
        kq.so_finding[f["severity"]] = kq.so_finding.get(f["severity"], 0) + 1
    return kq


# ---------------------------------------------------------------------------
# Đọc dữ liệu và chạy nhiều case
# ---------------------------------------------------------------------------


def _doc_json(duong_dan: Path) -> dict:
    return json.loads(duong_dan.read_text(encoding="utf-8-sig"))


def liet_ke_case(thu_muc_gold: Path) -> list[str]:
    """Tên các case có gold.json trong thu_muc_gold (theo thứ tự tên)."""
    return sorted(p.parent.name for p in thu_muc_gold.glob("*/gold.json"))


def kiem_thu_mot_case(ten_case: str, thu_muc_gold: Path, thu_muc_runs: Path, nguong_giong: float) -> KetQuaCase:
    """Đọc gold và kết quả của một case rồi kiểm thử; thiếu/hỏng file thì ghi rõ lý do."""
    gold = _doc_json(thu_muc_gold / ten_case / "gold.json")
    gold.setdefault("meeting_id", ten_case)
    file_record = thu_muc_runs / ten_case / "s7_record.json"
    if not file_record.exists():
        return KetQuaCase(ten_case, gold.get("muc_dich", ""), co_ket_qua=False,
                          thong_bao=f"Chưa có {file_record}. Chạy pipeline cho case này trước.")
    try:
        kq = kiem_thu_case(gold, _doc_json(file_record), nguong_giong)
    except (ValueError, KeyError, TypeError) as loi:
        return KetQuaCase(ten_case, gold.get("muc_dich", ""), co_ket_qua=False,
                          thong_bao=f"Không đọc được {file_record}: {type(loi).__name__}: {loi}")
    kq.co_html_bao_cao = any((thu_muc_runs / ten_case / t).exists() for t in ("s8_report.html",))
    return kq


def chay_pipeline_cho_case(ten_case: str, thu_muc_samples: Path, thu_muc_runs: Path, **tham_so) -> bool:
    """Chạy pipeline s1→s8 cho một case có trong data/samples. Trả về True nếu chạy xong không lỗi."""
    from pipeline import chay_pipeline  # nhập muộn: chỉ cần khi --chay

    thu_muc_sample = thu_muc_samples / ten_case
    if not thu_muc_sample.exists():
        print(f"BỎ QUA {ten_case}: không thấy {thu_muc_sample}")
        return False
    print(f"=== Chạy {ten_case} ===")
    ket_qua = chay_pipeline(thu_muc_sample, thu_muc_runs / ten_case, ghi=lambda s: print("  " + s), **tham_so)
    return ket_qua.ok


# ---------------------------------------------------------------------------
# Báo cáo HTML
# ---------------------------------------------------------------------------

CSS = """
:root{--bg:#fafaf7;--card:#fff;--text:#1f2328;--muted:#656d76;--line:#d8dce0;--accent:#2f5d8a;
--ok:#1a7f4b;--warn:#9a6700;--err:#b42318;--okbg:#e6f4ec;--warnbg:#fdf3d8;--errbg:#fde8e6;--neutralbg:#eef1f4}
@media (prefers-color-scheme: dark){:root{--bg:#16181c;--card:#1e2126;--text:#e6e8eb;--muted:#9aa3ad;--line:#343a42;
--accent:#7fb0e0;--ok:#5fd19a;--warn:#e3b341;--err:#ff8f85;--okbg:#17332a;--warnbg:#3a2f12;--errbg:#3d1c1a;--neutralbg:#262b31}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:20px 16px 48px}
h1{font-size:1.5rem;margin:0 0 4px}h2{font-size:1.2rem;margin:34px 0 8px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:1rem;margin:20px 0 6px}
.muted{color:var(--muted);font-size:.88rem}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:.88rem;background:var(--card)}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:var(--neutralbg)}
.badge{display:inline-block;border-radius:999px;padding:1px 9px;font-size:.78rem;white-space:nowrap}
.dat{background:var(--okbg);color:var(--ok)}.truot{background:var(--errbg);color:var(--err)}
.luu_y{background:var(--warnbg);color:var(--warn)}.bo_qua{background:var(--neutralbg);color:var(--muted)}
tr.r-truot td:first-child{border-left:4px solid var(--err)}tr.r-luu_y td:first-child{border-left:4px solid var(--warn)}
.hide-dat tr.r-dat,.hide-dat tr.r-bo_qua{display:none}
button{font:inherit;padding:4px 12px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--text);cursor:pointer}
.case-head{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:4px 0 8px}
.note{margin:6px 0;padding:8px 12px;background:var(--warnbg);color:var(--warn);border-radius:8px}
a{color:var(--accent)}
"""


def _e(x: Any) -> str:
    return escape(str(x))


def _huy_hieu(kq: str, so: Optional[int] = None) -> str:
    chu = TEN_KET_QUA[kq] + (f" {so}" if so is not None else "")
    return f'<span class="badge {kq}">{_e(chu)}</span>'


def _khoi_tom_tat(ket_qua: list[KetQuaCase]) -> str:
    hang = []
    for k in ket_qua:
        if not k.co_ket_qua:
            hang.append(f'<tr><td><a href="#{_e(k.ten_case)}">{_e(k.ten_case)}</a></td>'
                        f'<td colspan="5" class="muted">Chưa có kết quả để kiểm thử</td></tr>')
            continue
        d = k.dem()
        hang.append(
            f'<tr><td><a href="#{_e(k.ten_case)}">{_e(k.ten_case)}</a></td>'
            f"<td>{_huy_hieu(DAT, d[DAT])}</td><td>{_huy_hieu(TRUOT, d[TRUOT])}</td>"
            f"<td>{_huy_hieu(LUU_Y, d[LUU_Y])}</td><td>{_huy_hieu(BO_QUA, d[BO_QUA])}</td>"
            f"<td>{len(k.muc_thua)}</td></tr>"
        )
    return ('<div class="scroll"><table><tr><th>Case</th><th>Đạt</th><th>Trượt</th><th>Lưu ý</th><th>Bỏ qua</th>'
            "<th>Mục không có trong gold</th></tr>" + "".join(hang) + "</table></div>")


def _khoi_case(k: KetQuaCase, thu_muc_runs_tuong_doi: str) -> str:
    dau = f'<h2 id="{_e(k.ten_case)}">{_e(k.ten_case)}</h2>'
    if k.muc_dich:
        dau += f'<p class="muted">{_e(k.muc_dich)}</p>'
    if not k.co_ket_qua:
        return dau + f'<div class="note">{_e(k.thong_bao)}</div>'

    d = k.dem()
    lien_ket = ""
    if k.co_html_bao_cao:
        lien_ket = f'<a href="{_e(thu_muc_runs_tuong_doi)}/{_e(k.ten_case)}/s8_report.html">Mở báo cáo bước 8</a>'
    finding = ", ".join(f"{n} {_e(m)}" for m, n in sorted(k.so_finding.items())) or "không có"
    dau += (f'<div class="case-head">{_huy_hieu(DAT, d[DAT])}{_huy_hieu(TRUOT, d[TRUOT])}'
            f"{_huy_hieu(LUU_Y, d[LUU_Y])}{_huy_hieu(BO_QUA, d[BO_QUA])}"
            f'<span class="muted">Finding bước 6: {finding}</span>{lien_ket}</div>')

    hang = []
    for t in k.kiem_tra:
        ghi_chu = f'<div class="muted">{_e(t.ghi_chu)}</div>' if t.ghi_chu else ""
        hang.append(
            f'<tr class="r-{t.ket_qua}"><td>{_e(t.gold_id) or "·"}</td><td>{_e(t.nhom)}</td>'
            f"<td>{_huy_hieu(t.ket_qua)}</td><td>{_e(t.ky_vong)}</td><td>{_e(t.thuc_te)}{ghi_chu}</td></tr>"
        )
    bang = ('<div class="scroll"><table><tr><th>Gold</th><th>Kiểm tra</th><th>Kết quả</th><th>Kỳ vọng</th>'
            "<th>Thực tế</th></tr>" + "".join(hang) + "</table></div>")

    thua = ""
    if k.muc_thua:
        dong = "".join(
            f"<tr><td>{_e(m['item_id'])}</td><td>{_e(m['type'])}</td><td>{_e(m['status'])}</td>"
            f"<td>{_e(_chuoi(m['owner']))}</td><td>{_e(m['summary'])}</td></tr>" for m in k.muc_thua
        )
        thua = ("<h3>Mục dự đoán không khớp mục gold nào</h3>"
                '<p class="muted">Không tính là lỗi: gold có thể chưa liệt kê hết. Xem có phải mục bịa hay mục đúng mà gold bỏ sót.</p>'
                '<div class="scroll"><table><tr><th>Mục</th><th>Loại</th><th>Trạng thái</th><th>Owner</th><th>Tóm tắt</th></tr>'
                + dong + "</table></div>")
    return dau + bang + thua


def tao_html(ket_qua: list[KetQuaCase], nguong_giong: float, thu_muc_runs_tuong_doi: str = ".") -> str:
    """Dựng trang HTML báo cáo kiểm thử cho nhiều case."""
    tong = {DAT: 0, TRUOT: 0, LUU_Y: 0, BO_QUA: 0}
    for k in ket_qua:
        for t, n in k.dem().items():
            tong[t] += n
    return (
        '<!DOCTYPE html><html lang="vi"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>Báo cáo kiểm thử so với gold</title><style>{CSS}</style></head><body><main>"
        "<h1>Báo cáo kiểm thử so với gold</h1>"
        f'<p class="muted">Tạo lúc {_e(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))} · '
        f"ngưỡng độ giống dùng cho kiểm tra cặp việc: {_e(nguong_giong)} · "
        f"tổng: {_huy_hieu(DAT, tong[DAT])} {_huy_hieu(TRUOT, tong[TRUOT])} "
        f"{_huy_hieu(LUU_Y, tong[LUU_Y])} {_huy_hieu(BO_QUA, tong[BO_QUA])}</p>"
        '<p><button onclick="document.body.classList.toggle(\'hide-dat\')">Chỉ hiện dòng trượt / lưu ý</button></p>'
        f"{_khoi_tom_tat(ket_qua)}"
        + "".join(_khoi_case(k, thu_muc_runs_tuong_doi) for k in ket_qua)
        + "</main></body></html>"
    )


# ---------------------------------------------------------------------------
# Dòng lệnh
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Kiểm thử kết quả pipeline so với gold, ghi báo cáo HTML")
    parser.add_argument("--gold-dir", default=str(THU_MUC_GOC / "data" / "gold"), help="thư mục chứa <case>/gold.json")
    parser.add_argument("--runs-dir", default=str(THU_MUC_GOC / "data" / "runs"), help="thư mục chứa <case>/s7_record.json")
    parser.add_argument("--samples-dir", default=str(THU_MUC_GOC / "data" / "samples"),
                        help="thư mục chứa <case>/transcript.txt (chỉ dùng với --chay)")
    parser.add_argument("--case", nargs="+", help="chỉ kiểm các case này (mặc định: mọi case có gold)")
    parser.add_argument("--chay", action="store_true", help="chạy pipeline cho từng case trước (TỐN lượt gọi LLM)")
    parser.add_argument("--ra", help="đường dẫn file HTML (mặc định <runs-dir>/bao_cao_kiem_thu.html)")
    parser.add_argument("--nguong-giong-nhau", type=float, default=NGUONG_GIONG_MAC_DINH,
                        help="ngưỡng độ giống cho kiểm tra cặp việc, và cho pipeline nếu dùng --chay")
    parser.add_argument("--model", help="(với --chay) ghi đè tên mô hình")
    parser.add_argument("--temperature", type=float, help="(với --chay) nhiệt độ lấy mẫu")
    args = parser.parse_args(argv)

    thu_muc_gold, thu_muc_runs, thu_muc_samples = Path(args.gold_dir), Path(args.runs_dir), Path(args.samples_dir)
    if not thu_muc_gold.exists():
        print(f"LỖI: không thấy thư mục gold {thu_muc_gold}.")
        return 2
    ten_cases = args.case or liet_ke_case(thu_muc_gold)
    if not ten_cases:
        print(f"LỖI: không có gold.json nào trong {thu_muc_gold}.")
        return 2
    thieu = [c for c in ten_cases if not (thu_muc_gold / c / "gold.json").exists()]
    if thieu:
        print(f"LỖI: không có gold cho: {', '.join(thieu)}")
        return 2

    if args.chay:
        for c in ten_cases:
            chay_pipeline_cho_case(c, thu_muc_samples, thu_muc_runs, model=args.model,
                                   temperature=args.temperature, nguong_giong=args.nguong_giong_nhau)

    ket_qua = [kiem_thu_mot_case(c, thu_muc_gold, thu_muc_runs, args.nguong_giong_nhau) for c in ten_cases]

    file_html = Path(args.ra) if args.ra else thu_muc_runs / "bao_cao_kiem_thu.html"
    file_html.parent.mkdir(parents=True, exist_ok=True)
    try:
        tuong_doi = Path(thu_muc_runs).resolve().relative_to(file_html.parent.resolve()).as_posix()
    except ValueError:
        tuong_doi = thu_muc_runs.resolve().as_uri()
    file_html.write_text(tao_html(ket_qua, args.nguong_giong_nhau, tuong_doi), encoding="utf-8")

    for k in ket_qua:
        if not k.co_ket_qua:
            print(f"{k.ten_case}: CHƯA CÓ KẾT QUẢ")
        else:
            d = k.dem()
            print(f"{k.ten_case}: đạt {d[DAT]}, trượt {d[TRUOT]}, lưu ý {d[LUU_Y]}, bỏ qua {d[BO_QUA]}")
    print(f"Đã ghi báo cáo: {file_html}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
