# Báo cáo Day 09 — Pham Lam Anh, 03029

## 1. Kết luận trước
Pipeline đưa ra kết luận **HOLD** (mã thoát `10`). Trong lô dữ liệu ban đầu, có **224 ảnh** đưa vào cửa nhận (intake); pipeline loại bỏ **21 ảnh** (hỏng, quá nhỏ, trùng lặp, rò rỉ tập test) và tiếp nhận **203 ảnh** vào quy trình QC. Sau khi máy tự động sửa các lỗi cú pháp an toàn và người duyệt mô phỏng 80 ảnh ưu tiên cao nhất, bộ dữ liệu **không còn bất kỳ lỗi bắt buộc nào** (0 lỗi ERROR). Tuy nhiên, do ngân sách người duyệt có hạn (80/130 ảnh), vẫn còn **44/203 ảnh** chứa cảnh báo chưa được xử lý, tương đương tỉ lệ cảnh báo chưa duyệt là **21.67%** ($\ge$ ngưỡng cho phép 10.00%). Do đó, pipeline xuất bản nháp (draft) vào `submission/export/clean_v1` để thử nghiệm nhưng chưa phát hành chính thức.

## 2. Lỗi và phân việc
Tổng hợp các lỗi phát hiện tại vòng QC 1 (`02_error_list_v1`):

| Mã lỗi | Số ảnh/dòng | Ai sửa (máy/người) | Vì sao |
|---|---:|---|---|
| `BAD_CLASS_ID` | 6 dòng | Máy (autofix) | ID lớp ngoài dải 0..3 (-1, 4, 7, 93) là lỗi cú pháp rõ ràng, máy xóa dòng (`drop_line`) an toàn. |
| `BAD_CLASS_NAME` | 2 lỗi | Máy (autofix) | Tên lớp trong `data.yaml` viết hoa sai ('Person', 'Bus'), máy sửa lại (`rename_classes`) theo danh mục chuẩn `cfg["classes"]`. |
| `BAD_FORMAT` | 3 dòng | Máy (autofix) | Dòng thiếu cột hoặc chứa giá trị `nan`, máy xóa dòng (`drop_line`) tránh làm crash các công cụ huấn luyện. |
| `BAD_SIZE` | 3 ảnh | Máy (intake) | Cạnh ngắn ảnh < 250px không đạt độ phân giải tối thiểu quy định, máy loại bỏ ảnh (`remove_image`). |
| `BOX_OUT_OF_IMAGE` | 8 dòng | Máy (autofix) | Box tràn ra ngoài biên ảnh [0, 1], máy cắt gọn tọa độ (`clip_box`) về trong [0, 1]. |
| `BOX_ZERO` | 4 dòng | Máy (autofix) | Box có chiều rộng hoặc chiều cao $\le 0$ không mang thông tin không gian, máy xóa dòng (`drop_line`). |
| `CORRUPT_IMAGE` | 2 ảnh | Máy (intake) | File ảnh bị hỏng không thể giải mã (`UnidentifiedImageError`, `OSError`), máy loại bỏ ảnh (`remove_image`). |
| `DUP_BOX` | 7 dòng | Máy (autofix) | Hai box cùng lớp trùng đè lên nhau (IoU > 0.9), máy xóa box lặp xuất hiện phía sau (`drop_line`). |
| `DUP_IMAGE_EXACT` | 8 ảnh | Máy (intake) | Trùng từng byte (khớp MD5 checksum), máy loại bỏ ảnh trùng (`remove_image`). |
| `DUP_IMAGE_NEAR` | 3 ảnh | Máy (intake) | Trùng gần đúng qua perceptual hash (thu nhỏ, nén ảnh), máy loại bỏ ảnh trùng (`remove_image`). |
| `LEAK_TEST` | 5 ảnh | Máy (intake) | Ảnh trùng với kho test/val làm sai lệch kết quả đánh giá mô hình, máy loại bỏ (`remove_image`). |
| `MISSING_LABEL_FILE` | 6 ảnh | Người (review) | Ảnh không có file nhãn `.txt`, máy không thể tự bịa ra nhãn nên đánh dấu `needs_label` và chuyển người gán. |
| `BOX_HUGE` | 3 dòng | Người (review) | Box chiếm > 95% diện tích ảnh, nghi ngờ gán nhãn bao trùm cả khung hình, cần người thẩm định. |
| `BOX_TINY` | 6 dòng | Người (review) | Cạnh ngắn < 12px, nghi ngờ vật thể quá nhỏ không đủ đặc trưng nhận diện, cần người quyết định giữ hay lọc. |
| `CLASS_RARE` | 4 lỗi | Người (review) | Lớp xuất hiện quá ít box ở cấp thống kê dataset, cần con người xem xét thu thập bổ sung dữ liệu. |
| `EMPTY_LABEL` | 12 ảnh | Người (review) | File nhãn rỗng, cần người xác nhận là ảnh nền thực sự (negative sample) hay do người gán bỏ quên. |
| `POSSIBLE_FALSE_POS` | 29 dòng | Người (review) | Nhãn có box nhưng model checker không phát hiện vật thể, nghi ngờ gán nhãn thừa. |
| `POSSIBLE_LOOSE_BOX` | 31 dòng | Người (review) | Cùng lớp nhưng IoU thấp (< 0.5), box bị lệch hoặc quá rộng, cần người căn chỉnh lại viền. |
| `POSSIBLE_MISSING` | 68 lỗi | Người (review) | Model checker phát hiện vật thể rõ ràng nhưng nhãn không có box, cần người bổ sung. |
| `POSSIBLE_WRONG_CLASS` | 18 lỗi | Người (review) | Cùng vị trí nhưng sai lớp (nhầm lẫn giữa car, truck, bus), cần người phân biệt ngữ nghĩa. |

**Giải thích hàng đợi `05_review_queue.csv`:**
- Hàng đợi ưu tiên ảnh dựa trên tổng trọng số lỗi kết hợp với độ tin cậy của model: các ảnh có `NEEDS_LABEL` (trọng số 10) và các ảnh vừa bị xóa dòng lỗi cú pháp vừa chứa nhiều nghi ngờ sai lớp/thiếu nhãn nặng được đẩy lên đầu (ví dụ: `img_0020` có priority 14.528, `img_0185` có priority 10.052, tiếp theo là 6 ảnh thiếu nhãn `img_0031`, `img_0053`, `img_0126`, `img_0135`, `img_0170`, `img_0219`).
- Với ngân sách duyệt 80 ảnh trên tổng số 130 ảnh trong hàng đợi, con người đã xử lý được toàn bộ 6 ảnh thiếu nhãn và giải quyết phần lớn các lỗi ngữ nghĩa nghiêm trọng nhất: sửa 14/18 lỗi `POSSIBLE_WRONG_CLASS` (chỉ còn lại 4 lỗi ở các ảnh chưa duyệt), xử lý 42/68 lỗi `POSSIBLE_MISSING` (còn lại 26 lỗi), và 9/29 lỗi `POSSIBLE_FALSE_POS` (còn lại 20 lỗi).

## 3. Calibration (2 ngưỡng)
| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau) | Lý do (đánh đổi) |
|---|---|---|---|---|
| `duplicates.phash_dist` | 2 | 8 | NEAR: 1.00 / 0.50 → 1.00 / 0.67 (F1: 0.67 → 0.80) | Lỗi này đi kèm với hành động xóa ảnh (`remove_image`), bắt buộc ưu tiên Precision tuyệt đối (1.00) để không xóa nhầm ảnh tốt. Ngưỡng 8 tăng Recall bắt thêm ảnh biến đổi mà không gây báo động giả. |
| `second_opinion.conf` | 0.25 | 0.5 | MISSING: 0.50 / 1.00 → 0.57 / 1.00; WRONG_CLASS: 0.56 / 0.83 → 0.56 / 0.83 | Tăng độ tin cậy của cảnh báo đưa vào hàng đợi cho người duyệt, giảm bớt cảnh báo nhiễu trong khi vẫn bảo toàn Recall cao (1.00 cho missing, 0.83 cho wrong class). |

**Điểm calibration có thể đánh lừa bạn:**
Trên tập `calib` (chỉ có 39 ảnh), ngưỡng `phash_dist = 16` cho Recall cao nhất (0.83, F1 = 0.91). Tuy nhiên, trên tập `raw` thực tế (224 ảnh đường phố có góc nhìn và bố cục tương đồng), khi thử nghiệm `phash_dist = 16`, số ảnh bị cờ rò rỉ test (`LEAK_TEST`) nhảy vọt từ **5 lên 11 ảnh** và ảnh gần trùng (`DUP_IMAGE_NEAR`) từ **4 lên 7 ảnh**. Nguyên nhân là khoảng cách pHash giữa các ảnh khác nhau có cùng bố cục chung đường xá bị thu hẹp vào khoảng 10–16. Nếu chọn theo F1 cao nhất trên tập calib nhỏ, pipeline sẽ xóa nhầm 6 ảnh hợp lệ trên dữ liệu thật. Do đó, việc giữ `phash_dist = 8` là đánh đổi an toàn bắt buộc.

## 4. Cửa chặn và điều pipeline KHÔNG bắt được
**(a) Bằng chứng cửa chặn (Gate) hoạt động chính xác:**
Khi chạy thử nghiệm pipeline với ngân sách người duyệt bằng 0:
```bash
python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb
```
Kết quả ghi nhận:
- Do `--budget 0`, không có người duyệt can thiệp, 6 ảnh thiếu file nhãn (`MISSING_LABEL_FILE`) không được tạo nhãn, dẫn đến còn nguyên 6 lỗi bắt buộc (ERROR).
- Cửa chặn `gate` kết luận: `REWORK — Còn 6 lỗi bắt buộc (ERROR) chưa xử lý`.
- Mã thoát trả về là `20` (`Exit code: 20`).
- Pipeline kích hoạt cơ chế bảo vệ: **KHÔNG xuất** dataset ra thư mục `work/exp_nb` (thư mục xuất hoàn toàn không được tạo ra).

**(b) Hai điểm mù của pipeline:**
1. *Box lệch hoặc lỏng ở mức độ nhẹ:* Khi box nhãn và box dự đoán của model có IoU nằm trong khoảng $[0.5, 0.9]$, pipeline coi đây là độ phủ chấp nhận được (`iou_match = 0.5`) và không đưa ra cảnh báo `POSSIBLE_LOOSE_BOX`, dẫn đến bỏ sót sự không nhất quán về độ khít bounding box giữa các annotator.
2. *Lỗi ngữ nghĩa mà cả model lớn cũng nhầm (khuyết tật thị giác chung):* Với các vật thể bị che khuất nặng (heavy occlusion) hoặc trong điều kiện thiếu sáng/bóng râm, cả người gán nhãn lẫn model lớn `yolo26l` đều nhận diện sai (ví dụ nhầm xe tải nhỏ/bán tải thành xe con), dẫn đến `second_opinion` đồng thuận giả và không cảnh báo.
3. *Ảnh trùng bị biến đổi cực mạnh:* Những ảnh bị cắt cúp > 50% hoặc xoay góc/thay đổi màu sắc mạnh vượt quá ngưỡng khoảng cách pHash thì thuật toán băm tri giác không thể nhận diện được.

## 5. Train: raw vs clean (tùy chọn, chấm riêng)
Chưa chạy. Lý do: Môi trường làm việc hiện tại không có GPU rời hỗ trợ CUDA để huấn luyện YOLO (2 seed $\times$ 20 epoch). Toàn bộ mã nguồn và pipeline đã được chuẩn bị sẵn sàng để chạy thí nghiệm trên Google Colab qua notebook `notebooks/day09_train_compare.ipynb` theo hướng dẫn tại `docs/COLAB.md`.

## 6. Quyết định và ghi chú AI
**(a) Quyết định cuối cùng:**
Quyết định hiện tại là **HOLD** (không còn lỗi bắt buộc, nhưng tỉ lệ ảnh còn cảnh báo là 21.67% $\ge$ 10.00%).
- *Điều kiện để chuyển thành RELEASE:* Cần tăng ngân sách duyệt của người (`budget_images`) từ 80 lên 130 ảnh để người duyệt kiểm tra nốt 50 ảnh còn lại trong hàng đợi, giải quyết 44 ảnh cảnh báo còn tồn đọng và đưa tỉ lệ cảnh báo chưa xử lý về dưới 10.00%.

**(b) Ghi chú sử dụng AI:**
1. *Prompt chính:* "Viết module Python 3 kiểm tra và xử lý định dạng nhãn YOLO theo docstring và các test case trong tests/test_label_format.py, đảm bảo xử lý ngoại lệ an toàn và không làm crash script khi gặp dòng hỏng."
2. *Cách kiểm code AI:* Chạy kiểm thử tự động qua `pytest`, kiểm tra tính lặp lại (idempotent), và tự kiểm tra các ca biên phức tạp (dòng trống, một dòng dính cả lỗi format lẫn trùng lặp, ảnh bị xóa ở bước trước).
3. *Một lần AI sai và cách sửa:* Khi triển khai `second_opinion.py`, AI ban đầu đã áp dụng bộ lọc diện tích `min_area_px` cho cả bước kiểm tra `POSSIBLE_FALSE_POS`. Điều này làm các box nhãn nhỏ hợp lệ bị cảnh báo nhầm là nhãn thừa dù model có phát hiện vật thể ở vị trí đó. Tôi đã phát hiện qua test `test_false_positive_uses_fp_conf_and_ignores_min_area` và sửa lại để nhánh False Positive chỉ lọc theo `fp_conf` mà không lọc theo `min_area_px`.
