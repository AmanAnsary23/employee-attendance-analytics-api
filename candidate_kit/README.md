# Employee Attendance & Analytics API

A REST API built with FastAPI and MongoDB for employee management, attendance tracking, attendance regularization, and analytics.

## Tech Stack

- Python
- FastAPI
- MongoDB
- PyMongo
- Pydantic

## Setup

Create and activate a virtual environment:

```bash
python -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a `.env` file in the project root:

```env
MONGO_URI=your_mongodb_connection_string
MONGO_DB=attendance_db
```

Replace the connection string with your MongoDB connection details. Do not commit `.env` or expose credentials.

## Run the Application

```bash
uvicorn app.main:app --reload --port 8000
```

Health check: `http://localhost:8000/health`

Interactive API documentation: `http://localhost:8000/docs`

## Main API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Check API and MongoDB connectivity |
| POST | `/employees` | Create an employee |
| GET | `/employees` | List employees with pagination |
| POST | `/attendance/punch-in` | Record attendance punch-in |
| POST | `/attendance/punch-out` | Record attendance punch-out |
| GET | `/attendance` | List attendance records |
| PATCH | `/attendance/{emp_code}/{date}` | Regularize attendance |
| GET | `/analytics/employees/{emp_code}/monthly` | Retrieve monthly employee analytics |
| GET | `/analytics/departments/summary` | Retrieve department summaries |
| GET | `/analytics/leaderboard/late` | Retrieve the late-arrival leaderboard |
| GET | `/analytics/departments/{department}/trend` | Retrieve department attendance trends |
| GET | `/admin/explain/{endpoint}` | Inspect supported MongoDB query plans |

Use Swagger UI at `/docs` to explore endpoints, provide request parameters, and inspect responses.

## Project Files

- `app/main.py` — API implementation
- `requirements.txt` — Python dependencies
- `REVIEW.md` — Starter-code defect review
- `DECISIONS.md` — Design decisions

## Notes

- MongoDB 6.0 or newer is required.
- Configure database credentials through environment variables.
- Do not commit secrets or the local `.env` file.
