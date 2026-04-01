"""
Cron schedule parser - deterministic, no LLM needed.

This module provides accurate cron schedule interpretation to prevent
LLM hallucinations about time schedules.
"""
import re
import logging

logger = logging.getLogger(__name__)


def parse_cron_to_human(cron_str: str) -> str:
    """
    Parse cron schedule to human-readable string.

    Args:
        cron_str: "* 4 * * *" or "*/5 * * * *" or "0 0 * * 0"

    Returns:
        Human-readable string

    Examples:
        "* * * * *" -> "Every minute"
        "*/5 * * * *" -> "Every 5 minutes"
        "0 * * * *" -> "Every hour (at minute 0)"
        "* 4 * * *" -> "Every minute between 4:00 AM and 4:59 AM"
        "0 4 * * *" -> "Daily at 4:00 AM"
        "0 */4 * * *" -> "Every 4 hours (at minute 0)"
        "0 0 * * 0" -> "Weekly on Sunday at 00:00"
    """
    if not cron_str or cron_str.strip() == "":
        return "No schedule specified"

    parts = cron_str.strip().split()
    if len(parts) != 5:
        return f"Invalid cron format: {cron_str}"

    minute, hour, day, month, weekday = parts

    # Handle simple patterns
    if minute == "*" and hour == "*" and day == "*" and month == "*" and weekday == "*":
        return "Every minute"

    # Every N minutes
    if re.match(r'^\*/(\d+)$', minute) and hour == "*" and day == "*":
        interval = re.match(r'^\*/(\d+)$', minute).group(1)
        return f"Every {interval} minutes"

    # Specific minute every hour
    if minute.isdigit() and hour == "*" and day == "*":
        return f"Every hour at minute {minute}"

    # Every minute at specific hour (THIS IS THE CRITICAL CASE!)
    # Example: * 4 * * * means "every minute during the 4th hour (4 AM)"
    if minute == "*" and hour.isdigit() and day == "*" and month == "*" and weekday == "*":
        hour_num = int(hour)
        hour_12 = hour_num if hour_num <= 12 else hour_num - 12
        am_pm = "AM" if hour_num < 12 else "PM"
        if hour_12 == 0:
            hour_12 = 12
        return f"Every minute during hour {hour_num} (between {hour_12}:00 {am_pm} and {hour_12}:59 {am_pm})"

    # Specific time daily
    if minute.isdigit() and hour.isdigit() and day == "*" and month == "*" and weekday == "*":
        hour_num = int(hour)
        hour_12 = hour_num if hour_num <= 12 else hour_num - 12
        am_pm = "AM" if hour_num < 12 else "PM"
        if hour_12 == 0:
            hour_12 = 12
        return f"Daily at {hour_num}:{minute.zfill(2)} ({hour_12}:{minute.zfill(2)} {am_pm})"

    # Every N hours
    if minute.isdigit() and re.match(r'^\*/(\d+)$', hour) and day == "*":
        interval = re.match(r'^\*/(\d+)$', hour).group(1)
        return f"Every {interval} hours at minute {minute}"

    # Weekly on specific day
    if minute.isdigit() and hour.isdigit() and day == "*" and month == "*" and weekday.isdigit():
        days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
        weekday_int = int(weekday) % 7  # cron: both 0 and 7 mean Sunday
        day_name = days[weekday_int]
        hour_num = int(hour)
        return f"Weekly on {day_name} at {hour_num}:{minute.zfill(2)}"

    # Monthly on specific day
    if minute.isdigit() and hour.isdigit() and day.isdigit() and month == "*" and weekday == "*":
        return f"Monthly on day {day} at {hour}:{minute.zfill(2)}"

    return f"Custom schedule: {cron_str}"


def explain_cron_detailed(cron_str: str) -> str:
    """
    Detailed cron explanation with field breakdown.

    Returns markdown formatted explanation.
    """
    if not cron_str or len(cron_str.strip().split()) != 5:
        return "Invalid cron format"

    minute, hour, day, month, weekday = cron_str.strip().split()

    human = parse_cron_to_human(cron_str)

    return f"""**Cron Schedule:** `{cron_str}`

**Human Readable:** {human}

**Field Breakdown:**
```
{cron_str}
│ │ │ │ │
│ │ │ │ └─ Day of week (0-7, 0=Sunday)   → {weekday}
│ │ │ └─── Month (1-12)                  → {month}
│ │ └───── Day of month (1-31)           → {day}
│ └─────── Hour (0-23)                   → {hour}
└───────── Minute (0-59)                 → {minute}
```

**Key:**
- `*` = every
- `*/N` = every N units
- `N` = specific value
- `N,M` = multiple values
- `N-M` = range
"""


def detect_and_explain_crons_in_text(text: str) -> str:
    """
    Find all cron schedules in text and provide explanations.

    Args:
        text: Text containing cron_schedule = ... lines

    Returns:
        Markdown formatted cron explanations
    """
    cron_pattern = r'cron_schedule\s*=\s*([^\n]+)'
    matches = re.findall(cron_pattern, text)

    if not matches:
        return ""

    explanations = []
    seen = set()

    for cron in matches:
        cron = cron.strip()
        if cron in seen:
            continue
        seen.add(cron)

        human = parse_cron_to_human(cron)
        explanations.append(f"- `{cron}` → **{human}**")

    if not explanations:
        return ""

    return "\n\n**Cron Schedule Reference (Accurate Interpretations):**\n" + "\n".join(explanations) + "\n"


# Test cases
if __name__ == "__main__":
    test_cases = [
        ("* * * * *", "Every minute"),
        ("*/5 * * * *", "Every 5 minutes"),
        ("0 * * * *", "Every hour (at minute 0)"),
        ("* 4 * * *", "Every minute during hour 4 (between 4:00 AM and 4:59 AM)"),
        ("0 4 * * *", "Daily at 4:00 AM"),
        ("0 */4 * * *", "Every 4 hours at minute 0"),
        ("0 0 * * 0", "Weekly on Sunday at 00:00"),
        ("30 2 * * 1-5", "Custom schedule: 30 2 * * 1-5"),
    ]

    print("=" * 80)
    print("Cron Parser Tests")
    print("=" * 80)

    for cron, expected_contains in test_cases:
        result = parse_cron_to_human(cron)
        status = "✓" if expected_contains.lower() in result.lower() else "✗"
        print(f"\n{status} {cron:20} → {result}")

    print("\n" + "=" * 80)
    print("Detailed Explanation Example")
    print("=" * 80)
    print(explain_cron_detailed("* 4 * * *"))
