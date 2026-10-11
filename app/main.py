"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""
from pydantic import HttpUrl
import os
import re
from datetime import datetime, timedelta, timezone , date
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pymongo import MongoClient
from fastapi import FastAPI, HTTPException , Query
from datetime import datetime , timezone
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel, model_validator
from decimal import Decimal , ROUND_HALF_UP
from pydantic import BaseModel, StrictInt
from typing import Optional
from bson.json_util import dumps
import json

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


@app.on_event("startup")
def create_indexes():

    db.employees.create_index(
        [("emp_code", 1)],
        unique=True
    )

    db.attendance_logs.create_index(
        [("emp_code", 1), ("date", 1)],
        unique=True
    )

    db.attendance_logs.create_index(
        [("date", -1), ("emp_code", 1)],
        name="ix_attendance_date_emp"
    )

    db.employees.create_index(
        [("department", 1), ("joined_on", 1)],
        name="ix_employee_department_joined"
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    h, m = map(int, shift_start.split(":"))
    start = punch_in.replace(hour=h, minute=m, second=0, microsecond=0)
    minutes = int((punch_in - start).total_seconds() / 60)
    return minutes if minutes > 10 else 0


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    return round((punch_out - punch_in).total_seconds() / 3600, 2)


def compute_overtime(punch_out: datetime, shift_end: str, date_str: str) -> int:
    h, m = map(int, shift_end.split(":"))
    end = datetime.fromisoformat(date_str).replace(hour=h, minute=m, tzinfo=IST)
    return max(0, int((punch_out - end).total_seconds() / 60))


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str

    @model_validator(mode="after")
    def validate_employee(self):
        try:
            joined_date = datetime.strptime(self.joined_on, "%Y-%m-%d")
            if joined_date.strftime("%Y-%m-%d") != self.joined_on:
                raise ValueError("joined_on must use YYYY-MM-DD format")
        except ValueError:
            raise ValueError("joined_on must be a valid date in YYYY-MM-DD format")

        for field_name in ("shift_start", "shift_end"):
            value = getattr(self, field_name)
            try:
                parsed_time = datetime.strptime(value, "%H:%M")
                if parsed_time.strftime("%H:%M") != value:
                    raise ValueError
            except ValueError:
                raise ValueError(f"{field_name} must be a valid time in HH:MM format")

        if self.shift_start == self.shift_end:
            raise ValueError("shift_start and shift_end must be different")

        return self


class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"

class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None

class RegularizeIn(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[StrictInt] = None
    punch_out: Optional[StrictInt] = None
    reason: str
    regularized_by: str


# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        db.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="MongoDB unavailable"
        )

@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    doc["created_at"] = datetime.now(timezone.utc)

    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="emp_code already exists"
        )

    doc.pop("_id", None)
    return doc


@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100)
):
    q = {}

    if department:
        q["department"] = department

    skip = (page - 1) * page_size

    total = db.employees.count_documents(q)

    items = list(
        db.employees.find(q, {"_id": 0})
        .sort("emp_code", 1)
        .skip(skip)
        .limit(page_size)
    )

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size
    }


IIST = timezone(timedelta(hours=5, minutes=30))


@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if not emp:
        raise HTTPException(
            status_code=404,
            detail="Employee not found"
        )

    if body.punched_at is not None:
        if (
            isinstance(body.punched_at, bool)
            or not isinstance(body.punched_at, int)
            or body.punched_at < 100_000_000_000
            or body.punched_at > 253_402_300_799_999
        ):
            raise HTTPException(
                status_code=422,
                detail="punched_at must be a valid epoch timestamp in milliseconds"
            )

        try:
            ts = datetime.fromtimestamp(
                body.punched_at / 1000,
                tz=timezone.utc
            )
        except (ValueError, OverflowError, OSError):
            raise HTTPException(
                status_code=422,
                detail="Invalid punched_at timestamp"
            )
    else:
        ts = datetime.now(timezone.utc)

    local_ts = ts.astimezone(IST).replace(microsecond=0)
    ts = local_ts.astimezone(timezone.utc)
    attendance_date = local_ts.date().isoformat()

    doc = {
        "emp_code": body.emp_code,
        "date": attendance_date,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(
            local_ts, emp["shift_start"]
        ),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }

    try:
        result = db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=409,
            detail="already punched in for this date"
        )

    doc["id"] = str(result.inserted_id)
    doc.pop("_id", None)

    return doc


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    q = {}
    if emp_code:
        q["emp_code"] = emp_code
    if date_from or date_to:
        q["date"] = {}
        if date_from:
            q["date"]["$gte"] = date_from
        if date_to:
            q["date"]["$lte"] = date_to
    if status:
        q["status"] = status
    docs = list(db.attendance_logs.find(q))
    docs.sort(key=lambda d: d["date"], reverse=True)
    total = len(docs)
    page_docs = docs[(page - 1) * page_size : page * page_size]
    for d in page_docs:
        d["id"] = str(d.pop("_id"))
    return {"items": page_docs, "total": total, "page": page, "page_size": page_size}



@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if not emp:
        raise HTTPException(404, "Employee not found")

    if body.punched_at is not None:
        if (
            isinstance(body.punched_at, bool)
            or not isinstance(body.punched_at, int)
            or not 100_000_000_000 <= body.punched_at <= 253_402_300_799_999
        ):
            raise HTTPException(
                422, "punched_at must be valid epoch milliseconds"
            )

        try:
            punch_out_ts = datetime.fromtimestamp(
                body.punched_at / 1000,
                tz=timezone.utc
            )
        except (ValueError, OverflowError, OSError):
            raise HTTPException(422, "Invalid punched_at timestamp")
    else:
        punch_out_ts = datetime.now(timezone.utc)

    punch_out_local = punch_out_ts.astimezone(IST).replace(microsecond=0)
    punch_out_ts = punch_out_local.astimezone(timezone.utc)
    attendance_date = punch_out_local.date().isoformat()

    record = db.attendance_logs.find_one({
        "emp_code": body.emp_code,
        "date": attendance_date
    })

    if not record:
        raise HTTPException(404, "Punch-in record not found for this date")

    if record.get("punch_out") is not None:
        raise HTTPException(409, "Already punched out")

    punch_in_ts = record["punch_in"]
    if punch_in_ts.tzinfo is None:
        punch_in_ts = punch_in_ts.replace(tzinfo=timezone.utc)

    if punch_out_ts <= punch_in_ts:
        raise HTTPException(422, "Punch-out must be after punch-in")

    start_local = punch_in_ts.astimezone(IST)
    end_local = punch_out_ts.astimezone(IST)

    work_seconds = int((punch_out_ts - punch_in_ts).total_seconds())

    work_hours = float(
        (Decimal(work_seconds) / Decimal(3600)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP
        )
    )

    shift_start = datetime.strptime(
        emp["shift_start"], "%H:%M"
    ).time()
    shift_end = datetime.strptime(
        emp["shift_end"], "%H:%M"
    ).time()

    shift_end_dt = datetime.combine(
        start_local.date(), shift_end, tzinfo=IST
    )

    if shift_end <= shift_start:
        shift_end_dt += timedelta(days=1)

    overtime_minutes = 0
    extra_minutes = int(
        (end_local - shift_end_dt).total_seconds() // 60
    )

    if extra_minutes >= 30:
        overtime_minutes = extra_minutes

    half_day = work_hours < 4.50

    result = db.attendance_logs.update_one(
        {
            "_id": record["_id"],
            "punch_out": None
        },
        {
            "$set": {
                "punch_out": punch_out_ts,
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day
            }
        }
    )

    if result.modified_count != 1:
        raise HTTPException(409, "Already punched out")

    updated = db.attendance_logs.find_one({"_id": record["_id"]})
    updated["id"] = str(updated.pop("_id"))

    return updated


@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(emp_code: str, date: str, body: RegularizeIn):
    from datetime import date as Date
    from pydantic import ValidationError

    try:
        if Date.fromisoformat(date).isoformat() != date:
            raise ValueError
    except ValueError:
        raise HTTPException(422, "date must be YYYY-MM-DD")

    if not 5 <= len(body.reason) <= 200:
        raise HTTPException(422, "reason must be 5-200 characters")
    if not 1 <= len(body.regularized_by) <= 50:
        raise HTTPException(422, "regularized_by must be 1-50 characters")

    allowed_statuses = {"PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"}
    supplied = body.model_fields_set

    if body.status is not None and body.status not in allowed_statuses:
        raise HTTPException(422, "Invalid status")

    for field in ("punch_in", "punch_out"):
        value = getattr(body, field)
        if field in supplied:
            if (
                value is None
                or isinstance(value, bool)
                or not isinstance(value, int)
                or not 100_000_000_000 <= value <= 253_402_300_799_999
            ):
                raise HTTPException(
                    422, f"{field} must be epoch milliseconds"
                )

    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(404, "Employee not found")

    record = db.attendance_logs.find_one({
        "emp_code": emp_code,
        "date": date
    })
    if not record:
        raise HTTPException(404, "Attendance record not found")

    old_history = record.get("history", [])
    old_status = record["status"]
    old_in = record.get("punch_in")
    old_out = record.get("punch_out")

    def as_utc(value):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def from_ms(value):
        return datetime.fromtimestamp(value / 1000, timezone.utc).replace(
            microsecond=0
        )

    new_status = body.status if "status" in supplied else old_status
    new_in = as_utc(old_in)
    new_out = as_utc(old_out)

    if "punch_in" in supplied:
        new_in = from_ms(body.punch_in)
    if "punch_out" in supplied:
        new_out = from_ms(body.punch_out)

    if new_status in {"ABSENT", "LEAVE"}:
        if "punch_in" in supplied or "punch_out" in supplied:
            raise HTTPException(
                422, "ABSENT or LEAVE cannot include punch times"
            )
        new_in = None
        new_out = None
    elif new_in is None:
        raise HTTPException(422, "Presence status requires punch_in")

    shift_start = datetime.strptime(emp["shift_start"], "%H:%M").time()
    shift_end = datetime.strptime(emp["shift_end"], "%H:%M").time()
    overnight = shift_end <= shift_start

    if new_in is not None:
        local_in = new_in.astimezone(IST)
        shift_date = local_in.date()

        if overnight and local_in.time().replace(tzinfo=None) < shift_end:
            from datetime import timedelta as TD
            shift_date -= TD(days=1)

        if shift_date.isoformat() != date:
            raise HTTPException(
                422, "punch_in must belong to the attendance date"
            )

        if new_out is not None:
            seconds = (new_out - new_in).total_seconds()
            if seconds <= 0 or seconds > 86400:
                raise HTTPException(
                    422, "punch_out must be after punch_in and within 24 hours"
                )

    late_minutes = 0
    work_hours = None
    overtime_minutes = 0
    half_day = False

    if new_in is not None:
        local_in = new_in.astimezone(IST)
        shift_date = local_in.date()

        if overnight and local_in.time().replace(tzinfo=None) < shift_end:
            from datetime import timedelta as TD
            shift_date -= TD(days=1)

        shift_start_dt = datetime.combine(
            shift_date, shift_start, tzinfo=IST
        )
        shift_end_dt = datetime.combine(
            shift_date, shift_end, tzinfo=IST
        )

        if overnight:
            shift_end_dt += timedelta(days=1)

        elapsed = (local_in - shift_start_dt).total_seconds()
        if elapsed > 600:
            late_minutes = int(elapsed // 60)

        if new_out is not None:
            work_seconds = int((new_out - new_in).total_seconds())
            work_hours = float(
                (Decimal(work_seconds) / Decimal(3600)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            )

            local_out = new_out.astimezone(IST)
            extra_minutes = int(
                (local_out - shift_end_dt).total_seconds() // 60
            )
            if extra_minutes >= 30:
                overtime_minutes = extra_minutes

            half_day = work_hours < 4.50

    final_values = {
        "status": new_status,
        "punch_in": new_in,
        "punch_out": new_out,
        "late_minutes": late_minutes,
        "work_hours": work_hours,
        "overtime_minutes": overtime_minutes,
        "half_day": half_day,
    }

    old_values = {
        "status": old_status,
        "punch_in": as_utc(old_in),
        "punch_out": as_utc(old_out),
        "late_minutes": record.get("late_minutes", 0),
        "work_hours": record.get("work_hours"),
        "overtime_minutes": record.get("overtime_minutes", 0),
        "half_day": record.get("half_day", False),
    }

    changes = {}
    for field, new_value in final_values.items():
        old_value = old_values[field]
        if old_value != new_value:
            changes[field] = {
                "from": old_value,
                "to": new_value
            }

    if not changes:
        raise HTTPException(422, "Request does not change anything")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    history_entry = {
        "at": now,
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": changes,
    }

    query = {"_id": record["_id"]}
    if "history" in record:
        query["history"] = old_history
    else:
        query["history"] = {"$exists": False}

    result = db.attendance_logs.update_one(
        query,
        {
            "$set": final_values,
            "$push": {"history": history_entry}
        }
    )

    if result.modified_count != 1:
        raise HTTPException(409, "Record changed concurrently; retry")

    updated = db.attendance_logs.find_one({"_id": record["_id"]})

    def to_ms(value):
        value = as_utc(value)
        return int(value.timestamp() * 1000) if value else None

    updated.pop("_id", None)
    updated["punch_in"] = to_ms(updated.get("punch_in"))
    updated["punch_out"] = to_ms(updated.get("punch_out"))

    for entry in updated.get("history", []):
        entry["at"] = to_ms(entry["at"])
        for field in ("punch_in", "punch_out"):
            if field in entry["changes"]:
                entry["changes"][field]["from"] = to_ms(
                    entry["changes"][field]["from"]
                )
                entry["changes"][field]["to"] = to_ms(
                    entry["changes"][field]["to"]
                )

    return updated

@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str = Query(...)):
    import calendar
    from datetime import date as Date
    from decimal import Decimal, ROUND_HALF_UP

    try:
        month_date = datetime.strptime(month, "%Y-%m").date()
        if month_date.strftime("%Y-%m") != month:
            raise ValueError
    except ValueError:
        raise HTTPException(422, "month must be YYYY-MM")

    emp = db.employees.find_one({"emp_code": emp_code})

    if not emp:
        raise HTTPException(404, "Employee not found")

    year, month_num = month_date.year, month_date.month
    month_start = Date(year, month_num, 1)
    month_end = Date(year, month_num, calendar.monthrange(year, month_num)[1])

    joined_on = Date.fromisoformat(emp["joined_on"])
    first_day = max(month_start, joined_on)

    working_days = 0
    if first_day <= month_end:
        current = first_day
        while current <= month_end:
            if current.weekday() < 5:
                working_days += 1
            current += timedelta(days=1)

    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {
                    "$gte": month_start.isoformat(),
                    "$lte": month_end.isoformat()
                }
            }
        },
        {
            "$group": {
                "_id": None,
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                    {
                                        "$in": [
                                            {"$dayOfWeek": {
                                                "$dateFromString": {
                                                    "dateString": "$date"
                                                }
                                            }},
                                            [2, 3, 4, 5, 6]
                                        ]
                                    }
                                ]
                            },
                            {
                                "$cond": [
                                    "$half_day",
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },
                "leave_days": {
                    "$sum": {
                        "$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]
                    }
                },
                "total_late_minutes": {"$sum": "$late_minutes"},
                "total_overtime_minutes": {"$sum": "$overtime_minutes"}
            }
        }
    ]

    results = list(db.attendance_logs.aggregate(pipeline))
    data = results[0] if results else {}

    present_days = data.get("present_days", 0)
    attendance_pct = None

    if working_days > 0:
        attendance_pct = float(
            (Decimal(str(present_days)) * Decimal(100) /
             Decimal(working_days)).quantize(
                Decimal("0.0001"),
                rounding=ROUND_HALF_UP
            )
        )

    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": data.get("leave_days", 0),
        "late_count": data.get("late_count", 0),
        "total_late_minutes": data.get("total_late_minutes", 0),
        "total_overtime_minutes": data.get("total_overtime_minutes", 0),
        "attendance_pct": attendance_pct
    }


@app.get("/analytics/departments/summary")
def department_summary(month: str = Query(...)):
    import calendar
    from datetime import date as Date

    try:
        month_date = datetime.strptime(month, "%Y-%m").date()
        if month_date.strftime("%Y-%m") != month:
            raise ValueError
    except ValueError:
        raise HTTPException(422, "month must be YYYY-MM")

    year, month_num = month_date.year, month_date.month
    month_start = Date(year, month_num, 1)
    month_end = Date(
        year, month_num,
        calendar.monthrange(year, month_num)[1]
    )

    employees = list(db.employees.find({
        "joined_on": {"$lte": month_end.isoformat()}
    }))

    departments = {}

    for emp in employees:
        departments.setdefault(emp["department"], []).append(emp)

    items = []

    for department, dept_employees in departments.items():
        emp_codes = [e["emp_code"] for e in dept_employees]

        pipeline = [
            {
                "$match": {
                    "emp_code": {"$in": emp_codes},
                    "date": {
                        "$gte": month_start.isoformat(),
                        "$lte": month_end.isoformat()
                    }
                }
            },
            {
                "$group": {
                    "_id": None,
                    "present_days": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$and": [
                                        {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                                        {
                                            "$in": [
                                                {"$dayOfWeek": {
                                                    "$dateFromString": {
                                                        "dateString": "$date"
                                                    }
                                                }},
                                                [2, 3, 4, 5, 6]
                                            ]
                                        }
                                    ]
                                },
                                {"$cond": [{"$ifNull": ["$half_day", False]}, 0.5, 1]},
                                0
                            ]
                        }
                    },
                    "avg_work_hours": {"$avg": "$work_hours"},
                    "late_count": {
                        "$sum": {"$cond": [{"$gt": ["$late_minutes", 0]}, 1, 0]}
                    },
                    "total_late_minutes": {"$sum": "$late_minutes"},
                    "leave_count": {
                        "$sum": {"$cond": [{"$eq": ["$status", "LEAVE"]}, 1, 0]}
                    },
                    "on_duty_count": {
                        "$sum": {"$cond": [{"$eq": ["$status", "ON_DUTY"]}, 1, 0]}
                    }
                }
            }
        ]

        result = list(db.attendance_logs.aggregate(pipeline))
        data = result[0] if result else {}

        avg_hours = data.get("avg_work_hours")
        if avg_hours is not None:
            avg_hours = float(
                Decimal(str(avg_hours)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            )

        items.append({
            "department": department,
            "headcount": len(dept_employees),
            "present_days": data.get("present_days", 0),
            "avg_work_hours": avg_hours,
            "late_count": data.get("late_count", 0),
            "total_late_minutes": data.get("total_late_minutes", 0),
            "leave_count": data.get("leave_count", 0),
            "on_duty_count": data.get("on_duty_count", 0)
        })

    return {"month": month, "items": sorted(items, key=lambda x: x["department"])}


@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str = Query(...),
    limit: int = Query(10, ge=1, le=50),
    department: str | None = Query(None),
):

    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(
            status_code=422,
            detail="month must be in YYYY-MM format"
        )

    year, month_number = map(int, month.split("-"))

    from calendar import monthrange
    last_day = monthrange(year, month_number)[1]

    start_date = f"{month}-01"
    end_date = f"{month}-{last_day:02d}"

    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": start_date,
                    "$lte": end_date
                }
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {
                    "$sum": {"$ifNull": ["$late_minutes", 0]}
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]},
                            1,
                            0
                        ]
                    }
                }
            }
        },
        {
            "$match": {
                "total_late_minutes": {"$gt": 0}
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee"
            }
        },
        {"$unwind": "$employee"},
    ]

    if department is not None:
        pipeline.append({
            "$match": {"employee.department": department}
        })

    pipeline.extend([
        {
            "$project": {
                "_id": 0,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "late_count": 1
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"total_late_minutes": -1},
                "output": {
                    "rank": {"$rank": {}}
                }
            }
        },
        {"$match": {"rank": {"$lte": limit}}},
        {
            "$sort": {
                "total_late_minutes": -1,
                "emp_code": 1
            }
        }
    ])

    items = list(db.attendance_logs.aggregate(pipeline))

    return {
        "month": month,
        "items": items
    }


@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
):

    try:
        start = date.fromisoformat(from_date)
        end = date.fromisoformat(to_date)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Dates must use YYYY-MM-DD format"
        )

    if start.isoformat() != from_date or end.isoformat() != to_date:
        raise HTTPException(
            status_code=422,
            detail="Dates must use YYYY-MM-DD format"
        )

    if end < start:
        raise HTTPException(
            status_code=422,
            detail="'to' must be on or after 'from'"
        )

    number_of_days = (end - start).days + 1
    if number_of_days > 92:
        raise HTTPException(
            status_code=422,
            detail="Date range cannot exceed 92 days"
        )

    if not db.employees.find_one({"department": department}):
        raise HTTPException(
            status_code=404,
            detail="Department not found"
        )

    start_string = start.isoformat()

    pipeline = [
        {"$match": {"department": department}},
        {
            "$set": {
                "_joined": {
                    "$dateFromString": {
                        "dateString": "$joined_on"
                    }
                }
            }
        },
        {
            "$set": {
                "_dates": {
                    "$map": {
                        "input": {"$range": [0, number_of_days]},
                        "as": "offset",
                        "in": {
                            "$dateAdd": {
                                "startDate": {
                                    "$dateFromString": {
                                        "dateString": start_string
                                    }
                                },
                                "unit": "day",
                                "amount": "$$offset"
                            }
                        }
                    }
                }
            }
        },
        {"$unwind": "$_dates"},
        {
            "$set": {
                "_day": {
                    "$dateToString": {
                        "date": "$_dates",
                        "format": "%Y-%m-%d",
                        "timezone": "UTC"
                    }
                },
                "_joined_by_day": {
                    "$lte": ["$_joined", "$_dates"]
                }
            }
        },
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {
                    "code": "$emp_code",
                    "day": "$_day",
                    "joined": "$_joined_by_day"
                },
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$emp_code", "$$code"]},
                                    {"$eq": ["$date", "$$day"]},
                                    {"$eq": ["$$joined", True]}
                                ]
                            }
                        }
                    }
                ],
                "as": "_logs"
            }
        },
        {
            "$unwind": {
                "path": "$_logs",
                "preserveNullAndEmptyArrays": True
            }
        },
        {
            "$group": {
                "_id": "$_day",
                "headcount": {
                    "$sum": {
                        "$cond": ["$_joined_by_day", 1, 0]
                    }
                },
                "present_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    "$_joined_by_day",
                                    {
                                        "$in": [
                                            "$_logs.status",
                                            ["PRESENT", "WFH", "ON_DUTY"]
                                        ]
                                    }
                                ]
                            },
                            {
                                "$cond": [
                                    {"$ifNull": ["$_logs.half_day", False]},
                                    0.5,
                                    1
                                ]
                            },
                            0
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    "$_joined_by_day",
                                    {"$gt": ["$_logs.late_minutes", 0]}
                                ]
                            },
                            1,
                            0
                        ]
                    }
                }
            }
        },
        {
            "$set": {
                "is_working_day": {
                    "$and": [
                        {
                            "$gte": [
                                {"$dayOfWeek": {
                                    "$dateFromString": {"dateString": "$_id"}
                                }},
                                2
                            ]
                        },
                        {
                            "$lte": [
                                {"$dayOfWeek": {
                                    "$dateFromString": {"dateString": "$_id"}
                                }},
                                6
                            ]
                        }
                    ]
                },
                "attendance_rate": {
                    "$cond": [
                        {
                            "$and": [
                                {
                                    "$gte": [
                                        {"$dayOfWeek": {
                                            "$dateFromString": {"dateString": "$_id"}
                                        }},
                                        2
                                    ]
                                },
                                {
                                    "$lte": [
                                        {"$dayOfWeek": {
                                            "$dateFromString": {"dateString": "$_id"}
                                        }},
                                        6
                                    ]
                                },
                                {"$gt": ["$headcount", 0]}
                            ]
                        },
                        {"$divide": ["$present_count", "$headcount"]},
                        None
                    ]
                }
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"_id": 1},
                "output": {
                    "_moving_avg": {
                        "$avg": "$attendance_rate",
                        "window": {"documents": [-6, 0]}
                    }
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "date": "$_id",
                "is_working_day": 1,
                "headcount": 1,
                "present_count": 1,
                "late_count": 1,
                "attendance_rate": 1,
                "moving_avg_7d": "$_moving_avg"
            }
        },
        {"$sort": {"date": 1}}
    ]

    items = list(db.employees.aggregate(pipeline))

    for item in items:
        for field in ("attendance_rate", "moving_avg_7d"):
            value = item[field]
            if value is not None:
                item[field] = float(
                    Decimal(str(value)).quantize(
                        Decimal("0.0001"),
                        rounding=ROUND_HALF_UP
                    )
                )

    return {
        "department": department,
        "items": items
    }


@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: str,
    emp_code: Optional[str] = None,
    month: Optional[str] = None,
    department: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """
    Return MongoDB execution statistics for supported query patterns.
    """

    if endpoint == "attendance_list":
        query = {}

        if emp_code:
            query["emp_code"] = emp_code
        if date_from or date_to:
            query["date"] = {}
            if date_from:
                query["date"]["$gte"] = date_from
            if date_to:
                query["date"]["$lte"] = date_to
        if status:
            query["status"] = status

        cursor = (
            db.attendance_logs
            .find(query)
            .sort("date", -1)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )

        result = db.command(
            "explain",
            {
                "find": "attendance_logs",
                "filter": query,
                "sort": {"date": -1},
                "skip": (page - 1) * page_size,
                "limit": page_size,
            },
            verbosity="executionStats",
        )
        collection = "attendance_logs"

    elif endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(
                status_code=422,
                detail="emp_code and month are required",
            )

        query = {"emp_code": emp_code, "date": {"$regex": f"^{re.escape(month)}"}}

        result = db.command(
            "explain",
            {
                "find": "attendance_logs",
                "filter": query,
            },
            verbosity="executionStats",
        )
        collection = "attendance_logs"

    elif endpoint == "department_summary":
        if not month:
            raise HTTPException(status_code=422, detail="month is required")

        query = {"date": {"$regex": f"^{re.escape(month)}"}}

        result = db.command(
            "explain",
            {
                "find": "attendance_logs",
                "filter": query,
            },
            verbosity="executionStats",
        )
        collection = "attendance_logs"

    elif endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(status_code=422, detail="month is required")

        query = {
            "date": {"$regex": f"^{re.escape(month)}"},
            "late_minutes": {"$gt": 0},
        }

        result = db.command(
            "explain",
            {
                "find": "attendance_logs",
                "filter": query,
            },
            verbosity="executionStats",
        )
        collection = "attendance_logs"

    elif endpoint == "department_trend":
        if not department or not date_from or not date_to:
            raise HTTPException(
                status_code=422,
                detail="department, date_from and date_to are required",
            )

        query = {
            "department": department,
            "joined_on": {"$lte": date_to},
        }

        result = db.command(
            "explain",
            {
                "find": "employees",
                "filter": query,
            },
            verbosity="executionStats",
        )
        collection = "employees"

    else:
        raise HTTPException(
            status_code=404,
            detail=f"Unsupported endpoint: {endpoint}",
        )

    return json.loads(dumps({
    "endpoint": endpoint,
    "collection": collection,
    "explain": result,
}))



# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #