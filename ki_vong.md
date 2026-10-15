# Đáp án kỳ vọng — Meeting Pipeline

Tài liệu này dùng làm **ground truth** để đối chiếu kết quả đầu ra của pipeline. Không đưa nội dung đáp án vào đầu vào pipeline khi chạy đánh giá.

---

## Case 1 — Đảo ngược quyết định (`case1_dao_nguoc`)

**Quyết định cuối cùng:** Chọn phương án B — xây dựng module tùy chỉnh quản lý quyền người dùng, thay thế phương án A — sử dụng framework có sẵn.

**Bằng chứng:** Minh ban đầu nghiêng về A, nhưng tại lượt 10 đã quyết định chuyển sang B và dừng triển khai A. Tại lượt 11, Nam đề xuất cân nhắc lại A, nhưng đây chỉ là đề xuất. Đến lượt 13, Minh xác nhận B vẫn là quyết định cuối cùng.

**Công việc:**
- **Nam:** Xây dựng module quản lý quyền người dùng theo phương án B. Deadline: `2026-10-16`.
- **Lan:** Kiểm thử đăng nhập, phân quyền và kiểm soát truy cập. Deadline: `2026-10-20`.

**MVP:** Hoàn thành trước ngày `2026-10-23`.

**Blocker và unresolved items:** Không có thông tin xác nhận blocker hoặc vấn đề chưa giải quyết trong transcript.

**Điểm cần kiểm tra:** Pipeline phải nhận diện đúng B thay thế A, không nhầm đề xuất quay lại A tại lượt 11 thành quyết định mới, đồng thời trích xuất đúng người phụ trách và deadline.

---

## Case 2 — Chốt ngầm (`case2_chot_ngam`)

**Quyết định ngầm:** Triển khai phương án B — thông báo trực tiếp trên website, không triển khai gửi email trong đợt này.

**Bằng chứng:** Minh ưu tiên người dùng nhìn thấy thông báo trên website; Nam xác nhận sẽ không làm chức năng gửi email; Minh đồng ý với phạm vi và yêu cầu nhóm triển khai theo kế hoạch.

**Công việc:**
- **Nam:** Xây dựng bảng thông báo, API lấy danh sách và API đánh dấu đã đọc. Deadline: `2026-10-18`.
- **Lan:** Kiểm thử thông báo và phân quyền liên quan. Deadline: `2026-10-21`.

**MVP:** Tích hợp trước ngày `2026-10-23`.

**Blocker và unresolved items:** Không có thông tin xác nhận blocker hoặc vấn đề chưa giải quyết.

**Điểm cần kiểm tra:** Pipeline phải suy luận được quyết định từ ngữ cảnh và sự đồng thuận, dù Minh không nói trực tiếp câu “Tôi chọn B”.

---

## Case 3 — Để xem lại (`case3_de_xem_lai`)

**Quyết định:** Chưa có quyết định cuối cùng giữa phương án A — sử dụng thư viện biểu đồ có sẵn — và phương án B — tự xây dựng thành phần biểu đồ. Cả hai vẫn đang được xem xét.

**Bằng chứng:** Minh nói rõ tại lượt 8 rằng chưa chốt phương án nào; tại lượt 11 yêu cầu không triển khai chính thức theo A hoặc B; tại lượt 16 xác nhận cả hai vẫn đang được xem xét.

**Công việc:**
- **Lan:** Kiểm tra hiệu năng thư viện A trên bộ dữ liệu lớn và gửi kết quả trước ngày `2026-10-16`.
- **Nam:** Tổng hợp các kiểu biểu đồ cần hỗ trợ và ước lượng thời gian phát triển phương án B. Deadline: `2026-10-16`.
- **Minh:** Xem kết quả đánh giá và tổ chức trao đổi lại ngày `2026-10-16` để quyết định phương án cuối cùng.

**MVP:** Hoàn thành trước ngày `2026-10-23`.

**Blocker:** Chưa có blocker được xác nhận. Việc thiếu dữ liệu đánh giá là lý do chưa thể ra quyết định, nhưng không nên tự động coi đó là blocker chính thức.

**Unresolved items:** Chưa xác định chọn A hay B; cần chờ kết quả kiểm tra hiệu năng và ước lượng công sức phát triển.

**Điểm cần kiểm tra:**
1. Không tự chọn A chỉ vì Nam đề xuất trước.
2. Không tự chọn B chỉ vì Lan nêu hạn chế của A.
3. Không nhầm nhiệm vụ khảo sát thành phát triển chính thức.
4. Không bỏ sót buổi trao đổi lại ngày `2026-10-16`.
5. Không ghi nhận A hoặc B là quyết định cuối cùng.

---

## Case 4 — Không chốt quyết định (`case4_khong_chot`)

**Quyết định:** Chưa chọn phương án A — tích hợp cổng thanh toán bên thứ ba — hay phương án B — tự xây dựng hệ thống thanh toán.

**Bằng chứng:** Minh xác nhận nhiều lần rằng chưa chốt phương án nào; cả A và B vẫn đang được cân nhắc.

**Công việc:**
- **Nam:** Khảo sát API và phí của các cổng thanh toán. Deadline: Chưa xác định.
- **Lan:** Tổng hợp thành phần cần xây dựng và rủi ro của phương án B. Deadline: Chưa xác định.

**MVP:** `2026-10-23`.

**Blocker:** Không có blocker chính thức được xác nhận.

**Unresolved items:** Chưa đủ thông tin để lựa chọn phương án và chưa xác định ngày chốt.

**Điểm cần kiểm tra:** Pipeline không được tự chọn A hoặc B, không tự tạo deadline, không nhầm việc khảo sát với triển khai và không tự động đánh dấu blocker khi chưa có bằng chứng rõ ràng.

---

## Case 5 — Giao việc ngầm (`case5_giao_viec_ngam`)

**Quyết định:** Nhóm thống nhất chuẩn bị dữ liệu sản phẩm và bộ kiểm thử tìm kiếm.

**Công việc:**
- **Nam:** Chuẩn hóa khoảng 100 sản phẩm gồm tên, mã và danh mục; kiểm tra dữ liệu trùng hoặc thiếu. Deadline: `2026-10-17`.
- **Lan:** Chuẩn bị từ khóa, kết quả mong đợi và các trường hợp kiểm thử tìm kiếm. Deadline: `2026-10-20`.

**Bằng chứng:** Nam và Lan chủ động nhận việc qua trao đổi; Minh đồng thuận với cách làm và xác định thời hạn.

**MVP:** `2026-10-23`.

**Blocker:** Không có blocker chính thức được xác nhận.

**Unresolved items:** Chưa có kết quả kiểm thử thực tế vì dữ liệu và bộ kiểm thử đang được chuẩn bị.

**Điểm cần kiểm tra:** Pipeline phải nhận diện được nhiệm vụ được giao gián tiếp qua ngữ cảnh, sự nhận trách nhiệm và sự đồng thuận; đồng thời gắn đúng người, công việc và deadline. Không được suy diễn thành nhiệm vụ xây dựng thuật toán tìm kiếm.

---

## Bảng tổng hợp các case

| Case | Tình huống cần kiểm tra | Kết quả kỳ vọng |
|---|---|---|
| Case 1 | Đảo ngược quyết định | B thay thế A |
| Case 2 | Chốt quyết định ngầm | Chọn B từ ngữ cảnh và sự đồng thuận |
| Case 3 | Để xem lại | Chưa chốt; chờ kết quả đánh giá |
| Case 4 | Không chốt quyết định | Hai phương án vẫn đang được cân nhắc, chưa có ngày chốt |
| Case 5 | Giao việc ngầm | Nhận diện đúng công việc, người phụ trách và deadline |

## Nguyên tắc đánh giá chung

1. Ưu tiên quyết định cuối cùng của người có quyền quyết định, không chỉ dựa vào tần suất nhắc đến phương án.
2. Phân biệt quyết định chính thức, quyết định ngầm và trạng thái chưa chốt.
3. Mỗi nhiệm vụ phải có người phụ trách, nội dung và deadline đúng theo transcript; nếu không có deadline thì ghi chưa xác định.
4. Phân biệt nhiệm vụ khảo sát, chuẩn bị và ước lượng với nhiệm vụ triển khai chính thức.
5. Không tự tạo blocker, quyết định, deadline hoặc vấn đề chưa giải quyết khi transcript không cung cấp đủ bằng chứng.
6. Ưu tiên bằng chứng trực tiếp từ transcript khi đối chiếu kết quả pipeline.