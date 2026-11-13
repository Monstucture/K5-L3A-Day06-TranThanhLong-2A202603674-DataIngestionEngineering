# Day 06 · Data Ingestion Engineering

**Lab cá nhân** · **4 giờ** · **Dữ liệu tự chọn**

Biến tài liệu thành kho tri thức có thể truy xuất cho AI agent, rồi đo xem cách chuẩn bị dữ liệu nào hiệu quả nhất.

| 📄 Dữ liệu | 🧩 Chiến lược | 🎯 Benchmark |
|---|---|---|
| Tối thiểu **30 trang nội dung** | Tối thiểu **3 cấu hình** | Tối thiểu **20 câu hỏi** |

## Bài làm: Trần Thanh Long (2A202603674)

**Corpus:** OpenStax *Anatomy & Physiology 2e*, chương 1–2 (CC BY-NC-SA 4.0), file [data/anatomy-and-physiology-2e_70pages.pdf](data/anatomy-and-physiology-2e_70pages.pdf): 78 trang vật lý, **62 trang nội dung** được tính (ch. 1: trang 1–26, ch. 2: trang 35–70; bỏ Key Terms/ôn tập). Nguồn, giấy phép, SHA-256, số ký tự từng trang: [data/manifest.json](data/manifest.json).

**Benchmark:** 34 câu ([benchmark/questions.json](benchmark/questions.json)), **24 dev / 10 test**, 5 câu có filter `chapter` (3 dev, 2 test); mọi `evidence_quote` được kiểm tra tự động trên trang gold trước khi chạy.

| | Chunking | Filter | Index |
|---|---|---|---|
| **A** | Cửa sổ cố định 500 ký tự, overlap 50, theo trang | không | `A` (368 chunk) |
| **B** | Theo section (`1.1`, `1.2`…), tối đa 500 ký tự, không vượt heading, có thể nối sang trang sau | không | `B` (390 chunk) |
| **C** | Giống B | lọc `chapter` khi câu hỏi có filter | dùng chung `B` |

**Model và store:** Ollama 0.40.16 (local) · `qwen3-embedding:4b` (ID `df5bd2e3c74c`, Q4_K_M, 2560 chiều; query có instruction prefix, document không) · PostgreSQL 16 + pgvector 0.8.7, cosine `<=>`, exact search (không index vì > 2000 chiều) · Python 3.14.3 · **chi phí 0**.

### Cách chạy

Cần Docker Desktop, [Ollama](https://ollama.com) và Python 3.11–3.14. Chạy trong thư mục `starter/`:

```powershell
cd starter
python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
Copy-Item .env.example .env          # macOS/Linux: cp .env.example .env
ollama pull qwen3-embedding:4b
docker compose -p day6_student_starter up -d --wait
python scripts/check_setup.py        # kỳ vọng: Setup OK

python -m tests.test_evaluation      # kiểm tra luật tính hit (6 test)
python -m src.run --split dev        # chọn chiến lược trên dev
python -m src.run --split test       # chạy một lần sau khi đã chốt
```

Mỗi lần chạy: đọc và chuẩn hóa PDF, kiểm tra corpus ≥ 30 trang và benchmark (≥ 20 câu, ≥ 15 dev / 5 test, ≥ 3 câu filter, evidence có trên trang gold), chunk A/B, embed, upsert idempotent (chạy lại không nhân đôi), truy xuất top-3 cho A/B/C và tính Hit@1 / Evidence Hit@3. Lỗi Docker/Ollama/dữ liệu được báo rõ, không fallback sang vector giả.

### Kết quả và artifact

| Strategy | Dev Hit@1 | Dev Hit@3 | Test Hit@1 | Test Hit@3 |
|---|---|---|---|---|
| A | 13/24 | 18/24 | 5/10 | 9/10 |
| B | 18/24 | 20/24 | 8/10 | 10/10 |
| C | 18/24 | 20/24 | 8/10 | 10/10 |

Thời gian embed: khoảng 12 s cho mỗi index (A 368, B 390 chunk) trên laptop.

| File | Nội dung |
|---|---|
| [starter/results/summary_dev.json](starter/results/summary_dev.json), [summary_test.json](starter/results/summary_test.json) | chỉ số, cấu hình, thống kê chunk, thời gian, phiên bản thư viện |
| [starter/results/traces_dev.jsonl](starter/results/traces_dev.jsonl), [traces_test.jsonl](starter/results/traces_test.jsonl) | trace top-3 đầy đủ cho mỗi câu × chiến lược |
| [starter/results/ingestion_log.json](starter/results/ingestion_log.json) | trang được tính, trang loại, trang rỗng/lỗi |
| [starter/results/reload_check.txt](starter/results/reload_check.txt) | bằng chứng nạp lại không nhân đôi (A 368→368, B 390→390) |
| [starter/results/coherence_labels_test.csv](starter/results/coherence_labels_test.csv) | coherence, 10 vị trí × A/B/C |
| [starter/results/metadata_audit_labels.csv](starter/results/metadata_audit_labels.csv) | metadata top-3 của 10 câu test × A/B/C |
| [starter/results/grounding_labels_test.csv](starter/results/grounding_labels_test.csv) | grounding 10 câu test × A/B/C |
| [artifacts/experiment_log.csv](artifacts/experiment_log.csv), [report/individual/2A202603674_TranThanhLong.md](report/individual/2A202603674_TranThanhLong.md) | nhật ký thí nghiệm và báo cáo |

**Cách gán nhãn:** cột `labeled_by` trong mỗi file ghi rõ nguồn nhãn. Metadata được **kiểm tra tự động với text của PDF** (chunk có nằm trên đúng trang, đúng chương, đúng filter). Coherence và grounding là **bản nháp do AI (Claude) chấm kèm lý do**, tác giả xem lại và chịu trách nhiệm. Nhãn tác giả tự nhập được giữ nguyên.

**Demo (tùy chọn, ngoài yêu cầu lab):** `python -m demo.server` rồi mở http://127.0.0.1:8000: hỏi đáp chỉ dựa trên đoạn truy xuất, highlight bằng chứng trên trang PDF, xem chunk của A/B/C.

## Bắt đầu nhanh

Dùng [starter PostgreSQL + pgvector](starter/README.md) để dựng database và hoàn thiện các hàm TODO, hoặc tự chọn vector store tương đương. Starter chỉ là khung: **bạn tự hiện thực pipeline và benchmark**.

## 1. Xây pipeline

![Đọc tài liệu, chuẩn hóa, chia chunk, tạo vector, lưu và kiểm tra](assets/ingestion-pipeline.svg)

Chọn tài liệu được phép sử dụng; giữ **ID tài liệu, nguồn, trang/vị trí** và metadata phù hợp. Dùng embedding model thật qua API hoặc chạy local; lưu và truy xuất bằng pgvector, Qdrant, Chroma hoặc một store tương đương.

## 2. So sánh và đánh giá

![Ba chiến lược được đánh giá trên cùng corpus và benchmark dev/test](assets/benchmark-workflow.svg)

Dùng cùng dữ liệu, model và câu hỏi cho cả ba cấu hình. Tách **15 câu dev / 5 câu test** trước khi chạy; chọn cấu hình trên dev, rồi đánh giá test sau khi cố định. Mỗi câu hỏi cần có đoạn bằng chứng và trang nguồn; thiết kế bộ câu hỏi và đánh giá theo [BENCHMARK.md](BENCHMARK.md).

Đánh giá theo năm khía cạnh: **độ chính xác truy xuất**, **tính mạch lạc của chunk**, **tính hữu dụng của metadata**, **chất lượng grounding** và **tác động của chiến lược dữ liệu**. Giải thích lựa chọn bằng kết quả, ví dụ lỗi và các đánh đổi.

## 3. Chuẩn bị bài nộp

1. Chạy pipeline và lưu cấu hình, kết quả top-3, trace cùng nhãn đánh giá thủ công.
2. Điền [thông tin học viên](STUDENT.md), [nhật ký thí nghiệm](artifacts/experiment_log.csv) và bản sao [mẫu báo cáo cá nhân](report/individual/MSSV_HoTen.md).
3. Kiểm tra mã nguồn, cách chạy, manifest dữ liệu và checklist trong [SUBMISSION.md](SUBMISSION.md).

## Tài liệu hướng dẫn

| Bạn cần tìm | Tài liệu |
|---|---|
| Setup baseline PostgreSQL + pgvector | [starter/README.md](starter/README.md) |
| Các bước làm và cách tính chỉ số | [GUIDE.md](GUIDE.md) |
| Tiến độ trong 4 giờ | [CHECKPOINTS.md](CHECKPOINTS.md) |
| Năm tiêu chí benchmark và bộ câu hỏi | [BENCHMARK.md](BENCHMARK.md) |
| Tiêu chí chấm điểm | [RUBRIC.md](RUBRIC.md) |
| Quy tắc sử dụng dữ liệu, AI và API | [RULES.md](RULES.md) |
| Cách nộp bài | [SUBMISSION.md](SUBMISSION.md) |

[data/format-example.json](data/format-example.json) chỉ minh họa định dạng, không phải corpus đủ điều kiện. Phần xử lý và benchmark do bạn tự hiện thực; không bắt buộc xây chatbot.
