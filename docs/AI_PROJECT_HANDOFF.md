# GPS Journey Analyzer — Báo cáo bàn giao cho AI

Tài liệu này là nguồn ngữ cảnh kỹ thuật chính dành cho AI hoặc lập trình viên tiếp quản. Hãy cập nhật nó khi kiến trúc, ý nghĩa chỉ tiêu hoặc quy tắc nghiệp vụ thay đổi.

## 1. Trạng thái hiện tại

- Loại ứng dụng: desktop Windows, Python + PySide6.
- Phiên bản thuật toán: đọc từ `config/settings.py::ALGORITHM_VERSION`.
- Môi trường phát triển đang dùng: `.venv312`.
- Lệnh test chuẩn: `.\.venv312\Scripts\python.exe -m pytest -q`.
- Mốc kiểm tra gần nhất: 28/10/2026, 95 test pass.
- File mẫu thật nằm trong `file_sample_excel/`; không được chỉnh sửa.
- Dữ liệu audit sinh ra nằm trong `output/audit_v12/` và không phải source code.

Con số test và mốc kiểm tra có thể cũ sau lần sửa tiếp theo. Luôn chạy lại test thay vì tin tuyệt đối vào snapshot này.

## 2. Mục đích nghiệp vụ

Ứng dụng đọc báo cáo hành trình Excel, chuẩn hóa dữ liệu nhiều thiết bị/file, phát hiện GPS lỗi, tái dựng các đoạn đủ tin cậy, tổng hợp theo thiết bị/ngày và xuất báo cáo đối soát.

Hai nguồn quãng đường độc lập:

- Công-tơ thiết bị: lấy từ cột `Số Km` và tính theo delta dương của chuỗi canonical.
- GPS: tính Haversine từ tọa độ, sau đó lọc và tái dựng.

Không có quy tắc nào được phép ép hai nguồn bằng nhau.

## 3. Luồng xử lý

```text
Excel nguồn
  → core/excel_reader.py
  → core/gps_validator.py
  → core/gps_filter.py
  → core/reconciliation.py
  → core/daily_aggregator.py
  → core/pipeline.py / AnalysisResult
  → ui/* hoặc reports/excel_exporter.py
```

### Trách nhiệm từng module

| Module | Trách nhiệm |
|---|---|
| `core/excel_reader.py` | Tìm header, ánh xạ cột, parse timestamp/tọa độ, sửa style OOXML trên bản sao tạm |
| `core/gps_validator.py` | Chuẩn hóa số, sắp xếp, đánh dấu duplicate/timestamp/tọa độ lỗi |
| `core/gps_filter.py` | Pair metrics, nhận diện drift/teleport/gap, cụm nhảy-quay lại, tái dựng segment |
| `core/reconciliation.py` | Event ID, segment ledger, bằng chứng công-tơ, đối soát toàn kỳ và invariant |
| `core/daily_aggregator.py` | Tổng hợp canonical edges theo thiết bị/ngày và trình bày theo file |
| `core/models.py` | `AnalysisResult` và totals dùng bởi GUI/report |
| `core/pipeline.py` | Điều phối toàn bộ quá trình cho file thật và DataFrame test/cache |
| `ui/` | Chỉ trình bày/tương tác; không đặt logic tính km tại đây |
| `reports/` | Xuất Excel, giữ truy vết và các sheet đối soát |
| `tests/` | Regression nghiệp vụ, invariant, file thật và GUI smoke |

## 4. Hợp đồng dữ liệu quan trọng

### Chỉ tiêu quãng đường

| Trường | Ý nghĩa |
|---|---|
| `raw_distance_km` | Haversine của cặp mẫu nguồn liên tiếp; chỉ dùng điều tra |
| `gps_filtered_segment_km` | Km của segment đã được chấp nhận sau tái dựng |
| `gps_filtered_km` | Tổng km GPS tin cậy |
| `gps_unverified_segment_km` | Khoảng cách thẳng tham khảo giữa hai đầu segment chưa xác minh |
| `gps_unverified_km` | Tổng tham khảo, không phải quãng đường thực bị mất |
| `gps_confirmed_outlier_segment_km` | Hình học thô bị loại; không cộng chồng vào trusted/unverified |
| `device_original_km` | Delta công-tơ dương đã phân bổ được ngày |
| `unallocated_device_km` | Delta công-tơ đi qua ranh giới ngày, giữ riêng |
| `device_suspected_km` | Khoản tăng cần xem xét, chưa được trừ |
| `confirmed_false_km` | Khoản công-tơ sai có bằng chứng độc lập; hiện mặc định không tự xác nhận |
| `device_corrected_km` | Chỉ tiêu nội bộ: device original trừ confirmed false; không còn hiển thị chính trên GUI |

### Trạng thái nội bộ

`VALID`, `SUSPECTED_NOISE`, `CONFIRMED_OUTLIER`, `GPS_GAP`, `GPS_DRIFT`, `INVALID_COORDINATE`, `DUPLICATE`, `NEED_REVIEW`.

Không đổi mã nội bộ sang tiếng Việt. Dùng `core/display_labels.py` để Việt hóa giao diện.

### Truy vết bắt buộc

Mọi quyết định phải giữ được `device_id`, `timestamp`, `source_file`, `source_sheet`, `source_row`, tọa độ, chỉ số đầu/cuối segment và lý do thuật toán.

## 5. Quy tắc thuật toán hiện tại

- Haversine dùng bán kính Trái Đất `6371.0088 km`.
- Timestamp bằng/giảm không tạo vận tốc hợp lệ.
- `(0,0)` chỉ được coi là mất fix khi cùng cụm có bằng chứng mất GPS.
- Duplicate vẫn được giữ nhưng không tạo canonical edge mới.
- Không nối tự động qua mất tín hiệu, gap quá ngưỡng, ranh giới ngày hoặc tọa độ lỗi.
- Bước nhảy không bị loại chỉ vì lớn hơn 500 m; phải xét thời gian, vận tốc, trạng thái, công-tơ và chuỗi trước/sau.
- Jump-and-return chỉ được xác nhận khi quay về gần anchor và có bằng chứng dừng đủ mạnh.
- Cụm drift nhiều bước nhỏ được xét theo cửa sổ. Nhánh counter plateau yêu cầu chuỗi đủ dài, công-tơ phẳng, trạng thái dừng lặp lại, đường vẽ lớn, đầu-cuối gần nhau và tortuosity cao.
- Kẹt xe/đi chậm được giữ khi tuyến có tiến triển hoặc công-tơ tăng. Luôn thêm test đối nghịch khi sửa drift.
- Điểm bị nghi có thể được dùng lại làm endpoint nếu chuỗi sau chứng minh việc tái nhận GPS hợp lý; raw jump vào điểm đó vẫn không được cộng lại.

Ngưỡng người dùng cấu hình nằm trong `FilterSettings`; ngưỡng cấu trúc cụm hiện nằm gần `_mark_stationary_drift_clouds()` và phải có regression test nếu thay đổi.

## 6. Invariant không được phá

1. Bản ghi nguồn không bị xóa.
2. Canonical interval ledger không thiếu và không chồng lấn.
3. Một segment không vừa có trusted km vừa có unverified km.
4. Tổng raw geometry của segment khớp raw canonical edges trong sai số số học.
5. Tổng công-tơ ngày + phần chưa phân bổ khớp tổng kỳ tính độc lập.
6. `confirmed_false_km` không được suy ra chỉ từ GPS.
7. Bảng theo file không tự diff lại công-tơ và không double count file chồng lấn.
8. GUI/report không thay đổi dữ liệu nguồn hoặc thuật toán khi chỉ đổi nhãn hiển thị.

Các invariant được kiểm tra chủ yếu tại `core/reconciliation.py::validate_reconciliation` và test regression.

## 7. Vùng dễ phát sinh lỗi

- Tốc độ hiển thị có thể được suy ra từ chính GPS; không luôn là bằng chứng độc lập.
- Công-tơ làm tròn 0,1 km nên một edge có delta 0 chưa chứng minh xe đứng yên.
- Plateau công-tơ có thể chứa kẹt xe hoặc di chuyển trong bãi; cần đường khép vòng/tortuosity và trạng thái dừng lặp lại trước khi loại.
- Gap dài có khoảng cách đầu-cuối nhưng quãng đường thực bên trong vẫn chưa biết.
- Reset công-tơ không cho biết quãng đường mất quanh reset.
- Timestamp nhiều định dạng có thể bị đảo ngày/tháng; ISO phải parse trước fallback day-first.
- File Excel mẫu có style XML lỗi; tuyệt đối không sửa file gốc để đọc.
- Cột cảnh báo trên GUI đếm bản ghi cảnh báo; `unique_warning_events` mới là số nhóm sự kiện.

## 8. Chiến lược kiểm thử

Trước khi sửa thuật toán, thêm test tái hiện với giá trị km cụ thể. Tối thiểu phải kiểm tra:

- GPS nhảy 300 m, 700 m, 2 km, 18 km với nhiều khoảng thời gian.
- Nhảy rồi quay lại và cụm nhiều điểm.
- Xe đậu bật khóa bị trôi tọa độ.
- Kẹt xe/dừng-chạy không bị loại nhầm.
- GPS mất tín hiệu và `(0,0)`.
- Duplicate và timestamp conflict giữa file.
- Reset công-tơ.
- Hành trình qua nửa đêm.
- Segment ledger không chồng lấn và bảo toàn raw distance.
- GUI dựng được ở chế độ offscreen.

Lệnh:

```powershell
.\.venv312\Scripts\python.exe -m pytest tests\test_v12_regressions.py -q
.\.venv312\Scripts\python.exe -m pytest tests\test_gui_smoke.py -q
.\.venv312\Scripts\python.exe -m pytest -q
```

## 9. Audit dữ liệu thật

```powershell
.\.venv312\Scripts\python.exe tools\audit_v12.py after
.\.venv312\Scripts\python.exe tools\audit_v12.py report
.\.venv312\Scripts\python.exe tools\verify_audit_v12.py
```

Không chạy lại phase `baseline` bằng code hiện tại. Khi báo trước/sau, cần nêu:

- Tổng và theo thiết bị/ngày.
- Km GPS tin cậy thay đổi bao nhiêu.
- Km unverified/reference thay đổi bao nhiêu.
- Outlier geometry nào bị loại và nguồn/dòng/thời điểm.
- Có hay không thay đổi công-tơ; nếu không có bằng chứng thì phải ghi rõ không trừ.
- Hash file nguồn trước/sau.

Không hardcode tổng kỳ hoặc kết quả của file mẫu vào production code hay unit test.

## 10. GUI và báo cáo

- Dashboard chính chỉ hiển thị Km thiết bị và Km GPS lọc.
- Các mã cảnh báo được Việt hóa ở tầng hiển thị.
- Bảng chi tiết GPS dùng tiêu đề tiếng Việt nhưng DataFrame nội bộ vẫn dùng tên trường tiếng Anh.
- Báo cáo reconciliation có thể chứa trường kỹ thuật tiếng Anh để truy vết; không đổi schema cũ nếu không có yêu cầu rõ ràng.
- Khi đổi model/tên cột trình bày, cập nhật `tests/test_gui_smoke.py` và `tests/test_reconciliation_report.py` tương ứng.

## 11. Quy trình thêm tính năng

1. Ghi yêu cầu và định nghĩa chỉ tiêu mới trong tài liệu này.
2. Xác định nguồn dữ liệu và mức độ tin cậy; không tái sử dụng cột có ý nghĩa khác.
3. Thêm field vào tầng core/model trước, sau đó mới nối GUI/report.
4. Thêm test đơn vị và test đối nghịch.
5. Chạy toàn bộ test và audit file thật nếu ảnh hưởng km.
6. Tăng `ALGORITHM_VERSION` nếu thay đổi kết quả phân tích.
7. Ghi mục mới vào `CHANGELOG.md` gồm lý do, file sửa, test và ảnh hưởng dữ liệu.

## 12. Cách bàn giao cho AI tiếp theo

Khi kết thúc một thay đổi lớn, bổ sung vào tài liệu này:

- Ngày và phiên bản thuật toán.
- Vấn đề đã tái hiện.
- Công thức/điều kiện mới.
- Test mới và tổng test pass.
- File thật đã chạy và chênh lệch trước/sau.
- Hạn chế còn lại hoặc phần chưa đủ căn cứ.
- Trạng thái Git: đã commit/push hay chỉ là thay đổi local.

