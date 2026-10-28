# Hướng dẫn bắt buộc cho AI

File này áp dụng cho toàn bộ repository. Trước khi sửa code, hãy đọc lần lượt:

1. `AGENTS.md`
2. `docs/AI_PROJECT_HANDOFF.md`
3. `README.md`
4. Các test liên quan trực tiếp đến phần sắp sửa

## Mục tiêu bất biến

- Giữ nguyên file Excel nguồn; chỉ sửa style lỗi trên bản sao tạm để đọc.
- Không ép `gps_filtered_km` bằng `device_original_km` và không lấy trung bình hai nguồn.
- Không tự trừ km thiết bị chỉ vì GPS bất thường. Chỉ ghi `confirmed_false_km` khi có bằng chứng độc lập xác định được đúng số km sai.
- Không cộng đoạn GPS chưa đủ căn cứ vào km tin cậy. Giữ riêng trong `gps_unverified_km` dưới dạng khoảng cách tham khảo giữa hai đầu mút.
- Không xóa bản ghi nguồn. Duplicate, tọa độ lỗi và điểm bị loại vẫn phải tồn tại trong `details` với trạng thái/lý do.
- Phân biệt tốc độ bằng 0 với tốc độ bị thiếu.
- Không tự nối qua mất tín hiệu, khoảng thời gian dài, qua ngày hoặc tọa độ không hợp lệ.
- Giữ GUI và định dạng báo cáo tương thích trừ khi yêu cầu thay đổi rõ ràng.

## Quy trình sửa thuật toán

1. Tái hiện lỗi bằng test thất bại trước khi sửa.
2. Thêm ca đối nghịch để chống loại nhầm quãng đường thật, đặc biệt kẹt xe và chuyển động chậm.
3. Sửa ở tầng phù hợp: đọc/chuẩn hóa → kiểm tra → lọc → tái dựng → tổng hợp → trình bày.
4. Chạy test mục tiêu, sau đó chạy toàn bộ `pytest`.
5. Với thay đổi cách tính km, phân tích lại file thật và báo trước/sau; không hardcode kết quả file mẫu vào thuật toán hoặc unit test.
6. Cập nhật `docs/AI_PROJECT_HANDOFF.md`, `CHANGELOG.md` và `ALGORITHM_VERSION` khi ý nghĩa nghiệp vụ thay đổi.

## Lệnh chuẩn

```powershell
.\.venv312\Scripts\python.exe main.py
.\.venv312\Scripts\python.exe -m pytest -q
.\.venv312\Scripts\python.exe tools\audit_v12.py after
.\build_exe.ps1
```

Không chạy lại `tools/audit_v12.py baseline` bằng code mới; baseline hiện có dùng để so với commit lịch sử.

## Quy ước code và dữ liệu

- Mã nội bộ dùng tên ổn định như `VALID`, `GPS_DRIFT`, `CONFIRMED_OUTLIER`; chỉ Việt hóa ở tầng hiển thị.
- Khoảng cách dùng Haversine từ `core/haversine.py`.
- Canonical counter edges chỉ được tính một lần sau xử lý trùng lặp; bảng ngày và bảng file phải tái sử dụng cùng edge.
- `source_file`, `source_sheet`, `source_row`, timestamp và hai đầu đoạn phải được giữ để truy vết.
- Không sửa hoặc xóa thay đổi không liên quan trong worktree đang bẩn.
- File văn bản dùng UTF-8. Cảnh báo LF/CRLF của Git trên Windows không phải lỗi nội dung.

## Định nghĩa hoàn thành

- Có regression test giá trị cụ thể, không chỉ smoke test.
- Toàn bộ test pass.
- Đối soát không đếm chồng trusted/unverified/outlier và tổng công-tơ ngày + chưa phân bổ khớp tổng kỳ.
- Báo cáo nêu rõ thay đổi km, lý do, phạm vi ảnh hưởng và phần vẫn chưa đủ căn cứ.

