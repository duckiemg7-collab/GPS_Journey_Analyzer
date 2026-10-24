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
- `reports/`: báo cáo Excel 6 sheet, định dạng và biểu đồ native.
- `config/`: tham số mặc định và phiên bản thuật toán.
- `tests/`: kiểm thử dữ liệu tổng hợp, file thực tế và smoke test GUI.

## Quy tắc phân tích chính

- Khoảng cách dùng Haversine với bán kính Trái Đất `6371.0088 km`.
- Không tính vận tốc khi timestamp bằng hoặc giảm.
- Không xóa dòng. Mỗi dòng có `algorithm_status`, `warning_reason` và `exclude_from_gps`.
- Cụm nhảy–quay lại chỉ được xác nhận khi hai biên bất khả thi, tọa độ quay về gần điểm neo, phần lớn mẫu báo xe dừng và bộ đếm km gần như không đổi trong cụm.
- Khoản km thiết bị sai chỉ bị trừ một lần tại biên quay về có bằng chứng.
- Đoạn mất GPS không được tự nối thành quãng đường chính xác.
- Km GPS và km thiết bị được tính độc lập; ứng dụng không lấy trung bình hay ép hai kết quả khớp nhau.

## Trạng thái

`VALID`, `SUSPECTED_NOISE`, `CONFIRMED_OUTLIER`, `GPS_GAP`, `GPS_DRIFT`, `INVALID_COORDINATE`, `DUPLICATE`, `NEED_REVIEW`.

## Lưu ý file mẫu

File mẫu có một số mã màu XML không đúng chuẩn OOXML. Reader tự sửa phần style trên một bản sao tạm để đọc dữ liệu; file gốc được giữ nguyên và sự kiện này được ghi vào nhật ký báo cáo.
