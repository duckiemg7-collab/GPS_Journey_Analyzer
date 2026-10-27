# GPS Journey Analyzer

Ứng dụng desktop Windows để đọc báo cáo hành trình Excel, phát hiện nhiễu GPS, tính quãng đường Haversine và xuất báo cáo đối soát. Dữ liệu nguồn không bị sửa đổi; mọi quyết định lọc đều được lưu ở các cột trạng thái và lý do.

## Cài đặt và chạy

Khuyến nghị Python 3.11 hoặc 3.12 (64-bit):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Trên máy phát triển hiện tại, môi trường tương thích nằm ở `.venv312`:

```powershell
.\.venv312\Scripts\python.exe main.py
```

Phân tích thư mục và xuất báo cáo mà không mở GUI:

```powershell
.\.venv312\Scripts\python.exe main.py --analyze file_sample_excel --output output\GPS_Journey_Analyzer_Report.xlsx
```

Chạy kiểm thử:

```powershell
.\.venv312\Scripts\python.exe -m pytest -q
```

Đóng gói Windows:

```powershell
.\build_exe.ps1
```

## Cấu trúc

- `core/`: đọc Excel, chuẩn hóa, Haversine, kiểm tra, lọc và tổng hợp ngày.
- `ui/`: dashboard PySide6, bảng chi tiết, sự kiện, biểu đồ và cấu hình.
- `reports/`: giữ các sheet cũ, thêm bảng chứng cứ công tơ, đoạn chưa xác minh và đối soát toàn kỳ.
- `config/`: tham số mặc định và phiên bản thuật toán.
- `tests/`: kiểm thử dữ liệu tổng hợp, file thực tế và smoke test GUI.

## Quy tắc phân tích chính

- Khoảng cách dùng Haversine với bán kính Trái Đất `6371.0088 km`.
- Không tính vận tốc khi timestamp bằng hoặc giảm.
- Không xóa dòng. Mỗi dòng có `algorithm_status`, `warning_reason` và `exclude_from_gps`.
- Cụm nhảy–quay lại chỉ được xác nhận khi hai biên bất khả thi, tọa độ quay về gần điểm neo, phần lớn mẫu báo xe dừng và bộ đếm km gần như không đổi trong cụm.
- Cụm trôi gồm nhiều bước nhỏ khi xe vẫn bật khóa được xét theo cửa sổ: tốc độ sát 0 hoặc trạng thái dừng, công-tơ gần như đứng yên, đường GPS vẽ lớn, độ dịch chuyển đầu-cuối nhỏ và tỷ lệ đường vòng cao. Nếu tốc độ hiển thị cũng bị GPS kéo sai, nhánh bảo thủ hơn chỉ xác nhận trên plateau công-tơ đủ dài, có trạng thái dừng lặp lại và đường GPS khép vòng. Chuyển động dừng–chạy có tiến triển theo tuyến hoặc có công-tơ tăng không bị coi là cụm trôi.
- GPS nhảy rồi quay về không đủ chứng minh số km công tơ cộng sai. Các khoản tăng nghi vấn ở trạng thái `device_anomaly_status=NEED_REVIEW`, chưa bị trừ. V1.2 hiện chưa có nguồn chứng cứ độc lập để tự xác nhận khoản trừ.
- Đoạn mất GPS không được tự nối thành quãng đường chính xác.
- Km GPS và km thiết bị được tính độc lập; ứng dụng không lấy trung bình hay ép hai kết quả khớp nhau.

## Trạng thái

`VALID`, `SUSPECTED_NOISE`, `CONFIRMED_OUTLIER`, `GPS_GAP`, `GPS_DRIFT`, `INVALID_COORDINATE`, `DUPLICATE`, `NEED_REVIEW`.

## Lưu ý file mẫu

File mẫu có một số mã màu XML không đúng chuẩn OOXML. Reader tự sửa phần style trên một bản sao tạm để đọc dữ liệu; file gốc được giữ nguyên và sự kiện này được ghi vào nhật ký báo cáo.

## Đối soát V1.2

`gps_filtered_km` là tổng Haversine của các đoạn được chấp nhận sau tái dựng. `gps_unverified_km` chỉ là đường thẳng giữa hai đầu đoạn chưa rõ hành trình; không phải số km thực bị mất. `actual_unverified_km` để trống/hiển thị “Không đủ căn cứ”. Nếu đầu hoặc cuối mất tọa độ hợp lệ, cả khoảng cách tham khảo cũng chưa biết.

`gps_raw_km` giữ hình học thô để điều tra, có thể rất lớn vì tọa độ `(0,0)` khi thiết bị mất GPS. Chỉ nhận dạng `(0,0)` là mất fix nếu cùng cụm liên tiếp có thông báo mất GPS; không cấm vị trí địa lý `(0,0)` nói chung. `gps_confirmed_outlier_km` là hình học thô bị loại, không cộng vào các nhóm km tuyến đã tái dựng. Sổ đoạn phân chia các khoảng mẫu nguồn không chồng lấn; pipeline kiểm tra đối soát trước khi trả kết quả.

`device_original_km` trong bảng ngày chỉ gồm tăng công tơ đã phân bổ được ngày. `unallocated_device_km` giữ riêng phần tăng qua nửa đêm; ngày của đầu cuối chỉ là nhãn truy vết. Tổng toàn kỳ tính độc lập từ chuỗi công tơ sau xử lý trùng lặp; tổng ngày + chưa phân bổ phải khớp tổng kỳ. Reset được đếm riêng, không tự suy đoán số km không quan sát được quanh reset.

“Tổng số bản ghi” và “Số bản ghi” theo ngày đều gồm mọi dòng nguồn, cả duplicate. “Bản ghi có cảnh báo” dùng cùng tiêu chí ở dashboard và bảng ngày. Một nhóm sự kiện là các dòng cảnh báo liên tiếp cùng loại/xe/ngày, cách tối đa 120 giây. Duplicate, excluded và warning có thể giao nhau; không cộng chúng thành một tổng mới. Di chuột lên thẻ dashboard để xem chú thích.

Để tái lập audit trên dữ liệu hiện tại:

```powershell
.\.venv312\Scripts\python.exe tools/audit_v12.py after
```

Lệnh này cần baseline trong `output/audit_v12/`, đã lưu trước khi sửa từ commit `4d647b0`. Đừng chạy lại `baseline` bằng code mới để so sánh với bản cũ. `report` chỉ xuất lại báo cáo từ chi tiết đã tính, không chạy lại thuật toán. Thư mục audit chứa dữ liệu riêng và được bỏ qua bởi Git.

Fixture thật trong `tests/fixtures/` ghi tên file, sheet, dòng nguồn và SHA-256: bốn lần tái nhận GPS của xe 50CD00062 và một cụm mất fix của xe 51D83217. Các kiểm thử dùng tọa độ/thời gian để tính kỳ vọng độc lập, không ép GPS khớp công tơ. Giữ các kịch bản test cũ; hai kỳ vọng tự trừ 18,5/4,4 km và kỳ vọng cộng km của file xung đột timestamp được sửa để phản ánh quy tắc đối soát an toàn hơn.
