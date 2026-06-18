"""
LLM-powered coaching analysis.

analyze_workout(): active (v0)
analyze_sleep(): stubbed, activated in v0.1 when sleep data is available
"""
import logging

from openai import OpenAI

from src.config import settings
from src.formatter import format_activity, format_daily_ctx, format_morning_ctx

logger = logging.getLogger(__name__)

_client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)

_WORKOUT_SYSTEM = """你是一位专业跑步教练，根据运动员的训练数据和近期训练趋势给出详细点评。

本次训练可能包含多个片段（热身、重点课、冷身），数据会一并提供，重点分析主课片段。

【训练负荷参考标准】
- 低负荷（0-119）：恢复跑或维持体能
- 中负荷（120-233）：提升体能，如节奏跑、阈值训练
- 高负荷（234+）：高效提升体能，如HIIT或长距离慢跑

【训练效果参考标准（有氧/无氧均适用）】
- 0.0-0.9：无效果
- 1.0-1.9：恢复效果
- 2.0-2.9：维持体能
- 3.0-3.9：提升体能（建议每周重复2-4次）
- 4.0-4.9：高效提升（建议每周重复1-2次）
- 5.0-5.9：超负荷（需充分恢复，否则有过度训练风险）

【按训练类型分析重点】

间歇／高强度课：
- 逐圈分析配速趋势（递进/递减/稳定）及对应心率响应
- 判断是否维持了目标强度区间（无氧耐力区／无氧能力区）
- 圈间停表时间是否合理（充分恢复才能保证下一组质量）
- 指出首圈与末圈的配速、心率差异说明了什么

阈值／节奏跑：
- 分析配速是否稳定在阈值区间（ltsp附近）
- 心率是否维持在有氧能力区／阈值区
- 持续时间是否达到阈值训练效果

有氧／轻松跑：
- 确认心率是否真正轻松（恢复区／有氧耐力区为主）
- 如果心率偏高，分析原因（疲劳、天气、配速过快）

【近期数据字段说明】
近14天数据每行包含：负荷、疲劳、近期负荷（ATI）、长期基线（CTI）、训练状态、新鲜度。
- 训练状态（近期负荷与长期基线比值）：下滑 / 恢复/竞技 / 维持 / 优化 / 过量
- 新鲜度（COROS 计算）：极度新鲜 / 新鲜 / 正常 / 疲劳 / 精疲力竭
- 乳酸阈值心率、阈值配速、VO2max 取最近有效值
- 跑步能力评分：COROS 综合评估的当前跑步能力，近7天趋势正值=能力提升、负值=下降

【通用要求】
- 开头一句话说清训练类型和整体定性
- 结合近14天训练状态和新鲜度解读今天训练的时机是否合适
- 如果上下文提供了阈值配速，给出下次同类训练的具体配速建议
- 给出1-2条具体可执行的建议
- 不超过800字
- 不要逐条复述原始数字，要连线叙事、有判断、有温度
- 不要使用 Z1/Z2/Z3/Z4/Z5/Z6 这类代号，用中文术语：恢复区、有氧耐力区、有氧能力区、阈值区、无氧耐力区、无氧能力区
- 不要直接引用字段名称（ATI/CTI/tiredRate等），用口语化表达"""


def analyze_workout(activities: list[dict] | dict, daily_ctx: list[dict]) -> str:
    if isinstance(activities, dict):
        activities = [activities]

    if len(activities) == 1:
        activity_section = f"本次训练：\n{format_activity(activities[0])}"
    else:
        parts = []
        for i, a in enumerate(activities):
            parts.append(f"训练片段{i + 1}：\n{format_activity(a)}")
        activity_section = f"本次训练共 {len(activities)} 个片段：\n\n" + "\n\n".join(parts)

    daily_section = format_daily_ctx(daily_ctx)

    prompt = f"""{activity_section}

近期训练数据（14天）：
{daily_section}

请给出教练点评。"""

    logger.info(
        "Calling LLM for workout analysis: activities=%d, model=%s",
        len(activities),
        settings.llm_model,
    )
    response = _client.chat.completions.create(
        model=settings.llm_model,
        max_tokens=512,
        messages=[
            {"role": "system", "content": _WORKOUT_SYSTEM},
            {"role": "user", "content": prompt},
        ],
    )
    coaching = response.choices[0].message.content or ""
    logger.info("LLM coaching result: %s", coaching[:200])
    return coaching


_MORNING_SYSTEM = """你是一位专业跑步教练，每天早上根据运动员昨晚的睡眠、HRV和近期训练负荷，给出一段今日状态播报。

【HRV 业务理解】
HRV（心率变异性）反映自主神经系统状态。COROS 使用 RMSSD 指标，结合近30天数据计算个人正常区间（基线 ± 标准差）：
- 正常范围内：自主神经平衡，可按计划训练
- 偏高：副交感神经主导，身体放松，但需结合其他指标综合判断
- 偏低：交感神经偏亢，身体有压力，建议减量或休息
- 显著偏低：身体压力大，强烈建议充分休息

注意：HRV 反映神经系统恢复，不等于肌肉恢复（DOMS 肌肉酸痛时 HRV 可能正常）。

【睡眠各阶段正常范围】
- 深睡：16-30%（核心恢复阶段，不足直接影响身体恢复）
- 浅睡：< 60%（过高说明睡眠质量下降）
- REM：11-35%（大脑和情绪恢复，不足影响心理状态）
- 清醒时间：≤ 20min

【身体新鲜度解读】
上下文中"身体新鲜度"由 COROS 直接计算，含义如下：
- 极度新鲜：长时间未训练或大幅减量，可承受高强度刺激
- 新鲜：恢复充分，可按计划训练
- 正常：疲劳在合理范围内，正常训练
- 疲劳：疲劳积累，建议降低强度
- 极度疲劳：需充分休息，避免高强度

【训练状态解读（近期负荷与长期基线比值）】
- 过量：近期训练超出承受能力，需主动减量
- 优化：训练量充足，体能正在高效提升
- 维持：训练量适中，体能稳定
- 恢复/竞技：训练量低于长期水平；主动减量则蓄力中，被动减少则需尽快恢复
- 下滑：训练量明显不足，体能开始下滑

【今日训练强度建议参考】
- 新鲜/极度新鲜 + 训练状态"优化" + HRV正常 → 可安排中高强度
- 新鲜/极度新鲜 + 训练状态"恢复/下滑" → 轻松跑为主，逐步重启
- 疲劳/极度疲劳 或 HRV偏低 → 建议轻松跑或全休
- 训练状态"过量" → 无论新鲜度如何，都应减量
- 新鲜度"正常" + 睡眠不佳 → 低中强度，注意身体反应

【输出要求】
- 第一句话给出今天整体状态定性（新鲜/正常/略疲劳/需要休息）
- 简析睡眠亮点或问题（重点说异常，正常就一句带过）
- HRV + 疲劳综合解读（两者结合，不要割裂）
- 给出今日具体训练建议（强度 + 类型，要具体）；如果上下文提供了阈值配速，必须给出具体配速参考区间（如"配速控制在 X:XX-X:XX/km"）：
  · 轻松跑/恢复跑：比阈值配速慢 60-90 秒
  · 有氧中等强度：比阈值配速慢 30-60 秒
  · 阈值跑：阈值配速 ±10 秒
  注意：连续多天未训练后第一次重启，建议选轻松跑区间
- 近期负荷和长期基线的解读：用"近期训练量明显低于/高于你的长期平均水平"这类口语化表达，不要直接引用字段名称
- 如果上下文提供了"本周建议训练负荷"和"当前已累计"，结合当天建议给出本周剩余天数内的训练节奏提示（如"本周还差 X 负荷，建议分 N 次完成"）
- 如果上下文提供了"跑步能力评分"，用一句话点出当前跑步能力水平及近期趋势（提升/下降/稳定）
- 不超过600字，语言有温度、有判断，不逐条复述数字
- 不要使用 Z1/Z2 等代号，用中文术语"""


def analyze_morning(sleep: dict, hrv: dict, daily_records: list[dict]) -> str:
    ctx = format_morning_ctx(sleep, hrv, daily_records)
    prompt = f"{ctx}\n\n请给出今日状态播报。"

    logger.info("Morning report context:\n%s", ctx)
    logger.info("Calling LLM for morning report, model=%s", settings.llm_model)
    response = _client.chat.completions.create(
        model=settings.llm_model,
        max_tokens=400,
        messages=[
            {"role": "system", "content": _MORNING_SYSTEM},
            {"role": "user", "content": prompt},
        ],
    )
    result = response.choices[0].message.content or ""
    logger.info("Morning report result: %s", result[:200])
    return result


def analyze_sleep(sleep: dict, hrv: dict) -> str:
    # 已被 analyze_morning() 替代
    raise NotImplementedError("use analyze_morning() instead")
