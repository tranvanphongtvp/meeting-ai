"""
state_rules.py - Bước 4 [Code]: luật trạng thái đè lên kết quả của LLM.

Vai trò: LLM (bước 3) ĐỀ XUẤT trạng thái cho từng mục. File này tính lại trạng thái
từ chính các SỰ KIỆN LỜI NÓI làm bằng chứng của mục đó, rồi so với đề xuất của LLM.
Hai bên mâu thuẫn thì LUẬT THẮNG và mục bị gắn cờ rule_conflict.
*Ví dụ đời thường:* như trọng tài video, người xem nói gì cũng được, nhưng quyết
định cuối phải theo luật thi đấu.

Các luật (đã chốt với người dùng):

Decision
  D1. Chỉ là `confirmed` khi có sự kiện `confirm`. Không có thì là `proposed`.
  D2. Lấy lần `confirm` MUỘN NHẤT. Nếu sau đó còn `object` hoặc `defer` trong cùng mục
      thì chưa chốt được: hạ về `proposed` + rule_conflict. Còn `amend` sau đó thì giữ
      `confirmed` nhưng gắn rule_conflict (người duyệt xem nội dung đã khớp chưa).
  D3. Thẩm quyền: nếu roster có người can_decide=true mà người chốt không thuộc nhóm
      đó -> hạ về `proposed` + authority_unclear. Roster không ai có can_decide=true thì
      KHÔNG hạ, chỉ gắn authority_unclear (không thể kiểm chứng).
  D4. Lần chốt có certainty=tentative (chốt ngầm) -> giữ `confirmed` + implicit_signal.
  D5. Hai Decision cùng một luồng cùng `confirmed`: coi là phương án thay thế nhau, chốt
      muộn nhất thắng, các mục còn lại thành `superseded` + rule_conflict.
  D6. `rejected` chỉ được nhận khi mục có sự kiện `object` và chưa có ai chốt.
Goal
  G1. Dùng đúng luật của Decision (D1-D4): `confirmed` khi có `confirm` và người chốt có
      can_decide (đã chốt với người dùng: "như decision"), không thì `proposed`.
Proposal
  P1. Chưa bao giờ được chốt nên KHÔNG có `confirmed`: luôn `proposed`. `rejected` chỉ nhận
      khi có `object` (D6). Nếu mục có sự kiện `confirm` mà bị xếp là proposal thì gắn
      rule_conflict (nhiều khả năng đáng lẽ là Decision).
Action
  A1. `confirmed` khi có `assign` HOẶC `accept_task` (không cần thẩm quyền). Không có
      thì `proposed`.
  A2. Sau lần giao/nhận muộn nhất còn `object` hoặc `defer` -> `proposed` + rule_conflict.
  A3. Lần giao/nhận muộn nhất có certainty=tentative -> implicit_signal.
Issue, OpenQuestion
  I1. Issue mặc định `open`; OpenQuestion luôn `open`.
RequirementFeedback
  R1. `confirmed` khi có `confirm` hoặc `accept_task` và sau đó không còn `object`/`defer`.
  R2. Không có: sự kiện cuối là `defer` -> `open`, còn lại `proposed`. `rejected` chỉ nhận
      khi có `object` và chưa ai chấp nhận.
Chung
  S1. `superseded` chỉ hợp lệ khi mục thay thế (superseded_by) tồn tại, cùng luồng (riêng
      Issue có thể khác luồng), cùng loại (riêng Issue có thể do loại khác giải quyết;
      riêng Proposal có thể do Decision thay),
      xảy ra SAU, và bản thân nó đang `confirmed` hoặc `superseded`. Loại không cho phép
      `superseded` (RequirementFeedback, OpenQuestion) thì không nhận.
      Không hợp lệ -> trả về trạng thái theo luật + rule_conflict.

Giới hạn đã biết: mục chỉ có một trường `supersedes` nên khi một mục thay thế nhiều mục,
chỉ ghi mục bị thay thế gần nhất; quan hệ đầy đủ xem `superseded_by` của các mục cũ.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from schemas import (
    TRANG_THAI_THEO_LOAI,
    ActType,
    Certainty,
    ItemStatus,
    Participant,
    ReviewReason,
    SpeechEvent,
)

# Thứ tự ưu tiên khi suy trạng thái của cả luồng từ các mục trong luồng.
UU_TIEN_TRANG_THAI_LUONG = [
    ItemStatus.CONFIRMED,
    ItemStatus.PROPOSED,
    ItemStatus.OPEN,
    ItemStatus.REJECTED,
    ItemStatus.SUPERSEDED,
]


@dataclass
class BoiCanh:
    """Thông tin chung mà các luật cần."""

    thu_tu: dict[str, int]                     # event_id -> vị trí trong cuộc họp
    nguoi_theo_ten: dict[str, Participant]     # tên chính thức -> người trong roster

    @property
    def co_nguoi_co_quyen(self) -> bool:
        """Roster có ít nhất một người được đánh dấu can_decide=true."""
        return any(p.can_decide for p in self.nguoi_theo_ten.values())


@dataclass
class MucNhap:
    """Một mục nghiệp vụ ở dạng nháp, trước khi dựng thành Decision/Action/..."""

    id_tam: str                      # khoá nội bộ (từ item_id do LLM đặt)
    loai: str                        # decision | action | issue | requirement_feedback | open_question
    thread_id: str                   # mã luồng đã chuẩn hoá
    su_kien: list[SpeechEvent]       # sự kiện làm bằng chứng, đã sắp theo thời gian
    trang_thai_llm: ItemStatus       # trạng thái LLM đề xuất
    thay_the_boi: Optional[str] = None   # id_tam của mục thay thế (LLM nêu, sau đó được kiểm)
    raw: Any = None                  # dữ liệu thô từ LLM, dùng khi dựng mục
    trang_thai: ItemStatus = field(init=False)
    ly_do: list[ReviewReason] = field(default_factory=list)
    nguoi_chot: Optional[str] = None
    muc_bi_thay_ids: list[str] = field(default_factory=list)  # các mục mà mục này thay thế
    ghi_chu: list[str] = field(default_factory=list)          # lời giải thích cho người đọc

    def __post_init__(self) -> None:
        self.trang_thai = self.trang_thai_llm

    @property
    def muc_bi_thay_gan_nhat(self) -> Optional[str]:
        """Mục bị thay thế gần nhất (danh sách đã được sắp theo thời gian)."""
        return self.muc_bi_thay_ids[-1] if self.muc_bi_thay_ids else None


# ---------------------------------------------------------------------------
# Luật cho từng loại mục: trả về (trạng thái, lý do cờ, người chốt)
# ---------------------------------------------------------------------------


def _sau_moc(m: MucNhap, moc: SpeechEvent, ctx: BoiCanh) -> list[SpeechEvent]:
    """Các sự kiện của mục xảy ra SAU sự kiện mốc."""
    return [e for e in m.su_kien if ctx.thu_tu[e.event_id] > ctx.thu_tu[moc.event_id]]


def _luat_decision(m: MucNhap, ctx: BoiCanh):
    cac_chot = [e for e in m.su_kien if e.act == ActType.CONFIRM]
    if not cac_chot:
        return ItemStatus.PROPOSED, [], None
    cuoi = cac_chot[-1]  # D2: chốt muộn nhất
    sau = _sau_moc(m, cuoi, ctx)
    if any(e.act in (ActType.OBJECT, ActType.DEFER) for e in sau):
        m.ghi_chu.append(f"{m.id_tam}: có phản đối/hoãn sau lần chốt, chưa thể coi là đã chốt.")
        return ItemStatus.PROPOSED, [ReviewReason.RULE_CONFLICT], None

    ly_do: list[ReviewReason] = []
    if any(e.act == ActType.AMEND for e in sau):
        ly_do.append(ReviewReason.RULE_CONFLICT)
        m.ghi_chu.append(f"{m.id_tam}: có sửa đổi sau lần chốt, cần kiểm tra nội dung đã khớp chưa.")

    nguoi = ctx.nguoi_theo_ten.get(cuoi.speaker)
    if ctx.co_nguoi_co_quyen:
        if nguoi is None or not nguoi.can_decide:  # D3
            m.ghi_chu.append(f"{m.id_tam}: '{cuoi.speaker}' chốt nhưng không có thẩm quyền theo roster.")
            return ItemStatus.PROPOSED, ly_do + [ReviewReason.AUTHORITY_UNCLEAR], None
    else:
        ly_do.append(ReviewReason.AUTHORITY_UNCLEAR)
        m.ghi_chu.append(f"{m.id_tam}: roster không có ai can_decide=true nên không kiểm chứng được thẩm quyền.")

    if cuoi.certainty == Certainty.TENTATIVE:  # D4
        ly_do.append(ReviewReason.IMPLICIT_SIGNAL)
    return ItemStatus.CONFIRMED, ly_do, cuoi.speaker


def _luat_proposal(m: MucNhap, ctx: BoiCanh):
    """P1: đề xuất chưa từng được chốt nên luôn `proposed`; có `confirm` thì nghi xếp sai loại."""
    if any(e.act == ActType.CONFIRM for e in m.su_kien):
        m.ghi_chu.append(f"{m.id_tam}: có sự kiện confirm nhưng được xếp là proposal (đáng lẽ là decision?).")
        return ItemStatus.PROPOSED, [ReviewReason.RULE_CONFLICT], None
    return ItemStatus.PROPOSED, [], None


def _luat_action(m: MucNhap, ctx: BoiCanh):
    cac_giao = [e for e in m.su_kien if e.act in (ActType.ASSIGN, ActType.ACCEPT_TASK)]
    if not cac_giao:
        return ItemStatus.PROPOSED, [], None
    cuoi = cac_giao[-1]
    if any(e.act in (ActType.OBJECT, ActType.DEFER) for e in _sau_moc(m, cuoi, ctx)):  # A2
        m.ghi_chu.append(f"{m.id_tam}: có phản đối/hoãn sau lần giao/nhận việc.")
        return ItemStatus.PROPOSED, [ReviewReason.RULE_CONFLICT], None
    ly_do = [ReviewReason.IMPLICIT_SIGNAL] if cuoi.certainty == Certainty.TENTATIVE else []  # A3
    return ItemStatus.CONFIRMED, ly_do, None


def _luat_requirement_feedback(m: MucNhap, ctx: BoiCanh):
    cac_chap_nhan = [e for e in m.su_kien if e.act in (ActType.CONFIRM, ActType.ACCEPT_TASK)]
    if cac_chap_nhan:
        cuoi = cac_chap_nhan[-1]
        if any(e.act in (ActType.OBJECT, ActType.DEFER) for e in _sau_moc(m, cuoi, ctx)):
            m.ghi_chu.append(f"{m.id_tam}: có phản đối/hoãn sau lần chấp nhận.")
            return ItemStatus.PROPOSED, [ReviewReason.RULE_CONFLICT], None
        return ItemStatus.CONFIRMED, [], None
    if m.su_kien and m.su_kien[-1].act == ActType.DEFER:  # R2
        return ItemStatus.OPEN, [], None
    return ItemStatus.PROPOSED, [], None


def _luat_mo(m: MucNhap, ctx: BoiCanh):
    """Issue và OpenQuestion: mặc định `open`."""
    return ItemStatus.OPEN, [], None


_LUAT_THEO_LOAI = {
    "decision": _luat_decision,
    "goal": _luat_decision,  # G1: goal dùng đúng luật của decision
    "proposal": _luat_proposal,
    "action": _luat_action,
    "requirement_feedback": _luat_requirement_feedback,
    "issue": _luat_mo,
    "open_question": _luat_mo,
}


# ---------------------------------------------------------------------------
# Áp dụng luật cho cả danh sách mục
# ---------------------------------------------------------------------------


def _chi_so_cuoi(m: MucNhap, ctx: BoiCanh) -> int:
    return ctx.thu_tu[m.su_kien[-1].event_id] if m.su_kien else -1


def _chi_so_chot(m: MucNhap, ctx: BoiCanh) -> int:
    chot = [ctx.thu_tu[e.event_id] for e in m.su_kien if e.act == ActType.CONFIRM]
    return chot[-1] if chot else -1


def ap_dung_luat(ds: list[MucNhap], ctx: BoiCanh) -> list[str]:
    """Tính lại trạng thái cho mọi mục theo luật, trả về danh sách cảnh báo.

    Hàm sửa trực tiếp các MucNhap: trang_thai, ly_do, nguoi_chot, thay_the_boi,
    muc_bi_thay_ids, ghi_chu.
    """
    # Bước A: trạng thái theo luật cho từng mục, so với đề xuất của LLM.
    for m in ds:
        tt_luat, ly_do, nguoi = _LUAT_THEO_LOAI[m.loai](m, ctx)
        m.nguoi_chot = nguoi
        m.ly_do += ly_do
        de_xuat = m.trang_thai_llm
        if de_xuat == ItemStatus.SUPERSEDED:
            m.trang_thai = tt_luat  # tạm thời, bước B sẽ quyết định superseded có hợp lệ không
            continue
        co_phan_doi = any(e.act == ActType.OBJECT for e in m.su_kien)
        if (
            de_xuat == ItemStatus.REJECTED  # D6, R2
            and m.loai in ("decision", "proposal", "requirement_feedback")
            and tt_luat == ItemStatus.PROPOSED
            and co_phan_doi
        ):
            m.trang_thai = ItemStatus.REJECTED
            continue
        m.trang_thai = tt_luat
        if de_xuat != tt_luat:
            m.ly_do.append(ReviewReason.RULE_CONFLICT)
            m.ghi_chu.append(f"{m.id_tam}: LLM đề xuất '{de_xuat.value}' nhưng luật cho '{tt_luat.value}'.")

    # Bước B: kiểm tra các mục LLM cho là superseded (S1). Xét từ mục MUỘN đến sớm để mục
    # thay thế đã có trạng thái cuối trước khi dùng làm đích.
    theo_id = {m.id_tam: m for m in ds}
    for m in ds:
        if m.trang_thai_llm != ItemStatus.SUPERSEDED:
            m.thay_the_boi = None  # chỉ giữ liên kết khi mục thực sự bị thay thế
    for m in sorted(ds, key=lambda x: _chi_so_cuoi(x, ctx), reverse=True):
        if m.trang_thai_llm != ItemStatus.SUPERSEDED:
            continue
        dich = theo_id.get(m.thay_the_boi) if m.thay_the_boi else None
        hop_le = (
            dich is not None
            and dich is not m
            and ItemStatus.SUPERSEDED in TRANG_THAI_THEO_LOAI[m.loai]
            and (dich.thread_id == m.thread_id or m.loai == "issue")
            and (
                dich.loai == m.loai
                or m.loai == "issue"
                or (m.loai == "proposal" and dich.loai == "decision")
            )
            and _chi_so_cuoi(dich, ctx) > _chi_so_cuoi(m, ctx)
            and dich.trang_thai in (ItemStatus.CONFIRMED, ItemStatus.SUPERSEDED)
        )
        if hop_le:
            m.trang_thai = ItemStatus.SUPERSEDED
        else:
            m.thay_the_boi = None
            m.ly_do.append(ReviewReason.RULE_CONFLICT)
            m.ghi_chu.append(
                f"{m.id_tam}: LLM cho là bị thay thế nhưng mục thay thế không hợp lệ "
                f"(thiếu, sai luồng/loại, không xảy ra sau, hoặc chưa được chốt); giữ '{m.trang_thai.value}'."
            )

    # Bước C: D5, nhiều Decision cùng luồng cùng confirmed thì chốt muộn nhất thắng.
    theo_luong: dict[str, list[MucNhap]] = {}
    for m in ds:
        if m.loai == "decision" and m.trang_thai == ItemStatus.CONFIRMED:
            theo_luong.setdefault(m.thread_id, []).append(m)
    for ma_luong, cac_muc in theo_luong.items():
        if len(cac_muc) < 2:
            continue
        nguoi_thang = max(cac_muc, key=lambda x: _chi_so_chot(x, ctx))
        for m in cac_muc:
            m.ly_do.append(ReviewReason.RULE_CONFLICT)
            if m is not nguoi_thang:
                m.trang_thai = ItemStatus.SUPERSEDED
                m.thay_the_boi = nguoi_thang.id_tam
                m.ghi_chu.append(
                    f"{m.id_tam}: cùng luồng {ma_luong} có nhiều quyết định confirmed, "
                    f"lấy lần chốt muộn nhất ({nguoi_thang.id_tam})."
                )

    # Bước D: ghi quan hệ ngược (mục nào thay thế mục nào) và khử trùng lý do cờ.
    for m in sorted(ds, key=lambda x: _chi_so_cuoi(x, ctx)):
        if m.thay_the_boi and m.thay_the_boi in theo_id:
            theo_id[m.thay_the_boi].muc_bi_thay_ids.append(m.id_tam)
    for m in ds:
        m.ly_do = list(dict.fromkeys(m.ly_do))

    return [g for m in ds for g in m.ghi_chu]


# ---------------------------------------------------------------------------
# Suy ra thông tin cho cả luồng
# ---------------------------------------------------------------------------


def trang_thai_luong(cac_trang_thai: list[ItemStatus]) -> ItemStatus:
    """Trạng thái của cả luồng, suy từ các mục trong luồng theo thứ tự ưu tiên.

    Không có mục nào thì trả `open` (đây chỉ là giá trị quy ước, thread.note sẽ nói rõ
    luồng không có mục nghiệp vụ).
    """
    for tt in UU_TIEN_TRANG_THAI_LUONG:
        if tt in cac_trang_thai:
            return tt
    return ItemStatus.OPEN


def su_kien_quyet_dinh(cac_muc: list[MucNhap], ctx: BoiCanh) -> Optional[str]:
    """Sự kiện quyết định trạng thái của luồng: lần chốt của Decision confirmed (ưu tiên),
    rồi lần giao/nhận việc muộn nhất của Action confirmed, rồi lần chốt của Goal confirmed."""
    for loai, cac_act in (
        ("decision", (ActType.CONFIRM,)),
        ("action", (ActType.ASSIGN, ActType.ACCEPT_TASK)),
        ("goal", (ActType.CONFIRM,)),
    ):
        ung_vien = [
            e
            for m in cac_muc
            if m.loai == loai and m.trang_thai == ItemStatus.CONFIRMED
            for e in m.su_kien
            if e.act in cac_act
        ]
        if ung_vien:
            return max(ung_vien, key=lambda e: ctx.thu_tu[e.event_id]).event_id
    return None