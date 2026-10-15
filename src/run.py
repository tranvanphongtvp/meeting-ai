"""
run.py - Điểm vào dòng lệnh của pipeline: chọn đường dẫn rồi giao cho pipeline.py.

Vai trò: như quầy tiếp nhận. Việc của file này chỉ là hiểu bạn muốn chạy cái gì, ở đâu, ghi
kết quả vào đâu; còn chạy từng bước thế nào là việc của pipeline.py.

Quy ước thư mục (gốc dự án = thư mục chứa src/):
    Đầu vào: một thư mục cuộc họp, ví dụ data/case0_test/ có transcript.txt và meeting.json
    Đầu ra mặc định: data/runs/<tên thư mục cuộc họp>/  (đổi bằng --ra). Chạy lại cùng tên sẽ GHI ĐÈ.

Các cách dùng (đứng trong thư mục src):
    # 1) Chạy trọn bước 1-8
    python run.py ../data/case0_test

    # 2) Chọn nơi ghi kết quả
    python run.py ../data/case0_test --ra ../data/runs/lan_thu_2

    # 3) Chỉ xem prompt sẽ gửi, KHÔNG gọi LLM (chạy bước 1 rồi ghi s2_prompt.txt và dừng)
    python run.py ../data/case0_test --dry-run

    # 4) Chạy lại từ giữa chừng, đọc kết quả trước đó từ thư mục run (không tốn lượt gọi LLM).
    #    Khi --tu-buoc > 1, tham số đầu là THƯ MỤC RUN (không phải thư mục cuộc họp):
    python run.py ../data/runs/case0_test --tu-buoc 6
    python run.py ../data/runs/case0_test --tu-buoc 6 --nguong-giong-nhau 0.6   # thử ngưỡng khác

    # 5) Chỉ chạy một đoạn, ví dụ dừng sau bước 2 để xem sự kiện
    python run.py ../data/case0_test --den-buoc 2

    # 6) Ghi báo cáo thành index.html để đưa lên hosting tĩnh (Vercel...)
    python run.py ../data/case0_test --index

Các bước hợp lệ: 1, 2, 3, 6, 7, 8 (bước 4-5 đã nằm trong bước 3).
Mã thoát: 0 = xong, 1 = một bước báo lỗi, 2 = thiếu file hoặc cấu hình (ví dụ chưa đặt GEMINI_API_KEY).
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

import s6_verify
from pipeline import THU_TU_BUOC, TEN_BUOC, chay_pipeline

THU_MUC_GOC = Path(__file__).resolve().parent.parent
THU_MUC_RUN_MAC_DINH = THU_MUC_GOC / "data" / "runs"


def xac_dinh_duong_dan(
    tham_so_dau: str, ra: Optional[str], tu_buoc: int
) -> tuple[Optional[Path], Path]:
    """Trả về (thư mục cuộc họp hoặc None, thư mục run).

    - tu_buoc = 1: tham số đầu là thư mục cuộc họp; thư mục run lấy từ --ra, không có thì
      data/runs/<tên thư mục cuộc họp>.
    - tu_buoc > 1: không cần thư mục cuộc họp; tham số đầu là thư mục run (hoặc --ra nếu có).
    """
    dau = Path(tham_so_dau)
    if tu_buoc == 1:
        return dau, (Path(ra) if ra else THU_MUC_RUN_MAC_DINH / dau.resolve().name)
    return None, Path(ra) if ra else dau


def _dung_tham_so() -> argparse.ArgumentParser:
    cac_buoc = ", ".join(f"{b}={TEN_BUOC[b]}" for b in THU_TU_BUOC)
    parser = argparse.ArgumentParser(
        description="Chạy pipeline bước 1-8. Các bước: " + cac_buoc,
        epilog="Xem hướng dẫn và ví dụ ở đầu file run.py.",
    )
    parser.add_argument(
        "duong_dan",
        help="thư mục cuộc họp (có transcript.txt, meeting.json); với --tu-buoc > 1 thì là thư mục run",
    )
    parser.add_argument("--ra", help="thư mục ghi kết quả (mặc định data/runs/<tên thư mục cuộc họp>)")
    parser.add_argument("--tu-buoc", type=int, default=1, choices=THU_TU_BUOC, help="bắt đầu từ bước này")
    parser.add_argument("--den-buoc", type=int, default=8, choices=THU_TU_BUOC, help="dừng sau bước này")
    parser.add_argument("--dry-run", action="store_true", help="chỉ dựng prompt bước LLM đầu tiên, KHÔNG gọi LLM")
    parser.add_argument("--model", help="ghi đè tên mô hình LLM")
    parser.add_argument("--temperature", type=float, help="nhiệt độ lấy mẫu (bỏ qua = mặc định của API)")
    parser.add_argument(
        "--nguong-giong-nhau", type=float, default=s6_verify.NGUONG_GIONG_MAC_DINH,
        help=f"ngưỡng độ giống để bước 6 coi hai việc là một (mặc định {s6_verify.NGUONG_GIONG_MAC_DINH})",
    )
    parser.add_argument("--gioi-han-ky-tu", type=int, help="cảnh báo nếu transcript dài hơn mức này")
    parser.add_argument("--index", action="store_true", help="ghi báo cáo thành index.html (để đưa lên hosting)")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _dung_tham_so().parse_args(argv)
    if args.tu_buoc > args.den_buoc:
        print(f"LỖI: --tu-buoc ({args.tu_buoc}) lớn hơn --den-buoc ({args.den_buoc}).")
        return 2

    thu_muc_cuoc_hop, thu_muc_run = xac_dinh_duong_dan(args.duong_dan, args.ra, args.tu_buoc)
    print(f"Thư mục run: {thu_muc_run}")
    ket_qua = chay_pipeline(
        thu_muc_cuoc_hop=thu_muc_cuoc_hop,
        thu_muc_run=thu_muc_run,
        tu_buoc=args.tu_buoc,
        den_buoc=args.den_buoc,
        dry_run=args.dry_run,
        model=args.model,
        temperature=args.temperature,
        nguong_giong=args.nguong_giong_nhau,
        gioi_han_ky_tu=args.gioi_han_ky_tu,
        ten_file_html="index.html" if args.index else "s8_report.html",
    )
    return ket_qua.ma_thoat


if __name__ == "__main__":
    sys.exit(main())