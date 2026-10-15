"""
s3_resolve.py - Bước 3-5 [LLM #2 + luật code]: Phân luồng và lập mục nghiệp vụ.

Làm gì: nhận danh sách sự kiện từ bước 2, nhờ LLM gom thành luồng vấn đề (Thread) và
đề xuất các mục nghiệp vụ (Decision, Proposal, Action, Goal, Issue, RequirementFeedback,
OpenQuestion). Sau đó CODE kiểm tra và dựng lại kết quả cuối.

Phân công LLM và code (hướng "lai", đã chốt với người dùng):
- LLM chỉ trả: luồng (thread_id, topic, event_ids, note) và mục (item_id, type, summary,
  thread_id, event_ids, status đề xuất, superseded_by, và vài trường mô tả như owner,
  deadline_raw, raised_by...).
- Code TỰ làm (không tin LLM):
  * evidence: dựng từ event_ids đã kiểm tra, lấy speaker/timestamp/quote từ dữ liệu gốc.
  * trạng thái: tính lại bằng luật (state_rules.py), luật thắng LLM + gắn rule_conflict.
  * thẩm quyền chốt, decided_by, assignment_clarity, supersedes, status và decisive_event
    của luồng.
  * hạn chót: LLM chép nguyên văn, code quy đổi (deadline_utils.py), kiểm tra cụm từ có thật
    trong lượt nói.
  * owner: phải có cơ sở trong lượt nói, tên phải khớp roster.
- Mục sai (sai định dạng, loại lạ, trạng thái không thuộc loại đó) bị BỎ kèm cảnh báo,
  các mục còn lại vẫn dùng. Cả lượt chỉ báo lỗi nếu không còn mục nào dùng được.
- JSON hỏng: thử lại tối đa SO_LAN_THU_LAI_JSON lần kèm lý do lỗi (dùng chung helper
  trong llm_client.py).

Chạy riêng bước này (đứng trong thư mục src):
    python s3_resolve.py <thu_muc_run> --dry-run   # chỉ dựng prompt, KHÔNG gọi LLM
    python s3_resolve.py <thu_muc_run>              # gọi LLM thật (cần GEMINI_API_KEY)
    python s3_resolve.py <thu_muc_run> --model <ten_model>
Trong đó <thu_muc_run> là thư mục đã có s1_turns.json và s2_events.json.
Kết quả ghi cùng thư mục: s3_threads.json và s3_raw_llm.json.
"""

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

from pydantic import ConfigDict, Field, ValidationError, field_validator

from deadline_utils import quy_doi_han_chot
from llm_client import GeminiClient, LoiCauHinh, goi_json_co_thu_lai
from s1_preprocess import KetQuaTienXuLy, _xay_dung_ban_do_ten, chuan_hoa_ten
from s2_extract_acts import KetQuaTrichXuat, _chuan_hoa_so_khop, _trich_dan_co_trong_luot
from schemas import (
    TRANG_THAI_THEO_LOAI,
    Action,
    ActType,
    AssignmentClarity,
    Base,
    Decision,
    Evidence,
    FeedbackKind,
    Goal,
    Issue,
    Item,
    ItemStatus,
    OpenQuestion,
    Proposal,
    RequirementFeedback,
    ReviewReason,
    Sentiment,
    SpeechEvent,
    Thread,
)
from state_rules import BoiCanh, MucNhap, ap_dung_luat, su_kien_quyet_dinh, trang_thai_luong

THU_MUC_GOC = Path(__file__).resolve().parent.parent
FILE_PROMPT = THU_MUC_GOC / "configs" / "prompts" / "resolve_threads.md"

# Số lần thử lại khi JSON hỏng (không tính lỗi API, lỗi API đã được llm_client xử lý).
SO_LAN_THU_LAI_JSON = 2

# Mã luồng dùng khi mục không xác định được luồng.
LUONG_CHUA_XAC_DINH = "UNASSIGNED"


# ---------------------------------------------------------------------------
# Dữ liệu
# ---------------------------------------------------------------------------


class KetQuaPhanGiai(Base):
    """Đầu ra bước 3: luồng + mục nghiệp vụ + thống kê + cờ lỗi."""

    threads: list[Thread]
    items: list[Item]
    thong_ke: dict[str, int]
    theo_loai: dict[str, int]
    canh_bao: list[str] = Field(default_factory=list)  # chạy tiếp được, nhưng nên xem
    loi: list[str] = Field(default_factory=list)       # không có kết quả dùng được
    su_dung_llm: dict[str, Any] = Field(default_factory=dict)

    @property
    def ok(self) -> bool:
        """True nếu không có lỗi nghiêm trọng, có thể dùng đầu ra."""
        return not self.loi


def _lam_sach_chuoi(gia_tri: Any) -> Any:
    """Cắt khoảng trắng; chuỗi rỗng hoặc "null"/"none" (LLM hay viết) thành None."""
    if isinstance(gia_tri, str):
        gia_tri = gia_tri.strip()
        if gia_tri.lower() in ("", "null", "none"):
            return None
    return gia_tri


class ThreadTho(Base):
    """Một luồng đúng như LLM trả về (bỏ qua trường lạ, code tự tính status và decisive)."""

    model_config = ConfigDict(extra="ignore")

    thread_id: str
    topic: str = ""
    event_ids: list[str] = Field(default_factory=list)
    note: Optional[str] = None

    @field_validator("thread_id", "topic", "note", mode="before")
    @classmethod
    def _chuoi(cls, v: Any) -> Any:
        return _lam_sach_chuoi(v) if v is not None else v

    @field_validator("event_ids", mode="before")
    @classmethod
    def _ds(cls, v: Any) -> Any:
        return _lam_ds_chuoi(v)


class MucTho(Base):
    """Một mục đúng như LLM trả về. Chỉ gồm trường LLM được phép điền."""

    model_config = ConfigDict(extra="ignore")

    item_id: str
    type: str
    summary: str
    status: str
    thread_id: Optional[str] = None
    event_ids: list[str] = Field(default_factory=list)
    superseded_by: Optional[str] = None
    rejected_options: list[str] = Field(default_factory=list)
    rationale: Optional[str] = None
    owner: Optional[str] = None
    deadline_raw: Optional[str] = None
    raised_by: Optional[str] = None
    proposed_by: Optional[str] = None
    blocked_what: Optional[str] = None
    cause: Optional[str] = None
    can_unblock: Optional[str] = None
    directed_to: Optional[str] = None
    awaiting: Optional[str] = None
    scope: Optional[str] = None
    kind: Optional[str] = None
    sentiment: Optional[str] = None
    is_group_conclusion: bool = False

    @field_validator(
        "item_id", "type", "summary", "status", "thread_id", "superseded_by", "rationale", "owner",
        "deadline_raw", "raised_by", "proposed_by", "blocked_what", "cause", "can_unblock",
        "directed_to", "awaiting", "scope", "kind", "sentiment",
        mode="before",
    )
    @classmethod
    def _chuoi(cls, v: Any, info) -> Any:
        v = _lam_sach_chuoi(v)
        if isinstance(v, str) and info.field_name in ("type", "status", "kind", "sentiment"):
            v = v.lower()
        return v

    @field_validator("event_ids", "rejected_options", mode="before")
    @classmethod
    def _ds(cls, v: Any) -> Any:
        return _lam_ds_chuoi(v)

    @field_validator("is_group_conclusion", mode="before")
    @classmethod
    def _bool(cls, v: Any) -> Any:
        return False if v is None else v


def _lam_ds_chuoi(v: Any) -> Any:
    """None thành [], một chuỗi đơn thành [chuỗi]; bỏ phần tử rỗng và trùng, giữ thứ tự."""
    if v is None:
        return []
    if isinstance(v, str):
        v = [v]
    if isinstance(v, list):
        sach = [_lam_sach_chuoi(x) for x in v]
        return list(dict.fromkeys(x for x in sach if isinstance(x, str) and x))
    return v


# ---------------------------------------------------------------------------
# Dựng nội dung gửi LLM
# ---------------------------------------------------------------------------


def xay_dung_noi_dung_nguoi_dung(
    s1: KetQuaTienXuLy,
    s2: KetQuaTrichXuat,
) -> str:
    """Ghép thông tin cuộc họp + sự kiện bước 2 + transcript thành user message.

    Gửi can_decide (khác bước 2): để LLM đặt trạng thái sơ bộ sát thực tế hơn, giảm số
    lần luật code phải sửa lại. Code vẫn kiểm tra lại thẩm quyền, LLM không có quyền quyết.
    """
    m = s1.meeting
    dong: list[str] = [
        "# Thông tin cuộc họp",
        f"Ngày họp: {m.meeting_date.isoformat()}",
    ]
    if m.title:
        dong.append(f"Tiêu đề: {m.title}")
    dong.append("Người tham gia (can_decide = có quyền chốt quyết định cho cả nhóm):")
    for nguoi in m.participants:
        chi_tiet: list[str] = []
        if nguoi.role:
            chi_tiet.append(nguoi.role)
        if nguoi.aliases:
            chi_tiet.append("còn gọi: " + ", ".join(nguoi.aliases))
        chi_tiet.append("can_decide=" + ("true" if nguoi.can_decide else "false"))
        dong.append(f"- {nguoi.name} ({'; '.join(chi_tiet)})")
    if m.glossary:
        dong.append("Thuật ngữ nội bộ:")
        dong += [f"- {k}: {v}" for k, v in m.glossary.items()]

    dong += ["", "# Danh sách sự kiện lời nói (đầu ra bước 2)"]
    dong.append("event_id | turn_id | speaker | act | topic_label | quote | certainty")
    for e in s2.events:
        dong.append(
            f"{e.event_id} | {e.turn_id} | {e.speaker} | {e.act.value} | "
            f"{e.topic_label} | {e.quote} | {e.certainty.value}"
        )

    dong += ["", "# Transcript gốc (dùng để tra bằng chứng nếu cần)"]
    dong += [
        f"{t.turn_id} [{t.timestamp}] {t.speaker}: {t.text}"
        for t in s1.turns
    ]
    return "\n".join(dong)


# ---------------------------------------------------------------------------
# Đọc JSON của LLM
# ---------------------------------------------------------------------------


def _doc_json(text: str) -> dict:
    """Đọc JSON từ đầu ra LLM. Chịu được khối ```json … ```."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    du_lieu = json.loads(t)
    if not isinstance(du_lieu, dict):
        raise ValueError("JSON phải là một đối tượng (object), không phải mảng.")
    if not isinstance(du_lieu.get("threads"), list):
        raise ValueError('JSON thiếu khoá "threads" là danh sách.')
    if not isinstance(du_lieu.get("items"), list):
        raise ValueError('JSON thiếu khoá "items" là danh sách.')
    return du_lieu


def _tom_tat_loi(loi: ValidationError) -> str:
    """Rút gọn lỗi Pydantic thành một dòng."""
    return "; ".join(
        f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in loi.errors()[:3]
    )


# ---------------------------------------------------------------------------
# Hạn chót: kiểm tra cụm từ có thật, quy đổi ra ngày, phát hiện mơ hồ
# ---------------------------------------------------------------------------

# Dấu phân tách các diễn đạt hạn chót khác nhau trong deadline_raw (theo prompt: " | ").
# Chịu được LLM viết "|" không có khoảng trắng.
_MAU_TACH_DIEN_DAT = re.compile(r"\s*\|\s*")
# Chú thích cuối mỗi diễn đạt do prompt yêu cầu, ví dụ "(Minh, T006)".
_MAU_CHU_THICH = re.compile(r"\s*\([^()]*\bT\d+\b[^()]*\)\s*$", re.IGNORECASE)


def _tach_dien_dat(raw: str) -> list[str]:
    """Tách deadline_raw thành các diễn đạt riêng, bỏ phần rỗng."""
    return [p for p in _MAU_TACH_DIEN_DAT.split(raw) if p.strip()]


def _bo_chu_thich(dien_dat: str) -> str:
    """Bỏ chú thích "(Tên, Txxx)" ở cuối để còn đúng cụm từ nguyên văn."""
    return _MAU_CHU_THICH.sub("", dien_dat).strip()


def _xu_ly_han_chot(
    raw: Optional[str],
    van_ban_luot_chuan_hoa: str,
    ngay_hop: date,
    ly_do: list[ReviewReason],
    canh_bao: list[str],
    nhan: str,
) -> Optional[date]:
    """Quy đổi deadline_raw ra ngày; gắn lý do cờ vào `ly_do`; trả ngày hoặc None.

    - Mỗi diễn đạt phải xuất hiện trong lượt nói của mục, không thì evidence_mismatch.
    - Diễn đạt đầu không có thật trong lượt nói thì KHÔNG quy đổi (tránh dùng ngày bịa).
    - Nhiều diễn đạt (ngăn bằng "|") thì quy đổi diễn đạt đầu và gắn deadline_ambiguity.
    - Không quy đổi được (mơ hồ, ngày đã qua, dạng chưa hỗ trợ) thì deadline_invalid.
    """
    if not raw:
        return None
    cac_dien_dat = _tach_dien_dat(raw)
    if not cac_dien_dat:
        return None
    sach = [_bo_chu_thich(d) for d in cac_dien_dat]

    khong_co = [d for d in sach if _chuan_hoa_so_khop(d) not in van_ban_luot_chuan_hoa]
    if khong_co:
        ly_do.append(ReviewReason.EVIDENCE_MISMATCH)
        canh_bao.append(
            f"{nhan}: hạn chót '{khong_co[0]}' không có trong các lượt nói làm bằng chứng của mục."
        )
    if len(cac_dien_dat) >= 2:
        ly_do.append(ReviewReason.DEADLINE_AMBIGUITY)
        canh_bao.append(
            f"{nhan}: hạn chót có nhiều diễn đạt khác nhau: '{raw}' — cần người dùng xác nhận."
        )
    if sach[0] in khong_co:
        return None

    ngay = quy_doi_han_chot(sach[0], ngay_hop)
    if ngay is None:
        ly_do.append(ReviewReason.DEADLINE_INVALID)
        canh_bao.append(
            f"{nhan}: không quy đổi được hạn chót '{sach[0]}' (mơ hồ, đã qua, hoặc chưa hỗ trợ) "
            "— người dùng cần kiểm tra và nhập ngày cụ thể."
        )
    return ngay


# ---------------------------------------------------------------------------
# Dựng từng mục
# ---------------------------------------------------------------------------


class _BoiCanhDung:
    """Dữ liệu dùng chung khi dựng mục (gom lại cho khỏi truyền nhiều tham số)."""

    def __init__(self, s1: KetQuaTienXuLy, canh_bao: list[str]):
        self.ngay_hop: date = s1.meeting.meeting_date
        self.luot_theo_id = {t.turn_id: t for t in s1.turns}
        self.ban_do_ten, _ = _xay_dung_ban_do_ten(s1.meeting)
        self.canh_bao = canh_bao

    def chuan_hoa_nguoi(self, ten: Optional[str], ly_do: list[ReviewReason]) -> Optional[str]:
        """Đưa tên về tên chính thức trong roster. Không có trong roster: giữ nguyên + speaker_unknown.

        Roster rỗng thì không gắn cờ (không có gì để đối chiếu).
        """
        if not ten:
            return None
        chinh_thuc = self.ban_do_ten.get(chuan_hoa_ten(ten))
        if chinh_thuc:
            return chinh_thuc
        if self.ban_do_ten:
            ly_do.append(ReviewReason.SPEAKER_UNKNOWN)
        return ten

    def van_ban_luot(self, su_kien: list[SpeechEvent]) -> str:
        """Nội dung (đã chuẩn hoá) các lượt nói của sự kiện, nối lại để tra cụm từ."""
        luot = dict.fromkeys(e.turn_id for e in su_kien)
        return " ".join(_chuan_hoa_so_khop(self.luot_theo_id[t].text) for t in luot)


def _dung_bang_chung(su_kien: list[SpeechEvent], bc: _BoiCanhDung, ly_do: list[ReviewReason]) -> list[Evidence]:
    """Dựng evidence từ sự kiện. Speaker/timestamp lấy từ lượt nói gốc, không từ LLM."""
    ket_qua: list[Evidence] = []
    da_thay: set[tuple[str, str]] = set()
    for e in su_kien:
        luot = bc.luot_theo_id[e.turn_id]
        if not _trich_dan_co_trong_luot(e.quote, luot.text):
            ly_do.append(ReviewReason.EVIDENCE_MISMATCH)
        khoa = (e.turn_id, e.quote)
        if khoa in da_thay:
            continue
        da_thay.add(khoa)
        ket_qua.append(
            Evidence(turn_id=e.turn_id, speaker=luot.speaker, timestamp=luot.timestamp, quote=e.quote)
        )
    return ket_qua


def _nguoi_dau_tien(su_kien: list[SpeechEvent], uu_tien: tuple[ActType, ...]) -> Optional[str]:
    """Người nói của sự kiện đầu tiên thuộc `uu_tien`, không có thì của sự kiện đầu tiên."""
    for e in su_kien:
        if e.act in uu_tien:
            return e.speaker
    return su_kien[0].speaker if su_kien else None


def _co_so_cho_ten(ten: str, su_kien: list[SpeechEvent], van_ban_luot: str, bc: _BoiCanhDung) -> bool:
    """Tên người phụ trách có cơ sở: là người nói trong các sự kiện, hoặc được nhắc trong lượt nói."""
    cac_khoa = {chuan_hoa_ten(ten)} | {k for k, v in bc.ban_do_ten.items() if v == ten}
    if any(chuan_hoa_ten(e.speaker) in cac_khoa for e in su_kien):
        return True
    return any(k and k in van_ban_luot for k in cac_khoa)


def _dung_muc(
    m: MucNhap,
    ma_moi: dict[str, str],
    tom_tat: dict[str, str],
    bc: _BoiCanhDung,
) -> Item:
    """Dựng Decision/Proposal/Action/Goal/Issue/RequirementFeedback/OpenQuestion từ MucNhap."""
    raw: MucTho = m.raw
    ly_do: list[ReviewReason] = list(m.ly_do)
    nhan = ma_moi[m.id_tam]
    if not m.su_kien:
        ly_do.append(ReviewReason.NO_EVIDENCE)
        bc.canh_bao.append(f"{nhan}: mục không có sự kiện nào làm bằng chứng.")
    van_ban = bc.van_ban_luot(m.su_kien)

    chung: dict[str, Any] = dict(
        item_id=nhan,
        summary=raw.summary,
        status=m.trang_thai,
        thread_id=m.thread_id,
        evidence=_dung_bang_chung(m.su_kien, bc, ly_do),
        event_ids=[e.event_id for e in m.su_kien],
        supersedes=ma_moi.get(m.muc_bi_thay_gan_nhat) if m.muc_bi_thay_gan_nhat else None,
        superseded_by=ma_moi.get(m.thay_the_boi) if m.thay_the_boi else None,
    )

    def chon_ten(ten_llm: Optional[str], mac_dinh: Optional[str]) -> Optional[str]:
        return bc.chuan_hoa_nguoi(ten_llm or mac_dinh, ly_do)

    if m.loai == "decision":
        thay_the = [tom_tat[i] for i in m.muc_bi_thay_ids if i in tom_tat]
        item: Item = Decision(
            decided_by=bc.chuan_hoa_nguoi(m.nguoi_chot, ly_do),
            # LLM nêu tên phương án bị loại thì dùng; không nêu thì lấy tóm tắt các mục bị thay.
            rejected_options=raw.rejected_options or list(dict.fromkeys(thay_the)),
            rationale=raw.rationale,
            **chung,
            needs_review=False,
        )
    elif m.loai == "proposal":
        item = Proposal(
            proposed_by=chon_ten(raw.proposed_by, _nguoi_dau_tien(m.su_kien, (ActType.PROPOSE,))),
            rejected_options=raw.rejected_options,
            rationale=raw.rationale,
            **chung,
        )
    elif m.loai == "action":
        cac_act = {e.act for e in m.su_kien}
        cac_nhan = [e for e in m.su_kien if e.act == ActType.ACCEPT_TASK]
        owner = chon_ten(raw.owner, cac_nhan[-1].speaker if cac_nhan else None)
        if owner is None:
            ly_do.append(ReviewReason.NO_OWNER)
        elif not _co_so_cho_ten(owner, m.su_kien, van_ban, bc):
            ly_do.append(ReviewReason.EVIDENCE_MISMATCH)
            bc.canh_bao.append(f"{nhan}: owner '{owner}' không có cơ sở trong các lượt nói làm bằng chứng.")
        if ActType.ASSIGN in cac_act:
            ro_rang = AssignmentClarity.EXPLICIT
        elif ActType.ACCEPT_TASK in cac_act:
            ro_rang = AssignmentClarity.IMPLICIT
        else:
            ro_rang = AssignmentClarity.UNASSIGNED
        item = Action(
            owner=owner,
            deadline=_xu_ly_han_chot(raw.deadline_raw, van_ban, bc.ngay_hop, ly_do, bc.canh_bao, nhan),
            deadline_raw=raw.deadline_raw,
            assignment_clarity=ro_rang,
            **chung,
        )
    elif m.loai == "goal":
        item = Goal(
            deadline=_xu_ly_han_chot(raw.deadline_raw, van_ban, bc.ngay_hop, ly_do, bc.canh_bao, nhan),
            deadline_raw=raw.deadline_raw,
            scope=raw.scope,
            **chung,
        )
    elif m.loai == "issue":
        item = Issue(
            raised_by=chon_ten(raw.raised_by, _nguoi_dau_tien(m.su_kien, (ActType.BLOCKER, ActType.FEEDBACK))),
            blocked_what=raw.blocked_what,
            cause=raw.cause,
            can_unblock=raw.can_unblock,
            **chung,
        )
    elif m.loai == "requirement_feedback":
        try:
            loai_yc = FeedbackKind(raw.kind) if raw.kind else None
        except ValueError:
            loai_yc = None
        if loai_yc is None:
            loai_yc = (
                FeedbackKind.REQUIREMENT
                if any(e.act == ActType.REQUEST for e in m.su_kien)
                else FeedbackKind.FEEDBACK
            )
            bc.canh_bao.append(f"{nhan}: thiếu/sai 'kind', tạm đặt '{loai_yc.value}' theo hành động trong sự kiện.")
        try:
            cam_xuc = Sentiment(raw.sentiment) if raw.sentiment else None
        except ValueError:
            cam_xuc = None
            bc.canh_bao.append(f"{nhan}: sentiment '{raw.sentiment}' không hợp lệ, bỏ.")
        item = RequirementFeedback(
            kind=loai_yc,
            raised_by=chon_ten(raw.raised_by, _nguoi_dau_tien(m.su_kien, (ActType.REQUEST, ActType.FEEDBACK))),
            directed_to=raw.directed_to,
            sentiment=cam_xuc,
            is_group_conclusion=raw.is_group_conclusion,
            **chung,
        )
    else:  # open_question
        item = OpenQuestion(
            raised_by=chon_ten(raw.raised_by, _nguoi_dau_tien(m.su_kien, (ActType.ASK, ActType.DEFER))),
            awaiting=raw.awaiting,
            **chung,
        )

    item.review_reasons = list(dict.fromkeys(ly_do))
    item.needs_review = bool(item.review_reasons)
    return item


# ---------------------------------------------------------------------------
# Xử lý toàn bộ đầu ra của LLM (thuần code, kiểm thử được không cần mạng)
# ---------------------------------------------------------------------------


def xu_ly_dau_ra(
    s1: KetQuaTienXuLy,
    s2: KetQuaTrichXuat,
    du_lieu: dict,
) -> KetQuaPhanGiai:
    """Biến JSON thô của LLM thành luồng + mục đã kiểm tra (chưa có su_dung_llm)."""
    canh_bao: list[str] = []
    loi: list[str] = []
    luot_theo_id = {t.turn_id: t for t in s1.turns}
    su_kien_theo_id = {e.event_id: e for e in s2.events}
    thu_tu = {e.event_id: i for i, e in enumerate(s2.events)}

    for e in s2.events:
        if e.turn_id not in luot_theo_id:
            loi.append(f"Sự kiện {e.event_id} trỏ tới {e.turn_id} không có trong s1_turns.json (s1 và s2 không cùng lượt chạy?).")
    if loi:
        return KetQuaPhanGiai(threads=[], items=[], thong_ke={}, theo_loai={}, canh_bao=canh_bao, loi=loi)

    # --- 1. Luồng ---
    ma_luong_moi: dict[str, str] = {}      # mã LLM đặt -> TH01...
    luong_cua_su_kien: dict[str, str] = {}  # event_id -> mã luồng mới
    luong_nhap: list[dict] = []
    for stt, tho in enumerate(du_lieu["threads"], start=1):
        try:
            th = ThreadTho.model_validate(tho)
        except ValidationError as e:
            canh_bao.append(f"Bỏ luồng #{stt}: sai định dạng ({_tom_tat_loi(e)}).")
            continue
        if th.thread_id in ma_luong_moi:
            canh_bao.append(f"Bỏ luồng #{stt}: thread_id '{th.thread_id}' bị trùng.")
            continue
        moi = f"TH{len(luong_nhap) + 1:02d}"
        ids: list[str] = []
        for eid in th.event_ids:
            if eid not in su_kien_theo_id:
                canh_bao.append(f"Luồng {th.thread_id}: bỏ event_id không tồn tại: {eid}.")
            elif eid in luong_cua_su_kien:
                canh_bao.append(
                    f"Luồng {th.thread_id}: {eid} đã thuộc luồng {luong_cua_su_kien[eid]}, chỉ giữ ở luồng đầu."
                )
            else:
                ids.append(eid)
        if not ids:
            canh_bao.append(f"Bỏ luồng {th.thread_id}: không còn sự kiện hợp lệ nào.")
            continue
        ma_luong_moi[th.thread_id] = moi
        for eid in ids:
            luong_cua_su_kien[eid] = moi
        ids.sort(key=thu_tu.__getitem__)
        luong_nhap.append({"thread_id": moi, "topic": th.topic or "(không rõ chủ đề)", "event_ids": ids, "note": th.note})

    chua_vao_luong = [
        e.event_id for e in s2.events if e.event_id not in luong_cua_su_kien and e.act != ActType.SHARE_INFO
    ]
    if chua_vao_luong:
        canh_bao.append(f"Các sự kiện chưa thuộc luồng nào (có thể bị bỏ sót): {chua_vao_luong}.")

    # --- 2. Mục nháp ---
    nguoi_theo_ten = {p.name: p for p in s1.meeting.participants}
    ctx = BoiCanh(thu_tu=thu_tu, nguoi_theo_ten=nguoi_theo_ten)
    ds: list[MucNhap] = []
    khoa_da_dung: set[str] = set()
    so_muc_bi_bo = 0
    for stt, tho in enumerate(du_lieu["items"], start=1):
        try:
            m = MucTho.model_validate(tho)
        except ValidationError as e:
            canh_bao.append(f"Bỏ mục #{stt}: sai định dạng ({_tom_tat_loi(e)}).")
            so_muc_bi_bo += 1
            continue
        if m.type not in TRANG_THAI_THEO_LOAI:
            canh_bao.append(f"Bỏ mục {m.item_id}: loại '{m.type}' không có trong schema.")
            so_muc_bi_bo += 1
            continue
        try:
            trang_thai = ItemStatus(m.status)
        except ValueError:
            canh_bao.append(f"Bỏ mục {m.item_id}: trạng thái '{m.status}' không có trong schema.")
            so_muc_bi_bo += 1
            continue
        if trang_thai not in TRANG_THAI_THEO_LOAI[m.type]:
            canh_bao.append(
                f"Bỏ mục {m.item_id}: loại '{m.type}' không được dùng trạng thái '{trang_thai.value}'."
            )
            so_muc_bi_bo += 1
            continue

        ids = []
        for eid in m.event_ids:
            if eid in su_kien_theo_id:
                ids.append(eid)
            else:
                canh_bao.append(f"Mục {m.item_id}: bỏ event_id không tồn tại: {eid}.")
        ids.sort(key=thu_tu.__getitem__)

        thread_id = ma_luong_moi.get(m.thread_id) if m.thread_id else None
        if thread_id is None and ids:
            thread_id = luong_cua_su_kien.get(ids[0])
        if thread_id is None:
            thread_id = LUONG_CHUA_XAC_DINH
            canh_bao.append(f"Mục {m.item_id}: không xác định được luồng, đặt '{LUONG_CHUA_XAC_DINH}'.")

        khoa = m.item_id
        if khoa in khoa_da_dung:
            khoa = f"{m.item_id}#{stt}"
            canh_bao.append(f"Mục #{stt}: item_id '{m.item_id}' bị trùng, đổi nội bộ thành '{khoa}'.")
        khoa_da_dung.add(khoa)
        ds.append(
            MucNhap(
                id_tam=khoa,
                loai=m.type,
                thread_id=thread_id,
                su_kien=[su_kien_theo_id[e] for e in ids],
                trang_thai_llm=trang_thai,
                thay_the_boi=m.superseded_by,
                raw=m,
            )
        )

    if du_lieu["items"] and not ds:
        loi.append("Mọi mục LLM trả về đều bị bỏ (xem cảnh báo). Kiểm tra s3_raw_llm.json.")
        return KetQuaPhanGiai(
            threads=[], items=[], thong_ke={"so_muc_bi_bo": so_muc_bi_bo}, theo_loai={},
            canh_bao=canh_bao, loi=loi,
        )

    # --- 3. Luật trạng thái (luật thắng LLM) ---
    canh_bao += ap_dung_luat(ds, ctx)

    # --- 4. Đánh lại mã I001..., dựng mục kiểu đầy đủ ---
    thu_tu_dung = sorted(
        range(len(ds)),
        key=lambda i: (thu_tu[ds[i].su_kien[0].event_id] if ds[i].su_kien else len(thu_tu), i),
    )
    ma_moi = {ds[i].id_tam: f"I{n:03d}" for n, i in enumerate(thu_tu_dung, start=1)}
    tom_tat = {m.id_tam: m.raw.summary for m in ds}
    bc = _BoiCanhDung(s1, canh_bao)
    items: list[Item] = []
    muc_theo_ma: dict[str, MucNhap] = {}
    for i in thu_tu_dung:
        m = ds[i]
        try:
            items.append(_dung_muc(m, ma_moi, tom_tat, bc))
            muc_theo_ma[ma_moi[m.id_tam]] = m
        except ValidationError as e:
            canh_bao.append(f"Bỏ mục {m.id_tam}: lỗi khi dựng ({_tom_tat_loi(e)}).")
            so_muc_bi_bo += 1

    # --- 5. Luồng: trạng thái và sự kiện quyết định do code suy ra ---
    threads: list[Thread] = []
    for l in luong_nhap:
        cac_muc_luong = [muc_theo_ma[it.item_id] for it in items if it.thread_id == l["thread_id"]]
        note = l["note"]
        if not cac_muc_luong and not note:
            note = "Luồng này không có mục nghiệp vụ nào được lập."
        threads.append(
            Thread(
                thread_id=l["thread_id"],
                topic=l["topic"],
                event_ids=l["event_ids"],
                status=trang_thai_luong([m.trang_thai for m in cac_muc_luong]),
                decisive_event_id=su_kien_quyet_dinh(cac_muc_luong, ctx),
                note=note,
            )
        )

    thong_ke = {
        "so_luong": len(threads),
        "so_muc": len(items),
        "so_muc_can_xem_lai": sum(1 for it in items if it.needs_review),
        "so_muc_bi_bo": so_muc_bi_bo,
    }
    theo_loai: dict[str, int] = {}
    for it in items:
        theo_loai[it.type] = theo_loai.get(it.type, 0) + 1
    return KetQuaPhanGiai(
        threads=threads, items=items, thong_ke=thong_ke, theo_loai=theo_loai,
        canh_bao=canh_bao, loi=loi,
    )


# ---------------------------------------------------------------------------
# Hàm chính bước 3
# ---------------------------------------------------------------------------


def phan_giai(
    s1: KetQuaTienXuLy,
    s2: KetQuaTrichXuat,
    client,
    system_prompt: str,
    so_lan_thu_lai: int = SO_LAN_THU_LAI_JSON,
) -> tuple[KetQuaPhanGiai, list[dict]]:
    """Gọi LLM #2, kiểm tra và dựng kết quả bước 3.

    client: đối tượng có phương thức generate_json(system_prompt, user_content).
    Trả về (ket_qua, nhat_ky_tho). Nhật ký lưu toàn bộ lần gọi để lần lỗi.
    """
    noi_dung = xay_dung_noi_dung_nguoi_dung(s1, s2)
    du_lieu, loi_cuoi, nhat_ky, su_dung_llm = goi_json_co_thu_lai(
        client, system_prompt, noi_dung, _doc_json, so_lan_thu_lai
    )
    if du_lieu is None:
        return (
            KetQuaPhanGiai(threads=[], items=[], thong_ke={}, theo_loai={}, loi=[loi_cuoi], su_dung_llm=su_dung_llm),
            nhat_ky,
        )

    ket_qua = xu_ly_dau_ra(s1, s2, du_lieu)
    ket_qua.su_dung_llm = su_dung_llm
    if ket_qua.ok and not ket_qua.items:
        ket_qua.canh_bao.append(
            "LLM không lập mục nghiệp vụ nào. Nếu cuộc họp có nội dung, hãy xem s3_raw_llm.json."
        )
    return ket_qua, nhat_ky


# ---------------------------------------------------------------------------
# Đọc/ghi file
# ---------------------------------------------------------------------------


def luu_ket_qua(
    ket_qua: KetQuaPhanGiai,
    nhat_ky: list[dict],
    thu_muc_run: str | Path,
) -> Path:
    """Ghi s3_threads.json (kết quả) và s3_raw_llm.json (nhật ký thô)."""
    thu_muc_run = Path(thu_muc_run)
    thu_muc_run.mkdir(parents=True, exist_ok=True)
    duong_dan = thu_muc_run / "s3_threads.json"
    duong_dan.write_text(
        json.dumps(ket_qua.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (thu_muc_run / "s3_raw_llm.json").write_text(
        json.dumps(nhat_ky, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return duong_dan


# ---------------------------------------------------------------------------
# Chạy riêng bước 3
# ---------------------------------------------------------------------------


def _chay_rieng() -> int:
    """Chạy riêng bước 3 từ command line."""
    parser = argparse.ArgumentParser(
        description="Chạy riêng bước 3: phân luồng và lập mục nghiệp vụ"
    )
    parser.add_argument(
        "thu_muc_run",
        help="thư mục đã có s1_turns.json và s2_events.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="chỉ dựng prompt, KHÔNG gọi LLM",
    )
    parser.add_argument(
        "--model",
        help="ghi đè tên mô hình (mặc định lấy từ GEMINI_MODEL_RESOLVE hoặc GEMINI_MODEL)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        help="nhiệt độ lấy mẫu (bỏ qua = mặc định của API)",
    )
    args = parser.parse_args()

    thu_muc_run = Path(args.thu_muc_run)

    # Kiểm tra file đầu vào.
    file_s1 = thu_muc_run / "s1_turns.json"
    file_s2 = thu_muc_run / "s2_events.json"
    for f in (file_s1, file_s2):
        if not f.exists():
            ten_buoc = "bước 1 (s1_preprocess.py)" if f == file_s1 else "bước 2 (s2_extract_acts.py)"
            print(f"LỖI: không thấy {f}. Chạy {ten_buoc} trước.")
            return 2

    s1 = KetQuaTienXuLy.model_validate_json(file_s1.read_text(encoding="utf-8"))
    if not s1.ok:
        print("LỖI: bước 1 còn lỗi, sửa transcript trước:")
        for loi in s1.loi:
            print(f"  - {loi}")
        return 1

    s2 = KetQuaTrichXuat.model_validate_json(file_s2.read_text(encoding="utf-8"))
    if not s2.ok:
        print("LỖI: bước 2 còn lỗi, xem s2_events.json trước:")
        for loi in s2.loi:
            print(f"  - {loi}")
        return 1
    if not s2.events:
        print("LỖI: bước 2 không có sự kiện nào. Kiểm tra s2_events.json và chạy lại bước 2.")
        return 1

    system_prompt = FILE_PROMPT.read_text(encoding="utf-8")
    noi_dung = xay_dung_noi_dung_nguoi_dung(s1, s2)

    if args.dry_run:
        duong_dan = thu_muc_run / "s3_prompt.txt"
        duong_dan.write_text(
            "=== SYSTEM PROMPT ===\n"
            + system_prompt
            + "\n\n=== NỘI DUNG GỬI ===\n"
            + noi_dung,
            encoding="utf-8",
        )
        print("Chế độ dry-run: KHÔNG gọi LLM.")
        print(
            f"Độ dài: system prompt {len(system_prompt)} ký tự, "
            f"nội dung gửi {len(noi_dung)} ký tự."
        )
        print(f"Đã ghi toàn bộ nội dung sẽ gửi để bạn kiểm tra: {duong_dan}")
        return 0

    # Xác định model: --model > GEMINI_MODEL_RESOLVE > GEMINI_MODEL (do GeminiClient xử lý).
    model_arg = args.model or os.environ.get("GEMINI_MODEL_RESOLVE") or None

    try:
        client = GeminiClient(model=model_arg, temperature=args.temperature)
    except LoiCauHinh as loi:
        print(f"LỖI CẤU HÌNH: {loi}")
        return 2

    print(f"Đang gọi mô hình '{client.model}' ...")
    ket_qua, nhat_ky = phan_giai(s1, s2, client, system_prompt)
    duong_dan = luu_ket_qua(ket_qua, nhat_ky, thu_muc_run)

    print(f"Thống kê: {ket_qua.thong_ke}")
    print(f"Theo loại: {ket_qua.theo_loai}")
    print(f"LLM: {ket_qua.su_dung_llm}")
    for c in ket_qua.canh_bao:
        print(f"CẢNH BÁO: {c}")
    for e in ket_qua.loi:
        print(f"LỖI: {e}")
    print(f"Đã ghi: {duong_dan}")
    return 0 if ket_qua.ok else 1


if __name__ == "__main__":
    sys.exit(_chay_rieng())