"""
pipeline.py - Nối các bước 1-8 thành một lượt chạy.

Vai trò: như người điều phối dây chuyền. Mỗi bước (s1...s8) đã tự làm xong việc của nó và tự
ghi file ra thư mục run; file này chỉ gọi đúng thứ tự, kiểm tra bước trước có dùng được
không rồi mới sang bước sau, và dừng sớm kèm lý do rõ ràng khi có lỗi.

Các bước và file ghi ra thư mục run:
    1  Tiền xử lý [code]            -> s1_turns.json
    2  Trích xuất hành động [LLM]   -> s2_events.json, s2_raw_llm.json
    3  Phân luồng, lập mục [LLM]    -> s3_threads.json, s3_raw_llm.json
    6  Kiểm chứng [code]            -> s6_verified.json
    7  Ghép bản ghi [code]          -> s7_record.json
    8  Báo cáo HTML [code]          -> s8_report.html (hoặc index.html)
(Các số 4, 5 là luật trạng thái và đối chiếu thời gian, đã nằm trong bước 3 nên không có bước riêng.)
Ngoài ra pipeline ghi run_info.json: bước nào đã chạy, mất bao lâu, mức dùng LLM.

Chạy lại từ giữa chừng: tu_buoc > 1 thì các bước trước được ĐỌC LẠI từ file trong thư mục run
(không gọi lại LLM). Ví dụ chỉ chỉnh bước 6 thì chạy lại từ bước 6, không tốn lượt gọi LLM.

Mã thoát (ma_thoat) khớp các bước riêng: 0 = xong, 1 = một bước báo lỗi, 2 = thiếu file/cấu hình.
Gọi từ dòng lệnh qua run.py.
"""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from pydantic import ValidationError

import s1_preprocess
import s2_extract_acts
import s3_resolve
import s6_verify
import s7_assemble
import s8_report
from llm_client import GeminiClient, LoiCauHinh
from s1_preprocess import KetQuaTienXuLy
from s2_extract_acts import KetQuaTrichXuat
from s3_resolve import KetQuaPhanGiai
from s6_verify import KetQuaKiemChung
from schemas import MeetingRecord

# Thứ tự chạy. Số bước giữ nguyên như tài liệu thiết kế (4, 5 đã gộp vào bước 3).
THU_TU_BUOC: tuple[int, ...] = (1, 2, 3, 6, 7, 8)

TEN_BUOC: dict[int, str] = {
    1: "Tiền xử lý transcript",
    2: "Trích xuất hành động lời nói (LLM)",
    3: "Phân luồng và lập mục (LLM)",
    6: "Kiểm chứng",
    7: "Ghép bản ghi",
    8: "Báo cáo HTML",
}

# Mỗi bước cần kết quả của những bước nào (đọc từ file khi chạy lại từ giữa chừng).
CAN_DAU_VAO: dict[int, tuple[str, ...]] = {
    1: (),
    2: ("s1",),
    3: ("s1", "s2"),
    6: ("s1", "s2", "s3"),
    7: ("s1", "s6"),
    8: ("s7",),
}

# Tên file kết quả và lớp để đọc lại; kèm bước cần chạy nếu thiếu file.
FILE_KET_QUA: dict[str, tuple[str, type, int]] = {
    "s1": ("s1_turns.json", KetQuaTienXuLy, 1),
    "s2": ("s2_events.json", KetQuaTrichXuat, 2),
    "s3": ("s3_threads.json", KetQuaPhanGiai, 3),
    "s6": ("s6_verified.json", KetQuaKiemChung, 6),
    "s7": ("s7_record.json", MeetingRecord, 7),
}

# Số cảnh báo/finding tối đa in ra màn hình (toàn bộ vẫn nằm trong file).
TOI_DA_DONG_IN = 10


class _ThieuFile(Exception):
    """Thiếu file kết quả của một bước trước khi chạy lại từ giữa chừng."""


@dataclass
class KetQuaPipeline:
    """Kết quả một lượt chạy pipeline."""

    thu_muc_run: Path
    ma_thoat: int = 0
    buoc_da_chay: list[int] = field(default_factory=list)
    loi: list[str] = field(default_factory=list)
    file_ra: dict[int, Path] = field(default_factory=dict)
    giay: dict[int, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.ma_thoat == 0


def _in_gioi_han(ghi: Callable[[str], None], tieu_dau: str, ds: list[str]) -> None:
    """In tối đa TOI_DA_DONG_IN dòng, phần còn lại chỉ báo số lượng."""
    for d in ds[:TOI_DA_DONG_IN]:
        ghi(f"  {tieu_dau}: {d}")
    if len(ds) > TOI_DA_DONG_IN:
        ghi(f"  ... và {len(ds) - TOI_DA_DONG_IN} {tieu_dau.lower()} khác (xem trong file kết quả).")


def chay_pipeline(
    thu_muc_cuoc_hop: Optional[str | Path],
    thu_muc_run: str | Path,
    tu_buoc: int = 1,
    den_buoc: int = 8,
    dry_run: bool = False,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    nguong_giong: float = s6_verify.NGUONG_GIONG_MAC_DINH,
    gioi_han_ky_tu: Optional[int] = None,
    ten_file_html: str = "s8_report.html",
    ghi: Callable[[str], None] = print,
    client_s2=None,
    client_s3=None,
) -> KetQuaPipeline:
    """Chạy các bước từ `tu_buoc` đến `den_buoc` (đều thuộc THU_TU_BUOC).

    thu_muc_cuoc_hop: thư mục có transcript.txt và meeting.json (chỉ cần khi tu_buoc = 1).
    dry_run: chạy bước 1, rồi chỉ ghi prompt của bước LLM đầu tiên sẽ chạy và DỪNG (không gọi LLM).
    client_s2, client_s3: truyền client có sẵn (dùng khi kiểm thử); bỏ trống thì tự tạo GeminiClient.
    ghi: hàm in tiến trình (mặc định print), truyền hàm khác để bắt thông báo.
    """
    kq = KetQuaPipeline(thu_muc_run=Path(thu_muc_run))
    thu_muc_run = kq.thu_muc_run
    if tu_buoc not in THU_TU_BUOC or den_buoc not in THU_TU_BUOC or tu_buoc > den_buoc:
        kq.ma_thoat = 2
        kq.loi.append(f"tu_buoc/den_buoc không hợp lệ: {tu_buoc}-{den_buoc} (chọn trong {list(THU_TU_BUOC)}).")
        return kq
    if tu_buoc == 1 and thu_muc_cuoc_hop is None:
        kq.ma_thoat = 2
        kq.loi.append("Bước 1 cần thư mục cuộc họp (có transcript.txt và meeting.json).")
        return kq

    ket_qua: dict[str, object] = {}  # kết quả các bước đã có trong bộ nhớ
    thong_tin_llm: dict[str, dict] = {}

    def lay(ten: str):
        """Lấy kết quả của một bước: trong bộ nhớ nếu vừa chạy, không thì đọc file trong thư mục run."""
        if ten not in ket_qua:
            ten_file, lop, so_buoc = FILE_KET_QUA[ten]
            duong_dan = thu_muc_run / ten_file
            if not duong_dan.exists():
                raise _ThieuFile(f"Thiếu {duong_dan}. Chạy bước {so_buoc} ({TEN_BUOC[so_buoc]}) trước.")
            ket_qua[ten] = lop.model_validate_json(duong_dan.read_text(encoding="utf-8"))
        return ket_qua[ten]

    def loi_buoc(so_buoc: int, noi_dung: list[str]) -> KetQuaPipeline:
        kq.ma_thoat = 1
        kq.loi += [f"Bước {so_buoc}: {n}" for n in noi_dung]
        ghi(f"DỪNG ở bước {so_buoc} vì lỗi:")
        for n in noi_dung[:TOI_DA_DONG_IN]:
            ghi(f"  - {n}")
        return ghi_run_info()

    def ghi_run_info() -> KetQuaPipeline:
        """Ghi run_info.json (best-effort: lỗi ghi file không làm hỏng lượt chạy)."""
        if not thu_muc_run.exists() and not kq.file_ra:
            return kq  # chưa có gì được ghi: không tạo thư mục run rỗng chỉ để ghi run_info
        try:
            thu_muc_run.mkdir(parents=True, exist_ok=True)
            (thu_muc_run / "run_info.json").write_text(
                json.dumps(
                    {
                        "ma_thoat": kq.ma_thoat,
                        "buoc_da_chay": kq.buoc_da_chay,
                        "giay": {str(k): round(v, 2) for k, v in kq.giay.items()},
                        "su_dung_llm": thong_tin_llm,
                        "loi": kq.loi,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass
        return kq

    for so_buoc in THU_TU_BUOC:
        if so_buoc < tu_buoc:
            continue
        if so_buoc > den_buoc:
            break
        ghi(f"[Bước {so_buoc}] {TEN_BUOC[so_buoc]} ...")
        bat_dau = time.perf_counter()
        try:
            # ---------------- Bước 1 ----------------
            if so_buoc == 1:
                noi_dung, meeting = s1_preprocess.doc_cuoc_hop(thu_muc_cuoc_hop)
                s1 = s1_preprocess.tien_xu_ly(noi_dung, meeting, gioi_han_ky_tu=gioi_han_ky_tu)
                kq.file_ra[1] = s1_preprocess.luu_ket_qua(s1, thu_muc_run)
                ket_qua["s1"] = s1
                ghi(f"  {s1.thong_ke}")
                _in_gioi_han(ghi, "Cảnh báo", s1.canh_bao)
                if not s1.ok:
                    return loi_buoc(1, s1.loi)

            # ---------------- Bước 2 ----------------
            elif so_buoc == 2:
                s1 = lay("s1")
                system_prompt = s2_extract_acts.FILE_PROMPT.read_text(encoding="utf-8")
                if dry_run:
                    duong_dan = thu_muc_run / "s2_prompt.txt"
                    duong_dan.write_text(
                        "=== SYSTEM PROMPT ===\n" + system_prompt + "\n\n=== NỘI DUNG GỬI ===\n"
                        + s2_extract_acts.xay_dung_noi_dung_nguoi_dung(s1),
                        encoding="utf-8",
                    )
                    ghi(f"Dry-run: KHÔNG gọi LLM. Đã ghi prompt bước 2 để bạn kiểm tra: {duong_dan}")
                    kq.buoc_da_chay.append(so_buoc)
                    return ghi_run_info()
                client = client_s2 or GeminiClient(model=model, temperature=temperature)
                ghi(f"  Đang gọi mô hình '{getattr(client, 'model', '?')}' ...")
                s2, nhat_ky = s2_extract_acts.trich_xuat(s1, client, system_prompt)
                kq.file_ra[2] = s2_extract_acts.luu_ket_qua(s2, nhat_ky, thu_muc_run)
                ket_qua["s2"] = s2
                thong_tin_llm["s2"] = s2.su_dung_llm
                ghi(f"  {s2.thong_ke}")
                _in_gioi_han(ghi, "Cảnh báo", s2.canh_bao)
                if not s2.ok:
                    return loi_buoc(2, s2.loi)
                if not s2.events:
                    return loi_buoc(2, ["không có sự kiện nào. Xem s2_raw_llm.json và chạy lại bước 2."])

            # ---------------- Bước 3 ----------------
            elif so_buoc == 3:
                s1, s2 = lay("s1"), lay("s2")
                if not s2.ok or not s2.events:
                    return loi_buoc(3, ["s2_events.json không dùng được (có lỗi hoặc không có sự kiện); chạy lại bước 2."])
                system_prompt = s3_resolve.FILE_PROMPT.read_text(encoding="utf-8")
                if dry_run:
                    duong_dan = thu_muc_run / "s3_prompt.txt"
                    duong_dan.write_text(
                        "=== SYSTEM PROMPT ===\n" + system_prompt + "\n\n=== NỘI DUNG GỬI ===\n"
                        + s3_resolve.xay_dung_noi_dung_nguoi_dung(s1, s2),
                        encoding="utf-8",
                    )
                    ghi(f"Dry-run: KHÔNG gọi LLM. Đã ghi prompt bước 3 để bạn kiểm tra: {duong_dan}")
                    kq.buoc_da_chay.append(so_buoc)
                    return ghi_run_info()
                # Giống s3 chạy riêng: --model > GEMINI_MODEL_RESOLVE > GEMINI_MODEL (do GeminiClient xử lý).
                model_s3 = model or os.environ.get("GEMINI_MODEL_RESOLVE") or None
                client = client_s3 or GeminiClient(model=model_s3, temperature=temperature)
                ghi(f"  Đang gọi mô hình '{getattr(client, 'model', '?')}' ...")
                s3, nhat_ky = s3_resolve.phan_giai(s1, s2, client, system_prompt)
                kq.file_ra[3] = s3_resolve.luu_ket_qua(s3, nhat_ky, thu_muc_run)
                ket_qua["s3"] = s3
                thong_tin_llm["s3"] = s3.su_dung_llm
                ghi(f"  {s3.thong_ke}  theo loại: {s3.theo_loai}")
                _in_gioi_han(ghi, "Cảnh báo", s3.canh_bao)
                if not s3.ok:
                    return loi_buoc(3, s3.loi)

            # ---------------- Bước 6 ----------------
            elif so_buoc == 6:
                s6 = s6_verify.kiem_chung(lay("s1"), lay("s2"), lay("s3"), nguong_giong)
                if not s6.ok:
                    return loi_buoc(6, s6.loi)
                kq.file_ra[6] = s6_verify.luu_ket_qua(s6, thu_muc_run)
                ket_qua["s6"] = s6
                ghi(f"  {s6.thong_ke}")
                _in_gioi_han(ghi, "Cảnh báo", s6.canh_bao)
                loi_find = [f"{f.finding_id} {f.kind.value}: {f.message}"
                            for f in s6.findings if f.severity.value == "error"]
                _in_gioi_han(ghi, "Finding lỗi", loi_find)

            # ---------------- Bước 7 ----------------
            elif so_buoc == 7:
                s7 = s7_assemble.ghep_ban_ghi(lay("s1"), lay("s6"))
                kq.file_ra[7] = s7_assemble.luu_ket_qua(s7, thu_muc_run)
                ket_qua["s7"] = s7
                ghi(f"  Bản ghi {s7.record_id}: {len(s7.items)} mục, "
                    f"{sum(1 for i in s7.items if i.needs_review)} cần xem lại.")

            # ---------------- Bước 8 ----------------
            elif so_buoc == 8:
                kq.file_ra[8] = s8_report.luu_ket_qua(lay("s7"), thu_muc_run, ten_file_html)

        except _ThieuFile as loi:
            kq.ma_thoat = 2
            kq.loi.append(str(loi))
            ghi(f"LỖI: {loi}")
            return ghi_run_info()
        except FileNotFoundError as loi:  # thiếu transcript.txt / meeting.json / file prompt
            kq.ma_thoat = 2
            kq.loi.append(str(loi))
            ghi(f"LỖI: {loi}")
            return ghi_run_info()
        except LoiCauHinh as loi:
            kq.ma_thoat = 2
            kq.loi.append(f"Cấu hình LLM: {loi}")
            ghi(f"LỖI CẤU HÌNH: {loi}")
            return ghi_run_info()
        except ValidationError as loi:  # file kết quả cũ sai dạng, hoặc meeting.json sai dạng
            return loi_buoc(so_buoc, [f"dữ liệu đọc vào sai định dạng: {loi.errors()[0]['msg']} "
                                      f"(vị trí {'.'.join(map(str, loi.errors()[0]['loc']))})"])

        kq.giay[so_buoc] = time.perf_counter() - bat_dau
        kq.buoc_da_chay.append(so_buoc)

    ghi_run_info()
    if 8 in kq.file_ra:
        ghi(f"XONG. Báo cáo: {kq.file_ra[8]}")
    else:
        ghi(f"XONG các bước {tu_buoc}-{den_buoc}. Kết quả nằm trong: {thu_muc_run}")
    return kq