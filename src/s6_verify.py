"""
s6_verify.py - Bước 6a [Code, KHÔNG gọi LLM]: kiểm chứng kết quả bước 3.

Vai trò: giống "kiểm toán viên" đọc lại sổ sách sau khi kế toán (LLM + luật bước 3) đã
làm xong. Kiểm toán viên không sửa số, chỉ đánh dấu chỗ đáng ngờ để người duyệt xem.
Vì vậy bước này CHỈ ghi finding và gắn cờ needs_review, tuyệt đối không đổi status hay
nội dung mục (status chỉ do state_rules.py quyết định).

Đầu vào: s1_turns.json, s2_events.json, s3_threads.json (cùng một thư mục run).
Đầu ra:  s6_verified.json (KetQuaKiemChung).

Bốn nhóm kiểm tra:
  V1 Toàn vẹn bằng chứng   (turn/speaker/timestamp/quote có thật, mục có bằng chứng)
  V2 Mâu thuẫn giữa việc   (cùng một việc mà khác người phụ trách/hạn; hạn việc > hạn goal)
  V3 Bất biến của bản ghi  (id trùng, tham chiếu treo, vòng thay thế, trạng thái sai loại...)
  V4 Độ phủ sự kiện        (sự kiện quan trọng không thuộc mục nào)

Mức độ:
  ERROR   -> dữ liệu sai/mâu thuẫn: gắn cờ needs_review + review_reasons cho mục liên quan.
  WARNING -> đáng xem nhưng chưa chắc sai: chỉ ghi lại, KHÔNG gắn cờ.

Chạy riêng (đứng trong thư mục src):
    python s6_verify.py <thu_muc_run>
    python s6_verify.py <thu_muc_run> --nguong-giong-nhau 0.6
Mã thoát: 0 = chạy xong (kể cả có finding error); 1 = đầu vào lỗi; 2 = thiếu file.
"""

import argparse
import sys
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Optional

from pydantic import Field

from s1_preprocess import KetQuaTienXuLy
from s2_extract_acts import KetQuaTrichXuat
from s3_resolve import LUONG_CHUA_XAC_DINH, KetQuaPhanGiai
from schemas import (
    TRANG_THAI_THEO_LOAI,
    ActType,
    Base,
    Finding,
    FindingKind,
    FindingSeverity,
    Item,
    ItemStatus,
    ReviewReason,
    Thread,
    trang_thai_hop_le_cho_loai,
)
from text_utils import chuan_hoa_bo_dau, chuan_hoa_giu_dau, do_giong

# ---------------------------------------------------------------------------
# Hằng số
# ---------------------------------------------------------------------------

# Hai việc cùng luồng có tóm tắt giống từ ngưỡng này trở lên thì coi là "cùng một việc".
# CHƯA kiểm chứng bằng dữ liệu thật, hãy chỉnh sau khi chạy thử (--nguong-giong-nhau).
NGUONG_GIONG_MAC_DINH = 0.5

# Hành động lời nói "quan trọng": nếu không thuộc mục nào thì đáng nghi bị bỏ sót.
# share_info, agree, amend, feedback không nằm trong tập này (hay là ngữ cảnh, ít gây mất mục).
HANH_DONG_QUAN_TRONG = frozenset(
    {
        ActType.CONFIRM,
        ActType.ASSIGN,
        ActType.ACCEPT_TASK,
        ActType.BLOCKER,
        ActType.OBJECT,
        ActType.DEFER,
        ActType.REQUEST,
        ActType.ASK,
        ActType.PROPOSE,
    }
)

# Mục `confirmed` phải có ít nhất một sự kiện thuộc tập này làm căn cứ (V3.9).
# Khớp với luật D1/G1/A1/R1 trong state_rules.py.
HANH_DONG_CAN_CHO_CONFIRMED: dict[str, frozenset[ActType]] = {
    "decision": frozenset({ActType.CONFIRM}),
    "goal": frozenset({ActType.CONFIRM}),
    "action": frozenset({ActType.ASSIGN, ActType.ACCEPT_TASK}),
    "requirement_feedback": frozenset({ActType.CONFIRM, ActType.ACCEPT_TASK}),
}

_THU_TU_MUC_DO = {FindingSeverity.ERROR: 0, FindingSeverity.WARNING: 1}


# ---------------------------------------------------------------------------
# Dữ liệu
# ---------------------------------------------------------------------------


class KetQuaKiemChung(Base):
    """Đầu ra bước 6: dữ liệu bước 3 + finding + cờ review."""

    threads: list[Thread]                 # giữ nguyên từ s3
    items: list[Item]                     # nội dung giữ nguyên; chỉ bổ sung review_reasons, needs_review
    findings: list[Finding] = Field(default_factory=list)  # mọi phát hiện
    thong_ke: dict[str, int] = Field(default_factory=dict)  # {"error": N, "warning": M, "muc_can_xem_lai": K}
    canh_bao: list[str] = Field(default_factory=list)       # chạy tiếp được, nhưng nên xem
    loi: list[str] = Field(default_factory=list)            # không có kết quả dùng được

    @property
    def ok(self) -> bool:
        """True nếu không có lỗi đầu vào, có thể dùng đầu ra."""
        return not self.loi


@dataclass
class _PhatHien:
    """Phát hiện nội bộ: như Finding nhưng chưa có finding_id và có kèm lý do gắn cờ.

    Finding trong schemas.py không có trường lý do, nên lý do được giữ ở đây để gan_co dùng.
    """

    severity: FindingSeverity
    kind: FindingKind
    message: str
    ly_do: Optional[ReviewReason] = None   # chỉ có tác dụng khi severity = ERROR
    item_ids: list[str] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)
    thread_ids: list[str] = field(default_factory=list)

    def khoa_sap_xep(self) -> tuple:
        """Khoá sắp xếp cố định để finding_id ổn định giữa các lần chạy cùng đầu vào."""
        return (
            _THU_TU_MUC_DO[self.severity],
            self.kind.value,
            self.item_ids,
            self.event_ids,
            self.thread_ids,
            self.message,
        )


@dataclass
class ChiMuc:
    """Các bảng tra cứu dựng một lần, dùng chung cho V1-V4."""

    turn_theo_id: dict
    su_kien_theo_id: dict
    muc_theo_id: dict          # item_id -> mục đầu tiên mang id đó
    luong_theo_id: dict        # thread_id -> luồng đầu tiên mang id đó
    vi_tri_su_kien: dict[str, int]  # event_id -> vị trí trong cuộc họp (theo thứ tự s2)
    co_event_ids: bool         # False nếu s3 cũ, mọi mục đều thiếu event_ids


def dung_chi_muc(s1, s2, s3) -> ChiMuc:
    """Dựng các bảng tra cứu từ s1, s2, s3 (chỉ cần các thuộc tính .turns, .events, .threads, .items)."""
    muc_theo_id: dict = {}
    for it in s3.items:
        muc_theo_id.setdefault(it.item_id, it)
    luong_theo_id: dict = {}
    for th in s3.threads:
        luong_theo_id.setdefault(th.thread_id, th)
    return ChiMuc(
        turn_theo_id={t.turn_id: t for t in s1.turns},
        su_kien_theo_id={e.event_id: e for e in s2.events},
        muc_theo_id=muc_theo_id,
        luong_theo_id=luong_theo_id,
        vi_tri_su_kien={e.event_id: i for i, e in enumerate(s2.events)},
        co_event_ids=any(it.event_ids for it in s3.items),
    )


def _vi_tri_cuoi(it, cm: ChiMuc) -> Optional[int]:
    """Vị trí của sự kiện MUỘN NHẤT của mục (cùng cách tính _chi_so_cuoi của state_rules)."""
    vt = [cm.vi_tri_su_kien[e] for e in it.event_ids if e in cm.vi_tri_su_kien]
    return max(vt) if vt else None


# ---------------------------------------------------------------------------
# V1: Toàn vẹn bằng chứng
# ---------------------------------------------------------------------------


def kiem_bang_chung(items: list, cm: ChiMuc) -> list[_PhatHien]:
    """V1.1-V1.6: bằng chứng của mỗi mục có thật và khớp lượt nói gốc không."""
    ds: list[_PhatHien] = []
    E, W = FindingSeverity.ERROR, FindingSeverity.WARNING
    for it in items:
        # V1.5: không có bằng chứng nào.
        if not it.evidence:
            ds.append(_PhatHien(
                E, FindingKind.EVIDENCE_MISSING, f"Mục {it.item_id} không có bằng chứng nào.",
                ReviewReason.NO_EVIDENCE, item_ids=[it.item_id],
            ))

        for ev in it.evidence:
            luot = cm.turn_theo_id.get(ev.turn_id)
            # V1.1: turn_id phải có trong s1. Thiếu thì không kiểm được gì thêm.
            if luot is None:
                ds.append(_PhatHien(
                    E, FindingKind.EVIDENCE_TURN_MISSING,
                    f"Mục {it.item_id}: bằng chứng trỏ tới {ev.turn_id} không có trong s1_turns.json.",
                    ReviewReason.EVIDENCE_MISMATCH, item_ids=[it.item_id],
                ))
                continue
            # V1.2, V1.3: người nói và timestamp phải đúng với lượt nói gốc.
            if ev.speaker != luot.speaker:
                ds.append(_PhatHien(
                    E, FindingKind.EVIDENCE_SPEAKER_MISMATCH,
                    f"Mục {it.item_id}: bằng chứng {ev.turn_id} ghi người nói '{ev.speaker}' "
                    f"nhưng lượt nói gốc là '{luot.speaker}'.",
                    ReviewReason.EVIDENCE_MISMATCH, item_ids=[it.item_id],
                ))
            if ev.timestamp != luot.timestamp:
                ds.append(_PhatHien(
                    E, FindingKind.EVIDENCE_TIMESTAMP_MISMATCH,
                    f"Mục {it.item_id}: bằng chứng {ev.turn_id} ghi thời điểm '{ev.timestamp}' "
                    f"nhưng lượt nói gốc là '{luot.timestamp}'.",
                    ReviewReason.EVIDENCE_MISMATCH, item_ids=[it.item_id],
                ))
            # V1.4: so trích dẫn. Khớp đủ dấu -> OK; chỉ khớp khi bỏ dấu -> warning; còn lại -> error.
            quote_giu_dau = chuan_hoa_giu_dau(ev.quote)
            if quote_giu_dau and quote_giu_dau in chuan_hoa_giu_dau(luot.text):
                continue
            quote_bo_dau = chuan_hoa_bo_dau(ev.quote)
            if quote_bo_dau and quote_bo_dau in chuan_hoa_bo_dau(luot.text):
                ds.append(_PhatHien(
                    W, FindingKind.EVIDENCE_QUOTE_DIACRITICS,
                    f"Mục {it.item_id}: trích dẫn ở {ev.turn_id} chỉ khớp khi bỏ dấu "
                    f"(có thể LLM đã đổi dấu).",
                    item_ids=[it.item_id],
                ))
            else:
                ds.append(_PhatHien(
                    E, FindingKind.EVIDENCE_QUOTE_MISMATCH,
                    f"Mục {it.item_id}: trích dẫn không có trong lượt nói {ev.turn_id}.",
                    ReviewReason.EVIDENCE_MISMATCH, item_ids=[it.item_id],
                ))

        # V1.6: event_id của mục phải có trong s2.
        treo = [e for e in it.event_ids if e not in cm.su_kien_theo_id]
        if treo:
            ds.append(_PhatHien(
                E, FindingKind.DANGLING_REFERENCE,
                f"Mục {it.item_id}: event_id không có trong s2_events.json: {', '.join(treo)}.",
                ReviewReason.INVALID_REFERENCE, item_ids=[it.item_id], event_ids=sorted(treo),
            ))
    return ds


# ---------------------------------------------------------------------------
# V2: Mâu thuẫn giữa các mục
# ---------------------------------------------------------------------------


def _khac_nguoi(a: Optional[str], b: Optional[str]) -> bool:
    """Hai owner đều có và khác nhau (so sau chuẩn hoá để khỏi lệch hoa/thường, khoảng trắng)."""
    return bool(a) and bool(b) and chuan_hoa_giu_dau(a) != chuan_hoa_giu_dau(b)


def kiem_mau_thuan(items: list, nguong: float) -> list[_PhatHien]:
    """V2.1-V2.4: mâu thuẫn owner/hạn giữa các việc, và hạn việc vượt hạn goal."""
    ds: list[_PhatHien] = []
    E, W = FindingSeverity.ERROR, FindingSeverity.WARNING
    viec = sorted(
        (it for it in items if it.type == "action" and it.status != ItemStatus.SUPERSEDED),
        key=lambda x: x.item_id,
    )

    # V2.1-V2.3: "cùng một việc" = cùng luồng VÀ tóm tắt giống >= ngưỡng.
    for a, b in combinations(viec, 2):
        if a.thread_id != b.thread_id or a.thread_id == LUONG_CHUA_XAC_DINH:
            continue
        gioi = do_giong(a.summary, b.summary)
        if gioi < nguong:
            continue
        ids = sorted([a.item_id, b.item_id])
        co_mau_thuan = False
        if _khac_nguoi(a.owner, b.owner):
            co_mau_thuan = True
            ds.append(_PhatHien(
                E, FindingKind.OWNER_CONFLICT,
                f"Hai việc giống nhau ({gioi:.2f}) nhưng khác người phụ trách: "
                f"{a.item_id} -> {a.owner}, {b.item_id} -> {b.owner}.",
                ReviewReason.CONTRADICTION, item_ids=ids, thread_ids=[a.thread_id],
            ))
        if a.deadline and b.deadline and a.deadline != b.deadline:
            co_mau_thuan = True
            ds.append(_PhatHien(
                E, FindingKind.DEADLINE_CONFLICT,
                f"Hai việc giống nhau ({gioi:.2f}) nhưng khác hạn: "
                f"{a.item_id} -> {a.deadline}, {b.item_id} -> {b.deadline}.",
                ReviewReason.CONTRADICTION, item_ids=ids, thread_ids=[a.thread_id],
            ))
        if not co_mau_thuan:
            ds.append(_PhatHien(
                W, FindingKind.DUPLICATE_TASK,
                f"{a.item_id} và {b.item_id} có vẻ là cùng một việc (độ giống {gioi:.2f}), "
                f"không mâu thuẫn owner/hạn.",
                item_ids=ids, thread_ids=[a.thread_id],
            ))

    # V2.4: so MỌI goal confirmed có hạn (không giới hạn cùng luồng) với mỗi việc có hạn.
    goals = sorted(
        (it for it in items if it.type == "goal" and it.status == ItemStatus.CONFIRMED and it.deadline),
        key=lambda x: x.item_id,
    )
    for g in goals:
        for v in viec:
            if v.deadline and v.deadline > g.deadline:
                ds.append(_PhatHien(
                    W, FindingKind.DEADLINE_AFTER_GOAL,
                    f"Việc {v.item_id} có hạn {v.deadline} muộn hơn hạn goal {g.item_id} ({g.deadline}).",
                    item_ids=sorted([v.item_id, g.item_id]),
                ))
    return ds


# ---------------------------------------------------------------------------
# V3: Bất biến của bản ghi
# ---------------------------------------------------------------------------


def _tim_vong(muc_theo_id: dict) -> list[list[str]]:
    """Tìm vòng trong chuỗi superseded_by. Mỗi vòng trả về một lần (danh sách id, đã sắp xếp)."""
    vong: dict[frozenset, list[str]] = {}
    for bat_dau in sorted(muc_theo_id):
        duong: list[str] = []
        hien = bat_dau
        while hien in muc_theo_id and hien not in duong:
            duong.append(hien)
            hien = muc_theo_id[hien].superseded_by
            if not hien:
                break
        if hien in duong:
            thanh_vien = duong[duong.index(hien):]
            vong.setdefault(frozenset(thanh_vien), sorted(thanh_vien))
    return [vong[k] for k in sorted(vong, key=lambda k: sorted(k))]


def kiem_bat_bien(threads: list, items: list, cm: ChiMuc) -> list[_PhatHien]:
    """V3.1-V3.10: tính nhất quán của bản ghi (id, tham chiếu, thay thế, trạng thái, luồng)."""
    ds: list[_PhatHien] = []
    E, W = FindingSeverity.ERROR, FindingSeverity.WARNING
    ref = ReviewReason.INVALID_REFERENCE

    # V3.1: id không trùng.
    for loai_id, danh_sach in (("item_id", [i.item_id for i in items]), ("thread_id", [t.thread_id for t in threads])):
        da_thay: set[str] = set()
        for x in danh_sach:
            if x in da_thay:
                continue
            if danh_sach.count(x) > 1:
                da_thay.add(x)
                ds.append(_PhatHien(
                    E, FindingKind.DUPLICATE_ID, f"{loai_id} '{x}' bị trùng ({danh_sach.count(x)} lần).", ref,
                    item_ids=[x] if loai_id == "item_id" else [],
                    thread_ids=[x] if loai_id == "thread_id" else [],
                ))

    for it in items:
        # V3.2: thread_id của mục phải có trong danh sách luồng.
        th = cm.luong_theo_id.get(it.thread_id)
        if th is None:
            if it.thread_id == LUONG_CHUA_XAC_DINH:
                # s3 đã tự cảnh báo; chỉ ghi lại, không gắn cờ.
                ds.append(_PhatHien(
                    W, FindingKind.THREAD_INCONSISTENT,
                    f"Mục {it.item_id} chưa được xếp vào luồng nào ({LUONG_CHUA_XAC_DINH}).",
                    item_ids=[it.item_id],
                ))
            else:
                ds.append(_PhatHien(
                    E, FindingKind.THREAD_INCONSISTENT,
                    f"Mục {it.item_id} thuộc luồng '{it.thread_id}' không có trong danh sách luồng.", ref,
                    item_ids=[it.item_id], thread_ids=[it.thread_id],
                ))
        else:
            ngoai = [e for e in it.event_ids if e not in th.event_ids]
            if ngoai:
                ds.append(_PhatHien(
                    W, FindingKind.THREAD_INCONSISTENT,
                    f"Mục {it.item_id} có sự kiện không thuộc luồng {th.thread_id}: {', '.join(ngoai)}.",
                    item_ids=[it.item_id], event_ids=sorted(ngoai), thread_ids=[th.thread_id],
                ))

        # V3.3: supersedes/superseded_by phải trỏ mục có thật và không tự trỏ.
        for ten_truong, gia_tri in (("supersedes", it.supersedes), ("superseded_by", it.superseded_by)):
            if not gia_tri:
                continue
            if gia_tri == it.item_id:
                ds.append(_PhatHien(
                    E, FindingKind.DANGLING_REFERENCE,
                    f"Mục {it.item_id}: {ten_truong} tự trỏ về chính nó.", ref, item_ids=[it.item_id],
                ))
            elif gia_tri not in cm.muc_theo_id:
                ds.append(_PhatHien(
                    E, FindingKind.DANGLING_REFERENCE,
                    f"Mục {it.item_id}: {ten_truong} trỏ tới '{gia_tri}' không tồn tại.", ref,
                    item_ids=[it.item_id],
                ))

        # V3.5: superseded <-> có superseded_by.
        if it.status == ItemStatus.SUPERSEDED and not it.superseded_by:
            ds.append(_PhatHien(
                E, FindingKind.SUPERSEDE_INCONSISTENT,
                f"Mục {it.item_id} có trạng thái superseded nhưng thiếu superseded_by.", ref,
                item_ids=[it.item_id],
            ))
        if it.superseded_by and it.status != ItemStatus.SUPERSEDED:
            ds.append(_PhatHien(
                E, FindingKind.SUPERSEDE_INCONSISTENT,
                f"Mục {it.item_id} có superseded_by nhưng trạng thái là '{it.status.value}'.", ref,
                item_ids=[it.item_id],
            ))

        # V3.6: mục thay thế phải xảy ra SAU và đang confirmed/superseded (cùng luật S1 của state_rules).
        dich = cm.muc_theo_id.get(it.superseded_by) if it.superseded_by else None
        if dich is not None and dich is not it:
            if dich.status not in (ItemStatus.CONFIRMED, ItemStatus.SUPERSEDED):
                ds.append(_PhatHien(
                    E, FindingKind.SUPERSEDE_INCONSISTENT,
                    f"Mục {it.item_id} bị thay bởi {dich.item_id} nhưng {dich.item_id} đang "
                    f"'{dich.status.value}' (phải là confirmed hoặc superseded).", ref,
                    item_ids=sorted([it.item_id, dich.item_id]),
                ))
            vt_dich, vt_it = _vi_tri_cuoi(dich, cm), _vi_tri_cuoi(it, cm)
            if vt_dich is not None and vt_it is not None and vt_dich <= vt_it:
                ds.append(_PhatHien(
                    E, FindingKind.SUPERSEDE_INCONSISTENT,
                    f"Mục thay thế {dich.item_id} không xảy ra sau mục bị thay {it.item_id}.", ref,
                    item_ids=sorted([it.item_id, dich.item_id]),
                ))

        # V3.7: B.supersedes = X thì X.superseded_by phải là B.
        if it.supersedes and it.supersedes != it.item_id:
            cu = cm.muc_theo_id.get(it.supersedes)
            if cu is not None and cu.superseded_by != it.item_id:
                ds.append(_PhatHien(
                    E, FindingKind.SUPERSEDE_INCONSISTENT,
                    f"Mục {it.item_id} nói thay thế {cu.item_id} nhưng {cu.item_id}.superseded_by "
                    f"là '{cu.superseded_by}'.", ref,
                    item_ids=sorted([it.item_id, cu.item_id]),
                ))

        # V3.8: trạng thái phải thuộc tập cho phép của loại mục.
        if not trang_thai_hop_le_cho_loai(it):
            ds.append(_PhatHien(
                E, FindingKind.STATUS_NOT_ALLOWED,
                f"Mục {it.item_id} ({it.type}) không được dùng trạng thái '{it.status.value}' "
                f"(cho phép: {', '.join(sorted(s.value for s in TRANG_THAI_THEO_LOAI[it.type]))}).", ref,
                item_ids=[it.item_id],
            ))

        # V3.9: trạng thái confirmed phải có sự kiện hỗ trợ. Bỏ qua nếu s3 cũ thiếu event_ids.
        can = HANH_DONG_CAN_CHO_CONFIRMED.get(it.type)
        if cm.co_event_ids and can and it.status == ItemStatus.CONFIRMED:
            cac_act = {cm.su_kien_theo_id[e].act for e in it.event_ids if e in cm.su_kien_theo_id}
            if not (cac_act & can):
                ds.append(_PhatHien(
                    E, FindingKind.STATUS_NOT_SUPPORTED,
                    f"Mục {it.item_id} ({it.type}) là confirmed nhưng không có sự kiện "
                    f"{'/'.join(sorted(a.value for a in can))} làm căn cứ.",
                    ReviewReason.RULE_CONFLICT, item_ids=[it.item_id], event_ids=sorted(it.event_ids),
                ))

    # V3.4: không có vòng trong chuỗi superseded_by.
    for thanh_vien in _tim_vong(cm.muc_theo_id):
        if len(thanh_vien) == 1:
            continue  # tự trỏ đã báo ở V3.3
        ds.append(_PhatHien(
            E, FindingKind.SUPERSEDE_CYCLE,
            f"Vòng thay thế: {' -> '.join(thanh_vien + [thanh_vien[0]])}.", ref, item_ids=thanh_vien,
        ))

    # V3.10: luồng có event_ids hợp lệ, decisive_event_id nằm trong luồng. (Không gắn cờ mục.)
    for th in threads:
        treo = [e for e in th.event_ids if e not in cm.su_kien_theo_id]
        if treo:
            ds.append(_PhatHien(
                E, FindingKind.THREAD_INCONSISTENT,
                f"Luồng {th.thread_id} có event_id không có trong s2: {', '.join(treo)}.",
                event_ids=sorted(treo), thread_ids=[th.thread_id],
            ))
        if th.decisive_event_id and th.decisive_event_id not in th.event_ids:
            ds.append(_PhatHien(
                E, FindingKind.THREAD_INCONSISTENT,
                f"Luồng {th.thread_id}: decisive_event_id '{th.decisive_event_id}' không thuộc luồng.",
                event_ids=[th.decisive_event_id], thread_ids=[th.thread_id],
            ))
    return ds


# ---------------------------------------------------------------------------
# V4: Độ phủ sự kiện
# ---------------------------------------------------------------------------


def kiem_do_phu(s2, items: list, threads: list, cm: ChiMuc) -> list[_PhatHien]:
    """V4: sự kiện quan trọng không thuộc mục nào (kể cả mục superseded) thì ghi warning."""
    if not cm.co_event_ids:
        return []
    da_phu = {e for it in items for e in it.event_ids}
    luong_cua = {e: th.thread_id for th in threads for e in th.event_ids}
    ds: list[_PhatHien] = []
    for e in s2.events:
        if e.act in HANH_DONG_QUAN_TRONG and e.event_id not in da_phu:
            ds.append(_PhatHien(
                FindingSeverity.WARNING, FindingKind.UNCOVERED_EVENT,
                f"Sự kiện {e.event_id} ({e.act.value}, {e.turn_id}) không thuộc mục nào: có thể bị bỏ sót.",
                event_ids=[e.event_id],
                thread_ids=[luong_cua[e.event_id]] if e.event_id in luong_cua else [],
            ))
    return ds


# ---------------------------------------------------------------------------
# Gắn cờ review
# ---------------------------------------------------------------------------


def gan_co(items: list, phat_hien: list[_PhatHien]) -> None:
    """Gắn cờ trực tiếp lên `items` (nhớ truyền BẢN SAO, không phải bản gốc).

    1. Mỗi finding ERROR có lý do: thêm lý do vào review_reasons của mọi mục trong item_ids.
    2. Khử trùng lý do, giữ thứ tự cũ (lý do s3 đã gắn đứng trước).
    3. needs_review = bool(review_reasons) cho MỌI mục.
    4. WARNING không gắn cờ. Không đổi status.
    """
    theo_id: dict[str, list] = {}
    for it in items:
        theo_id.setdefault(it.item_id, []).append(it)
    for p in phat_hien:
        if p.severity != FindingSeverity.ERROR or p.ly_do is None:
            continue
        for iid in p.item_ids:
            for it in theo_id.get(iid, []):
                it.review_reasons.append(p.ly_do)
    for it in items:
        it.review_reasons = list(dict.fromkeys(it.review_reasons))
        it.needs_review = bool(it.review_reasons)


# ---------------------------------------------------------------------------
# Hàm tổng thể
# ---------------------------------------------------------------------------


def kiem_chung(s1, s2, s3, nguong_giong: float = NGUONG_GIONG_MAC_DINH) -> KetQuaKiemChung:
    """Chạy V1-V4 trên kết quả bước 3, trả về KetQuaKiemChung. Không sửa đầu vào tại chỗ.

    s1, s2, s3 chỉ cần có: s1.turns, s2.events, s3.threads, s3.items, s3.loi.
    """
    if s3.loi:
        return KetQuaKiemChung(threads=[], items=[], loi=[f"s3 còn lỗi: {l}" for l in s3.loi])
    if not s3.items:
        return KetQuaKiemChung(threads=[], items=[], loi=["s3 không có mục nghiệp vụ nào để kiểm chứng."])

    # Làm việc trên bản sao để bản ghi đầu vào không bị sửa tại chỗ.
    threads = [t.model_copy(deep=True) for t in s3.threads]
    items = [i.model_copy(deep=True) for i in s3.items]

    cm = dung_chi_muc(s1, s2, s3)
    canh_bao: list[str] = []
    if not cm.co_event_ids:
        canh_bao.append("s3 cũ không có event_ids: bỏ qua V3.9 và V4, hãy chạy lại bước 3.")

    phat_hien: list[_PhatHien] = []
    phat_hien += kiem_bang_chung(items, cm)
    phat_hien += kiem_mau_thuan(items, nguong_giong)
    phat_hien += kiem_bat_bien(threads, items, cm)
    phat_hien += kiem_do_phu(s2, items, threads, cm)

    # Sắp xếp cố định (error trước) rồi mới đánh F001...: cùng đầu vào thì cùng finding_id.
    phat_hien.sort(key=_PhatHien.khoa_sap_xep)
    findings = [
        Finding(
            finding_id=f"F{n:03d}", severity=p.severity, kind=p.kind, message=p.message,
            item_ids=p.item_ids, event_ids=p.event_ids, thread_ids=p.thread_ids,
        )
        for n, p in enumerate(phat_hien, start=1)
    ]

    gan_co(items, phat_hien)

    thong_ke = {
        "error": sum(1 for f in findings if f.severity == FindingSeverity.ERROR),
        "warning": sum(1 for f in findings if f.severity == FindingSeverity.WARNING),
        "muc_can_xem_lai": sum(1 for it in items if it.needs_review),
    }
    return KetQuaKiemChung(
        threads=threads, items=items, findings=findings, thong_ke=thong_ke, canh_bao=canh_bao,
    )


# ---------------------------------------------------------------------------
# Đọc/ghi file
# ---------------------------------------------------------------------------


def luu_ket_qua(ket_qua: KetQuaKiemChung, thu_muc_run: str | Path) -> Path:
    """Ghi s6_verified.json vào thư mục run."""
    thu_muc_run = Path(thu_muc_run)
    thu_muc_run.mkdir(parents=True, exist_ok=True)
    duong_dan = thu_muc_run / "s6_verified.json"
    duong_dan.write_text(ket_qua.model_dump_json(indent=2), encoding="utf-8")
    return duong_dan


# ---------------------------------------------------------------------------
# Chạy riêng bước 6
# ---------------------------------------------------------------------------


def _chay_rieng(argv: Optional[list[str]] = None) -> int:
    """Chạy riêng bước 6 từ command line. Mã thoát: 0 chạy xong, 1 đầu vào lỗi, 2 thiếu file."""
    parser = argparse.ArgumentParser(description="Chạy riêng bước 6: kiểm chứng (không gọi LLM)")
    parser.add_argument("thu_muc_run", help="thư mục đã có s1_turns.json, s2_events.json, s3_threads.json")
    parser.add_argument(
        "--nguong-giong-nhau", type=float, default=NGUONG_GIONG_MAC_DINH,
        help=f"ngưỡng độ giống tóm tắt để coi là cùng một việc (mặc định {NGUONG_GIONG_MAC_DINH})",
    )
    args = parser.parse_args(argv)
    thu_muc_run = Path(args.thu_muc_run)

    cac_file = [
        (thu_muc_run / "s1_turns.json", "bước 1 (s1_preprocess.py)"),
        (thu_muc_run / "s2_events.json", "bước 2 (s2_extract_acts.py)"),
        (thu_muc_run / "s3_threads.json", "bước 3 (s3_resolve.py)"),
    ]
    for f, ten_buoc in cac_file:
        if not f.exists():
            print(f"LỖI: không thấy {f}. Chạy {ten_buoc} trước.")
            return 2

    s1 = KetQuaTienXuLy.model_validate_json(cac_file[0][0].read_text(encoding="utf-8"))
    s2 = KetQuaTrichXuat.model_validate_json(cac_file[1][0].read_text(encoding="utf-8"))
    s3 = KetQuaPhanGiai.model_validate_json(cac_file[2][0].read_text(encoding="utf-8"))
    for ten, kq in (("1", s1), ("2", s2), ("3", s3)):
        if not kq.ok:
            print(f"LỖI: bước {ten} còn lỗi, xem lại trước:")
            for loi in kq.loi:
                print(f"  - {loi}")
            return 1

    ket_qua = kiem_chung(s1, s2, s3, args.nguong_giong_nhau)
    if not ket_qua.ok:
        for loi in ket_qua.loi:
            print(f"LỖI: {loi}")
        return 1

    duong_dan = luu_ket_qua(ket_qua, thu_muc_run)
    tk = ket_qua.thong_ke
    print(f"Thống kê: {tk['error']} error, {tk['warning']} warning, {tk['muc_can_xem_lai']} mục cần xem lại.")
    for c in ket_qua.canh_bao:
        print(f"CẢNH BÁO: {c}")
    for f in sorted(ket_qua.findings, key=lambda x: _THU_TU_MUC_DO[x.severity]):
        print(f"[{f.severity.value.upper()}] {f.finding_id} {f.kind.value}: {f.message}")
    print(f"Đã ghi: {duong_dan}")
    return 0


if __name__ == "__main__":
    sys.exit(_chay_rieng())