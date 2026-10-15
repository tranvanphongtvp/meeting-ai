"""
schemas.py - Định nghĩa dữ liệu dùng chung cho MỌI bước của pipeline.

Vai trò: giống "biểu mẫu chung" giữa các phòng ban. Bước nào sinh ra dữ liệu
hay đọc dữ liệu đều phải theo đúng các mẫu ở đây, nên không bước nào phải đoán
cách đọc dữ liệu của bước trước.

Quy ước:
- Tên lớp, tên trường, giá trị trạng thái dùng tiếng Anh (khớp JSON đầu ra,
  prompt, luật trạng thái). Chú thích dùng tiếng Việt.
- File này CHỈ mô tả cấu trúc dữ liệu. Các luật nghiệp vụ (ví dụ "citation có
  thật không", "người chốt có thẩm quyền không") nằm ở s6_verify.py và
  state_rules.py. Lý do: dữ liệu sai thì phải bị GẮN CỜ needs_review, không
  được làm chương trình sập.
- Bộ trạng thái thống nhất: proposed, confirmed, rejected, superseded, open.
  Cờ riêng: needs_review (+ review_reasons). Không đổi tên ở nơi khác.

Sơ đồ dữ liệu đi qua các bước:
  Bước 1: Meeting + list[Turn]
  Bước 2 (LLM #1): ExtractionOutput  -> list[SpeechEvent]
  Bước 3-5 (LLM #2): ResolutionOutput -> list[Thread] + list[Item]
  Bước 6-7: kiểm chứng, gắn cờ -> MeetingRecord (đầu ra cuối)
"""

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class Base(BaseModel):
    """Lớp gốc cho mọi mẫu dữ liệu."""

    # Cấm trường lạ: nếu LLM tự bịa thêm trường ngoài schema thì bị bắt ngay,
    # thay vì lọt âm thầm vào kết quả.
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# 1. CÁC GIÁ TRỊ CỐ ĐỊNH (Enum)
# ---------------------------------------------------------------------------


class ItemStatus(str, Enum):
    """Trạng thái của một mục/vấn đề tại thời điểm KẾT THÚC cuộc họp."""

    PROPOSED = "proposed"      # có người đề xuất, chưa ai chốt hay bác rõ ràng
    CONFIRMED = "confirmed"    # có tín hiệu chốt rõ, người chốt có thẩm quyền, không bị đảo ngược
    REJECTED = "rejected"      # bị bác rõ ràng, không có phương án thay thế
    SUPERSEDED = "superseded"  # bị mục khác thay thế (kèm superseded_by)
    OPEN = "open"              # có bàn nhưng chưa có kết luận ("để xem lại", câu hỏi chưa trả lời)


class ActType(str, Enum):
    """Hành động lời nói: một lượt nói đang LÀM GÌ (bước 2).

    Lưu ý: ở bước này mô hình chưa được kết luận gì, chỉ nhận diện hành động.
    """

    PROPOSE = "propose"          # đề xuất
    AGREE = "agree"              # đồng ý
    OBJECT = "object"            # phản đối
    AMEND = "amend"              # sửa đổi một phần ("B nhưng dời hạn sang tuần sau")
    CONFIRM = "confirm"          # chốt
    ASSIGN = "assign"            # giao việc
    ACCEPT_TASK = "accept_task"  # nhận việc
    REQUEST = "request"          # yêu cầu
    FEEDBACK = "feedback"        # phản hồi, nhận xét về sản phẩm/quy trình
    BLOCKER = "blocker"          # nêu vướng mắc
    ASK = "ask"                  # đặt câu hỏi
    DEFER = "defer"              # hoãn ("để xem lại")
    SHARE_INFO = "share_info"    # chia sẻ thông tin


class Certainty(str, Enum):
    """Mức chắc chắn trong LỜI NÓI ("sẽ làm" khác "chắc là sẽ làm")."""

    FIRM = "firm"
    TENTATIVE = "tentative"


class AssignmentClarity(str, Enum):
    """Mức rõ ràng của việc giao cho một Action."""

    EXPLICIT = "explicit"      # giao rõ ràng: "Nam làm phần này"
    IMPLICIT = "implicit"      # giao ngầm: "để mình lo"
    UNASSIGNED = "unassigned"  # chưa có người nhận


class FeedbackKind(str, Enum):
    """Phân biệt yêu cầu và phản hồi (cùng một nhóm mục nghiệp vụ)."""

    REQUIREMENT = "requirement"  # yêu cầu: bên nào cần gì
    FEEDBACK = "feedback"        # phản hồi: nhận xét về sản phẩm/quy trình


class Sentiment(str, Enum):
    """Sắc thái của phản hồi (chỉ dùng khi kind = feedback)."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


class ReviewReason(str, Enum):
    """Lý do một mục bị gắn cờ needs_review (người duyệt xem lý do này đầu tiên)."""

    NO_EVIDENCE = "no_evidence"                # mục không có bằng chứng
    EVIDENCE_MISMATCH = "evidence_mismatch"    # trích dẫn không có trong lượt nói được dẫn
    SPEAKER_UNKNOWN = "speaker_unknown"        # người nói/người phụ trách không có trong roster
    DEADLINE_INVALID = "deadline_invalid"      # hạn chót không hợp lệ so với ngày họp
    DEADLINE_AMBIGUITY = "deadline_ambiguity"  # các bằng chứng diễn đạt deadline khác nhau
    RULE_CONFLICT = "rule_conflict"            # kết quả LLM mâu thuẫn với luật trạng thái
    IMPLICIT_SIGNAL = "implicit_signal"        # chốt ngầm, tín hiệu không rõ ràng
    AUTHORITY_UNCLEAR = "authority_unclear"    # người chốt không rõ có thẩm quyền không
    NO_OWNER = "no_owner"                      # việc chưa có người phụ trách
    CONTRADICTION = "contradiction"          # mục mâu thuẫn với mục khác (owner/hạn)
    INVALID_REFERENCE = "invalid_reference"  # tham chiếu hỏng: id treo, vòng thay thế, trạng thái sai loại

# ---------------------------------------------------------------------------
# 2. ĐẦU VÀO (bước 1)
# ---------------------------------------------------------------------------


class Participant(Base):
    """Một người trong danh sách người tham gia (roster)."""

    name: str
    aliases: list[str] = Field(default_factory=list)  # cách gọi khác: "anh Nam", "N."
    role: Optional[str] = None                        # vai trò: "Trưởng nhóm"...
    # Người có quyền chốt. Dùng để biết ai "chốt" thì tính là quyết định.
    can_decide: bool = False


class Meeting(Base):
    """Thông tin chung của một cuộc họp."""

    meeting_id: str
    meeting_date: date  # cần để quy đổi hạn tương đối ("thứ Sáu tới") thành ngày cụ thể
    title: Optional[str] = None
    participants: list[Participant]
    glossary: dict[str, str] = Field(default_factory=dict)  # thuật ngữ nội bộ: từ viết tắt -> nghĩa


class Turn(Base):
    """Một lượt nói sau khi chuẩn hoá (đầu ra bước 1)."""

    turn_id: str                  # "T001", "T002"... để mọi bước sau tham chiếu chính xác
    speaker: str                  # tên đã chuẩn hoá theo roster
    speaker_raw: str              # tên gốc trong transcript, giữ lại để lần lỗi
    speaker_known: bool = True    # False nếu không khớp được roster (đừng tự đoán)
    timestamp: str                # giữ nguyên dạng chuỗi, ví dụ "00:12:05"
    text: str                     # nội dung gốc, KHÔNG chỉnh sửa


# ---------------------------------------------------------------------------
# 3. BẰNG CHỨNG VÀ SỰ KIỆN (bước 2)
# ---------------------------------------------------------------------------


class Evidence(Base):
    """Bằng chứng gốc: trỏ về đúng lượt nói trong transcript."""

    turn_id: str
    speaker: str
    timestamp: str
    quote: str  # trích nguyên văn; bước 6 sẽ kiểm tra có thật trong lượt nói không


class SpeechEvent(Base):
    """Một hành động lời nói (đầu ra LLM #1)."""

    event_id: str                    # "E001", "E002"...
    turn_id: str
    speaker: str
    act: ActType
    topic_label: str                 # nhãn chủ đề tự do, ví dụ "chọn nhà cung cấp"
    quote: str                       # trích dẫn nguyên văn
    certainty: Certainty = Certainty.FIRM


class ExtractionOutput(Base):
    """Cấu trúc LLM #1 phải trả về."""

    events: list[SpeechEvent]


# ---------------------------------------------------------------------------
# 4. LUỒNG VẤN ĐỀ VÀ MỤC NGHIỆP VỤ (bước 3-5, LLM #2)
# ---------------------------------------------------------------------------


class Thread(Base):
    """Một luồng vấn đề: gom các sự kiện cùng một vấn đề, theo thứ tự thời gian.

    Đây là kết quả TRUNG GIAN, luôn được lưu ra file để lần lỗi. Khi kết quả
    sai, nhìn vào thread là biết sai ở khâu gom, khâu trạng thái hay khâu lập mục.
    """

    thread_id: str                              # "TH01", "TH02"...
    topic: str
    event_ids: list[str]                        # các sự kiện thuộc luồng, theo thời gian
    status: ItemStatus                          # trạng thái cuối của cả luồng
    decisive_event_id: Optional[str] = None     # sự kiện quyết định trạng thái cuối
    note: Optional[str] = None                  # ghi chú ngắn (ví dụ vì sao còn open)

class FindingSeverity(str, Enum):
    ERROR = "error"      # dữ liệu sai/mâu thuẫn: gắn cờ needs_review
    WARNING = "warning"  # đáng xem nhưng không chắc sai: chỉ ghi lại


class FindingKind(str, Enum):
    # V1: bằng chứng
    EVIDENCE_TURN_MISSING = "evidence_turn_missing"
    EVIDENCE_SPEAKER_MISMATCH = "evidence_speaker_mismatch"
    EVIDENCE_TIMESTAMP_MISMATCH = "evidence_timestamp_mismatch"
    EVIDENCE_QUOTE_MISMATCH = "evidence_quote_mismatch"
    EVIDENCE_QUOTE_DIACRITICS = "evidence_quote_diacritics"
    EVIDENCE_MISSING = "evidence_missing"
    # V2: mâu thuẫn giữa các việc
    OWNER_CONFLICT = "owner_conflict"
    DEADLINE_CONFLICT = "deadline_conflict"
    DUPLICATE_TASK = "duplicate_task"
    DEADLINE_AFTER_GOAL = "deadline_after_goal"
    # V3: bất biến của bản ghi
    DUPLICATE_ID = "duplicate_id"
    DANGLING_REFERENCE = "dangling_reference"
    SUPERSEDE_CYCLE = "supersede_cycle"
    SUPERSEDE_INCONSISTENT = "supersede_inconsistent"
    STATUS_NOT_ALLOWED = "status_not_allowed"
    STATUS_NOT_SUPPORTED = "status_not_supported"
    THREAD_INCONSISTENT = "thread_inconsistent"
    # V4: độ phủ
    UNCOVERED_EVENT = "uncovered_event"


class Finding(Base):
    """Một phát hiện của bước 6. Chỉ ghi lại, không tự sửa mục."""

    finding_id: str                                      # "F001"... ổn định giữa các lần chạy
    severity: FindingSeverity
    kind: FindingKind
    message: str                                         # mô tả ngắn, tiếng Việt
    item_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    thread_ids: list[str] = Field(default_factory=list)

class ItemBase(Base):
    """Phần chung của mọi mục nghiệp vụ."""
    event_ids: list[str] = Field(default_factory=list)  # sự kiện bước 2 làm căn cứ của mục
    item_id: str                                         # "I001", "I002"...
    summary: str
    status: ItemStatus
    thread_id: str                                       # mục thuộc luồng nào
    evidence: list[Evidence] = Field(default_factory=list)
    supersedes: Optional[str] = None                     # item_id mà mục này thay thế
    superseded_by: Optional[str] = None                  # item_id đã thay thế mục này
    # Kết quả kiểm chứng (bước 6-7). LLM không tự điền các trường này.
    needs_review: bool = False
    review_reasons: list[ReviewReason] = Field(default_factory=list)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class Decision(ItemBase):
    """Quyết định (và các phương án bị loại).

    CHỈ dùng khi phương án ĐÃ ĐƯỢC ai có thẩm quyền chốt (confirm).
    Phương án chưa bao giờ được chốt → dùng Proposal.
    """

    type: Literal["decision"] = "decision"
    decided_by: Optional[str] = None                     # người chốt
    rejected_options: list[str] = Field(default_factory=list)  # phương án bị loại, giữ làm bối cảnh
    rationale: Optional[str] = None                      # lý do chọn/loại, nếu có trong bằng chứng


class Proposal(ItemBase):
    """Đề xuất/phương án được nêu ra nhưng CHƯA BAO GIỜ được chốt thành quyết định.

    Dùng cho phương án bị loại (superseded), bị bác (rejected), hoặc chưa kết luận (proposed).
    Khác Decision: Decision là lựa chọn ĐÃ được ai có thẩm quyền chốt.
    """

    type: Literal["proposal"] = "proposal"
    proposed_by: Optional[str] = None                    # người đề xuất
    rejected_options: list[str] = Field(default_factory=list)
    rationale: Optional[str] = None


class Action(ItemBase):
    """Công việc cần làm sau cuộc họp."""

    type: Literal["action"] = "action"
    owner: Optional[str] = None                          # None = chưa có người nhận, KHÔNG tự điền
    deadline: Optional[date] = None                      # đã quy đổi theo ngày họp
    deadline_raw: Optional[str] = None                   # nguyên văn: "thứ Sáu tới"
    assignment_clarity: AssignmentClarity = AssignmentClarity.UNASSIGNED


class Goal(ItemBase):
    """Mục tiêu cấp dự án hoặc nhóm, có thể có deadline nhưng KHÔNG giao cho cá nhân cụ thể.

    Khác Action: Action là việc giao cho một người cụ thể (hoặc ít nhất cần có owner).
    Goal là đích đến chung mà cả nhóm/dự án hướng tới.
    """

    type: Literal["goal"] = "goal"
    deadline: Optional[date] = None                      # đã quy đổi theo ngày họp
    deadline_raw: Optional[str] = None                   # nguyên văn
    scope: Optional[str] = None                          # phạm vi: "nhóm", "dự án", "phòng ban"...


class OpenQuestion(ItemBase):
    """Vấn đề/câu hỏi chưa chốt."""

    type: Literal["open_question"] = "open_question"
    raised_by: Optional[str] = None
    awaiting: Optional[str] = None                       # đang chờ ai trả lời/quyết định


class Issue(ItemBase):
    """Vướng mắc/vấn đề đang cản trở công việc."""

    type: Literal["issue"] = "issue"
    raised_by: Optional[str] = None
    blocked_what: Optional[str] = None                   # cái gì đang bị cản
    cause: Optional[str] = None                          # nguyên nhân, chỉ điền nếu có trong bằng chứng
    can_unblock: Optional[str] = None                    # ai có thể gỡ, chỉ điền nếu có trong bằng chứng


class RequirementFeedback(ItemBase):
    """Yêu cầu hoặc phản hồi (phân biệt bằng trường kind)."""

    type: Literal["requirement_feedback"] = "requirement_feedback"
    kind: FeedbackKind
    raised_by: Optional[str] = None                      # bên đưa ra yêu cầu/phản hồi
    directed_to: Optional[str] = None                    # bên được yêu cầu / đối tượng phản hồi
    sentiment: Optional[Sentiment] = None                # chỉ dùng cho feedback
    # Phản hồi là ý kiến cá nhân hay đã thành kết luận chung của cuộc họp.
    is_group_conclusion: bool = False


# Mục nghiệp vụ: phân biệt loại bằng trường "type".
# 7 loại: Decision, Proposal, Action, Goal, Issue, RequirementFeedback, OpenQuestion.
# Knowledge (tri thức mới) để sau: viết thêm lớp rồi đưa vào Union này.
Item = Annotated[
    Union[Decision, Proposal, Action, Goal, Issue, RequirementFeedback, OpenQuestion],
    Field(discriminator="type"),
]


class ResolutionOutput(Base):
    """Cấu trúc LLM #2 phải trả về: luồng (kết quả trung gian) và mục nghiệp vụ."""

    threads: list[Thread]
    items: list[Item]


# ---------------------------------------------------------------------------
# 5. ĐẦU RA CUỐI (bước 7-9)
# ---------------------------------------------------------------------------


class MeetingRecord(Base):
    """Bản ghi cuộc họp có cấu trúc: đầu ra cuối cùng của pipeline."""
    findings: list[Finding] = Field(default_factory=list)   # kết quả kiểm chứng (bước 6)
    record_id: str
    created_at: datetime
    meeting: Meeting
    threads: list[Thread]
    items: list[Item]


# ---------------------------------------------------------------------------
# 6. QUY TẮC DÙNG CHUNG VỀ TRẠNG THÁI (một nguồn duy nhất, tránh lặp ở nhiều nơi)
# ---------------------------------------------------------------------------

# Trạng thái nào được chuyển sang trạng thái nào. state_rules.py và s6_verify.py
# cùng import bảng này, không tự định nghĩa lại.
# Lưu ý: rejected và superseded là trạng thái kết thúc. Nếu về sau có người đề xuất
# lại thì tạo MỤC MỚI (proposed), không chuyển trạng thái của mục cũ.
CHUYEN_TRANG_THAI_HOP_LE: dict[ItemStatus, set[ItemStatus]] = {
    ItemStatus.PROPOSED: {ItemStatus.CONFIRMED, ItemStatus.REJECTED, ItemStatus.SUPERSEDED},
    ItemStatus.CONFIRMED: {ItemStatus.SUPERSEDED},
    # open có thể được giải quyết trong cuộc họp: thành đề xuất/quyết định mới,
    # hoặc bị mục khác thay thế (ví dụ vướng mắc đã có cách gỡ).
    ItemStatus.OPEN: {ItemStatus.PROPOSED, ItemStatus.CONFIRMED, ItemStatus.SUPERSEDED},
    ItemStatus.REJECTED: set(),
    ItemStatus.SUPERSEDED: set(),
}

# Mỗi loại mục chỉ được dùng một số trạng thái nhất định.
TRANG_THAI_THEO_LOAI: dict[str, set[ItemStatus]] = {
    "decision": {
        ItemStatus.PROPOSED,
        ItemStatus.CONFIRMED,
        ItemStatus.REJECTED,
        ItemStatus.SUPERSEDED,
    },
    # Proposal chưa bao giờ được chốt → không có confirmed.
    "proposal": {
        ItemStatus.PROPOSED,
        ItemStatus.REJECTED,
        ItemStatus.SUPERSEDED,
    },
    # Action chỉ ghi trạng thái TẠI cuộc họp, không theo dõi tiến độ làm việc.
    "action": {ItemStatus.PROPOSED, ItemStatus.CONFIRMED, ItemStatus.SUPERSEDED},
    # Goal là mục tiêu cấp dự án/nhóm, tương tự Action nhưng không giao cá nhân.
    "goal": {ItemStatus.PROPOSED, ItemStatus.CONFIRMED, ItemStatus.SUPERSEDED},
    # Vướng mắc: còn vướng (open) hoặc đã có mục khác giải quyết (superseded).
    "issue": {ItemStatus.OPEN, ItemStatus.SUPERSEDED},
    # Yêu cầu/phản hồi: trạng thái cho biết cuộc họp đã chấp nhận chưa.
    #   proposed = mới nêu, chưa ai đáp (phản hồi thuần ý kiến thường ở đây)
    #   confirmed = được chấp nhận/ghi nhận; rejected = bị bác; open = đang bàn chưa kết
    "requirement_feedback": {
        ItemStatus.PROPOSED,
        ItemStatus.CONFIRMED,
        ItemStatus.REJECTED,
        ItemStatus.OPEN,
    },
    "open_question": {ItemStatus.OPEN},
}


def trang_thai_hop_le_cho_loai(
    item: Union[Decision, Proposal, Action, Goal, Issue, RequirementFeedback, OpenQuestion],
) -> bool:
    """True nếu trạng thái của mục nằm trong tập cho phép của loại mục đó."""
    return item.status in TRANG_THAI_THEO_LOAI[item.type]


def nhom_theo_loai(items: list) -> dict[str, list]:
    """Gom mục theo nhóm để báo cáo (bước 8) hiển thị đúng các nhóm quan trọng.

    Luôn trả về đủ 7 nhóm, kể cả nhóm rỗng, để người đọc thấy rõ "cuộc họp này
    không có vướng mắc nào" thay vì không biết hệ thống có tìm hay không.
    """
    nhom: dict[str, list] = {
        "decision": [],
        "proposal": [],
        "action": [],
        "goal": [],
        "issue": [],
        "requirement_feedback": [],
        "open_question": [],
    }
    for item in items:
        nhom[item.type].append(item)
    return nhom