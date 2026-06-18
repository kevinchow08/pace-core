"""
Converts raw COROS API responses to human-readable text for LLM analysis.

COROS unit conventions (reverse-engineered from API responses):
- distance:    centimeters  → ÷100000 → km
- time fields: centiseconds → ÷100    → seconds
- pace fields: seconds/km  → format as M:SS/km directly
- HR zones:    seconds      (already correct)
- weather.temperature: ÷10 → °C
- weather.humidity:    ÷10 → %  (verified: raw=760 → 76.0%)
- heart rate, cadence: already correct units

trainType enum (verified against COROS app Training Focus):
- 0: 热身/冷身（load极低）
- 1: Easy（轻松跑）        ✓ verified 2026-06-14
- 2: Base（有氧基础跑）    ✓ verified 2026-06-13
- 3: Tempo（节奏跑）       — inferred, not seen in 40-day sample
- 4: Threshold（阈值跑）   ✓ verified 2026-05-13
- 5: VO2 Max               ✓ verified 2026-05-27
- 6: Anaerobic（无氧/间歇）✓ verified 2026-06-10
"""

# ── 1. 枚举与常量 ────────────────────────────────────────────────────────
# 新增或修改枚举值在这里，formatter 其他部分自动生效

_TRAIN_TYPE_NAMES = {
    0: "热身／冷身",
    1: "轻松跑",       # Easy       — verified 2026-06-14
    2: "有氧基础跑",   # Base       — verified 2026-06-13
    3: "节奏跑",       # Tempo      — inferred, not seen in 40-day sample
    4: "阈值跑",       # Threshold  — verified 2026-05-13
    5: "VO2max",       # VO2 Max    — verified 2026-05-27
    6: "无氧／间歇",   # Anaerobic  — verified 2026-06-10
}

# training_load_ratio_state → 训练状态标签
# 来源：COROS API trainingLoadRatioState 字段（1-5）
_TRAINING_LOAD_STATE = {
    1: "下滑",
    2: "恢复/竞技",
    3: "维持",
    4: "优化",
    5: "过量",
}

# tired_rate_state → 身体新鲜度标签
# 来源：COROS API tiredRateStateNew 字段（1-5）
# 对应 App Recovery %：Fresh(90-100%) / Normal(70-89%) / Fatigued(20-69%) / Exhausted(0-19%)
# state=2 已验证对应 App "Fresh"；state=1 为极端新鲜（长时间停训），App 未单独显示
_TIRED_RATE_STATE = {
    1: "极度新鲜",
    2: "新鲜",       # ✅ verified
    3: "正常",
    4: "疲劳",
    5: "精疲力竭",
}

_HR_ZONE_NAMES = [
    "Z1 恢复",
    "Z2 有氧耐力",
    "Z3 有氧能力",
    "Z4 阈值",
    "Z5 无氧耐力",
    "Z6 无氧能力",
]


# ── 2. 单位换算工具函数 ──────────────────────────────────────────────────

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


def _fmt_date(date_raw: str) -> str:
    """yyyyMMdd → yyyy-MM-dd，其他格式原样返回。"""
    if len(date_raw) == 8 and date_raw.isdigit():
        return f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:]}"
    return date_raw


# ── 3. format_activity ───────────────────────────────────────────────────
# 单次活动详情 → 供练后点评 LLM 使用
# 新增活动级字段在这里添加

def _infer_train_type(summary: dict) -> str:
    return _TRAIN_TYPE_NAMES.get(summary.get("trainType"), "跑步训练")


def format_activity(activity: dict) -> str:
    s = activity.get("summary", {})
    lines = []

    distance = _km(s.get("distance", 0))
    workout_cs = s.get("workoutTime", 0)
    total_cs = s.get("totalTime", 0)
    raw_pace = s.get("avgSpeed", 0)
    adj_pace = s.get("adjustedPace", 0)
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

    lap_items = []
    for lap_group in activity.get("lapList", []):
        if lap_group.get("type") == 2:  # type=2: 按公里分圈（逆向魔数）
            lap_items = lap_group.get("lapItemList", [])
            break

    lines.append(f"【训练类型】{_infer_train_type(s)}")
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

    hr_zones = None
    for zone_group in activity.get("zoneList", []):
        if zone_group.get("type") == 126:  # type=126: 心率区间（逆向魔数）
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
                hr_range = f"<{right}bpm"       # Z1 只有上限
            elif i == len(hr_zones) - 1:
                hr_range = f">{left}bpm"         # Z6 只有下限
            else:
                hr_range = f"{left}-{right}bpm"  # 中间区间有上下限
            lines.append(f"{_HR_ZONE_NAMES[i]} {hr_range}：{pct}% / {_duration_s(sec) if sec else '0:00'}")

    return "\n".join(lines)


# ── 4. format_daily_ctx ──────────────────────────────────────────────────
# 近N天日报背景 → 供练后点评 LLM 使用
# 逐日明细字段：负荷、疲劳、ATI、CTI、训练状态、新鲜度
# 能力摘要字段：乳酸阈值心率、阈值配速、VO2max、跑步能力评分
# 新增日报字段：在逐日明细行 or _format_ability_summary() 中添加

def _format_ability_summary(records: list[dict]) -> list[str]:
    """
    从 daily_records 中提取最新有效的能力指标，返回文本行列表。
    format_daily_ctx 和 format_morning_ctx 共用，新增能力字段只改这里。
    """
    latest_lthr = latest_ltsp = latest_vo2 = latest_stamina = latest_stamina_7d = None

    for r in records:
        if latest_lthr is None and r.get("lthr"):
            latest_lthr = r["lthr"]
        if latest_ltsp is None and r.get("ltsp"):
            latest_ltsp = r["ltsp"]
        if latest_vo2 is None and r.get("vo2max"):
            latest_vo2 = r["vo2max"]
        if latest_stamina is None and r.get("stamina_level"):
            latest_stamina = r["stamina_level"]
            latest_stamina_7d = r.get("stamina_level_7d")

    lines = []
    if latest_lthr:
        lines.append(f"乳酸阈值心率：{latest_lthr} bpm")
    if latest_ltsp:
        lines.append(f"阈值配速：{_pace(latest_ltsp)}")
    if latest_vo2:
        lines.append(f"VO2max：{latest_vo2}")
    if latest_stamina is not None:
        trend_str = f"（近7天趋势：{latest_stamina_7d:+.1f}）" if latest_stamina_7d is not None else ""
        lines.append(f"跑步能力评分：{latest_stamina:.1f}{trend_str}")
    return lines


def format_daily_ctx(records: list[dict]) -> str:
    """近N天日报背景，供练后点评使用。records 按日期正序排列。"""
    if not records:
        return "（无近期训练数据）"

    lines = []
    for r in records:
        fmt_date = _fmt_date(r.get("date", ""))
        load = r.get("training_load") or 0
        tired = r.get("tired_rate")
        ati = r.get("ati")
        cti = r.get("cti")
        tl_state = r.get("training_load_ratio_state")
        tired_s = r.get("tired_rate_state")

        tired_str = f"{tired:+.0f}" if tired is not None else "—"
        ati_str = str(int(ati)) if ati is not None else "—"
        cti_str = str(int(cti)) if cti is not None else "—"
        status_str = _TRAINING_LOAD_STATE.get(tl_state, "—") if tl_state is not None else "—"
        fresh_str = _TIRED_RATE_STATE.get(tired_s, "—") if tired_s is not None else "—"

        lines.append(
            f"{fmt_date}: 负荷{load}  疲劳{tired_str}  近期负荷{ati_str}  长期基线{cti_str}"
            f"  训练状态{status_str}  新鲜度{fresh_str}"
        )

    ability_lines = _format_ability_summary(records)
    if ability_lines:
        lines.append("")
        lines.extend(ability_lines)

    return "\n".join(lines)


# ── 5. format_morning_ctx ────────────────────────────────────────────────
# 晨报背景 → 供晨起状态播报 LLM 使用
# 包含：睡眠、HRV、当前状态摘要、近7天负荷明细、能力摘要、本周负荷目标
# 新增晨报字段：在对应 section 中添加，section 之间用空行分隔

def format_morning_ctx(sleep: dict, hrv: dict, daily_records: list[dict]) -> str:
    """
    sleep / hrv 是 SleepRecord / HRVRecord 的 model_dump() 结果。
    daily_records: 最近7天 DailyRecord dicts，按日期正序排列。
    """
    lines = []

    # --- 睡眠 ---
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

        lines.append("\n【夜间HRV】")
        lines.append(f"昨夜HRV：{avg_hrv} ms  个人基线：{baseline} ms  正常区间：{low}-{high} ms")
        lines.append(f"状态：{hrv_status}")

    if not daily_records:
        return "\n".join(lines)

    # --- 当前状态摘要（反向遍历取最新有效值）---
    latest_tl_state = latest_tl_ratio = latest_tired_state = latest_ltsp = None
    for r in reversed(daily_records):
        if latest_tl_state is None and r.get("training_load_ratio_state") is not None:
            latest_tl_state = r["training_load_ratio_state"]
            latest_tl_ratio = r["training_load_ratio"]
        if latest_tired_state is None and r.get("tired_rate_state") is not None:
            latest_tired_state = r["tired_rate_state"]
        if latest_ltsp is None and r.get("ltsp"):
            latest_ltsp = r["ltsp"]
        if latest_tl_state is not None and latest_tired_state is not None and latest_ltsp is not None:
            break

    if latest_tl_state is not None:
        state_label = _TRAINING_LOAD_STATE.get(latest_tl_state, "未知")
        tired_label = _TIRED_RATE_STATE.get(latest_tired_state, "未知") if latest_tired_state else None
        status_line = f"训练状态：{state_label}（强度比值{latest_tl_ratio:.0%}）"
        if tired_label:
            status_line += f"  身体新鲜度：{tired_label}"
        lines.append(f"\n【当前状态】{status_line}")

    # --- 近7天逐日明细 ---
    # 新增每日字段：在这里的 f-string 中追加
    lines.append("\n【近7天训练负荷】")
    for r in daily_records[-7:]:
        fmt_date = _fmt_date(r.get("date", ""))
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
            f"{fmt_date}: 负荷{load}  疲劳{tired_str}  近期负荷{ati_str}"
            f"  长期基线{cti_str}  静息心率{rhr_str}"
        )

    # --- 能力摘要（与 format_daily_ctx 共用）---
    ability_lines = _format_ability_summary(daily_records)
    if ability_lines:
        lines.append("")
        lines.extend(ability_lines)

    # --- 本周负荷目标 ---
    latest_rec = next(
        (r for r in reversed(daily_records) if r.get("recommend_tl_min") is not None),
        None,
    )
    if latest_rec:
        rec_min = int(latest_rec["recommend_tl_min"])
        rec_max = int(latest_rec["recommend_tl_max"])
        t7d = int(latest_rec.get("t7d") or 0)
        lines.append(f"本周建议训练负荷：{rec_min}-{rec_max}，当前已累计：{t7d}")

    return "\n".join(lines)
