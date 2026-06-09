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

_WORKOUT_SYSTEM = """你是一位专业跑步教练，根据运动员的单次训练数据和近期训练趋势给出简短点评。

要求：
- 把本次活动的配速/心率放在近期负荷趋势里解读
- 指出今天与近期同类跑的异同
- 给一条具体可执行的建议
- 200个中文字以内
- 不要逐条复述指标，要连线叙事"""


def analyze_workout(activity: dict, daily_ctx: dict) -> str:
    prompt = f"""本次活动数据：
{activity}

近14天训练指标：
{daily_ctx}

请给出教练点评。"""

    logger.info(
        "Calling LLM for workout analysis: activity_len=%s, daily_ctx_len=%s, model=%s",
        len(str(activity)),
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
