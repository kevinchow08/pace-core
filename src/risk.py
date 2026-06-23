"""
伤病风险评估。

三个独立信号，任意两个同时触发才推送预警（单信号属于正常波动，不推）：

  1. 训练过量：ratio_state=5 且 ATI 仍在上升（已开始下降则不触发）
              或近3天 ATI 增幅 > 20%
  2. 疲劳积累：tired_rate_state >= 4 且 tired_rate 未在好转（仍在上升或持平）
  3. HRV 异常：近3天中 ≥ 2 天 avg_sleep_hrv < baseline - sd
              （sd 由 job 层从 HRVRecord 合并；无 sd 时降级用 interval_list P25）

趋势判断的意义：高频训练运动员的高负荷/高疲劳是常态，危险的是趋势在恶化，
而不是"数值高但稳定或已在恢复"。

新增信号：在 _check_* 函数中添加，然后在 assess_injury_risk() 的 signals 列表里注册。
"""


def _check_overload(records: list[dict]) -> bool:
    """
    训练过量信号。
    - ratio_state=5：只在 ATI 仍未开始下降时触发（ATI 下降说明已在恢复）
    - ATI 急速攀升：近3天增幅 > 20%（无论 ratio_state）
    """
    if not records:
        return False

    recent_ati = [r for r in records[-4:] if r.get("ati") is not None]

    latest = records[-1]
    if latest.get("training_load_ratio_state") == 5 and len(recent_ati) >= 2:
        # ATI 还没开始下降 → 仍在恶化，触发；已下降说明在恢复，不触发
        if recent_ati[-1]["ati"] >= recent_ati[-2]["ati"]:
            return True

    # 近3天 ATI 增幅超过 20%（急速堆量）
    if len(recent_ati) >= 2:
        ati_old = recent_ati[0]["ati"]
        ati_new = recent_ati[-1]["ati"]
        if ati_old > 0 and (ati_new - ati_old) / ati_old > 0.20:
            return True

    return False


def _check_fatigue(records: list[dict]) -> bool:
    """
    疲劳积累信号。
    tired_rate_state >= 4 且 tired_rate 未在好转：
    - tired_rate 下降（变小/变负）= 正在恢复 → 不触发
    - tired_rate 上升或持平 = 疲劳仍在积累 → 触发
    """
    recent = [
        r for r in records[-3:]
        if r.get("tired_rate_state") is not None and r.get("tired_rate") is not None
    ]
    if not recent or recent[-1].get("tired_rate_state", 0) < 4:
        return False

    # 状态已达疲劳，再看趋势方向
    if len(recent) >= 2:
        if recent[-1]["tired_rate"] < recent[-2]["tired_rate"]:
            return False  # tired_rate 在下降，说明正在恢复

    return True


def _check_hrv(records: list[dict]) -> bool:
    """
    HRV 异常信号。
    近3天中至少 2 天 avg_sleep_hrv 低于正常区间下沿，触发信号。

    阈值优先级：
    1. standard_deviation（由 job 层从 HRVRecord 合并进来）→ baseline - sd（更准确）
    2. interval_list[1]（P25，COROS 分位数）→ 降级方案
    """
    below_count = 0
    checked = 0
    for r in records[-3:]:
        avg = r.get("avg_sleep_hrv")
        baseline = r.get("baseline")
        sd = r.get("standard_deviation")
        interval_list = r.get("interval_list")

        if avg is None:
            continue

        if sd is not None and baseline is not None:
            threshold = baseline - sd
        elif interval_list and len(interval_list) >= 2:
            threshold = interval_list[1]  # P25
        else:
            continue

        checked += 1
        if avg < threshold:
            below_count += 1

    return checked >= 2 and below_count >= 2


def assess_injury_risk(daily_records: list[dict]) -> list[str] | None:
    """
    返回触发的风险信号列表（≥2个时）；风险不足时返回 None。
    调用方根据返回值决定是否推送预警，信号列表会传给 LLM 生成预警文案。
    """
    signals = []

    if _check_overload(daily_records):
        signals.append("训练过量（近期负荷仍在攀升，已超出长期承受能力）")
    if _check_fatigue(daily_records):
        signals.append("疲劳持续积累（身体处于疲劳状态且尚未好转）")
    if _check_hrv(daily_records):
        signals.append("HRV 连续偏低（自主神经系统持续承压，恢复未完成）")

    return signals if len(signals) >= 2 else None
