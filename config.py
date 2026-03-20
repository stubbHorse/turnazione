# Filenames
RAW_INPUT = "turni lauree 2025 - disp_tmp.csv"
TURNI_OUTPUT = "turni.csv"
DISPONIBILITA_OUTPUT = "disponibilita.csv"
MAXORE_OUTPUT = "max_ore.csv"
SCHEDULE_OUTPUT = "schedule.csv"

# Shift length parameters
MAX_IDEAL_MINUTES = 240  # 4 hours
MIN_IDEAL_MINUTES = 120  # 2 hours
PENALTY_WEIGHT = 10  # Penalty for every minute over the limit (no need to touch)

# Objective function weights - try playing with them to get the ideal result
EQUALITY_WEIGHT = 2
SWITCHES_WEIGHT = 15
FATIGUE_WEIGHT = 5
UNDERWORK_WEIGHT = 2
