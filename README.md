# Teaching Management System

**Hệ thống quản lý giảng dạy bằng Python | Python CLI Application**

> A Python-based academic management demo featuring role-based access, course registration, timetable management, attendance tracking, and reporting.

## 1. Giới thiệu

**Teaching Management System** là dự án học tập mô phỏng một số quy trình quản lý giảng dạy tại trường đại học. Chương trình chạy trên **giao diện dòng lệnh (CLI)**, hỗ trợ ba vai trò người dùng: **Admin**, **Lecturer (Giảng viên)** và **Student (Sinh viên)**.

Dự án giúp thực hành **Python, lập trình hướng đối tượng (OOP), kiểm tra dữ liệu đầu vào, xử lý quy tắc nghiệp vụ, phân quyền và lưu trữ JSON**.

**Lưu ý:** Đây là chương trình mô phỏng phục vụ học tập, **không phải hệ thống FAP chính thức của Đại học FPT**. Dự án hiện **không sử dụng mô hình AI/Machine Learning**.

## 2. Chức năng chính

### Admin

- Thêm, cập nhật, xóa môn học và thông tin giảng viên.
- Quản lý danh sách sinh viên.
- Kiểm tra xung đột lịch giảng dạy và phòng học.
- Xem danh sách môn học và các báo cáo thống kê.

### Lecturer (Giảng viên)

- Xem môn học, danh sách sinh viên và thời khóa biểu được phân công.
- Điểm danh theo từng buổi học (có mặt/vắng/muộn).
- Theo dõi tỷ lệ vắng và cảnh báo chuyên cần.
- Gửi thông báo đến sinh viên trong lớp.

### Student (Sinh viên)

- Tìm kiếm môn học bằng các bộ lọc.
- Đăng ký/hủy môn; kiểm tra trùng đăng ký, trùng lịch và giới hạn sĩ số.
- Tham gia **danh sách chờ**, tự động chuyển vào lớp khi có chỗ phù hợp.
- Xem môn đã đăng ký, thời khóa biểu tuần và báo cáo điểm danh.

### Tính năng kỹ thuật

- Phân quyền thao tác theo ba nhóm người dùng.
- Kiểm tra định dạng và giá trị dữ liệu đầu vào.
- Lưu/tải dữ liệu từ **JSON**, ghi qua file tạm trước khi thay thế file hiện có.
- Bộ kiểm thử nghiệp vụ tích hợp: `--selftest`.

## 3. Công nghệ sử dụng

| Thành phần | Công nghệ |
| --- | --- |
| Ngôn ngữ | Python 3.9+ |
| Thiết kế chương trình | OOP, `dataclasses`, service classes |
| Lưu trữ | JSON (`json`, `pathlib`) |
| Giao diện | Command-line interface (CLI) |
| Kiểm thử | Python assertions, built-in self-test |
| Phụ thuộc ngoài | Không có — chỉ dùng Python Standard Library |

## 4. Cài đặt và chạy

**Yêu cầu:** Cài đặt Python **3.9 trở lên**.

1. Tải repository về máy hoặc tải file `.py`.
2. Mở Terminal/PowerShell tại thư mục chứa mã nguồn.
3. Chạy lệnh tương ứng:

```bash
# Khởi chạy ứng dụng (tự tạo dữ liệu demo nếu chưa có)
python "teaching_management.py"

# Chạy bộ kiểm thử tự động
python "teaching_management.py" --selftest

# Tạo lại dữ liệu demo (ghi đè dữ liệu đã lưu)
python "teaching_management.py" --reset
```

Ứng dụng lưu dữ liệu mặc định trong file `fap_demo_data.json` nằm cùng thư mục với mã nguồn. Có thể thay đổi vị trí lưu bằng tùy chọn `--data`.

> **Cảnh báo:** `--reset` tạo lại dữ liệu mô phỏng và có thể ghi đè dữ liệu đang lưu. Hãy sao lưu nếu cần.

## 5. Kiểm thử

Chạy:

```bash
python "teaching_management.py" --selftest
```

Bộ kiểm thử bao gồm: phân quyền, tạo/sửa môn học, kiểm tra trùng lịch, đăng ký môn, danh sách chờ, điểm danh, thống kê, lưu/tải JSON và các quy tắc xóa dữ liệu.

**Kết quả kiểm tra:** Các nhóm self-test đã chạy thành công trên bản mã nguồn demo đã được thay dữ liệu mẫu.

## 6. Cấu trúc dự án

```text
teaching-management-system/
├── README.md
├── .gitignore
├── teaching_management.py   # Mã nguồn ứng dụng
└── fap_demo_data.json             # Dữ liệu sinh ra khi chạy; KHÔNG nên commit
```

## 7. Giới hạn và lưu ý bảo mật

- Dự án là **mô hình demo CLI**, chưa có giao diện web hoặc cơ sở dữ liệu máy chủ.
- Ngưỡng cảnh báo/cấm thi trong chương trình là **cấu hình mô phỏng**, không nên hiểu là quy định chính thức của trường.
- Cơ chế mật khẩu hiện dùng **SHA-256 với chuỗi muối cố định** nhằm minh họa; **không phù hợp cho hệ thống production**. Hệ thống thực tế nên sử dụng bcrypt/Argon2 và quy trình quản lý bí mật phù hợp.
- Dữ liệu mẫu dùng tên, mã số và email giả lập. Tài khoản demo chỉ phục vụ chạy thử cục bộ. Không dùng các mật khẩu mẫu này trong hệ thống thật.
- Không commit file `fap_demo_data.json`, dữ liệu người dùng thật hay thông tin đăng nhập thật. `.gitignore` đã bỏ qua file dữ liệu được tạo khi chạy.

## 8. Hướng phát triển

- Tách mã nguồn thành các module để dễ bảo trì.
- Bổ sung unit tests riêng và CI cho repository.
- Chuyển lưu trữ JSON sang cơ sở dữ liệu phù hợp.
- Phát triển giao diện web và cơ chế xác thực an toàn hơn.

## Tác giả

**Lê Duy Anh**  
Sinh viên chuyên ngành **Artificial Intelligence**, **FPT University**  
GitHub: [@duyanhfpt-AI](https://github.com/duyanhfpt-AI)
