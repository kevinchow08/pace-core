"""
Validation gate #1: verify COROS data can be fetched.

Run: python test_connection.py
"""
import json
from src.coros_client import get_recent_activities, get_activity_detail, get_recent_daily_records


def main():
    print("=== Fetching recent activities (last 7 days) ===")
    activities = get_recent_activities(days=7)
    for a in activities:
        print(f"  {a.activity_id} | {a.sport_name} | start={a.start_time} | dist={a.distance_meters}m")

    if not activities:
        print("No activities found.")
        return

    latest = activities[-1]  # most recent
    print(f"\n=== Activity detail: {latest.activity_id} ({latest.sport_name}) ===")
    detail = get_activity_detail(latest.activity_id, latest.sport_type or 0)
    print(json.dumps(detail, ensure_ascii=False, indent=2))

    print("\n=== Recent daily records (14 days) ===")
    records = get_recent_daily_records(days=14)
    for r in records:
        print(f"  {r.date} | load={r.training_load} | vo2max={r.vo2max} | hrv={r.avg_sleep_hrv}")


if __name__ == "__main__":
    main()
