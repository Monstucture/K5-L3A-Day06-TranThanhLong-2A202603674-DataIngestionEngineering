# Báo cáo cá nhân — Day 6

## Dữ liệu và pipeline
- Chủ đề, nguồn/quyền, số trang và quy tắc tính trang: OpenStax Anatomy & Physiology 2e, chapters 1–2 (CC BY-NC-SA 4.0), 78 trang tổng, 62 trang chứa thông tin (ch. 1: pages 1–26, ch. 2: pages 35–70); trang Key Terms and và review đc excluded
- Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí: qwen3-embedding:4b; 2560 dimensions ;local model cost my laptop vram
- Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:

## Cấu hình và benchmark
- A / B / C (tham số cụ thể, khác biệt duy nhất B–C):
- ≥20 câu: phân chia ≥15 dev / ≥5 test, câu metadata filter và cách kiểm chứng evidence: Chia 24 dev và 10 test
- Tiêu chí chọn chiến lược đã chốt trước khi xem test: chọn hịt dev nhiều hơn sau đó chọn hit test và nếu thấy ko hit dược thì giảm chunk lại để model không đọc nhiều quá, Sau do thử tăng chunk size lên tới mức cần thiết

## Kết quả
| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|

Đường dẫn trace, nhãn thủ công và cách chọn mẫu:

## Phân tích và kết luận
- So sánh A–B và B–C; 2 ví dụ sai có ID câu và nguồn:
- Chiến lược chọn, đánh đổi, điều kiện áp dụng:
- Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí:
- Nếu làm lại hoặc mở rộng, cải tiến gì?
