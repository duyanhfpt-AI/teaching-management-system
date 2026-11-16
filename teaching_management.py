#!/usr/bin/env python3
"""
TeachingManagement - Hệ thống quản lý giảng dạy
===============================================================================

Vai trò
-------
* Admin    : thêm/sửa/xóa môn học + giảng viên, thêm/xóa sinh viên, xem toàn bộ
             môn học và sinh viên, bảng thống kê.
* Lecturer : xem danh sách sinh viên và chi tiết môn MÌNH DẠY,
             điểm danh, báo cáo vắng/nguy cơ cấm thi, thời khóa biểu, thông báo lớp.
* Student  : tìm kiếm môn (nhiều bộ lọc), đăng ký (kiểm tra sĩ số, chống đăng ký
             trùng, chống trùng lịch, danh sách chờ), hủy môn, xem môn đã đăng ký,
             thời khóa biểu tuần (kèm dấu điểm danh), báo cáo điểm danh.

Tính năng sáng tạo
------------------
* Thời khóa biểu dạng lưới 8 slot, có dấu P/A/L theo từng buổi.
* Danh sách chờ tự động, tự đưa sinh viên vào lớp khi có chỗ trống.
* Phát hiện trùng lịch của sinh viên, giảng viên và phòng học.
* Cảnh báo điểm danh theo cấu hình mô phỏng: vắng >= 15% là CẢNH BÁO, > 20% là CẤM THI.
* Thông báo trong ứng dụng (đăng ký, được xếp lớp, đổi lịch, cảnh báo vắng...).
* Đăng nhập có mật khẩu (băm), lưu JSON an toàn,
  có sẵn bộ kiểm thử ``--selftest``.

Cách dùng
---------
    python teaching_management.py              # chạy chương trình
    python teaching_management.py --reset      # tạo lại dữ liệu mẫu
    python teaching_management.py --selftest   # chạy kiểm thử tự động
Python 3.9+, chỉ dùng thư viện chuẩn.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import random
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, ClassVar, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------- #
# Hằng số
# --------------------------------------------------------------------------- #
DATA_FILE = Path(__file__).with_name("fap_demo_data.json")

WEEKDAYS: List[str] = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
SLOT_TIMES: Dict[int, Tuple[str, str]] = {  # slot học kiểu FPT University
    1: ("07:30", "09:00"),
    2: ("09:10", "10:40"),
    3: ("10:50", "12:20"),
    4: ("12:50", "14:20"),
    5: ("14:30", "16:00"),
    6: ("16:10", "17:40"),
    7: ("18:00", "19:30"),
    8: ("19:45", "21:15"),
}

PRESENT, ABSENT, LATE = "P", "A", "L"
ATTENDANCE_STATUSES = (PRESENT, ABSENT, LATE)
ABSENCE_WARNING_RATIO = 0.15   # vắng từ 15% trở lên: cảnh báo
ABSENCE_LIMIT_RATIO = 0.20     # vắng quá 20%: cấm thi
MAX_NOTIFICATIONS = 50

# Nhãn hiển thị cho mức nguy cơ (giá trị nội bộ vẫn là OK/WARNING/BANNED)
RISK_LABEL: Dict[str, str] = {"OK": "Đạt", "WARNING": "Cảnh báo", "BANNED": "Cấm thi"}


# --------------------------------------------------------------------------- #
# Ngoại lệ
# --------------------------------------------------------------------------- #
class AppError(Exception):
    """Lớp cha của mọi lỗi nghiệp vụ hiển thị được cho người dùng."""


class ValidationError(AppError):
    """Dữ liệu nhập không hợp lệ."""


class NotFoundError(AppError):
    """Không tìm thấy đối tượng yêu cầu."""


class PermissionDenied(AppError):
    """Người dùng không có quyền thực hiện thao tác."""


class RegistrationError(AppError):
    """Vi phạm quy tắc đăng ký (trùng, trùng lịch...)."""


class CourseFullError(RegistrationError):
    """Môn học đã hết chỗ."""


# --------------------------------------------------------------------------- #
# Kiểm tra dữ liệu nhập
# --------------------------------------------------------------------------- #
class Validator:
    """Các hàm kiểm tra không lưu trạng thái; luôn trả về giá trị đã làm sạch."""

    _CODE_RE = re.compile(r"[A-Za-z]{3}\d{3}[A-Za-z]?")
    _EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
    _ID_RE = re.compile(r"[A-Za-z0-9_.]{3,20}")

    @staticmethod
    def text(value: object, label: str, min_len: int = 2, max_len: int = 80) -> str:
        """Chuỗi không rỗng, độ dài trong khoảng cho phép."""
        text = " ".join(str(value).split())
        if not min_len <= len(text) <= max_len:
            raise ValidationError(f"{label} phải có từ {min_len} đến {max_len} ký tự.")
        return text

    @staticmethod
    def integer(value: object, label: str, low: int, high: int) -> int:
        """Số nguyên trong đoạn [low, high]."""
        try:
            number = int(str(value).strip())
        except ValueError:
            raise ValidationError(f"{label} phải là số nguyên.") from None
        if not low <= number <= high:
            raise ValidationError(f"{label} phải nằm trong khoảng {low} đến {high}.")
        return number

    @classmethod
    def course_code(cls, value: object) -> str:
        """Mã môn dạng PRP201 / PRP201c (3 chữ + 3 số + 1 chữ tùy chọn)."""
        code = str(value).strip()
        if not cls._CODE_RE.fullmatch(code):
            raise ValidationError("Mã môn phải có dạng PRP201 hoặc PRP201c.")
        return code[:3].upper() + code[3:]

    @classmethod
    def email(cls, value: object) -> str:
        email = str(value).strip().lower()
        if not cls._EMAIL_RE.fullmatch(email):
            raise ValidationError("Email không hợp lệ.")
        return email

    @classmethod
    def user_id(cls, value: object) -> str:
        uid = str(value).strip()
        if not cls._ID_RE.fullmatch(uid):
            raise ValidationError("Mã người dùng gồm 3-20 ký tự: chữ, số, '_' hoặc '.'.")
        return uid

    @staticmethod
    def password(value: object) -> str:
        pwd = str(value)
        if len(pwd) < 6:
            raise ValidationError("Mật khẩu phải có ít nhất 6 ký tự.")
        return pwd

    @staticmethod
    def date_str(value: object, label: str = "Ngày") -> str:
        """Trả về chuỗi ngày ISO (YYYY-MM-DD)."""
        try:
            return date.fromisoformat(str(value).strip()).isoformat()
        except ValueError:
            raise ValidationError(f"{label} phải theo định dạng YYYY-MM-DD.") from None

    @staticmethod
    def status(value: object) -> str:
        status = str(value).strip().upper()
        if status not in ATTENDANCE_STATUSES:
            raise ValidationError("Trạng thái điểm danh chỉ nhận P (có mặt), A (vắng) hoặc L (muộn).")
        return status


def hash_password(password: str) -> str:
    """SHA-256 có muối (phục vụ học tập; thực tế nên dùng bcrypt/argon2)."""
    return hashlib.sha256(("teaching-mgmt::" + password).encode("utf-8")).hexdigest()


def monday_of(day: date) -> date:
    """Ngày thứ Hai của tuần chứa ``day``."""
    return day - timedelta(days=day.weekday())


# --------------------------------------------------------------------------- #
# Đối tượng giá trị
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TimeSlot:
    """Một slot học hằng tuần, ví dụ ``Mon-3`` (thứ Hai, slot 3)."""

    day: str
    slot: int

    def __post_init__(self) -> None:
        if self.day not in WEEKDAYS:
            raise ValidationError(f"Thứ phải là một trong: {', '.join(WEEKDAYS)}.")
        if self.slot not in SLOT_TIMES:
            raise ValidationError(f"Slot phải từ 1 đến {len(SLOT_TIMES)}.")

    @property
    def day_index(self) -> int:
        return WEEKDAYS.index(self.day)

    @property
    def sort_key(self) -> Tuple[int, int]:
        return self.day_index, self.slot

    @property
    def label(self) -> str:
        return f"{self.day}-{self.slot}"

    @property
    def times(self) -> str:
        start, end = SLOT_TIMES[self.slot]
        return f"{start}-{end}"

    @classmethod
    def parse(cls, text: str) -> "TimeSlot":
        match = re.fullmatch(r"\s*([A-Za-z]{3})\s*-\s*(\d)\s*", text)
        if not match:
            raise ValidationError(f"Slot '{text}' không hợp lệ. Ví dụ đúng: Mon-1.")
        return cls(match.group(1).capitalize(), int(match.group(2)))

    @classmethod
    def parse_many(cls, text: str) -> List["TimeSlot"]:
        """Phân tích 'Mon-1, Wed-3' thành danh sách đã sắp xếp, không trùng."""
        parts = [p for p in re.split(r"[,;]", text) if p.strip()]
        if not parts:
            raise ValidationError("Lịch học cần ít nhất một slot, ví dụ Mon-1,Wed-1.")
        slots = {cls.parse(p) for p in parts}
        return sorted(slots, key=lambda s: s.sort_key)


@dataclass(frozen=True)
class Session:
    """Một buổi học cụ thể (ngày + slot) của môn học."""

    number: int
    day: date
    slot: int

    @property
    def key(self) -> str:
        return f"{self.day.isoformat()}_S{self.slot}"

    @property
    def start(self) -> datetime:
        return datetime.combine(self.day, time.fromisoformat(SLOT_TIMES[self.slot][0]))

    @property
    def label(self) -> str:
        start, end = SLOT_TIMES[self.slot]
        return (f"#{self.number:02d} {WEEKDAYS[self.day.weekday()]} "
                f"{self.day:%d/%m/%Y} slot {self.slot} ({start}-{end})")


# --------------------------------------------------------------------------- #
# Người dùng
# --------------------------------------------------------------------------- #
@dataclass
class User:
    """Lớp cha của mọi người dùng trong hệ thống."""

    ROLE: ClassVar[str] = "user"

    user_id: str
    name: str
    email: str
    password_hash: str
    notifications: List[str] = field(default_factory=list)

    def check_password(self, password: str) -> bool:
        return self.password_hash == hash_password(password)

    def notify(self, message: str) -> None:
        """Thêm thông báo có mốc thời gian (giữ 50 thông báo gần nhất)."""
        self.notifications.append(f"[{datetime.now():%Y-%m-%d %H:%M}] {message}")
        del self.notifications[:-MAX_NOTIFICATIONS]

    def to_dict(self) -> dict:
        data = asdict(self)
        data["role"] = self.ROLE
        return data


@dataclass
class Admin(User):
    ROLE: ClassVar[str] = "admin"


@dataclass
class Lecturer(User):
    ROLE: ClassVar[str] = "lecturer"
    department: str = ""


@dataclass
class Student(User):
    ROLE: ClassVar[str] = "student"
    major: str = ""


USER_CLASSES: Dict[str, type] = {"admin": Admin, "lecturer": Lecturer, "student": Student}


def user_from_dict(data: dict) -> User:
    data = dict(data)
    role = data.pop("role")
    return USER_CLASSES[role](**data)


# --------------------------------------------------------------------------- #
# Môn học
# --------------------------------------------------------------------------- #
@dataclass
class Course:
    """Môn học: lịch, danh sách lớp, danh sách chờ và điểm danh."""

    code: str
    name: str
    lecturer_id: str
    capacity: int
    schedule: List[TimeSlot]
    start_date: str
    credits: int = 3
    room: str = ""
    total_sessions: int = 20
    student_ids: List[str] = field(default_factory=list)
    waitlist: List[str] = field(default_factory=list)
    # attendance[khóa_buổi_học][mã_sinh_viên] = "P" | "A" | "L"
    attendance: Dict[str, Dict[str, str]] = field(default_factory=dict)

    # ---- sĩ số ------------------------------------------------------------
    @property
    def enrolled(self) -> int:
        return len(self.student_ids)

    @property
    def seats_left(self) -> int:
        return max(0, self.capacity - self.enrolled)

    @property
    def is_full(self) -> bool:
        return self.enrolled >= self.capacity

    def has_student(self, student_id: str) -> bool:
        return student_id in self.student_ids

    @property
    def schedule_text(self) -> str:
        return ",".join(s.label for s in self.schedule)

    # ---- danh sách lớp ----------------------------------------------------
    def remove_student(self, student_id: str) -> bool:
        """Xóa khỏi lớp/danh sách chờ và xóa luôn dữ liệu điểm danh của sinh viên."""
        removed = False
        for bucket in (self.student_ids, self.waitlist):
            if student_id in bucket:
                bucket.remove(student_id)
                removed = True
        for marks in self.attendance.values():
            marks.pop(student_id, None)
        return removed

    # ---- buổi học & điểm danh ---------------------------------------------
    def sessions(self) -> List[Session]:
        """Sinh ra đủ ``total_sessions`` buổi học tính từ ``start_date``."""
        by_weekday: Dict[int, List[int]] = {}
        for ts in self.schedule:
            by_weekday.setdefault(ts.day_index, []).append(ts.slot)
        if not by_weekday:
            return []
        result: List[Session] = []
        day = date.fromisoformat(self.start_date)
        while len(result) < self.total_sessions:
            for slot in sorted(by_weekday.get(day.weekday(), [])):
                if len(result) < self.total_sessions:
                    result.append(Session(len(result) + 1, day, slot))
            day += timedelta(days=1)
        return result

    def attendance_counts(self, student_id: str) -> Dict[str, int]:
        counts = {PRESENT: 0, ABSENT: 0, LATE: 0}
        for marks in self.attendance.values():
            status = marks.get(student_id)
            if status in counts:
                counts[status] += 1
        return counts

    def absence_ratio(self, student_id: str) -> float:
        """Số buổi vắng / tổng số buổi dự kiến (cấu hình mô phỏng)."""
        return self.attendance_counts(student_id)[ABSENT] / max(1, self.total_sessions)

    def risk_level(self, student_id: str) -> str:
        ratio = self.absence_ratio(student_id)
        if ratio > ABSENCE_LIMIT_RATIO:
            return "BANNED"
        if ratio >= ABSENCE_WARNING_RATIO:
            return "WARNING"
        return "OK"

    def attendance_rate(self) -> Optional[float]:
        """Tỷ lệ % (có mặt + muộn) trên tổng số lượt điểm danh; None nếu chưa có dữ liệu."""
        marks = [s for per_session in self.attendance.values() for s in per_session.values()]
        if not marks:
            return None
        attended = sum(1 for s in marks if s in (PRESENT, LATE))
        return round(attended * 100 / len(marks), 1)

    # ---- (de)serialize ----------------------------------------------------
    def to_dict(self) -> dict:
        data = asdict(self)
        data["schedule"] = [s.label for s in self.schedule]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Course":
        data = dict(data)
        data["schedule"] = [TimeSlot.parse(s) for s in data["schedule"]]
        return cls(**data)


# --------------------------------------------------------------------------- #
# Lưu trữ
# --------------------------------------------------------------------------- #
class DataStore:
    """Kho dữ liệu trong bộ nhớ, lưu xuống JSON theo kiểu nguyên tử."""

    def __init__(self, path: Path = DATA_FILE) -> None:
        self.path = Path(path)
        self.users: Dict[str, User] = {}
        self.courses: Dict[str, Course] = {}

    # ---- lưu / tải --------------------------------------------------------
    def load(self) -> bool:
        """Tải từ đĩa. Trả về False nếu chưa có file."""
        if not self.path.exists():
            return False
        with self.path.open(encoding="utf-8") as fh:
            raw = json.load(fh)
        self.users = {u["user_id"]: user_from_dict(u) for u in raw.get("users", [])}
        self.courses = {c["code"]: Course.from_dict(c) for c in raw.get("courses", [])}
        return True

    def save(self) -> None:
        """Ghi file tạm rồi thay thế, tránh hỏng dữ liệu nếu chương trình dừng giữa chừng."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "users": [u.to_dict() for u in self.users.values()],
            "courses": [c.to_dict() for c in self.courses.values()],
        }
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)

    # ---- truy vấn ---------------------------------------------------------
    def find_user(self, user_id: str) -> Optional[User]:
        wanted = user_id.strip().lower()
        return next((u for u in self.users.values() if u.user_id.lower() == wanted), None)

    def lecturers(self) -> List[Lecturer]:
        return sorted((u for u in self.users.values() if isinstance(u, Lecturer)),
                      key=lambda u: u.user_id)

    def students(self) -> List[Student]:
        return sorted((u for u in self.users.values() if isinstance(u, Student)),
                      key=lambda u: u.user_id)

    def get_student(self, student_id: str) -> Student:
        user = self.find_user(student_id)
        if not isinstance(user, Student):
            raise NotFoundError(f"Không tìm thấy sinh viên '{student_id}'.")
        return user

    def get_lecturer(self, lecturer_id: str) -> Lecturer:
        user = self.find_user(lecturer_id)
        if not isinstance(user, Lecturer):
            raise NotFoundError(f"Không tìm thấy giảng viên '{lecturer_id}'.")
        return user

    def courses_of_student(self, student_id: str) -> List[Course]:
        return sorted((c for c in self.courses.values() if c.has_student(student_id)),
                      key=lambda c: c.code)

    def courses_of_lecturer(self, lecturer_id: str) -> List[Course]:
        return sorted((c for c in self.courses.values() if c.lecturer_id == lecturer_id),
                      key=lambda c: c.code)

    def schedule_conflict(self, student_id: str, course: Course) -> Optional[Course]:
        """Trả về môn sinh viên đang học có slot hằng tuần trùng với ``course``."""
        wanted = set(course.schedule)
        for other in self.courses_of_student(student_id):
            if other.code != course.code and wanted & set(other.schedule):
                return other
        return None


# --------------------------------------------------------------------------- #
# Dịch vụ nghiệp vụ (không có input()/print())
# --------------------------------------------------------------------------- #
ROLE_NAMES = {"admin": "Admin", "lecturer": "Giảng viên", "student": "Sinh viên"}


def ensure_role(user: User, *roles: str) -> None:
    """Ném PermissionDenied nếu ``user`` không thuộc các vai trò cho phép."""
    if user.ROLE not in roles:
        allowed = " / ".join(ROLE_NAMES[r] for r in roles)
        raise PermissionDenied(f"Thao tác này yêu cầu vai trò: {allowed}.")


class AuthService:
    """Đăng nhập và đổi mật khẩu."""

    def __init__(self, store: DataStore) -> None:
        self.store = store

    def login(self, user_id: str, password: str) -> User:
        user = self.store.find_user(user_id)
        if user is None or not user.check_password(password):
            raise AppError("Sai mã đăng nhập hoặc mật khẩu.")
        return user

    def change_password(self, user: User, old: str, new: str) -> None:
        if not user.check_password(old):
            raise AppError("Mật khẩu hiện tại không đúng.")
        user.password_hash = hash_password(Validator.password(new))
        self.store.save()


class UserService:
    """Thao tác của Admin trên giảng viên và sinh viên."""

    def __init__(self, store: DataStore) -> None:
        self.store = store

    def _new_id(self, user_id: str) -> str:
        uid = Validator.user_id(user_id)
        if self.store.find_user(uid):
            raise ValidationError(f"Mã '{uid}' đã tồn tại.")
        return uid

    def add_lecturer(self, actor: User, user_id: str, name: str, email: str,
                     department: str, password: str = "demo_user_2026") -> Lecturer:
        ensure_role(actor, "admin")
        lecturer = Lecturer(self._new_id(user_id), Validator.text(name, "Họ tên"),
                            Validator.email(email),
                            hash_password(Validator.password(password)),
                            department=Validator.text(department, "Bộ môn"))
        self.store.users[lecturer.user_id] = lecturer
        self.store.save()
        return lecturer

    def update_lecturer(self, actor: User, user_id: str, name: Optional[str] = None,
                        email: Optional[str] = None,
                        department: Optional[str] = None) -> Lecturer:
        ensure_role(actor, "admin")
        lecturer = self.store.get_lecturer(user_id)
        if name:
            lecturer.name = Validator.text(name, "Họ tên")
        if email:
            lecturer.email = Validator.email(email)
        if department:
            lecturer.department = Validator.text(department, "Bộ môn")
        self.store.save()
        return lecturer

    def delete_lecturer(self, actor: User, user_id: str) -> None:
        ensure_role(actor, "admin")
        lecturer = self.store.get_lecturer(user_id)
        owned = self.store.courses_of_lecturer(lecturer.user_id)
        if owned:
            codes = ", ".join(c.code for c in owned)
            raise ValidationError(f"Không thể xóa: giảng viên còn phụ trách {codes}. "
                                  "Hãy chuyển các môn này cho giảng viên khác trước.")
        del self.store.users[lecturer.user_id]
        self.store.save()

    def add_student(self, actor: User, user_id: str, name: str, email: str,
                    major: str, password: str = "demo_user_2026") -> Student:
        ensure_role(actor, "admin")
        student = Student(self._new_id(user_id), Validator.text(name, "Họ tên"),
                          Validator.email(email),
                          hash_password(Validator.password(password)),
                          major=Validator.text(major, "Chuyên ngành"))
        self.store.users[student.user_id] = student
        self.store.save()
        return student

    def delete_student(self, actor: User, user_id: str, courses: "CourseService") -> None:
        ensure_role(actor, "admin")
        student = self.store.get_student(user_id)
        for course in list(self.store.courses.values()):
            if course.remove_student(student.user_id):
                courses.fill_from_waitlist(course)
        del self.store.users[student.user_id]
        self.store.save()


class CourseService:
    """CRUD môn học, tìm kiếm và quản lý chỗ ngồi."""

    EDITABLE = {"name", "lecturer_id", "capacity", "credits", "room",
                "schedule", "start_date", "total_sessions"}
    SCHEDULE_FIELDS = {"schedule", "start_date", "total_sessions"}

    def __init__(self, store: DataStore) -> None:
        self.store = store

    # ---- tra cứu ----------------------------------------------------------
    def get(self, code: str) -> Course:
        key = Validator.course_code(code)
        course = self.store.courses.get(key)
        if course is None:
            raise NotFoundError(f"Không tìm thấy môn '{key}'.")
        return course

    def get_owned(self, actor: User, code: str) -> Course:
        """Môn mà ``actor`` (giảng viên) phụ trách; Admin được truy cập mọi môn."""
        course = self.get(code)
        if actor.ROLE == "lecturer" and course.lecturer_id != actor.user_id:
            raise PermissionDenied(f"Bạn không phụ trách môn {course.code}.")
        ensure_role(actor, "lecturer", "admin")
        return course

    def search(self, keyword: str = "", lecturer: str = "", day: str = "",
               credits: Optional[int] = None, available_only: bool = False) -> List[Course]:
        """Tìm kiếm nhiều tiêu chí; tiêu chí rỗng sẽ bị bỏ qua."""
        keyword, lecturer, day = keyword.strip().lower(), lecturer.strip().lower(), day.strip().capitalize()
        result = []
        for course in self.store.courses.values():
            teacher = self.store.users.get(course.lecturer_id)
            teacher_name = teacher.name.lower() if teacher else ""
            if keyword and keyword not in course.code.lower() and keyword not in course.name.lower():
                continue
            if lecturer and lecturer not in teacher_name and lecturer not in course.lecturer_id.lower():
                continue
            if day and not any(s.day == day for s in course.schedule):
                continue
            if credits is not None and course.credits != credits:
                continue
            if available_only and course.is_full:
                continue
            result.append(course)
        return sorted(result, key=lambda c: c.code)

    # ---- xung đột ---------------------------------------------------------
    def _check_conflicts(self, candidate: Course) -> None:
        for other in self.store.courses.values():
            if other.code == candidate.code:
                continue
            shared = set(other.schedule) & set(candidate.schedule)
            if not shared:
                continue
            slots = ", ".join(sorted(s.label for s in shared))
            if other.lecturer_id == candidate.lecturer_id:
                raise ValidationError(f"Giảng viên đã dạy {other.code} vào {slots}.")
            if other.room.lower() == candidate.room.lower():
                raise ValidationError(f"Phòng {candidate.room} đã được {other.code} sử dụng vào {slots}.")

    # ---- CRUD -------------------------------------------------------------
    def create(self, actor: User, code: str, name: str, lecturer_id: str, capacity: object,
               schedule: List[TimeSlot], start_date: str, credits: object = 3,
               room: str = "", total_sessions: object = 20) -> Course:
        ensure_role(actor, "admin")
        code = Validator.course_code(code)
        if code in self.store.courses:
            raise ValidationError(f"Môn {code} đã tồn tại.")
        lecturer = self.store.get_lecturer(lecturer_id)
        if not schedule:
            raise ValidationError("Lịch học cần ít nhất một slot.")
        course = Course(
            code=code,
            name=Validator.text(name, "Tên môn", 3, 60),
            lecturer_id=lecturer.user_id,
            capacity=Validator.integer(capacity, "Sĩ số tối đa", 1, 500),
            schedule=sorted(set(schedule), key=lambda s: s.sort_key),
            start_date=Validator.date_str(start_date, "Ngày bắt đầu"),
            credits=Validator.integer(credits, "Số tín chỉ", 1, 10),
            room=Validator.text(room, "Phòng học", 2, 20),
            total_sessions=Validator.integer(total_sessions, "Tổng số buổi", 1, 60),
        )
        self._check_conflicts(course)
        self.store.courses[code] = course
        lecturer.notify(f"Bạn được phân công dạy {code} - {course.name}.")
        self.store.save()
        return course

    def update(self, actor: User, code: str, **changes: object) -> Course:
        ensure_role(actor, "admin")
        course = self.get(code)
        unknown = set(changes) - self.EDITABLE
        if unknown:
            raise ValidationError(f"Không thể sửa trường: {', '.join(sorted(unknown))}.")
        if course.attendance and self.SCHEDULE_FIELDS & set(changes):
            raise ValidationError("Lịch học/ngày bắt đầu/số buổi bị khóa khi đã có dữ liệu điểm danh.")

        candidate = copy.deepcopy(course)
        for key, value in changes.items():
            if key == "name":
                candidate.name = Validator.text(value, "Tên môn", 3, 60)
            elif key == "lecturer_id":
                candidate.lecturer_id = self.store.get_lecturer(str(value)).user_id
            elif key == "capacity":
                candidate.capacity = Validator.integer(value, "Sĩ số tối đa", 1, 500)
                if candidate.capacity < candidate.enrolled:
                    raise ValidationError(
                        f"Sĩ số tối đa không được nhỏ hơn số sinh viên hiện có ({candidate.enrolled}).")
            elif key == "credits":
                candidate.credits = Validator.integer(value, "Số tín chỉ", 1, 10)
            elif key == "room":
                candidate.room = Validator.text(value, "Phòng học", 2, 20)
            elif key == "schedule":
                if not value:
                    raise ValidationError("Lịch học cần ít nhất một slot.")
                candidate.schedule = sorted(set(value), key=lambda s: s.sort_key)  # type: ignore[arg-type]
            elif key == "start_date":
                candidate.start_date = Validator.date_str(value, "Ngày bắt đầu")
            elif key == "total_sessions":
                candidate.total_sessions = Validator.integer(value, "Tổng số buổi", 1, 60)
        self._check_conflicts(candidate)

        self.store.courses[course.code] = candidate
        changed_logistics = {"schedule", "room", "lecturer_id"} & set(changes)
        if changed_logistics:
            for sid in candidate.student_ids:
                student = self.store.users.get(sid)
                if student:
                    student.notify(f"{candidate.code} đã thay đổi: {candidate.schedule_text} "
                                   f"tại phòng {candidate.room}.")
        self.fill_from_waitlist(candidate)
        self.store.save()
        return candidate

    def delete(self, actor: User, code: str) -> Course:
        ensure_role(actor, "admin")
        course = self.get(code)
        for sid in course.student_ids + course.waitlist:
            student = self.store.users.get(sid)
            if student:
                student.notify(f"Môn {course.code} - {course.name} đã bị hủy.")
        del self.store.courses[course.code]
        self.store.save()
        return course

    # ---- danh sách chờ ----------------------------------------------------
    def fill_from_waitlist(self, course: Course) -> List[str]:
        """Đưa sinh viên trong danh sách chờ vào lớp khi còn chỗ. Trả về mã sinh viên được đưa vào."""
        promoted: List[str] = []
        for sid in list(course.waitlist):
            if course.is_full:
                break
            student = self.store.users.get(sid)
            if not isinstance(student, Student):
                course.waitlist.remove(sid)
                continue
            if self.store.schedule_conflict(sid, course):
                continue  # tiếp tục chờ; hiện đang trùng lịch với môn khác
            course.waitlist.remove(sid)
            course.student_ids.append(sid)
            student.notify(f"Có chỗ trống: bạn đã được xếp vào lớp {course.code}.")
            promoted.append(sid)
        return promoted


class RegistrationService:
    """Quy tắc đăng ký: sĩ số, trùng đăng ký, trùng lịch, danh sách chờ."""

    def __init__(self, store: DataStore, courses: CourseService) -> None:
        self.store = store
        self.courses = courses

    def _enroll(self, student: Student, course: Course, join_waitlist: bool) -> str:
        if course.has_student(student.user_id):
            raise RegistrationError(f"{student.user_id} đã đăng ký môn {course.code} rồi.")
        if student.user_id in course.waitlist:
            raise RegistrationError(f"{student.user_id} đang trong danh sách chờ của {course.code}.")
        conflict = self.store.schedule_conflict(student.user_id, course)
        if conflict:
            raise RegistrationError(
                f"Trùng lịch với môn {conflict.code} ({conflict.schedule_text}).")
        if course.is_full:
            if not join_waitlist:
                raise CourseFullError(f"Môn {course.code} đã đầy ({course.enrolled}/{course.capacity}).")
            course.waitlist.append(student.user_id)
            position = len(course.waitlist)
            student.notify(f"Đã vào danh sách chờ môn {course.code} (vị trí {position}).")
            self.store.save()
            return f"Môn {course.code} đã đầy. Bạn đứng thứ #{position} trong danh sách chờ."
        course.student_ids.append(student.user_id)
        teacher = self.store.users.get(course.lecturer_id)
        student.notify(f"Đã đăng ký môn {course.code} - {course.name}.")
        self.store.save()
        return (f"Đăng ký thành công! {student.name} đã được ghi danh vào "
                f"{course.code} - {course.name}.\n"
                f"  Giảng viên : {teacher.name if teacher else course.lecturer_id}\n"
                f"  Lịch học   : {course.schedule_text}  |  Phòng: {course.room}\n"
                f"  Sĩ số      : {course.enrolled}/{course.capacity}")

    # ---- thao tác của sinh viên -------------------------------------------
    def register(self, actor: User, code: str, join_waitlist: bool = False) -> str:
        ensure_role(actor, "student")
        return self._enroll(actor, self.courses.get(code), join_waitlist)  # type: ignore[arg-type]

    def drop(self, actor: User, code: str) -> str:
        ensure_role(actor, "student")
        course = self.courses.get(code)
        if not course.remove_student(actor.user_id):
            raise RegistrationError(f"Bạn chưa đăng ký môn {course.code}.")
        promoted = self.courses.fill_from_waitlist(course)
        self.store.save()
        extra = f" Đã xếp {len(promoted)} sinh viên từ danh sách chờ vào lớp." if promoted else ""
        return f"Bạn đã hủy môn {course.code}.{extra}"



class AttendanceService:
    """Điểm danh và phân tích nguy cơ vắng."""

    def __init__(self, store: DataStore, courses: CourseService) -> None:
        self.store = store
        self.courses = courses

    @staticmethod
    def started_sessions(course: Course, now: Optional[datetime] = None) -> List[Session]:
        """Các buổi đã bắt đầu (được phép điểm danh)."""
        now = now or datetime.now()
        return [s for s in course.sessions() if s.start <= now]

    def take(self, actor: User, code: str, session_key: str,
             marks: Dict[str, str]) -> Dict[str, str]:
        """Ghi điểm danh một buổi. Sinh viên không được liệt kê mặc định là có mặt (P).

        Trả về {mã_sinh_viên: mức_nguy_cơ_mới} cho các sinh viên vừa chuyển sang
        mức CẢNH BÁO hoặc CẤM THI.
        """
        ensure_role(actor, "lecturer")
        course = self.courses.get_owned(actor, code)
        session = next((s for s in course.sessions() if s.key == session_key), None)
        if session is None:
            raise NotFoundError("Không tìm thấy buổi học của môn này.")
        if session.start > datetime.now():
            raise ValidationError("Không thể điểm danh buổi học chưa bắt đầu.")
        clean: Dict[str, str] = {}
        for sid in course.student_ids:
            clean[sid] = Validator.status(marks.get(sid, PRESENT))
        extra = set(marks) - set(course.student_ids)
        if extra:
            raise ValidationError(f"Không có trong lớp: {', '.join(sorted(extra))}.")

        before = {sid: course.risk_level(sid) for sid in course.student_ids}
        course.attendance[session.key] = clean
        changed: Dict[str, str] = {}
        for sid in course.student_ids:
            after = course.risk_level(sid)
            if after != before[sid] and after != "OK":
                changed[sid] = after
                student = self.store.users.get(sid)
                if student:
                    pct = course.absence_ratio(sid) * 100
                    student.notify(f"Điểm danh {RISK_LABEL[after].upper()} ở {course.code}: "
                                   f"vắng {pct:.0f}% (giới hạn {ABSENCE_LIMIT_RATIO:.0%}).")
        self.store.save()
        return changed

    def class_report(self, actor: User, code: str) -> List[dict]:
        """Tổng hợp điểm danh từng sinh viên của một môn."""
        course = self.courses.get_owned(actor, code)
        rows = []
        for sid in course.student_ids:
            student = self.store.users.get(sid)
            counts = course.attendance_counts(sid)
            rows.append({
                "student_id": sid, "name": student.name if student else sid,
                "present": counts[PRESENT], "late": counts[LATE], "absent": counts[ABSENT],
                "absent_pct": round(course.absence_ratio(sid) * 100, 1),
                "status": course.risk_level(sid),
            })
        return rows

    def student_report(self, student: Student) -> List[dict]:
        rows = []
        for course in self.store.courses_of_student(student.user_id):
            counts = course.attendance_counts(student.user_id)
            rows.append({
                "code": course.code, "name": course.name,
                "taken": sum(counts.values()), "total": course.total_sessions,
                "present": counts[PRESENT], "late": counts[LATE], "absent": counts[ABSENT],
                "absent_pct": round(course.absence_ratio(student.user_id) * 100, 1),
                "status": course.risk_level(student.user_id),
            })
        return rows


class TimetableService:
    """Thời khóa biểu tuần (dạng lưới giống FAP)."""

    def __init__(self, store: DataStore) -> None:
        self.store = store

    def week(self, user: User, week_start: date) -> Tuple[Dict[Tuple[int, int], str], List[str]]:
        """Trả về (lưới, danh sách chi tiết).

        grid[(chỉ_số_thứ, slot)] -> "MÃMÔN(dấu)";
        dấu: sinh viên -> P/A/L hoặc '-' (chưa điểm danh); giảng viên -> '*' đã điểm danh / '-' chưa.
        """
        if isinstance(user, Student):
            courses = self.store.courses_of_student(user.user_id)
        elif isinstance(user, Lecturer):
            courses = self.store.courses_of_lecturer(user.user_id)
        else:
            courses = sorted(self.store.courses.values(), key=lambda c: c.code)
        week_end = week_start + timedelta(days=6)
        grid: Dict[Tuple[int, int], str] = {}
        details: List[Tuple[date, int, str]] = []
        for course in courses:
            for session in course.sessions():
                if not week_start <= session.day <= week_end:
                    continue
                taken = course.attendance.get(session.key)
                if isinstance(user, Student):
                    mark = (taken or {}).get(user.user_id, "-")
                else:
                    mark = "*" if taken else "-"
                grid[(session.day.weekday(), session.slot)] = f"{course.code}({mark})"
                times = SLOT_TIMES[session.slot]
                details.append((session.day, session.slot,
                                f"{session.day:%a %d/%m} slot {session.slot} "
                                f"{times[0]}-{times[1]}  {course.code} {course.name} "
                                f"@ {course.room} | GV: {self.store.get_lecturer(course.lecturer_id).name} "
                                f"[#{session.number}] [{mark}]"))
        details.sort(key=lambda d: (d[0], d[1]))
        return grid, [d[2] for d in details]


@dataclass
class CourseStat:
    """Một dòng của báo cáo thống kê."""

    code: str
    name: str
    lecturer: str
    enrolled: int
    capacity: int
    waitlist: int
    attendance_rate: Optional[float]


class ReportService:
    """Thống kê."""

    def __init__(self, store: DataStore) -> None:
        self.store = store

    # ---- thống kê ---------------------------------------------------------
    def course_stats(self) -> List[CourseStat]:
        stats = []
        for course in sorted(self.store.courses.values(), key=lambda c: c.code):
            teacher = self.store.users.get(course.lecturer_id)
            stats.append(CourseStat(course.code, course.name,
                                    teacher.name if teacher else course.lecturer_id,
                                    course.enrolled, course.capacity, len(course.waitlist),
                                    course.attendance_rate()))
        return stats

    @staticmethod
    def _extremes(items: List[CourseStat], key: Callable[[CourseStat], float]
                  ) -> Tuple[List[CourseStat], List[CourseStat]]:
        """Tất cả phần tử đồng hạng cao nhất / thấp nhất theo ``key``."""
        if not items:
            return [], []
        high, low = max(key(i) for i in items), min(key(i) for i in items)
        return [i for i in items if key(i) == high], [i for i in items if key(i) == low]

    def summary(self) -> dict:
        stats = self.course_stats()
        with_data = [s for s in stats if s.attendance_rate is not None]
        top_enr, low_enr = self._extremes(stats, lambda s: s.enrolled)
        top_att, low_att = self._extremes(with_data, lambda s: s.attendance_rate or 0.0)
        capacity = sum(s.capacity for s in stats)
        enrollments = sum(s.enrolled for s in stats)
        unique = {sid for c in self.store.courses.values() for sid in c.student_ids}
        rates = [s.attendance_rate for s in with_data if s.attendance_rate is not None]
        return {
            "total_courses": len(stats),
            "total_lecturers": len(self.store.lecturers()),
            "total_students_registered": len(self.store.students()),
            "total_enrollments": enrollments,          # tổng sinh viên trên mọi môn
            "unique_enrolled_students": len(unique),
            "total_capacity": capacity,
            "utilisation_pct": round(enrollments * 100 / capacity, 1) if capacity else 0.0,
            "average_attendance_pct": round(sum(rates) / len(rates), 1) if rates else None,
            "highest_enrollment": top_enr, "lowest_enrollment": low_enr,
            "highest_attendance": top_att, "lowest_attendance": low_att,
        }


class Services:
    """Bộ chứa phụ thuộc: nối mọi service với cùng một DataStore."""

    def __init__(self, store: DataStore) -> None:
        self.store = store
        self.auth = AuthService(store)
        self.users = UserService(store)
        self.courses = CourseService(store)
        self.registration = RegistrationService(store, self.courses)
        self.attendance = AttendanceService(store, self.courses)
        self.timetable = TimetableService(store)
        self.reports = ReportService(store)


# --------------------------------------------------------------------------- #
# Dữ liệu mẫu
# --------------------------------------------------------------------------- #
def add_requested_students(store: DataStore) -> None:
    """Bổ sung ba sinh viên mô phỏng vào bốn môn, không ghi đè mật khẩu/điểm danh."""
    students = [("DEMO001", "Sinh Viên Demo A"), ("DEMO002", "Sinh Viên Demo B"),
                ("DEMO003", "Sinh Viên Demo C")]
    for sid, name in students:
        user = store.find_user(sid)
        if user is None:
            store.users[sid] = Student(sid, name, f"{sid.lower()}@example.com",
                                       hash_password("demo_user_2026"), major="Kỹ thuật phần mềm")
        elif isinstance(user, Student):
            user.name = name
        else:
            raise ValidationError(f"Mã {sid} đã được dùng cho vai trò khác.")
    for code in ("CSI106", "CSD106", "PFP191", "PRF191"):
        if code not in store.courses:
            raise ValidationError(f"Dữ liệu cũ thiếu môn {code}. Hãy dùng dữ liệu môn học đã cập nhật.")
        course = store.courses[code]
        for sid, _ in students:
            actual_id = store.get_student(sid).user_id
            if actual_id not in course.student_ids:
                if store.schedule_conflict(actual_id, course):
                    raise ValidationError(f"Sinh viên {sid} bị trùng lịch với môn {code}.")
                course.student_ids.append(actual_id)
            if actual_id in course.waitlist:
                course.waitlist.remove(actual_id)
        course.capacity = max(course.capacity, len(course.student_ids))

def seed_sample_data(store: DataStore) -> None:
    """Nạp người dùng, môn học, đăng ký và điểm danh mẫu vào ``store``."""
    store.users.clear()
    store.courses.clear()
    store.users["admin"] = Admin("admin", "Quản trị hệ thống", "admin@example.com",
                                 hash_password("demo_admin_2026"))
    default_pw = hash_password("demo_user_2026")
    for uid, name, dept in [
        ("lecturer_a", "Giảng Viên Demo A", "Kỹ thuật phần mềm"),
        ("lecturer_b", "Giảng Viên Demo B", "Kỹ thuật phần mềm"),
        ("lecturer_c", "Giảng Viên Demo C", "Hệ thống thông tin"),
        ("lecturer_d", "Giảng Viên Demo D", "Toán và Ngoại ngữ"),
    ]:
        store.users[uid] = Lecturer(uid, name, f"{uid}@example.com", default_pw, department=dept)
    names = ['Sinh Viên Mẫu 01', 'Sinh Viên Mẫu 02', 'Sinh Viên Mẫu 03', 'Sinh Viên Mẫu 04', 'Sinh Viên Mẫu 05', 'Sinh Viên Mẫu 06', 'Sinh Viên Mẫu 07', 'Sinh Viên Mẫu 08', 'Sinh Viên Mẫu 09', 'Sinh Viên Mẫu 10']
    majors = ["Kỹ thuật phần mềm", "Trí tuệ nhân tạo", "An toàn thông tin"]
    for i, name in enumerate(names, start=1):
        sid = f"SE17{i:04d}"
        store.users[sid] = Student(sid, name, f"{sid.lower()}@example.com", default_pw,
                                   major=majors[i % len(majors)])

    start = (monday_of(date.today()) - timedelta(weeks=3)).isoformat()
    spec = [  # mã môn, tên, giảng viên, sĩ số, tín chỉ, phòng, lịch, số thứ tự sinh viên
        ("CSI106", "Nhập môn khoa học máy tính", "lecturer_a", 8, 3, "DE-C201", "Mon-1,Wed-1", range(1, 7)),
        ("PFP191", "Cơ sở lập trình Python", "lecturer_b", 8, 3, "DE-C208", "Mon-2,Wed-2", []),
        ("PRF191", "Lập trình cơ bản", "lecturer_b", 8, 3, "DE-C209", "Tue-3,Fri-3", []),
        ("DBI202", "Cơ sở dữ liệu", "lecturer_c", 6, 3, "DE-C305", "Tue-2,Thu-2", range(1, 5)),
        ("MAD101", "Toán rời rạc", "lecturer_d", 5, 3, "AL-R101", "Mon-3,Thu-3", range(1, 6)),
        ("CSD106", "Cấu trúc dữ liệu và giải thuật", "lecturer_a", 8, 3, "DE-C207", "Tue-4,Fri-4", range(5, 11)),
        ("SWE201c", "Nhập môn Kỹ thuật phần mềm", "lecturer_c", 10, 3, "DE-C402", "Mon-1,Wed-5", range(7, 10)),
        ("ENW492c", "Viết học thuật", "lecturer_d", 12, 2, "AL-R204", "Wed-3,Fri-5", [1, 2, 8, 9]),
    ]
    for code, name, lec, cap, cred, room, sched, nums in spec:
        store.courses[code] = Course(
            code=code, name=name, lecturer_id=lec, capacity=cap, credits=cred, room=room,
            schedule=TimeSlot.parse_many(sched), start_date=start,
            student_ids=[f"SE17{n:04d}" for n in nums])
    store.courses["MAD101"].waitlist.append("SE170006")  # MAD101 đã đầy

    rng = random.Random(2026)
    today = date.today()
    for course in store.courses.values():
        for session in course.sessions():
            if session.day < today:
                course.attendance[session.key] = {
                    sid: rng.choices([PRESENT, LATE, ABSENT], [80, 7, 13])[0]
                    for sid in course.student_ids}
    prp = store.courses["CSI106"]  # minh họa quy tắc cấm thi do vắng nhiều
    for session in prp.sessions()[:5]:
        prp.attendance[session.key]["SE170003"] = ABSENT
    add_requested_students(store)
    store.save()


# --------------------------------------------------------------------------- #
# Giao diện dòng lệnh
# --------------------------------------------------------------------------- #
def seed_fap_demo(store: DataStore) -> None:
    """Tạo dữ liệu giả lập FAP chỉ khi khởi tạo hoặc chủ động reset."""
    seed_sample_data(store)
    ids = ["DEMO001", "DEMO002", "DEMO003"]
    patterns = ["PPPPLP", "PAPAPP", "AAAPAP"]
    for code in ("CSI106", "CSD106", "PFP191", "PRF191"):
        course = store.courses[code]
        course.student_ids = ids.copy()
        course.attendance.clear()
        past = [session for session in course.sessions() if session.day < date.today()]
        for index, session in enumerate(past[:6]):
            course.attendance[session.key] = {
                sid: patterns[number][index] for number, sid in enumerate(ids)}
    store.save()


class Console:
    """Các hàm hỗ trợ nhập/xuất thống nhất cho giao diện console."""

    @staticmethod
    def title(text: str) -> None:
        print("\n" + "=" * 70 + f"\n  {text}\n" + "=" * 70)

    @staticmethod
    def table(headers: List[str], rows: List[List[object]]) -> None:
        body = [[str(c) for c in row] for row in rows]
        widths = [max([len(h)] + [len(r[i]) for r in body]) for i, h in enumerate(headers)]
        sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
        print(sep)
        print("| " + " | ".join(h.ljust(w) for h, w in zip(headers, widths)) + " |")
        print(sep)
        for row in body:
            print("| " + " | ".join(c.ljust(w) for c, w in zip(row, widths)) + " |")
        print(sep)
        print(f"({len(body)} dòng)")

    @staticmethod
    def ask(prompt: str, parser: Callable[[str], object] = lambda v: v,
            default: Optional[object] = None, optional: bool = False) -> object:
        """Hỏi đến khi ``parser`` chấp nhận. ``optional``: nhấn Enter trả về None."""
        while True:
            suffix = f" [{default}]" if default is not None else (" (Enter để bỏ qua)" if optional else "")
            raw = input(f"  {prompt}{suffix}: ").strip()
            if not raw:
                if optional:
                    return None
                if default is not None:
                    raw = str(default)
            try:
                return parser(raw)
            except AppError as exc:
                print(f"    [!] {exc}")

    @staticmethod
    def confirm(prompt: str) -> bool:
        return input(f"  {prompt} (y/n): ").strip().lower() in ("y", "yes", "c", "co", "có")

    @staticmethod
    def bar(percent: float, width: int = 20) -> str:
        filled = int(round(percent / 100 * width))
        return "[" + "#" * filled + "." * (width - filled) + f"] {percent:5.1f}%"


def course_rows(store: DataStore, courses: List[Course]) -> List[List[object]]:
    rows = []
    for c in courses:
        teacher = store.users.get(c.lecturer_id)
        rows.append([c.code, c.name[:28], teacher.name if teacher else c.lecturer_id,
                     c.credits, c.schedule_text, c.room, f"{c.enrolled}/{c.capacity}",
                     c.seats_left, len(c.waitlist)])
    return rows


COURSE_HEADERS = ["Mã môn", "Tên môn", "Giảng viên", "TC", "Lịch học", "Phòng",
                  "Sĩ số", "Trống", "Chờ"]


class Menu:
    """Lớp cha: các thao tác dùng chung + vòng lặp menu. Lớp con khai báo ``options``."""

    title = "MENU"

    def __init__(self, sv: Services, user: User) -> None:
        self.sv = sv
        self.user = user

    def options(self) -> List[Tuple[str, Callable[[], None]]]:
        raise NotImplementedError

    def run(self) -> None:
        opts = self.options()
        while True:
            Console.title(f"{self.title} - {self.user.name} ({self.user.user_id})")
            if self.user.notifications:
                print(f"  Bạn có {len(self.user.notifications)} thông báo.")
            for i, (label, _) in enumerate(opts, start=1):
                print(f"  {i:>2}. {label}")
            print("   0. Đăng xuất")
            choice = input("\n  Chọn chức năng: ").strip()
            if choice == "0":
                return
            if choice.isdigit() and 1 <= int(choice) <= len(opts):
                try:
                    opts[int(choice) - 1][1]()
                except AppError as exc:
                    print(f"\n  [!] {exc}")
            else:
                print("  [!] Lựa chọn không hợp lệ.")

    # ---- thao tác dùng chung ----------------------------------------------
    def show_course_list(self, courses: Optional[List[Course]] = None) -> None:
        courses = courses if courses is not None else sorted(
            self.sv.store.courses.values(), key=lambda c: c.code)
        Console.table(COURSE_HEADERS, course_rows(self.sv.store, courses))

    def search_courses(self) -> None:
        print("  Để trống bộ lọc nào thì bỏ qua bộ lọc đó.")
        keyword = str(Console.ask("Từ khóa (mã/tên môn)", optional=True) or "")
        lecturer = str(Console.ask("Giảng viên (tên/mã)", optional=True) or "")
        day = str(Console.ask("Thứ (Mon..Sun)", optional=True) or "")
        credits = Console.ask("Số tín chỉ", lambda v: Validator.integer(v, "Số tín chỉ", 1, 10),
                              optional=True)
        available = Console.confirm("Chỉ hiện môn còn chỗ trống?")
        results = self.sv.courses.search(keyword, lecturer, day,
                                         credits if isinstance(credits, int) else None, available)
        self.show_course_list(results)

    def view_course(self) -> None:
        code = str(Console.ask("Mã môn", Validator.course_code))
        course = self.sv.courses.get(code)
        teacher = self.sv.store.users.get(course.lecturer_id)
        print(f"\n  {course.code} - {course.name}")
        print(f"  Giảng viên : {teacher.name if teacher else course.lecturer_id}")
        print(f"  Lịch học   : {course.schedule_text}   Phòng: {course.room}")
        print(f"  Tín chỉ    : {course.credits}   Số buổi: {course.total_sessions}   "
              f"Bắt đầu: {course.start_date}")
        print(f"  Sĩ số      : {course.enrolled}/{course.capacity} (còn {course.seats_left}), "
              f"danh sách chờ {len(course.waitlist)}")
        rate = course.attendance_rate()
        print(f"  Tỷ lệ điểm danh: {'chưa có' if rate is None else Console.bar(rate)}")
        can_see_roster = self.user.ROLE == "admin" or (
            self.user.ROLE == "lecturer" and course.lecturer_id == self.user.user_id)
        if can_see_roster:
            rows = []
            for sid in course.student_ids:
                s = self.sv.store.users.get(sid)
                rows.append([sid, s.name if s else sid, RISK_LABEL[course.risk_level(sid)]])
            Console.table(["Mã SV", "Họ tên", "Điểm danh"], rows)
            if course.waitlist:
                print("  Danh sách chờ: " + ", ".join(course.waitlist))

    def show_timetable(self) -> None:
        week = monday_of(date.today())
        while True:
            grid, details = self.sv.timetable.week(self.user, week)
            col = 12
            print(f"\n  Tuần {week:%d/%m/%Y} - {week + timedelta(days=6):%d/%m/%Y}")
            head = "Slot".ljust(14) + "".join(
                f"{WEEKDAYS[i]} {(week + timedelta(days=i)):%d/%m}".center(col) for i in range(7))
            print("  " + head)
            print("  " + "-" * len(head))
            for slot, (start, end) in SLOT_TIMES.items():
                cells = "".join(grid.get((d, slot), ".").center(col) for d in range(7))
                print("  " + f"{slot} {start}-{end}".ljust(14) + cells)
            print("  Chú thích: (P) có mặt  (A) vắng  (L) muộn  (-) chưa điểm danh  (*) đã điểm danh")
            for line in details:
                print("   - " + line)
            cmd = input("\n  [n] tuần sau, [p] tuần trước, [t] tuần này, Enter = quay lại: ").strip().lower()
            if cmd == "n":
                week += timedelta(weeks=1)
            elif cmd == "p":
                week -= timedelta(weeks=1)
            elif cmd == "t":
                week = monday_of(date.today())
            else:
                return

    def show_attendance_details(self, course: Course) -> None:
        labels = {PRESENT: "Có mặt", ABSENT: "Vắng", LATE: "Đi muộn", "-": "Chưa điểm danh"}
        teacher = self.sv.store.get_lecturer(course.lecturer_id)
        print(f"\n  {course.code} - {course.name} | Giảng viên: {teacher.name} | Phòng: {course.room}")
        if isinstance(self.user, Student):
            rows = [[session.number, session.day.strftime("%d/%m/%Y"), session.slot,
                     SLOT_TIMES[session.slot][0] + "-" + SLOT_TIMES[session.slot][1],
                     course.room, teacher.user_id,
                     labels[course.attendance.get(session.key, {}).get(self.user.user_id, "-")]]
                    for session in course.sessions()]
            Console.table(["Buổi", "Ngày", "Slot", "Giờ", "Phòng", "Giảng viên", "Điểm danh"], rows)
        else:
            sessions = course.sessions()
            rows = [[sid, self.sv.store.get_student(sid).name] +
                    [course.attendance.get(session.key, {}).get(sid, "-") for session in sessions]
                    for sid in course.student_ids]
            Console.table(["Mã SV", "Họ tên"] + [str(session.number) for session in sessions], rows)
            print("  P = Có mặt | A = Vắng | L = Đi muộn | - = Chưa điểm danh")
            for session in sessions:
                print(f"  Buổi {session.number:02d}: {session.day:%d/%m/%Y} - slot {session.slot}")

    def show_notifications(self) -> None:
        if not self.user.notifications:
            print("  Không có thông báo.")
            return
        for line in reversed(self.user.notifications):
            print("   * " + line)
        if Console.confirm("Xóa tất cả thông báo?"):
            self.user.notifications.clear()
            self.sv.store.save()

    def change_password(self) -> None:
        old = str(Console.ask("Mật khẩu hiện tại"))
        new = str(Console.ask("Mật khẩu mới (tối thiểu 6 ký tự)", Validator.password))
        self.sv.auth.change_password(self.user, old, new)
        print("  Đã đổi mật khẩu.")


class AdminMenu(Menu):
    title = "ADMIN"

    def options(self) -> List[Tuple[str, Callable[[], None]]]:
        return [
            ("Danh sách tất cả môn học", self.show_course_list),
            ("Tìm kiếm môn học", self.search_courses),
            ("Xem chi tiết môn + danh sách lớp", self.view_course),
            ("Tạo môn học", self.create_course),
            ("Cập nhật môn học", self.update_course),
            ("Xóa môn học", self.delete_course),
            ("Danh sách giảng viên", self.list_lecturers),
            ("Thêm giảng viên", self.add_lecturer),
            ("Cập nhật giảng viên", self.update_lecturer),
            ("Xóa giảng viên", self.delete_lecturer),
            ("Danh sách sinh viên", self.list_students),
            ("Thêm sinh viên", self.add_student),
            ("Xóa sinh viên", self.delete_student),
            ("Bảng thống kê", self.dashboard),
            ("Thời khóa biểu tất cả môn (tuần này)", self.show_timetable),
            ("Thông báo", self.show_notifications),
            ("Đổi mật khẩu", self.change_password),
        ]

    # ---- môn học ----------------------------------------------------------
    def create_course(self) -> None:
        self.list_lecturers()
        code = str(Console.ask("Mã môn (vd: PRP201c)", Validator.course_code))
        name = str(Console.ask("Tên môn", lambda v: Validator.text(v, "Tên môn", 3, 60)))
        lecturer = str(Console.ask("Mã giảng viên", Validator.user_id))
        capacity = Console.ask("Sĩ số tối đa",
                               lambda v: Validator.integer(v, "Sĩ số tối đa", 1, 500))
        credits = Console.ask("Số tín chỉ", lambda v: Validator.integer(v, "Số tín chỉ", 1, 10), default=3)
        room = str(Console.ask("Phòng học", lambda v: Validator.text(v, "Phòng học", 2, 20)))
        schedule = Console.ask("Lịch học (vd: Mon-1,Wed-3)", TimeSlot.parse_many)
        start = str(Console.ask("Ngày bắt đầu YYYY-MM-DD",
                                lambda v: Validator.date_str(v, "Ngày bắt đầu"),
                                default=monday_of(date.today()).isoformat()))
        sessions = Console.ask("Tổng số buổi",
                               lambda v: Validator.integer(v, "Tổng số buổi", 1, 60), default=20)
        course = self.sv.courses.create(self.user, code, name, lecturer, capacity,
                                        schedule, start, credits, room, sessions)  # type: ignore[arg-type]
        print(f"  Đã tạo môn {course.code} - {course.name}.")

    def update_course(self) -> None:
        course = self.sv.courses.get(str(Console.ask("Mã môn", Validator.course_code)))
        print("  Nhấn Enter để giữ nguyên giá trị hiện tại.")
        changes: Dict[str, object] = {}
        fields: List[Tuple[str, str, Callable[[str], object]]] = [
            ("name", f"Tên môn [{course.name}]", lambda v: Validator.text(v, "Tên môn", 3, 60)),
            ("lecturer_id", f"Mã giảng viên [{course.lecturer_id}]", Validator.user_id),
            ("capacity", f"Sĩ số tối đa [{course.capacity}]",
             lambda v: Validator.integer(v, "Sĩ số tối đa", 1, 500)),
            ("credits", f"Số tín chỉ [{course.credits}]",
             lambda v: Validator.integer(v, "Số tín chỉ", 1, 10)),
            ("room", f"Phòng học [{course.room}]", lambda v: Validator.text(v, "Phòng học", 2, 20)),
            ("schedule", f"Lịch học [{course.schedule_text}]", TimeSlot.parse_many),
        ]
        for key, prompt, parser in fields:
            value = Console.ask(prompt, parser, optional=True)
            if value is not None:
                changes[key] = value
        if not changes:
            print("  Không có gì để cập nhật.")
            return
        self.sv.courses.update(self.user, course.code, **changes)
        print(f"  Đã cập nhật {course.code}: {', '.join(changes)}.")

    def delete_course(self) -> None:
        course = self.sv.courses.get(str(Console.ask("Mã môn", Validator.course_code)))
        if Console.confirm(f"Xóa môn {course.code} ({course.enrolled} sinh viên đang học)?"):
            self.sv.courses.delete(self.user, course.code)
            print("  Đã xóa môn học; sinh viên trong lớp đã được thông báo.")

    # ---- giảng viên -------------------------------------------------------
    def list_lecturers(self) -> None:
        rows = [[l.user_id, l.name, l.email, l.department,
                 ", ".join(c.code for c in self.sv.store.courses_of_lecturer(l.user_id)) or "-"]
                for l in self.sv.store.lecturers()]
        Console.table(["Mã", "Họ tên", "Email", "Bộ môn", "Môn phụ trách"], rows)

    def add_lecturer(self) -> None:
        uid = str(Console.ask("Mã giảng viên", Validator.user_id))
        name = str(Console.ask("Họ tên", lambda v: Validator.text(v, "Họ tên")))
        email = str(Console.ask("Email", Validator.email))
        dept = str(Console.ask("Bộ môn", lambda v: Validator.text(v, "Bộ môn")))
        self.sv.users.add_lecturer(self.user, uid, name, email, dept)
        print(f"  Đã tạo giảng viên {uid} (mật khẩu mặc định: demo_user_2026).")

    def update_lecturer(self) -> None:
        lec = self.sv.store.get_lecturer(str(Console.ask("Mã giảng viên", Validator.user_id)))
        print("  Nhấn Enter để giữ nguyên giá trị hiện tại.")
        name = Console.ask(f"Họ tên [{lec.name}]", lambda v: Validator.text(v, "Họ tên"), optional=True)
        email = Console.ask(f"Email [{lec.email}]", Validator.email, optional=True)
        dept = Console.ask(f"Bộ môn [{lec.department}]",
                           lambda v: Validator.text(v, "Bộ môn"), optional=True)
        self.sv.users.update_lecturer(self.user, lec.user_id, name, email, dept)  # type: ignore[arg-type]
        print("  Đã cập nhật giảng viên.")

    def delete_lecturer(self) -> None:
        uid = str(Console.ask("Mã giảng viên", Validator.user_id))
        if Console.confirm(f"Xóa giảng viên {uid}?"):
            self.sv.users.delete_lecturer(self.user, uid)
            print("  Đã xóa giảng viên.")

    # ---- sinh viên --------------------------------------------------------
    def list_students(self) -> None:
        rows = [[s.user_id, s.name, s.major,
                 ", ".join(c.code for c in self.sv.store.courses_of_student(s.user_id)) or "-"]
                for s in self.sv.store.students()]
        Console.table(["Mã SV", "Họ tên", "Chuyên ngành", "Môn đã đăng ký"], rows)

    def add_student(self) -> None:
        uid = str(Console.ask("Mã sinh viên", Validator.user_id))
        name = str(Console.ask("Họ tên", lambda v: Validator.text(v, "Họ tên")))
        email = str(Console.ask("Email", Validator.email))
        major = str(Console.ask("Chuyên ngành", lambda v: Validator.text(v, "Chuyên ngành")))
        self.sv.users.add_student(self.user, uid, name, email, major)
        print(f"  Đã tạo sinh viên {uid} (mật khẩu mặc định: demo_user_2026).")

    def delete_student(self) -> None:
        uid = str(Console.ask("Mã sinh viên", Validator.user_id))
        if Console.confirm(f"Xóa sinh viên {uid} và toàn bộ đăng ký môn?"):
            self.sv.users.delete_student(self.user, uid, self.sv.courses)
            print("  Đã xóa sinh viên.")

    # ---- báo cáo ----------------------------------------------------------
    def dashboard(self) -> None:
        info = self.sv.reports.summary()
        print(f"\n  Môn học: {info['total_courses']}   Giảng viên: {info['total_lecturers']}   "
              f"Sinh viên: {info['total_students_registered']}")
        print(f"  Tổng sinh viên trên mọi môn : {info['total_enrollments']} "
              f"({info['unique_enrolled_students']} sinh viên khác nhau)")
        print(f"  Tỷ lệ sử dụng chỗ           : {Console.bar(info['utilisation_pct'])}")
        avg = info["average_attendance_pct"]
        print(f"  Điểm danh trung bình        : {'chưa có' if avg is None else Console.bar(avg)}")

        def fmt(items: List[CourseStat], attendance: bool = False) -> str:
            if not items:
                return "chưa có"
            value = (f"{items[0].attendance_rate}%" if attendance else f"{items[0].enrolled} sinh viên")
            return ", ".join(i.code for i in items) + f"  ({value})"

        print(f"  Đông sinh viên nhất  : {fmt(info['highest_enrollment'])}")
        print(f"  Ít sinh viên nhất    : {fmt(info['lowest_enrollment'])}")
        print(f"  Điểm danh cao nhất   : {fmt(info['highest_attendance'], True)}")
        print(f"  Điểm danh thấp nhất  : {fmt(info['lowest_attendance'], True)}\n")
        rows = [[s.code, s.name[:28], f"{s.enrolled}/{s.capacity}",
                 Console.bar(s.enrolled * 100 / s.capacity, 10),
                 "chưa có" if s.attendance_rate is None else Console.bar(s.attendance_rate, 10)]
                for s in self.sv.reports.course_stats()]
        Console.table(["Mã môn", "Tên môn", "Sĩ số", "Mức đầy", "Điểm danh"], rows)


class LecturerMenu(Menu):
    title = "GIẢNG VIÊN"

    def options(self) -> List[Tuple[str, Callable[[], None]]]:
        return [
            ("Các môn tôi dạy", self.my_courses),
            ("Xem chi tiết môn + danh sách lớp", self.view_course),
            ("Điểm danh", self.take_attendance),
            ("Báo cáo điểm danh / sinh viên có nguy cơ", self.attendance_report),
            ("Thời khóa biểu giảng dạy (tuần)", self.show_timetable),
            ("Thông báo đến lớp", self.announce),
            ("Thông báo của tôi", self.show_notifications),
            ("Đổi mật khẩu", self.change_password),
        ]

    def my_courses(self) -> None:
        self.show_course_list(self.sv.store.courses_of_lecturer(self.user.user_id))

    def _ask_own_course(self) -> Course:
        self.my_courses()
        code = str(Console.ask("Mã môn", Validator.course_code))
        return self.sv.courses.get_owned(self.user, code)

    def take_attendance(self) -> None:
        course = self._ask_own_course()
        if not course.student_ids:
            raise ValidationError("Môn này chưa có sinh viên.")
        sessions = self.sv.attendance.started_sessions(course)
        if not sessions:
            raise ValidationError("Chưa có buổi học nào bắt đầu.")
        print("\n  Các buổi học đã bắt đầu:")
        for s in sessions:
            mark = "đã điểm danh" if s.key in course.attendance else "chưa điểm danh"
            print(f"   {s.label}  [{mark}]")
        default = next((s.number for s in sessions if s.key not in course.attendance),
                       sessions[-1].number)
        number = Console.ask("Số thứ tự buổi học",
                             lambda v: Validator.integer(v, "Buổi học", 1, len(sessions)),
                             default=default)
        session = sessions[int(number) - 1]  # type: ignore[arg-type]
        print(f"\n  Điểm danh {course.code} {session.label}")
        print(f"  Giảng viên: {self.user.name} | Phòng: {course.room} | Sĩ số: {course.enrolled}")
        print("  P = có mặt (mặc định), A = vắng, L = muộn")
        marks: Dict[str, str] = {}
        for sid in course.student_ids:
            student = self.sv.store.users.get(sid)
            previous = course.attendance.get(session.key, {}).get(sid, PRESENT)
            marks[sid] = str(Console.ask(f"{sid} {student.name if student else ''}",
                                         Validator.status, default=previous))
        risky = self.sv.attendance.take(self.user, course.code, session.key, marks)
        print("  Đã lưu điểm danh.")
        for sid, level in risky.items():
            print(f"  [!] {sid} đã chuyển sang mức {RISK_LABEL[level].upper()}; đã thông báo cho sinh viên.")

    def attendance_report(self) -> None:
        course = self._ask_own_course()
        self.show_attendance_details(course)
        rows = [[r["student_id"], r["name"], r["present"], r["late"], r["absent"],
                 f"{r['absent_pct']}%", RISK_LABEL[r["status"]]]
                for r in self.sv.attendance.class_report(self.user, course.code)]
        Console.table(["Mã SV", "Họ tên", "P", "L", "A", "Vắng %", "Tình trạng"], rows)
        print(f"  Quy tắc: CẢNH BÁO khi vắng >= {ABSENCE_WARNING_RATIO:.0%}, "
              f"CẤM THI khi vắng > {ABSENCE_LIMIT_RATIO:.0%} trên {course.total_sessions} buổi.")

    def announce(self) -> None:
        course = self._ask_own_course()
        message = str(Console.ask("Nội dung", lambda v: Validator.text(v, "Nội dung", 3, 200)))
        for sid in course.student_ids:
            student = self.sv.store.users.get(sid)
            if student:
                student.notify(f"{course.code} - {self.user.name}: {message}")
        self.sv.store.save()
        print(f"  Đã gửi đến {course.enrolled} sinh viên.")


class StudentMenu(Menu):
    title = "SINH VIÊN"

    def options(self) -> List[Tuple[str, Callable[[], None]]]:
        return [
            ("Xem tất cả môn học", self.show_course_list),
            ("Tìm kiếm môn học (bộ lọc)", self.search_courses),
            ("Xem chi tiết môn học", self.view_course),
            ("Đăng ký môn học", self.register),
            ("Hủy đăng ký môn học", self.drop),
            ("Môn học đã đăng ký", self.my_courses),
            ("Thời khóa biểu tuần", self.show_timetable),
            ("Báo cáo điểm danh của tôi", self.attendance_report),
            ("Thông báo", self.show_notifications),
            ("Đổi mật khẩu", self.change_password),
        ]

    def register(self) -> None:
        code = str(Console.ask("Mã môn", Validator.course_code))
        try:
            print("\n  " + self.sv.registration.register(self.user, code))
        except CourseFullError as exc:
            print(f"\n  [!] {exc}")
            if Console.confirm("Vào danh sách chờ?"):
                print("  " + self.sv.registration.register(self.user, code, join_waitlist=True))

    def drop(self) -> None:
        self.my_courses()
        code = str(Console.ask("Mã môn cần hủy", Validator.course_code))
        if Console.confirm(f"Hủy môn {code}?"):
            print("  " + self.sv.registration.drop(self.user, code))

    def my_courses(self) -> None:
        courses = self.sv.store.courses_of_student(self.user.user_id)
        self.show_course_list(courses)
        waiting = [c.code for c in self.sv.store.courses.values() if self.user.user_id in c.waitlist]
        if waiting:
            print("  Đang trong danh sách chờ: " + ", ".join(waiting))
        print(f"  Tổng số tín chỉ: {sum(c.credits for c in courses)}")

    def attendance_report(self) -> None:
        rows = [[r["code"], r["name"][:24], f"{r['taken']}/{r['total']}", r["present"],
                 r["late"], r["absent"], f"{r['absent_pct']}%", RISK_LABEL[r["status"]]]
                for r in self.sv.attendance.student_report(self.user)]  # type: ignore[arg-type]
        Console.table(["Mã môn", "Tên môn", "Đã điểm danh", "P", "L", "A", "Vắng %", "Tình trạng"], rows)
        courses = self.sv.store.courses_of_student(self.user.user_id)
        code = input("  Nhập mã môn để xem từng buổi (Enter để quay lại): ").strip().upper()
        if code:
            course = next((c for c in courses if c.code.upper() == code), None)
            if course is None:
                raise PermissionDenied("Bạn chỉ được xem điểm danh môn đã đăng ký.")
            self.show_attendance_details(course)



MENUS: Dict[str, type] = {"admin": AdminMenu, "lecturer": LecturerMenu, "student": StudentMenu}


# --------------------------------------------------------------------------- #
# Ứng dụng
# --------------------------------------------------------------------------- #
class App:
    """Bộ điều khiển cấp cao nhất: vòng lặp đăng nhập + chuyển menu theo vai trò."""

    # CHỈ DÀNH CHO CHẾ ĐỘ DEMO CỤC BỘ; tuyệt đối không sử dụng tài khoản mẫu trong hệ thống thật.
    DEMO_HELP = (
        "  Tài khoản demo (Mã / Mật khẩu):\n"
        "    Admin       : admin / demo_admin_2026\n"
        "    Giảng viên  : lecturer_a, lecturer_b, lecturer_c, lecturer_d / demo_user_2026\n"
        "    Sinh viên   : SE170001 ... SE170010 / demo_user_2026"
    )

    def __init__(self, sv: Services) -> None:
        self.sv = sv

    def run(self) -> None:
        Console.title("HỆ THỐNG QUẢN LÝ GIẢNG DẠY")
        print(self.DEMO_HELP)
        while True:
            try:
                uid = input("\n  Mã đăng nhập (để trống để thoát): ").strip()
                if not uid:
                    break
                password = input("  Mật khẩu: ")
                user = self.sv.auth.login(uid, password)
            except AppError as exc:
                print(f"  [!] {exc}")
                continue
            except (EOFError, KeyboardInterrupt):
                break
            try:
                MENUS[user.ROLE](self.sv, user).run()
            except (EOFError, KeyboardInterrupt):
                break
            self.sv.store.save()
        self.sv.store.save()
        print("\n  Đã lưu dữ liệu. Tạm biệt!")


# --------------------------------------------------------------------------- #
# Kiểm thử tự động
# --------------------------------------------------------------------------- #
def run_selftest() -> None:
    """Kiểm tra các quy tắc nghiệp vụ cho từng vai trò."""
    import tempfile

    def expect(exc: type, fn: Callable[..., object], *args: object, **kwargs: object) -> None:
        try:
            fn(*args, **kwargs)
        except exc:
            return
        raise AssertionError(f"Cần có lỗi {exc.__name__} từ {getattr(fn, '__name__', fn)}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        store = DataStore(tmp_path / "data.json")
        seed_sample_data(store)
        sv = Services(store)
        admin = sv.auth.login("admin", "demo_admin_2026")
        lecturer_a = sv.auth.login("lecturer_a", "demo_user_2026")
        lecturer_d = sv.auth.login("lecturer_d", "demo_user_2026")
        lecturer_b = sv.auth.login("lecturer_b", "demo_user_2026")
        assert lecturer_a.name == "Giảng Viên Demo A"
        assert lecturer_b.name == "Giảng Viên Demo B"
        assert {c.code for c in store.courses_of_lecturer("lecturer_a")} == {"CSI106", "CSD106"}
        assert {c.code for c in store.courses_of_lecturer("lecturer_b")} == {"PFP191", "PRF191"}
        for sid in ("DEMO001", "DEMO002", "DEMO003"):
            assert isinstance(sv.auth.login(sid, "demo_user_2026"), Student)
            assert {"CSI106", "CSD106", "PFP191", "PRF191"} <= {
                c.code for c in store.courses_of_student(sid)}
        before = copy.deepcopy(store.courses)
        add_requested_students(store)
        assert store.courses == before
        assert not hasattr(RegistrationService, "enroll_by_lecturer")
        assert not hasattr(RegistrationService, "remove_by_lecturer")
        labels = [label for label, _ in LecturerMenu(sv, lecturer_a).options()]
        assert not any("Thêm sinh viên" in label or "Xóa sinh viên" in label for label in labels)
        expect(AppError, sv.auth.login, "admin", "wrong")

        # ---- Admin: CRUD môn học + kiểm tra dữ liệu
        slots = TimeSlot.parse_many("Wed-8")
        course = sv.courses.create(admin, "NEW101", "Môn mới", "lecturer_a", 2, slots,
                                   date.today().isoformat(), 3, "DE-X1", 10)
        expect(ValidationError, sv.courses.create, admin, "NEW101", "Trùng", "lecturer_a", 2, slots,
               date.today().isoformat(), 3, "DE-X2", 10)            # trùng mã
        expect(ValidationError, sv.courses.create, admin, "BAD1", "Sai", "lecturer_a", 2, slots,
               date.today().isoformat(), 3, "DE-X2", 10)            # mã sai
        expect(ValidationError, sv.courses.create, admin, "NEW102", "Sai", "lecturer_a", "abc", slots,
               date.today().isoformat(), 3, "DE-X2", 10)            # sĩ số sai
        expect(ValidationError, sv.courses.create, admin, "NEW103", "Trùng GV", "lecturer_a", 5,
               TimeSlot.parse_many("Mon-1"), date.today().isoformat(), 3, "DE-X3", 10)
        expect(ValidationError, sv.courses.create, admin, "NEW104", "Trùng phòng", "lecturer_c", 5,
               TimeSlot.parse_many("Mon-1"), date.today().isoformat(), 3, "DE-C201", 10)
        student10 = sv.auth.login("SE170010", "demo_user_2026")
        expect(PermissionDenied, sv.courses.create, student10, "NEW105", "X", "lecturer_a", 5, slots,
               date.today().isoformat(), 3, "DE-X9", 10)            # kiểm tra phân quyền
        expect(ValidationError, sv.courses.update, admin, "CSI106", capacity=2)  # nhỏ hơn sĩ số hiện có
        print("  [ok] Admin CRUD, kiểm tra dữ liệu, xung đột, phân quyền")

        # ---- Sinh viên: đăng ký / trùng / trùng lịch / danh sách chờ / hủy
        s9, s8 = (sv.auth.login(f"SE17{n:04d}", "demo_user_2026") for n in (9, 8))
        assert "thành công" in sv.registration.register(student10, "NEW101")
        expect(RegistrationError, sv.registration.register, student10, "NEW101")   # đăng ký trùng
        sv.registration.register(s9, "NEW101")
        expect(CourseFullError, sv.registration.register, s8, "NEW101")
        assert "danh sách chờ" in sv.registration.register(s8, "NEW101", join_waitlist=True)
        sv.registration.drop(student10, "NEW101")
        assert course.has_student("SE170008"), "Không đưa được sinh viên từ danh sách chờ vào lớp"
        s1 = sv.auth.login("SE170001", "demo_user_2026")
        expect(RegistrationError, sv.registration.register, s1, "SWE201c")  # Mon-1 trùng PRP201c
        print("  [ok] Đăng ký, chống trùng, trùng lịch, danh sách chờ tự động")

        # ---- Admin: tăng sĩ số thì đưa người từ danh sách chờ vào lớp
        assert "SE170006" in store.courses["MAD101"].waitlist
        sv.courses.update(admin, "MAD101", capacity=6)
        assert store.courses["MAD101"].has_student("SE170006")
        print("  [ok] Tăng sĩ số tự động xếp sinh viên đang chờ")

        # ---- Giảng viên: quyền sở hữu + điểm danh
        prp = store.courses["CSI106"]
        first, last = prp.sessions()[0], prp.sessions()[-1]
        expect(PermissionDenied, sv.attendance.take, lecturer_d, "CSI106", first.key, {})
        expect(ValidationError, sv.attendance.take, lecturer_a, "CSI106", last.key, {})  # buổi tương lai
        sv.attendance.take(lecturer_a, "CSI106", first.key,
                           {"SE170002": ABSENT, "SE170003": ABSENT})  # không liệt kê => có mặt
        assert prp.attendance[first.key]["SE170002"] == ABSENT
        assert prp.attendance[first.key]["SE170001"] == PRESENT
        report = {r["student_id"]: r for r in sv.attendance.class_report(lecturer_a, "CSI106")}
        assert report["SE170003"]["status"] == "BANNED"
        print("  [ok] Quyền giảng viên, điểm danh, phát hiện nguy cơ cấm thi")

        # ---- Báo cáo
        info = sv.reports.summary()
        assert info["total_enrollments"] == sum(c.enrolled for c in store.courses.values())
        assert info["highest_enrollment"] and info["lowest_attendance"]
        grid, details = sv.timetable.week(s1, monday_of(date.today()))
        assert grid and details
        print("  [ok] Thống kê, thời khóa biểu")

        # ---- Lưu trữ + quy tắc xóa
        reloaded = DataStore(tmp_path / "data.json")
        assert reloaded.load()
        assert {c: v.student_ids for c, v in reloaded.courses.items()} == \
               {c: v.student_ids for c, v in store.courses.items()}
        sv.courses.delete(admin, "NEW101")
        assert "NEW101" not in store.courses
        expect(ValidationError, sv.users.delete_lecturer, admin, "lecturer_a")
        print("  [ok] Lưu JSON, quy tắc xóa")
    print("\nTẤT CẢ KIỂM THỬ ĐỀU ĐẠT")


# --------------------------------------------------------------------------- #
# Điểm vào chương trình
# --------------------------------------------------------------------------- #
def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    parser = argparse.ArgumentParser(description="Hệ thống quản lý giảng dạy")
    parser.add_argument("--data", default=str(DATA_FILE), help="đường dẫn file dữ liệu JSON")
    parser.add_argument("--reset", action="store_true", help="tạo lại dữ liệu mẫu")
    parser.add_argument("--selftest", action="store_true", help="chạy kiểm thử tự động rồi thoát")
    args = parser.parse_args()

    if args.selftest:
        run_selftest()
        return
    store = DataStore(Path(args.data))
    if args.reset or not store.load():
        seed_fap_demo(store)
        print("Đã tạo dữ liệu mẫu.")
    App(Services(store)).run()


if __name__ == "__main__":
    main()
