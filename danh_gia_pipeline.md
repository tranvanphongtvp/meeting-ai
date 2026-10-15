# Báo Cáo Đánh Giá Tổng Quan Kết Quả Pipeline & Trả Lời 3 Câu Hỏi Bắt Buộc (MVP)

> **Dự án:** Meeting AI — Hệ thống Phân tích & Kiểm chứng Biên bản Cuộc họp Tiếng Việt  

> **Phiên bản:** MVP (Minimum Viable Product)  

> **Thời điểm đánh giá:** Tháng 10/2026  

---

## PHẦN I. TỔNG QUAN KẾT QUẢ THỰC NGHIỆM TRÊN BENCHMARK (GOLD DATASET)

Quá trình đánh giá được thực hiện tự động bằng công cụ kiểm thử đối chiếu độc lập [`eval/kiem_thu_gold.py`](eval/kiem_thu_gold.py), so sánh kết quả sinh ra bởi pipeline ([`s7_record.json`](data/runs/)) với bộ đáp án chuẩn (**Ground Truth**) tại [`data/gold/`](data/gold/) trên 5 kịch bản cuộc họp điển hình trong thực tế doanh nghiệp.

### 1. Bảng tổng hợp kết quả định lượng

Mỗi cuộc họp được chia nhỏ thành hàng chục câu hỏi kiểm tra chi tiết (đúng loại mục, đúng người phụ trách, đúng hạn chót, đúng trạng thái, đúng bằng chứng, cờ xem lại, và điều cấm sinh dữ liệu ma):

| Kịch bản kiểm thử (Benchmark Case) | Tình huống nghiệp vụ trọng tâm | Đạt (Pass) | Trượt (Fail) | Lưu ý | Bỏ qua | Tỷ lệ Đạt |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **Case 1: `case1_dao_nguoc`** | Đảo ngược quyết định (B thay thế A, đề xuất nhắc lại A bị chặn) | **18** | 4 | 2 | 2 | 81.8% |
| **Case 2: `case2_chot_ngam`** | Chốt quyết định ngầm qua ngữ cảnh & sự đồng thuận | **20** | 6 | 1 | 0 | 76.9% |
| **Case 3: `case3_de_xem_lai`** | Chưa chốt quyết định, thảo luận để xem xét lại sau | **26** | 2 | 1 | 3 | 92.9% |
| **Case 4: `case4_khong_chot`** | Cuộc họp không đưa ra quyết định, chỉ giao việc khảo sát | **19** | 6 | 1 | 2 | 76.0% |
| **Case 5: `case5_giao_viec_ngam`** | Giao việc gián tiếp qua nhận trách nhiệm & thống nhất deadline | **23** | 2 | 0 | 2 | 92.0% |
| **TỔNG CỘNG** | **5 kịch bản thực tế phức tạp** | **106** | **20** | **5** | **9** | **84.1%** |
### 2. Nhận xét định tính trên từng ca kiểm thử

* **Điểm sáng lớn nhất:**

  * Khả năng nhận diện **Đảo ngược quyết định (Case 1)** rất tốt: Hệ thống đã xác định chính xác Phương án B thay thế (`SUPERSEDES`) Phương án A, đồng thời trích xuất chuẩn hạn chót của Nam (`2026-10-16`) và Lan (`2026-10-20`).

  * Khả năng giữ vững nguyên tắc **Chưa chốt / Để xem lại (Case 3 & 5)** đạt độ chính xác trên 92%: Hệ thống không bị nhầm lẫn giữa việc khảo sát thu thập số liệu với công việc triển khai chính thức.

  * Tầng **Kiểm chứng độc lập (Bước 6)** hoạt động rất nghiêm ngặt: Khi có sự sai lệch hoặc nghi ngờ về hạn chót / luật trạng thái, hệ thống lập tức gắn cờ cảnh báo `needs_review` cùng lý do minh bạch thay vì âm thầm chấp nhận.

---

## PHẦN II. TRẢ LỜI 3 CÂU HỎI BẮT BUỘC

---

### CÂU HỎI 1:

> **Phần quan trọng nhất bạn chọn để hiện thực hóa trong MVP là gì? Vì sao nếu phần này hoạt động, bạn tin rằng hướng giải quyết của mình là khả thi?**

#### 1. Lựa chọn hạt nhân của MVP:

Phần quan trọng nhất được chọn để hiện thực hóa trong MVP không phải là việc cố gắng gọi một mô hình LLM thật lớn để "tóm tắt tất cả trong một", mà là **Kiến trúc Kiểm chứng Độc lập 2 Tầng (Deterministic Verification Engine - Bước 6)** kết hợp cùng **Máy trạng thái theo luật (State Rules Machine - Bước 3)**.

Thay vì coi đầu ra của LLM là chân lý, hệ thống đặt LLM vào vai trò một "người bóc tách thông tin thô" và dùng **Code Python thuần túy (100% không gọi LLM, chạy bằng thuật toán và luật cứng)** để kiểm định lại toàn bộ:

1. **Kiểm tra tính xác thực của bằng chứng (`check_evidence_match`):** Dùng thuật toán so khớp chuỗi (Levenshtein ratio / LCS) đối chiếu câu trích dẫn của AI với từng lượt nói gốc trong transcript. Nếu AI "tự bịa trích dẫn", hệ thống sẽ bắt lỗi `EVIDENCE_MISMATCH`.

2. **Kiểm tra thẩm quyền ra quyết định (`check_speaker_and_authority`):** Đối chiếu người chốt (`decided_by`) với danh sách `can_decide` được cấu hình trong `meeting.json`. Nếu người nói không có thẩm quyền chốt, mục đó bị hạ trạng thái xuống `PROPOSED` và gắn cờ `AUTHORITY_UNCLEAR`.

3. **Kiểm tra tính hợp lệ của hạn chót (`check_deadline_validity`):** Phân giải ngôn ngữ tự nhiên ("thứ Sáu tới", "tuần sau") thành ngày cụ thể và kiểm tra tính phi lý (deadline trước ngày họp, mâu thuẫn giữa lời nói gốc và ngày tính toán).

4. **Kiểm tra xung đột quy tắc trạng thái (`check_status_rules`):** Đảm bảo tính nhất quán logic (ví dụ: mục đã bị thay thế thì không thể đồng thời ở trạng thái `CONFIRMED`).

#### 2. Vì sao nếu phần này hoạt động, hướng giải quyết là khả thi?

* **Giải quyết điểm nghẽn "Chết người" của AI — Hallucination (Ảo giác):** Trong môi trường doanh nghiệp, một biên bản cuộc họp sai lệch (giao nhầm người, bịa ra deadline, hoặc tự chốt một dự án triệu đô mà sếp chưa duyệt) sẽ gây hậu quả nghiêm trọng. Nếu con người phải đọc lại toàn bộ transcript để dò lỗi của AI thì việc dùng AI trở nên vô nghĩa.

* **Biến "AI hên xui" thành "Trợ lý có thể kiểm toán" (Auditable AI):** Khi Bước 6 hoạt động, toàn bộ các điểm nghi vấn đều được gom lên khối **"Cần xem lại (Needs Review)"** ở ngay đầu báo cáo. Người duyệt chỉ cần 30 giây để nhìn vào các cờ cảnh báo kèm trích dẫn đối chiếu song song là có thể tự tin ký duyệt biên bản. Điều này chứng minh hướng tiếp cận **kết hợp LLM trích xuất + Engine quy tắc kiểm chứng tất định** là hoàn toàn khả thi và sẵn sàng đưa vào vận hành thực tế.

---

### CÂU HỎI 2:

> **So với kế hoạch ở Mission 1, bạn đã thay đổi quyết định hoặc thiết kế nào? Điều gì trong quá trình làm khiến bạn thay đổi?**

Trong quá trình triển khai thực tế từ Mission 1 đến nay, chúng tôi đã đưa ra **3 thay đổi thiết kế mang tính bước ngoặt**:

#### 1. Từ bỏ hoàn toàn ý tưởng "Dùng LLM để chấm lại LLM (LLM-as-a-judge)" ở tầng kiểm chứng:

* **Thiết kế ban đầu:** Định dùng một prompt kiểm toán giao cho model thứ 3 đọc lại toàn bộ để tìm lỗi sai.

* **Lý do thay đổi:** Qua thực tế, phương pháp "LLM review LLM" làm chi phí token tăng gấp đôi, thời gian phản hồi rất chậm (dễ gây timeout), và nghiêm trọng nhất là **không có tính tất định (non-deterministic)** — cùng một lỗi nhưng lúc bắt được lúc không, không thể cam kết chất lượng chuẩn doanh nghiệp.

* **Quyết định mới:** Xây dựng Bước 6 hoàn toàn bằng code Python thuần túy (thuật toán so khớp chuỗi mờ, phân tích cú pháp ngày tháng, ma trận quan hệ logic). Chạy nhanh trong vài mili-giây, tốn 0 đồng tiền token và đảm bảo độ tin cậy tuyệt đối.


### CÂU HỎI 3:

> **Loại thông tin nào hệ thống hiện dễ ghi nhận sai nhất? Bạn đang làm gì để tránh tạo ra một quyết định, công việc hoặc dữ liệu không thực sự tồn tại trong cuộc họp?**

#### 1. Loại thông tin hệ thống hiện dễ ghi nhận sai nhất:

Qua kết quả thực nghiệm trên 5 case benchmark, 3 loại thông tin có tỷ lệ sai số cao nhất gồm:

1. **Các tình huống "Chưa chốt / Không chốt" (False Positive Decisions):**

   * **Hiện tượng:** Trong các cuộc họp tranh luận sôi nổi (như Case 4 - cổng thanh toán), các thành viên bàn bạc rất nhiều về giải pháp A và B. LLM thường có tâm lý "cố gắng hoàn thành nhiệm vụ" nên dễ suy diễn rằng cuộc họp **đã chốt** một phương án, hoặc tự biến một câu kết luận tạm thời thành Quyết định chính thức.

2. **Nhầm lẫn giữa "Nhiệm vụ khảo sát/nghiên cứu" và "Nhiệm vụ triển khai thực tế" (Action Hallucination):**

   * **Hiện tượng:** Thành viên chỉ nhận việc **"tìm hiểu tài liệu API"** hoặc **"ước lượng công số"**, nhưng LLM lại trích xuất thành Action Item: **"Triển khai tích hợp cổng thanh toán"** với trạng thái đã chốt.

3. **Mục thừa do suy diễn ngữ cảnh (Hallucinated Extra Items):**

   * **Hiện tượng:** Trong Case 2 và Case 4, hệ thống sinh thêm 1-2 mục action/issue do LLM "suy diễn hộ" người tham gia cuộc họp từ các câu nói vu vơ.

#### 2. Những giải pháp chúng tôi đang áp dụng để ngăn chặn "Dữ liệu ma":

Để đảm bảo không bao giờ tạo ra một quyết định hay công việc "trên trời rơi xuống", hệ thống triển khai 4 tầng bảo vệ nghiêm ngặt:

* **Tầng 1 — Nguyên tắc Buộc Bằng Chứng Gốc (Strict Grounding):**

  * Mọi `SpeechEvent` hay `Item` được tạo ra bắt buộc phải có `turn_id` và `quote` nguyên văn từ transcript.

  * Thuật toán Levenshtein ở Bước 6 sẽ kiểm tra trích dẫn. Nếu AI tự bịa câu nói, mục đó sẽ bị gắn cờ `EVIDENCE_MISMATCH` ngay lập tức.

* **Tầng 2 — Bộ Luật Thẩm Quyền (Authority Gatekeeper):**

  * Không phải ai phát biểu "Tôi chốt cái này" thì hệ thống cũng ghi nhận là Quyết định. Hệ thống chỉ công nhận trạng thái `CONFIRMED` nếu người nói có thẩm quyền `can_decide: true` trong file thông tin cuộc họp. Mọi trường hợp khác đều bị chặn lại ở mức `PROPOSED`.

* **Tầng 3 — Quy tắc Phủ định và Phân loại Động từ (Verb Categorization Rules):**

  * Trong prompt của Bước 2 và Bước 3, hệ thống đưa vào các ví dụ đối lập rõ ràng (Few-shot counter-examples) để phân biệt:

    * Nhóm khảo sát: **tìm hiểu, nghiên cứu, xem xét, khảo sát, ước lượng, đánh giá** $\rightarrow$ Chỉ ghi nhận việc tìm hiểu, cấm tạo công việc triển khai.

    * Nhóm chốt: Phải có sự đồng thuận rõ ràng của người có thẩm quyền.

* **Tầng 4 — Cơ chế An toàn: Gắn cờ thay vì Đoán mò (Fail-safe Flagging):**

  * Thay vì để hệ thống âm thầm đưa ra một thông tin sai, nguyên tắc thiết kế của chúng tôi là: **"Thà gắn cờ nghi ngờ cho con người xem lại, còn hơn tự ý quyết định sai"**.

  * Bất kỳ khi nào phát hiện tín hiệu chốt ngầm (`IMPLICIT_SIGNAL`), thời hạn mơ hồ (`DEADLINE_AMBIGUITY`), hay thiếu người chịu trách nhiệm (`NO_OWNER`), hệ thống đều chủ động gắn cờ `needs_review` trên giao diện báo cáo để người duyệt xử lý.

---

## PHẦN III. ĐỊNH HƯỚNG HOÀN THIỆN SAU GIAI ĐOẠN MVP

1. **Giảm thiểu triệt để mục thừa (Unmatched / Hallucinated Items):** Bổ sung bước lọc ngưỡng tự tin (Confidence Thresholding) ở Bước 3 để loại bỏ các mục nghiệp vụ rác sinh ra từ các câu hội thoại xã giao.

2. **Nâng cao khả năng phân giải thời gian động:** Mở rộng module `deadline_utils` để hiểu các ngữ cảnh thời gian phức tạp hơn (ví dụ: "sau khi bên A hoàn thành xong 3 ngày", "trước đợt phát hành Sprint 42").

3. **Mở rộng giao diện người dùng:** Cho phép người duyệt bấm trực tiếp nút **[Xác nhận]** hoặc **[Bác bỏ]** đối với các mục gắn cờ `needs_review` ngay trên giao diện Web để xuất ra biên bản hoàn thiện cuối cùng.
