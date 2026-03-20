"""
Employee Shift Scheduling Optimization

This script solves a shift scheduling problem using Google OR-Tools (SCIP solver).
It assigns employees to work shifts while optimizing for:
  - Coverage: Exactly 2 workers per time segment
  - Fairness: Minimal workload imbalance
  - Preferences: Minimizing fatigue and underutilization
  - Efficiency: Minimizing sudden role changes

INPUTS:
  - Shifts (required coverage): Read from config.TURNI_OUTPUT
  - Availability (employee windows): Read from config.DISPONIBILITA_OUTPUT
  - Max hours (per-employee limits): Read from config.MAXORE_OUTPUT

OUTPUTS:
  - Console: Schedule and workload summary
  - CSV: Matrix view of assignments with hours totals

CONSTRAINTS:
  - Coverage: Each segment needs exactly 2 workers
  - Availability: Only assign available employees
  - Hours: Respect max hours per employee

SOFT OBJECTIVES (weighted penalties):
  - Load balance: Minimize difference between busiest and quietest workers
  - Efficiency: Penalize rapid role/position switches
  - Fatigue: Penalize excessive consecutive work
  - Underwork: Penalize shifts shorter than ideal
"""

from ortools.linear_solver import pywraplp
from datetime import datetime
import csv
import config


# ===========================
# INPUT DATA LOADING
# ===========================


def to_dt(date, start, end):
    # Standardizing to your parse_range output
    return datetime.strptime(f"{date} {start}", "%d/%m %H:%M"), datetime.strptime(
        f"{date} {end}", "%d/%m %H:%M"
    )


# 1. Fill 'shifts' (Requirements)
shifts = []
with open(config.TURNI_OUTPUT) as f:
    for row in csv.DictReader(f):
        shifts.append(to_dt(row["Date"], row["Start"], row["End"]))

# 2. Fill 'employees' (Availability)
availability = {}
with open(config.DISPONIBILITA_OUTPUT) as f:
    for row in csv.DictReader(f):
        name = row["Employee"]
        if name not in availability:
            availability[name] = []
        availability[name].append(to_dt(row["Date"], row["Start"], row["End"]))

# 3. Fill 'max hours' (Constraint)
max_hours = {}
with open(config.MAXORE_OUTPUT) as f:
    for row in csv.DictReader(f):
        name = row["Employee"]
        if name not in max_hours:
            max_hours[name] = float(row["MaxHours"]) * 60

# -----------------------------
# BUILD TIME SEGMENTS
# -----------------------------

time_points = set()

for s, e in shifts:
    time_points.add(s)
    time_points.add(e)

for e in availability:
    if availability[e]:
        for a, b in availability[e]:
            time_points.add(a)
            time_points.add(b)

time_points = sorted(time_points)

segments = []

for i in range(len(time_points) - 1):

    s = time_points[i]
    e = time_points[i + 1]

    # keep only segments inside shifts
    for ss, ee in shifts:
        if s >= ss and e <= ee:
            segments.append((s, e))
            break

# -----------------------------
# AVAILABILITY CHECK
# -----------------------------


def is_available(emp, seg):
    s, e = seg

    for a, b in availability[emp]:
        if s >= a and e <= b:
            return True

    return False


# -----------------------------
# COVERAGE CHECK
# -----------------------------

print("\nCOVERAGE CHECK\n")

for i, seg in enumerate(segments):
    s, e = seg

    # Calculate demand for this segment
    requirement_count = sum(1 for ss, ee in shifts if s >= ss and e <= ee)
    needed = requirement_count * 2

    available = [emp for emp in availability if is_available(emp, seg)]

    if len(available) < needed:
        print(
            f"{s.strftime('%d/%m %H:%M')} - {e.strftime('%H:%M')} "
            f"NEEDS {needed}, BUT ONLY {len(available)} AVAILABLE -> {available}"
        )
        # exit() to stop on first error


# -----------------------------
# MODEL
# -----------------------------

solver = pywraplp.Solver.CreateSolver("SCIP")

emp_list = list(availability.keys())
seg_ids = range(len(segments))

x = {}

for e in emp_list:
    for i in seg_ids:
        if is_available(e, segments[i]):
            x[(e, i)] = solver.BoolVar(f"x_{e}_{i}")


# -----------------------------
# DYNAMIC COVERAGE (2 or 4 workers)
# -----------------------------

for i, seg in enumerate(segments):
    s, e = seg

    # Count how many requirement shifts overlap this segment, in case more than one desk is to cover at the same time
    requirement_count = 0
    for ss, ee in shifts:
        if s >= ss and e <= ee:
            requirement_count += 1

    # Each shift needs 2 people
    needed = requirement_count * 2

    if needed > 0:
        solver.Add(sum(x[(e, i)] for e in emp_list if (e, i) in x) == needed)


# -----------------------------
# WORKLOAD
# -----------------------------

work = {}

for e in emp_list:

    work[e] = solver.NumVar(
        0, max_hours[e] if e in max_hours else solver.infinity(), f"work_{e}"
    )

    solver.Add(
        work[e]
        == sum(
            x[(e, i)] * (segments[i][1] - segments[i][0]).total_seconds() / 60
            for i in seg_ids
            if (e, i) in x
        )
    )


max_work = solver.NumVar(0, solver.infinity(), "max")
min_work = solver.NumVar(0, solver.infinity(), "min")

for e in emp_list:
    solver.Add(work[e] <= max_work)
    solver.Add(work[e] >= min_work)


# -----------------------------
# SWITCH PENALTY
# -----------------------------

switches = []

for e in emp_list:
    for i in range(len(segments) - 1):

        if (e, i) in x and (e, i + 1) in x:

            sw = solver.NumVar(0, 1, "")

            solver.Add(sw >= x[(e, i)] - x[(e, i + 1)])
            solver.Add(sw >= x[(e, i + 1)] - x[(e, i)])

            switches.append(sw)

# -----------------------------
# 1. SOFT LIMIT ON CONSECUTIVE WORK (OVERWORK)
# -----------------------------
fatigue_penalties = []

for e in emp_list:
    for i in seg_ids:
        if (e, i) not in x:
            continue

        duration_sum = 0
        window_vars = []

        for j in range(i, len(segments)):
            # Break if non-contiguous (gap in time)
            if j > i and segments[j][0] != segments[j - 1][1]:
                break
            if (e, j) not in x:
                break

            duration = (segments[j][1] - segments[j][0]).total_seconds() / 60
            duration_sum += duration
            window_vars.append(x[(e, j)])

            # If this sequence exceeds the limit, penalize if ALL segments are active
            if duration_sum > config.MAX_IDEAL_MINUTES:
                violation = solver.BoolVar(f"fatigue_{e}_{i}_{j}")
                # violation is 1 if sum of window == number of segments in window
                solver.Add(sum(window_vars) - (len(window_vars) - 1) <= violation)

                overtime_mins = duration_sum - config.MAX_IDEAL_MINUTES
                # We use FATIGUE_WEIGHT here
                fatigue_penalties.append(
                    violation * overtime_mins * config.FATIGUE_WEIGHT
                )
                break

# -----------------------------
# 2. MINIMUM SHIFT DURATION (UNDERWORK)
# -----------------------------
underwork_penalties = []

for e in emp_list:
    for i in seg_ids:
        if (e, i) not in x:
            continue

        # Define 'is_start': True if working segment i, but NOT working the segment before
        is_start = solver.BoolVar(f"start_{e}_{i}")
        if i == 0 or (e, i - 1) not in x or segments[i][0] != segments[i - 1][1]:
            solver.Add(is_start == x[(e, i)])
        else:
            # Linear logic for: is_start = x[i] AND NOT x[i-1]
            solver.Add(is_start <= x[(e, i)])
            solver.Add(is_start <= 1 - x[(e, i - 1)])
            solver.Add(is_start >= x[(e, i)] - x[(e, i - 1)])

        # If a shift starts at i, check every possible ending point j
        duration_sum = 0
        for j in range(i, len(segments)):
            if (e, j) not in x:
                break
            if j > i and segments[j][0] != segments[j - 1][1]:
                break

            duration_sum += (segments[j][1] - segments[j][0]).total_seconds() / 60

            # If the block from i to j is shorter than the minimum...
            if duration_sum < config.MIN_IDEAL_MINUTES:
                # ...and the shift ENDS at j (not working at j+1)
                is_end = solver.BoolVar(f"end_{e}_{i}_{j}")
                if (
                    j == len(segments) - 1
                    or (e, j + 1) not in x
                    or segments[j + 1][0] != segments[j][1]
                ):
                    solver.Add(is_end == x[(e, j)])
                else:
                    solver.Add(is_end <= x[(e, j)])
                    solver.Add(is_end <= 1 - x[(e, j + 1)])
                    solver.Add(is_end >= x[(e, j)] - x[(e, j + 1)])

                # Penalty applies ONLY IF shift starts at i AND ends at j
                short_shift = solver.BoolVar(f"short_shift_{e}_{i}_{j}")
                solver.Add(short_shift >= is_start + is_end - 1)

                shortfall_mins = config.MIN_IDEAL_MINUTES - duration_sum
                underwork_penalties.append(
                    short_shift * shortfall_mins * config.UNDERWORK_WEIGHT
                )

# -----------------------------
# OBJECTIVE
# -----------------------------

solver.Minimize(
    config.EQUALITY_WEIGHT * (max_work - min_work)
    + config.SWITCHES_WEIGHT * sum(switches)
    + config.FATIGUE_WEIGHT * sum(fatigue_penalties)
    + config.UNDERWORK_WEIGHT * sum(underwork_penalties)
)


# -----------------------------
# SOLVE
# -----------------------------

status = solver.Solve()

if status != pywraplp.Solver.OPTIMAL:
    print("No feasible solution")
    exit()


# -----------------------------
# BUILD SCHEDULE
# -----------------------------

schedule = []

for i in seg_ids:

    s, e = segments[i]

    workers = [
        emp for emp in emp_list if (emp, i) in x and x[(emp, i)].solution_value() > 0.5
    ]

    schedule.append((s, e, tuple(sorted(workers))))


# merge segments
merged = []

cs, ce, cw = schedule[0]

for s, e, w in schedule[1:]:

    if w == cw and s == ce:
        ce = e
    else:
        merged.append((cs, ce, cw))
        cs, ce, cw = s, e, w

merged.append((cs, ce, cw))

week_hours = {}
for e in emp_list:
    week_hours[e] = round(float(work[e].solution_value()) / 60, 2) or 0

# -----------------------------
# OUTPUT
# -----------------------------

# print("\nSCHEDULE\n")

# for s, e, w in merged:

#     print(f"{s.strftime('%d/%m %H:%M')} - {e.strftime('%H:%M')} : {', '.join(w)}")


# print("\nWORKLOAD\n")
# week_hours = {}

# for e in emp_list:
#     print(e, int(work[e].solution_value()), "minutes")


# -----------------------------
# EXPORT TO MATRIX CSV
# -----------------------------

import collections


def merge_time_ranges(ranges):
    if not ranges:
        return []

    # Convert to datetime tuples
    parsed = []
    for r in ranges:
        start, end = r.split("-")
        parsed.append(
            (datetime.strptime(start, "%H:%M"), datetime.strptime(end, "%H:%M"))
        )

    # Sort by start time
    parsed.sort()

    merged = []
    cs, ce = parsed[0]

    for s, e in parsed[1:]:
        if s == ce:  # contiguous
            ce = e
        else:
            merged.append((cs, ce))
            cs, ce = s, e

    merged.append((cs, ce))

    # Back to string
    return [f"{s.strftime('%H:%M')}-{e.strftime('%H:%M')}" for s, e in merged]


# 1. Organize merged shifts by employee and date
# Structure: { EmployeeName: { "17/03": ["8:30-11:30", "13:00-15:15"], ... } }
matrix_data = collections.defaultdict(lambda: collections.defaultdict(list))

# Get unique dates from the segments to create the header columns
unique_dates = sorted(list(set(s.strftime("%d/%m") for s, e in segments)))

for s, e, workers in merged:
    date_str = s.strftime("%d/%m")
    time_range = f"{s.strftime('%H:%M')}-{e.strftime('%H:%M')}"

    for emp in workers:
        matrix_data[emp][date_str].append(time_range)

with open(config.SCHEDULE_OUTPUT, mode="w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)

    # Header Row 1: Dates
    header = [""] + unique_dates
    writer.writerow(header)

    # Header Row 2: Global Shifts
    shift_row = [""]
    for d in unique_dates:
        day_shifts = [
            f"{s.strftime('%H:%M')}-{e.strftime('%H:%M')}"
            for s, e in shifts
            if s.strftime("%d/%m") == d
        ]
        shift_row.append(" / ".join(day_shifts))
    writer.writerow(shift_row)

    # Employee Rows
    for emp in sorted(emp_list):
        row = [emp]
        for d in unique_dates:
            # Join multiple shifts in one day with a " / " separator
            emp_shifts = matrix_data[emp].get(d, [])
            merged_shifts = merge_time_ranges(emp_shifts)
            row.append(" / ".join(merged_shifts))
        row.append(str(week_hours[emp]).replace('.',','))
        writer.writerow(row)

print(f"\nSchedule saved to: {config.SCHEDULE_OUTPUT}")
