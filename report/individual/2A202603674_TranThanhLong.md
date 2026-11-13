# Báo cáo cá nhân — Day 6

## Dữ liệu và pipeline
- Chủ đề, nguồn/quyền, số trang và quy tắc tính trang: OpenStax Anatomy & Physiology 2e, chapters 1–2 (CC BY-NC-SA 4.0), 78 trang tổng, 62 trang chứa thông tin (ch. 1: pages 1–26, ch. 2: pages 35–70); trang Key Terms and và review đc excluded
- Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí: qwen3-embedding:4b; 2560 dimensions ;local model cost my laptop vram
- Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn:

## Cấu hình và benchmark
- A / B / C (tham số cụ thể, khác biệt duy nhất B–C):
- ≥20 câu: phân chia ≥15 dev / ≥5 test, câu metadata filter và cách kiểm chứng evidence: Chia 24 dev và 10 test
- Tiêu chí chọn chiến lược đã chốt trước khi xem test: Chọn chiến lược có Evidence Hit@3 trên dev cao nhất; nếu bằng nhau thì chọn Hit@1 dev cao hơn; nếu vẫn bằng thì chọn chiến lược đơn giản hơn / ít chunk hơn. Mọi điều chỉnh tham số chỉ dựa trên dev. Test chỉ chạy một lần sau khi đã chốt.

## Kết quả
| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 13/24 | 18/24 | 368 | 12.6s | local model |
| B | dev | 19/24 | 20/24 | 390 | 12.0s | local model | 
| C | dev | 19/24 | 20/24 | 390 | 12.0s | local model |

| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | test | 5/10 | 9/10 | 368 | 12.4s | local model |
| B | test | 8/10 | 10/10 | 390 | 11.9s | local model | 
| C | test | 8/10 | 10/10 | 390 | 11.9s | local model |

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|

Đường dẫn trace, nhãn thủ công và cách chọn mẫu:

## Phân tích và kết luận
- So sánh A–B và B–C; 2 ví dụ sai có ID câu và nguồn:
- Chiến lược chọn, đánh đổi, điều kiện áp dụng:
- Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí:
- Nếu làm lại hoặc mở rộng, cải tiến gì?
