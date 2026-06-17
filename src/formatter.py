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
- 0: 热身/冷身（load极低）
- 1: Easy（轻松跑）✓ verified 2026-06-14
- 2: Base（有氧基础跑）✓ verified 2026-06-13
- 3: Tempo（节奏跑）— inferred, not seen in 40-day sample
- 4: Threshold（阈值跑）✓ verified 2026-05-13
- 5: VO2 Max ✓ verified 2026-05-27
- 6: Anaerobic（无氧/间歇）✓ verified 2026-06-10
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
    0: "热身／冷身",    # very low load, minimal training effect
    1: "轻松跑",        # Easy — verified 2026-06-14
    2: "有氧基础跑",    # Base — verified 2026-06-13
    3: "节奏跑",        # Tempo — inferred (not seen in 40-day sample)
    4: "阈值跑",        # Threshold — verified 2026-05-13
    5: "VO2max",        # VO2 Max — verified 2026-05-27
    6: "无氧／间歇",   # Anaerobic — verified 2026-06-10
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


def format_morning_ctx(sleep: dict, hrv: dict, daily_records: list[dict]) -> str:
    """
    Assembles morning broadcast context from last night's sleep, HRV, and recent training load.

    sleep / hrv are model_dump() dicts from SleepRecord / HRVRecord.
    daily_records: last 7 days of DailyRecord dicts, most recent last.
    """
    lines = []

    # --- Sleep ---
    total_min = sleep.get("total_duration_minutes") or 0
    phases = sleep.get("phases") or {}
    deep = phases.get("deep_minutes") or 0
    light = phases.get("light_minutes") or 0
    rem = phases.get("rem_minutes") or 0
    awake = phases.get("awake_minutes") or 0
    avg_hr = sleep.get("avg_hr")

    total_h, total_m = divmod(total_min, 60)
    deep_pct = round(deep / total_min * 100) if total_min else 0
    rem_pct = round(rem / total_min * 100) if total_min else 0
    light_pct = round(light / total_min * 100) if total_min else 0

    # COROS normal ranges for reference
    deep_status = "偏低" if deep_pct < 16 else ("偏高" if deep_pct > 30 else "正常")
    rem_status = "偏低" if rem_pct < 11 else ("偏高" if rem_pct > 35 else "正常")
    light_status = "偏高" if light_pct > 60 else "正常"

    lines.append("【昨晚睡眠】")
    lines.append(f"总时长：{total_h}h {total_m}min  清醒：{awake}min")
    lines.append(
        f"深睡：{deep}min（{deep_pct}%，{deep_status}）  "
        f"浅睡：{light}min（{light_pct}%，{light_status}）  "
        f"REM：{rem}min（{rem_pct}%，{rem_status}）"
    )
    if avg_hr:
        lines.append(f"睡眠均心率：{avg_hr} bpm")

    # --- HRV ---
    avg_hrv = hrv.get("avg_sleep_hrv")
    baseline = hrv.get("baseline")
    sd = hrv.get("standard_deviation")

    if avg_hrv and baseline and sd:
        low = round(baseline - sd)
        high = round(baseline + sd)
        if avg_hrv < low:
            hrv_status = "偏低（身体有压力）" if avg_hrv >= baseline * 0.85 else "显著偏低（建议充分休息）"
        elif avg_hrv > high:
            hrv_status = "偏高（身体放松，注意其他指标）"
        else:
            hrv_status = "正常范围"

        lines.append(f"\n【夜间HRV】")
        lines.append(f"昨夜HRV：{avg_hrv} ms  个人基线：{baseline} ms  正常区间：{low}-{high} ms")
        lines.append(f"状态：{hrv_status}")

    # --- Recent training load ---
    if not daily_records:
        return "\n".join(lines)

    # 一次反向遍历：同时取最新的训练状态、新鲜度、阈值配速
    latest_tl_state = latest_tl_ratio = latest_tired_state = latest_ltsp = None
    for r in reversed(daily_records):
        if latest_tl_state is None and r.get("training_load_ratio_state") is not None:
            latest_tl_state = r["training_load_ratio_state"]
            latest_tl_ratio = r["training_load_ratio"]
        if latest_tired_state is None and r.get("tired_rate_state") is not None:
            latest_tired_state = r["tired_rate_state"]
        if latest_ltsp is None and r.get("ltsp"):
            latest_ltsp = r["ltsp"]
        if all(v is not None for v in [latest_tl_state, latest_tired_state, latest_ltsp]):
            break

    # 当前状态摘要
    if latest_tl_state is not None:
        state_label = _TRAINING_LOAD_STATE.get(latest_tl_state, "未知")
        tired_label = _TIRED_RATE_STATE.get(latest_tired_state, "未知") if latest_tired_state else None
        status_line = f"训练状态：{state_label}（强度比值{latest_tl_ratio:.0%}）"
        if tired_label:
            status_line += f"  身体新鲜度：{tired_label}"
        lines.append(f"\n【当前状态】{status_line}")

    # 近7天逐日明细
    lines.append("\n【近7天训练负荷】")
    for r in daily_records[-7:]:
        date_raw = r.get("date", "")
        fmt_date = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:]}" if len(date_raw) == 8 else date_raw
        load = r.get("training_load") or 0
        tired = r.get("tired_rate")
        ati = r.get("ati")
        cti = r.get("cti")
        rhr = r.get("rhr")
        tired_str = f"{tired:+.0f}" if tired is not None else "—"
        ati_str = str(int(ati)) if ati is not None else "—"
        cti_str = str(int(cti)) if cti is not None else "—"
        rhr_str = str(rhr) if rhr is not None else "—"
        lines.append(
            f"{fmt_date}: 负荷{load}  疲劳{tired_str}  近期负荷{ati_str}  长期基线{cti_str}  静息心率{rhr_str}"
        )

    if latest_ltsp:
        lines.append(f"\n阈值配速：{_pace(latest_ltsp)}")

    # 本周建议训练负荷
    latest_rec = next(
        (r for r in reversed(daily_records) if r.get("recommend_tl_min") is not None),
        None
    )
    if latest_rec:
        rec_min = int(latest_rec["recommend_tl_min"])
        rec_max = int(latest_rec["recommend_tl_max"])
        t7d = int(latest_rec.get("t7d") or 0)
        lines.append(f"本周建议训练负荷：{rec_min}-{rec_max}，当前已累计：{t7d}")

    return "\n".join(lines)


_TRAINING_LOAD_STATE = {
    1: "下滑",
    2: "恢复/竞技",
    3: "维持",
    4: "优化",
    5: "过量",
}

_TIRED_RATE_STATE = {
    # App Recovery 4级：Fresh(90-100%) / Normal(70-89%) / Fatigued(20-69%) / Exhausted(0-19%)
    # state=2 已验证对应 App "Fresh"；state=1 为更极端的新鲜（长时间未训练），App 未单独显示
    1: "极度新鲜",   # Fresh 极端情况，长时间停训
    2: "新鲜",       # Fresh ✅ verified
    3: "正常",       # Normal
    4: "疲劳",       # Fatigued
    5: "精疲力竭",   # Exhausted
}


def format_daily_ctx(records: list[dict]) -> str:
    if not records:
        return "（无近期训练数据）"

    lines = []

    latest_lthr = None
    latest_ltsp = None
    latest_vo2 = None

    for r in records:
        date = r.get("date", "")
        fmt_date = f"{date[:4]}-{date[4:6]}-{date[6:]}" if len(date) == 8 else date
        load = r.get("training_load") or 0
        tired = r.get("tired_rate")
        ati = r.get("ati")
        cti = r.get("cti")
        perf = r.get("performance")

        tired_str = f"{tired:+.0f}" if tired is not None else "—"
        ati_str = str(int(ati)) if ati is not None else "—"
        cti_str = str(int(cti)) if cti is not None else "—"
        tl_state = r.get("training_load_ratio_state")
        status_str = _TRAINING_LOAD_STATE.get(tl_state, "—") if tl_state is not None else "—"
        tired_s = r.get("tired_rate_state")
        fresh_str = _TIRED_RATE_STATE.get(tired_s, "—") if tired_s is not None else "—"

        lines.append(
            f"{fmt_date}: 负荷{load}  疲劳{tired_str}  近期负荷{ati_str}  长期基线{cti_str}  训练状态{status_str}  新鲜度{fresh_str}"
        )

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
