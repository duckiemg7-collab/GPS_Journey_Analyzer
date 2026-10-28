# Changelog

Mọi thay đổi đáng kể của GPS Journey Analyzer được ghi tại đây. Kết quả audit chi tiết thuộc `output/audit_v12/`; changelog chỉ ghi quyết định và ảnh hưởng chính, không thay thế báo cáo truy vết.

## Chưa phát hành

- Việt hóa cảnh báo và tiêu đề bảng chi tiết GPS ở tầng hiển thị.
- Dashboard chính chỉ giữ Km thiết bị và Km GPS lọc; bỏ Km thiết bị hiệu chỉnh khỏi phần trình bày chính.
- Bổ sung tài liệu bàn giao cho AI và rule dự án luôn áp dụng.

## 1.2.1 — 2026-10-28

### Thay đổi

- Bổ sung nhận diện GPS trôi dạng đám mây gồm nhiều bước nhỏ khi xe đậu nhưng vẫn bật khóa.
- Bổ sung nhánh counter plateau khi tốc độ hiển thị cũng bị tọa độ GPS kéo sai.
- Giữ chuyển động dừng-chạy có tiến triển theo tuyến và vòng chạy thật có công-tơ tăng.
- Điểm quay về hợp lệ có thể làm endpoint tái dựng mà không cộng lại raw jump.

### Kiểm thử

- Thêm regression test cho cụm tốc độ 0, cụm có tốc độ GPS giả, kẹt xe và vòng chạy thật.
- Audit lại toàn bộ file Excel mẫu sau thay đổi; không sửa file nguồn.

## 1.2.0

### Thay đổi

- Tách GPS filtered, GPS unverified reference và confirmed outlier geometry.
- Tái dựng segment không chồng lấn sau khi loại điểm bất thường.
- Giữ riêng counter edge qua ngày và đối soát tổng kỳ độc lập.
- Không tự xác nhận hoặc trừ km công-tơ chỉ dựa trên GPS jump/return.
- Tổng hợp canonical theo thiết bị/ngày sau xử lý duplicate giữa file.
- Bổ sung báo cáo reconciliation, nguồn/dòng và hai đầu segment để truy vết.

