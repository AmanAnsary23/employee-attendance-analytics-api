
# Design Decisions

1. **Indexes:** I use a unique index on `employees.emp_code` to prevent duplicate employee codes, a unique compound index on `attendance_logs (emp_code, date)` to prevent duplicate daily attendance, and an index on `(date, emp_code)` for date-based attendance queries. The employee `(department, joined_on)` index helps department trend queries. I would avoid adding indexes without checking their query benefit and write overhead.

2. **Punch-in race:** Concurrent requests for the same employee and date compete to insert the attendance record. The unique compound index allows only one insert to succeed. The successful request returns 201, while the duplicate request returns 409.

3. **Ties:** The late leaderboard uses competition ranking, so employees with equal total late minutes receive the same rank. The cutoff logic should preserve employees tied at the last included rank rather than arbitrarily excluding them. The final behavior must match the API contract.

4. **Headcount:** The department summary must include employees who joined by the end of the requested month, even if they have no attendance records. This requires starting from employees or otherwise preserving employees with no matching logs.

5. **Scaling:** For 100 times more data, I would test query plans on representative data, review aggregation performance and indexes, and add pagination or other optimizations where the contract permits.