"""
LLM-powered coaching analysis.

analyze_workout(): active (v0)
analyze_sleep(): stubbed, activated in v0.1 when sleep data is available
"""
import anthropic

from src.config import settings

_client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

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

    message = _client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=_WORKOUT_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def analyze_sleep(sleep: dict, hrv: dict) -> str:
    # v0.1 — 有睡眠数据后实现
    raise NotImplementedError("analyze_sleep is pending sleep data (v0.1)")
