"""
Converts raw COROS API responses to human-readable text for LLM analysis.

COROS unit conventions (reverse-engineered from API responses):
- distance:    centimeters     → ÷100000 → km
- time fields: centiseconds    → ÷100    → seconds
- pace fields: seconds per km  → format as M:SS/km directly
- HR zones:    seconds         (already correct, no conversion needed)
- weather.temperature: ÷10   → °C
- heart rate, cadence: already correct units

trainType enum (verified against COROS app Training Focus):
- 2: Easy（轻松跑） ✓ inferred
- 3: Base（有氧基础） ✓ inferred (20km LSD, app didn't display label)
- 4: Threshold（阈值）✓ inferred
- 5: VO2 Max ✓ confirmed
- 6: Anaerobic（无氧）✓ confirmed
- 0, 1: unknown, fallback to generic labels
"""

_HR_ZONE_NAMES = [
    "Z1 恢复",
    "Z2 有氧耐力",
    "Z3 有氧能力",
    "Z4 阈值",
    "Z5 无氧耐力",
    "Z6 无氧能力",
]

_TRAIN_TYPE_NAMES = {
    0: "热身／基础有氧",
    1: "恢复跑",
    2: "轻松跑",        # Easy — confirmed pattern (low load, near-zero anaerobic)
    3: "有氧基础跑",    # Base — inferred (LSD long run, app didn't display label)
    4: "阈值跑",        # Threshold — inferred (trainType=5 is VO2Max, 4 is next tier down)
    5: "VO2max",        # VO2 Max — confirmed in COROS app
    6: "无氧／间歇",   # Anaerobic — confirmed in COROS app
}


def _pace(sec_per_km: float) -> str:
    if not sec_per_km or sec_per_km <= 0 or sec_per_km > 3600:
        return "—"
    m, s = divmod(int(sec_per_km), 60)
    return f"{m}:{s:02d}/km"


def _duration_cs(centiseconds: int) -> str:
    return _duration_s((centiseconds or 0) // 100)


def _duration_s(seconds: int) -> str:
    h, rem = divmod(seconds or 0, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _km(cm: int) -> float:
    return round((cm or 0) / 100000, 2)


def _infer_train_type(summary: dict, lap_items: list) -> str:
    """
    Primary: trainType field.
    Fallback: lap structure + aerobic/anaerobic effect ratio.
    """
    train_type = summary.get("trainType")
    if train_type in _TRAIN_TYPE_NAMES:
        label = _TRAIN_TYPE_NAMES[train_type]
    else:
        label = None

    # Structural fallback: multiple similar-distance laps with high pace variance = interval
    if not label or label == "基础有氧":
        if len(lap_items) >= 3:
            distances = [item.get("distance", 0) for item in lap_items[:-1]]
            paces = [item.get("avgPace", 0) for item in lap_items if item.get("avgPace", 0) > 0]
            if distances and paces:
                dist_cv = (max(distances) - min(distances)) / (max(distances) or 1)
                pace_cv = (max(paces) - min(paces)) / (min(paces) or 1)
                if dist_cv < 0.1 and pace_cv > 0.15:
                    label = "间歇／高强度"

    return label or "跑步训练"


def format_activity(activity: dict) -> str:
    s = activity.get("summary", {})
    lines = []

    distance = _km(s.get("distance", 0))
    workout_cs = s.get("workoutTime", 0)
    total_cs = s.get("totalTime", 0)
    raw_pace = s.get("avgSpeed", 0)       # moving pace in sec/km
    adj_pace = s.get("adjustedPace", 0)   # effort-adjusted pace
    avg_hr = s.get("avgHr", 0)
    max_hr = s.get("maxHr", 0)
    avg_cadence = s.get("avgCadence", 0)
    load = s.get("trainingLoad", 0)
    aerobic = s.get("aerobicEffect", 0)
    anaerobic = s.get("anaerobicEffect", 0)
    vo2max = s.get("currentVo2Max") or s.get("hrmVo2Max") or None
    best_km = s.get("bestKm", 0)

    weather = activity.get("weather", {})
    temp_raw = weather.get("temperature")
    humidity_raw = weather.get("humidity")
    temp_str = f"{temp_raw / 10:.0f}°C" if temp_raw else None
    humidity_str = f"湿度 {humidity_raw / 10:.0f}%" if humidity_raw else None

    # Laps (type=2 contains individual splits)
    lap_items = []
    for lap_group in activity.get("lapList", []):
        if lap_group.get("type") == 2:
            lap_items = lap_group.get("lapItemList", [])
            break

    # Training type header
    train_type_label = _infer_train_type(s, lap_items)
    lines.append(f"【训练类型】{train_type_label}")

    lines.append(f"距离：{distance} km  运动用时：{_duration_cs(workout_cs)}  总用时：{_duration_cs(total_cs)}")

    pace_parts = [f"移动配速：{_pace(raw_pace)}"]
    if adj_pace and adj_pace != raw_pace:
        pace_parts.append(f"努力配速：{_pace(adj_pace)}")
    lines.append("  ".join(pace_parts))

    lines.append(f"均心率：{avg_hr} bpm  最高心率：{max_hr} bpm  平均步频：{avg_cadence} 步/分")
    lines.append(f"训练负荷：{load}  有氧效果：{aerobic}  无氧效果：{anaerobic}")

    extras = []
    if best_km:
        extras.append(f"最佳1km：{_pace(best_km)}")
    if vo2max:
        extras.append(f"VO2max：{vo2max}")
    if temp_str:
        extras.append(f"气温：{temp_str}")
    if humidity_str:
        extras.append(humidity_str)
    if extras:
        lines.append("  ".join(extras))

    # Laps
    if len(lap_items) > 1:
        lines.append("\n【分圈】")
        for item in lap_items:
            dist = _km(item.get("distance", 0))
            pace_val = item.get("avgPace", 0)
            hr = item.get("avgHr", 0)
            pause_cs = item.get("pauseTime", 0)
            lap_line = f"圈{item.get('lapIndex', '?')}  {dist}km  配速 {_pace(pace_val)}  均心率 {hr} bpm"
            if pause_cs > 0:
                lap_line += f"  含停表 {_duration_cs(pause_cs)}"
            lines.append(lap_line)

    # HR zones (zoneList type=126)
    hr_zones = None
    for zone_group in activity.get("zoneList", []):
        if zone_group.get("type") == 126:
            hr_zones = zone_group.get("zoneItemList", [])
            break

    if hr_zones:
        lines.append("\n【心率区间】")
        for i, z in enumerate(hr_zones):
            if i >= len(_HR_ZONE_NAMES):
                break
            pct = z.get("percent", 0)
            sec = z.get("second", 0)
            left = z.get("leftScope", 0)
            right = z.get("rightScope", 0)

            if i == 0:
                hr_range = f"<{left}bpm"
            elif i == len(hr_zones) - 1:
                hr_range = f">{left}bpm"
            else:
                hr_range = f"{left}-{right}bpm"

            time_str = _duration_s(sec) if sec else "0:00"
            lines.append(f"{_HR_ZONE_NAMES[i]} {hr_range}：{pct}% / {time_str}")

    return "\n".join(lines)


def format_daily_ctx(records: list[dict]) -> str:
    if not records:
        return "（无近期训练数据）"

    lines = ["日期        负荷   疲劳   ATI  CTI  表现"]

    latest_lthr = None
    latest_ltsp = None
    latest_vo2 = None

    perf_map = {-1: "休息", 0: "中等", 1: "良好", 2: "优秀", 3: "出色", 4: "极佳"}

    for r in records:
        date = r.get("date", "")
        fmt_date = f"{date[:4]}-{date[4:6]}-{date[6:]}" if len(date) == 8 else date
        load = r.get("training_load") or 0
        tired = r.get("tired_rate")
        ati = r.get("ati") or "—"
        cti = r.get("cti") or "—"
        perf = r.get("performance")

        tired_str = f"{tired:+.0f}" if tired is not None else "—"
        perf_str = perf_map.get(perf, "—") if perf is not None else "—"

        lines.append(f"{fmt_date}  {load:4d}   {tired_str:>5}  {ati:3}  {cti:3}  {perf_str}")

        if r.get("lthr"):
            latest_lthr = r["lthr"]
        if r.get("ltsp"):
            latest_ltsp = r["ltsp"]
        if r.get("vo2max"):
            latest_vo2 = r["vo2max"]

    lines.append("")
    if latest_lthr:
        lines.append(f"乳酸阈值心率：{latest_lthr} bpm")
    if latest_ltsp:
        lines.append(f"阈值配速：{_pace(latest_ltsp)}")
    if latest_vo2:
        lines.append(f"VO2max：{latest_vo2}")

    return "\n".join(lines)
