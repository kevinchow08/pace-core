"""
LLM-powered coaching analysis.

analyze_workout(): active (v0)
analyze_sleep(): stubbed, activated in v0.1 when sleep data is available
"""
import logging

from openai import OpenAI

from src.config import settings
from src.formatter import format_activity, format_daily_ctx

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

【通用要求】
- 开头一句话说清训练类型和整体定性
- 结合近14天负荷趋势解读今天的位置
- 给出1-2条具体可执行的建议
- 不超过800字
- 不要逐条复述原始数字，要连线叙事、有判断、有温度
- 不要使用 Z1/Z2/Z3/Z4/Z5/Z6 这类代号，用中文术语：恢复区、有氧耐力区、有氧能力区、阈值区、无氧耐力区、无氧能力区"""


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


def analyze_sleep(sleep: dict, hrv: dict) -> str:
    # v0.1 — 有睡眠数据后实现
    raise NotImplementedError("analyze_sleep is pending sleep data (v0.1)")
