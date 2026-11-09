"""Pure leave rules. These mirror data/policies/leave-policy.md."""
from datetime import date, timedelta

LEAVE_TYPES = ("annual", "sick", "parental", "unpaid")
SENSITIVE_TYPES = {"sick", "parental", "unpaid"}
HR_APPROVAL_OVER_DAYS = 10
MAX_REQUEST_DAYS = 60


def working_days(start: str, end: str) -> int:
    """Count Monday-to-Friday days from start to end inclusive. Public holidays are not modelled."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if last < first:
        raise ValueError("end_date is before start_date")
    return sum((first + timedelta(n)).weekday() < 5 for n in range((last - first).days + 1))


def required_approver(leave_type: str, days: float) -> str:
    """Sensitive types and long absences need HR; everything else needs the direct manager."""
    return "hr" if leave_type in SENSITIVE_TYPES or days > HR_APPROVAL_OVER_DAYS else "manager"
