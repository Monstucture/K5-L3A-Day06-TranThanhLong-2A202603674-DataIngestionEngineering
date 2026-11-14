# Báo cáo cá nhân — Day 6

Trần Thanh Long · 2A202603674 · L3A

## Dữ liệu và pipeline
- **Chủ đề, nguồn/quyền, số trang và quy tắc tính trang:** OpenStax *Anatomy & Physiology 2e*, chương 1–2. File `data/anatomy-and-physiology-2e_70pages.pdf` là trích trang 23–100 của bản đầy đủ: **78 trang vật lý, 62 trang nội dung được tính** (ch. 1: trang 1–26, ch. 2: trang 35–70). Quy tắc: tính trang có nội dung bài học (đoạn văn, hình kèm chú thích, bảng, hộp kiến thức); loại trang Key Terms, Chapter Review, câu hỏi ôn tập cuối chương và trang trốn.
- **Chuẩn hóa, lỗi và giới hạn:** đọc bằng pypdf, chuẩn hóa Unicode NFKC, gộp khoảng trắng, xóa header/footer lặp lại, nhưng giữ xuống dòng để chunk theo cấu trúc. Chương được phát hiện từ dòng Chapter trong text, section từ các section heading. Log lỗi: `starter/results/ingestion_log.json`; trang 34 rỗng (0 ký tự, đã nằm ngoài các trang được tính), không có trang lỗi trích xuất, không cần OCR. Giới hạn: ranh giới đoạn được đoán từ cuối dòng (dòng kết thúc bằng `.`, các mẫu bài header/section chỉ đúng với bố cục OpenStax.
- **Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí:** `qwen3-embedding:4b` chạy local bằng Ollama 0.40.16, **2560 chiều**. Query có instruction prefix `Instruct: Given a question, retrieve passages from a textbook that answer it\nQuery: `, document không có prefix. PostgreSQL 16 + pgvector 0.8.7, khoảng cách cosine `<=>`, **exact search** (không tạo HNSW/IVFFlat vì pgvector chỉ index tối đa 2000 chiều; corpus nhỏ nên quét toàn bộ vẫn nhanh). **Chi phí: my vram**.
- **Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:** mỗi chunk có `document_id`, `source` (tên file PDF), `page` và `page_end` (chunk của B/C có thể nối sang trang sau), `char_start`. Trường lọc: **`chapter` (int: 1 hoặc 2)**, lấy từ dòng `CHAPTER N` của chính trang mở chương rồi gán cho các trang sau, không đoán tay; chọn vì nhiều khái niệm (pressure, temperature, energy, water, metabolism) xuất hiện ở cả hai chương, nên giới hạn chương có ý nghĩa với câu hỏi kiểu "trong chương hóa học…". B/C lưu thêm `section` và `section_title`

## Cấu hình và benchmark
- **A / B / C:**
  - **A:** cửa sổ cố định 500 ký tự, overlap 50, theo từng trang, không filter (368 chunk).
  - **B:** chunk theo section, tối đa 500 ký tự: gom đoạn văn/câu trọn vẹn, không bao giờ vượt qua heading section, được nối sang trang sau nếu vẫn cùng section; không filter (390 chunk, 35 chunk nối hai trang).
  - **C:** dùng **đúng chunk và index của B**, chỉ thêm filter `chapter` cho câu hỏi có filter (câu không có filter chạy như B).
  - **Khác biệt duy nhất B–C là metadata filter.** A–B chỉ đổi cách chunk (cùng ngân sách 500 ký tự, cùng model, cùng store).
- **≥20 câu:** 34 câu trong `benchmark/questions.json`, **24 dev / 10 test**, chia trước khi chạy. Loại câu: direct 11, comparison 11, paraphrase 6, metadata_filter 5, condition 1. **5 câu có filter `chapter`** (dev: q12, q14, q26; test: q04, q29); câu hỏi tự nêu phạm vi ("In the chemistry chapter…") nên filter không lấy từ đáp án. Kiểm chứng evidence: mỗi `evidence_quote` được chép nguyên văn và kiểm tra tự động là có trên `gold_page` sau chuẩn hóa (`run.py` dừng nếu thiếu); `gold_page` là số trang của file PDF (đã sửa từ số trang in của sách). Nguy cơ rò rỉ: trang 2 là trang gold của 2 câu test (q05, q06) và 2 câu dev (q01, q07), dù hỏi các ý khác nhau.
- **Tiêu chí chọn chiến lược đã chốt trước khi xem test:** Chọn chiến lược có Evidence Hit@3 trên dev cao nhất; nếu bằng nhau thì chọn Hit@1 dev cao hơn; nếu vẫn bằng thì chọn chiến lược đơn giản hơn / ít chunk hơn. Mọi điều chỉnh tham số chỉ dựa trên dev. Test chỉ chạy một lần sau khi đã chốt.

## Kết quả
# Chapter 1 & 2 of the book
| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 13/24 | 18/24 | 368 | 12.6 s | 0 |
| B | dev | 18/24 | 20/24 | 390 | 12.0 s | 0 |
| C | dev | 18/24 | 20/24 | 390 | 12.0 s | 0 |
| A | test | 5/10 | 9/10 | 368 | 12.4 s | 0 |
| B | test | 8/10 | 10/10 | 390 | 11.8 s | 0 |
| C | test | 8/10 | 10/10 | 390 | 11.8 s | 0 |

Thời gian = embed toàn bộ chunk của index trên laptop (upsert thêm khoảng 0,3 s). Độ dài chunk: A trung bình 462 ký tự (63–500), B trung bình 396 ký tự (27–500).

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 1 (10) | N/A | N/A (không filter) | 0 / 2 / 8 — 1.8 |
| B | 1 (10) | N/A | N/A (không filter) | 0 / 3 / 7 — 1.7 |
| C | 1 (10, cùng chunk với B) | 30/30 | 2/2 (q04, q29) | 0 / 3 / 7 — 1.7 |

# Full book (Cho demo only didn't check reports and runs)
| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 13/24 | 17/24 | 6356 | 229.3 s | 0 |
| B | dev | 18/24 | 20/24 | 6675 | 210.5 s | 0 |
| C | dev | 18/24 | 20/24 | 6675 | 210.5 s | 0 |

miss "q18", "q23", "q24", "q33" ; Same miss bởi vì không đổi cách chunk lẫn phân loại metadata từ bảng trên

| A | test | 5/10 | 9/10 | 6356 | 221.4s s | 0 |
| B | test | 8/10 | 10/10 | 6675 | 212.8 s | 0 |
| C | test | 8/10 | 10/10 | 6675 | 212.8 s | 0 |

Thời gian = embed toàn bộ chunk của index trên laptop (upsert thêm khoảng 0,3 s). Độ dài chunk: A trung bình 462 ký tự (63–500), B trung bình 396 ký tự (27–500).


**Đường dẫn trace, nhãn thủ công và cách chọn mẫu:**
- Trace top-3 đầy đủ: `starter/results/traces_dev.jsonl`, `starter/results/traces_test.jsonl`; chỉ số: `summary_dev.json`, `summary_test.json`.
- Coherence: `starter/results/coherence_labels_test.csv`. 10 vị trí chọn **trước khi chấm**: giữa trang (theo ký tự) của 10 trang cách đều trong 62 trang được tính (trang 1, 7, 13, 19, 25, 40, 46, 52, 58, 64); với mỗi chiến lược lấy chunk chứa vị trí đó.
- Metadata: `starter/results/metadata_audit_labels.csv`, 10 câu test × top-3 × 3 chiến lược = 90 bản ghi.
- Grounding: `starter/results/grounding_labels_test.csv`, 10 câu test × 3 chiến lược.
- **Cách gán nhãn (cột `labeled_by`):** metadata được kiểm tra tự động với text PDF (text chunk có nằm trên đúng trang/khoảng trang, chương đúng, filter đúng); 2 nhãn tác giả nhập tay trùng với kết quả tự động. Coherence và grounding do AI (Claude) chấm nháp kèm lý do theo thang 0–2 của GUIDE; tác giả xem lại từng nhãn và chịu trách nhiệm nhãn cuối cùng. 1 nhãn coherence (pos01/A = 2) do tác giả tự chấm.

## Phân tích và kết luận
- **So sánh A–B và B–C; 2 ví dụ sai có ID câu và nguồn:**
  - **A–B (chỉ đổi cách chunk):** B tốt hơn rõ ở Hit@1 (dev 18/24 so với 13/24; test 8/10 so với 5/10) và Hit@3 (dev 20/24 so với 18/24; test 10/10 so với 9/10). Coherence B 1.5 so với A 1.1: 9/10 chunk của A bắt đầu hoặc kết thúc giữa từ ("gadro's number", "At so"). Grounding A nhỉnh hơn (1.8 so với 1.7) vì cửa sổ A dài hơn trung bình (462 so với 396 ký tự) nên đôi khi mang thêm ngữ cảnh (q05: A có cả định nghĩa anatomy và physiology, B chỉ có câu "anatomy is about structure, physiology is about function"). Chi phí và thời gian gần như bằng nhau.
  - **B–C (chỉ đổi filter):** Hit@1/Hit@3 giống hệt trên cả dev và test. Lý do: với cả 5 câu có filter, B đã xếp chunk gold ở hạng 1, và 4/5 câu có top-3 toàn chunk đúng chương, nên filter không đổi được hit. Filter vẫn có tác dụng thấy được ở câu còn lại: dev q12, B có kết quả hạng 3 thuộc chương 2 (trang 47, §2.3), C thay bằng chunk chương 1. C tuân thủ filter 2/2 câu test. Kết luận: trên corpus nhỏ 2 chương, filter `chapter` đảm bảo phạm vi nhưng không cải thiện xếp hạng.
  - **Ví dụ sai 1 — test q06, chiến lược A (nguồn: trang 2):** câu evidence "Microscopic anatomy includes cytology, the study of cells and histology, the study of tissues." bị cửa sổ cố định cắt đôi: A:…:p002:c004 bắt đầu ở "the study of cells and histology…". Đúng trang (page hit) nhưng không chunk nào chứa đủ evidence nên Hit@3 = 0. B giữ trọn câu trong B:…:s1.1:c004 và đạt Hit@1.
  - **Ví dụ sai 2 — dev q18, chiến lược B (nguồn: trang 19):** câu hỏi về ba mặt phẳng giải phẫu; evidence là gạch đầu dòng về sagittal plane. B trả về chunk frontal/transverse plane (trang 19–20) và đoạn mở đầu về mặt phẳng, chunk chứa câu sagittal không vào top-3: các gạch đầu dòng gần như giống nhau về nghĩa nên cạnh tranh nhau. A lại đúng vì cửa sổ 500 ký tự gộp phần mở đầu với câu sagittal.
  - **Lỗi chung cả ba chiến lược:** dev q23, q24, q33 là câu so sánh rộng (ví dụ q33 so sánh triglyceride, phospholipid, steroid và protein); top-3 toàn chunk về lipid (trang 62–64) nên câu evidence về protein không được lấy. Câu hỏi bao nhiều ý nhưng evidence chỉ là một câu.
- **Chiến lược chọn, đánh đổi, điều kiện áp dụng:** theo tiêu chí đã chốt: Hit@3 dev B = C = 20/24 > A 18/24; Hit@1 dev B = C = 18/24; hòa nên chọn chiến lược đơn giản hơn: **B** (C cần thêm đầu vào filter mà không tăng chỉ số). Test xác nhận B ≥ A và B = C. Đánh đổi: B cần đoán cấu trúc (heading, đoạn) và tạo một số chunk rất ngắn (27 ký tự: heading bị tách) nhưng giữ câu trọn vẹn; A đơn giản, không phụ thuộc bố cục nhưng hay cắt evidence. Nên dùng C khi người dùng thật sự chỉ định phạm vi và corpus có nhiều chương/tài liệu dễ nhầm; với 2 chương như ở đây, B là đủ.
- **Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí:**
  - Test chỉ 10 câu: một câu sai làm thay đổi 10 điểm phần trăm; chênh lệch B–C bằng 0 không chứng minh filter vô ích.
  - Nhãn coherence/grounding do AI chấm nháp và một người (tác giả) xem lại: có nguy cơ thiên lệch, chưa có người chấm độc lập.
  - Hit yêu cầu chunk chứa **toàn bộ** evidence nên quote dài bất lợi cho chunk ngắn; câu so sánh nhiều ý chỉ có một câu evidence.
  - 4 câu (2 dev, 2 test) có gold ở trang 2 → rủi ro rò rỉ giữa dev và test.
  - Thiết kế B được đổi từ chunk theo đoạn sang chunk theo section sau khi xem kết quả dev đầu tiên (Hit@1 B: 19/24 → 18/24, Hit@3 giữ 20/24), trước khi chạy test; mọi số dev trong báo cáo là của thiết kế cuối.
  - Các câu filter ở dev không đủ mơ hồ để B lẫn chương, nên chưa đo được lợi ích xếp hạng của filter.
  - Thời gian đo một lần trên một laptop (GPU cục bộ), không lặp lại; chi phí 0 không tính điện năng.
  - Mẫu header/chương/section chỉ áp dụng cho bố cục OpenStax.
- **Nếu làm lại hoặc mở rộng, cải tiến gì?**
  - Thêm câu filter thật sự mơ hồ (cùng thuật ngữ ở nhiều chương) và mở rộng corpus nhiều chương/nhiều sách để đo đúng tác dụng của C; thử filter theo `section`.
  - Thêm overlap nhỏ hoặc gộp heading với đoạn kế tiếp để B không tạo chunk chỉ có heading.
  - Thử hybrid retrieval (BM25 + dense) cho các câu có thuật ngữ chính xác (q18, q23).
  - Viết câu so sánh với nhiều evidence (một quote cho mỗi ý) hoặc tách thành nhiều câu.
  - Có người chấm độc lập thứ hai cho coherence/grounding và tăng test lên ≥ 20 câu.

**Công cụ AI:** dùng Claude Code để hỗ trợ viết và review code pipeline, kiểm tra evidence, fomat README và chấm nháp nhãn còn lại của coherence/grounding
