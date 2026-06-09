"""
LLM-powered coaching analysis.

analyze_workout(): active (v0)
analyze_sleep(): stubbed, activated in v0.1 when sleep data is available
"""
import logging

from openai import OpenAI

from src.config import settings

logger = logging.getLogger(__name__)

_client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)

_WORKOUT_SYSTEM = """你是一位专业跑步教练，根据运动员的训练数据和近期训练趋势给出简短点评。

本次训练可能包含多个片段（如热身、重点课、冷身），数据会一并提供。

要求：
- 把本次训练的配速/心率放在近期负荷趋势里解读
- 如有多个片段，作为一堂完整训练课来整体评价，不要逐段罗列
- 指出今天与近期同类训练的异同
- 给一条具体可执行的建议
- 200个中文字以内
- 不要逐条复述指标，要连线叙事"""


def analyze_workout(activities: list[dict] | dict, daily_ctx: list[dict]) -> str:
    # 兼容单条（dict）和多条（list）传入
    if isinstance(activities, dict):
        activities = [activities]

    if len(activities) == 1:
        activity_section = f"本次训练数据：\n{activities[0]}"
    else:
        parts = "\n\n".join(
            f"片段{i+1}：\n{a}" for i, a in enumerate(activities)
        )
        activity_section = f"本次训练共 {len(activities)} 个片段：\n\n{parts}"

    prompt = f"""{activity_section}

近14天训练指标：
{daily_ctx}

请给出教练点评。"""

    logger.info(
        "Calling LLM for workout analysis: activity_len=%s, daily_ctx_len=%s, model=%s",
        len(str(activities)),
        len(str(daily_ctx)),
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
