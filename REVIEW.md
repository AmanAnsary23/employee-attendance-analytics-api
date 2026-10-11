# REVIEW.md

## Defects Found in the Starter Code

| # | Where | What is wrong | How to notice | How it was fixed |
|---|---|---|---|---|
| 1 | `health()` | Always returns success without checking MongoDB connectivity. | Stop MongoDB and call `/health`. | Added a MongoDB ping and return HTTP 503 when unavailable. |
| 2 | `create_employee()` | Checks duplicates before insertion without enforcing uniqueness at the database level. Concurrent requests can create duplicates. | Send simultaneous requests with the same `emp_code`. | Added a unique index and handle `DuplicateKeyError` with HTTP 409. |
| 3 | `create_employee()` | Stores `created_at` using a naive local timestamp. | Inspect the stored timestamp and compare it across time zones. | Store timestamps in UTC. |
| 4 | `list_employees()` | Uses `page * page_size` for the offset, causing the first page to skip records. | Request page 1 with a page size of 20. | Use `(page - 1) * page_size` and validate pagination parameters. |
| 5 | `list_employees()` | Counts all employees instead of counting the filtered query. | Request a department filter and compare `total` with matching employees. | Count documents using the same filter query. |
| 6 | `list_employees()` | Does not provide deterministic sorting. | Repeat paginated requests while records are present. | Sort by `emp_code` before pagination. |
| 7 | `punch_in()` | Does not handle a nonexistent employee before accessing employee shift details. | Punch in using an unknown employee code. | Return HTTP 404 when the employee does not exist. |
| 8 | `punch_in()` | Duplicate check and insertion are separate operations without a unique database constraint. Concurrent requests can create duplicate attendance records. | Send simultaneous punch-in requests for the same employee and date. | Added a unique compound index on `(emp_code, date)` and handle duplicate-key errors. |
| 9 | `punch_in()` | Does not validate epoch timestamps or consistently use IST to determine the attendance date. | Submit invalid timestamps or timestamps near midnight UTC. | Validate epoch milliseconds and derive the attendance date in IST. |
| 10 | `compute_late_minutes()` | Uses the punch-in date with the shift start time, which can miscalculate overnight shifts. | Test a shift that crosses midnight. | Calculate lateness against the correct shift start datetime. |
| 11 | `compute_work_hours()` | Uses Python's built-in `round()`, which does not guarantee the required half-up rounding behavior. | Test work durations at rounding boundaries. | Calculate work hours using `Decimal` with `ROUND_HALF_UP`. |
| 12 | `compute_overtime()` | Does not correctly handle overnight shifts and does not enforce the minimum 30-minute overtime threshold. | Test punch-out around the shift end and for overnight shifts. | Calculate the correct shift-end datetime and apply the 30-minute threshold. |
| 13 | `list_attendance()` | Loads all matching attendance records into memory before sorting and paginating. | Test with a large attendance collection. | Apply sorting, skipping and limiting in the MongoDB query. |
| 14 | `list_attendance()` | Does not validate pagination inputs. | Send page 0 or an invalid page size. | Added page and page-size validation. |
| 15 | Contract endpoints | Punch-out, attendance regularization and the required analytics and explain endpoints are missing from the starter. | Compare registered routes with `openapi.yaml`. | Implemented the missing endpoints in the current implementation. |

## Reviewed Items That Were Not Defects

- Using `emp_code` as the employee business identifier is consistent with the data model.
- Returning HTTP 201 for successful employee creation and punch-in is appropriate.
- Excluding MongoDB's internal `_id` from employee responses is intentional; the API can expose its own `id` field where required.
