"""
CSV Data Processing Script

This script processes raw shift data from a CSV file and generates three output files:
1. turni.csv - Required shifts/slots to be covered (Date, Start, End times)
2. disponibilita.csv - Employee availability windows (Employee, Date, Start, End times)
3. maxore.csv - Maximum hours allowed per employee (Employee, MaxHours)

Input Format (RAW_INPUT):
- Row 1: Dates in MM/DD format
- Row 2: Shifts to cover in format "HH:MM-HH:MM" separated by '/'
- Row 3+: Employee data with availability windows and max hours in last column

Time Format Normalization:
- Supports formats: '8', '8.30', '8:30' -> Normalized to '08:30'
"""

import csv
import re
from config import RAW_INPUT, TURNI_OUTPUT, DISPONIBILITA_OUTPUT, MAXORE_OUTPUT

def clean_time(t):
    """Normalizes '8', '8.30', '8:30' -> '08:30'"""
    t = t.strip().replace('.', ':')
    if ':' not in t:
        t = f"{t}:00"
    parts = t.split(':')
    return f"{parts[0].zfill(2)}:{parts[1].zfill(2)}"

with open(RAW_INPUT, mode='r', encoding='utf-8') as f_in:
    reader = list(csv.reader(f_in))
    header_days = reader[0]   # Row 1: Dates
    header_shifts = reader[1] # Row 2: The "Shifts to Cover"
    employee_rows = reader[2:] # Row 3+: People

    # --- 1. Process Required Shifts (The "Slots") ---
    with open(TURNI_OUTPUT, mode='w', newline='') as f_req:
        writer = csv.writer(f_req)
        writer.writerow(['Date', 'Start', 'End'])
        
        for i in range(1, len(header_shifts)-1):
            date_match = re.search(r'\d*/\d*', header_days[i])
            if not date_match or not header_shifts[i].strip(): continue
            
            date_str = date_match.group()
            for s in header_shifts[i].split('/'):
                if '-' in s:
                    start, end = s.split('-')
                    writer.writerow([date_str, clean_time(start), clean_time(end)])

    # --- 2. Process Employee Availability AND Employee Max Hours ---
    with open(DISPONIBILITA_OUTPUT, mode='w', newline='') as f_avail, open(MAXORE_OUTPUT, mode='w', newline='') as f_hours:
        writer = csv.writer(f_avail)
        writer.writerow(['Employee', 'Date', 'Start', 'End'])
        csv.writer(f_hours).writerow(['Employee', 'MaxHours'])
        
        for row in employee_rows:
            if not row or not row[0].strip(): continue
            name = row[0].strip()
            
            for i in range(1, len(row)):
                date_match = re.search(r'\d*/\d*', header_days[i])
                if i == len(row)-1:
                    csv.writer(f_hours).writerow([name, row[i].replace(',','.')])
                    continue
                elif not date_match or not row[i].strip():
                    continue
                date_str = date_match.group()
                for s in row[i].split('/'):
                    if '-' in s:
                        start, end = s.split('-')
                        writer.writerow([name, date_str, clean_time(start), clean_time(end)])

print("Done! Created 'turni.csv' and 'disponibilita.csv'")