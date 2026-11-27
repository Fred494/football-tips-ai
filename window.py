"""The exact two-calendar-year match history window shared by all models."""
def history_start(today):
    try:
        return today.replace(year=today.year-2)
    except ValueError:
        return today.replace(year=today.year-2,day=28)
