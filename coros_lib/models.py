
from pydantic import BaseModel


class SleepPhases(BaseModel):
    deep_minutes: int | None = None
    light_minutes: int | None = None
    rem_minutes: int | None = None
    awake_minutes: int | None = None
    nap_minutes: int | None = None    # shortSleepTime — daytime naps


class SleepRecord(BaseModel):
    date: str
    total_duration_minutes: int | None = None
    phases: SleepPhases | None = None
    avg_hr: int | None = None
    min_hr: int | None = None
    max_hr: int | None = None
    quality_score: int | None = None  # -1 = not computed


class HRVRecord(BaseModel):
    date: str
    avg_sleep_hrv: float | None = None    # Nacht-Durchschnitt RMSSD (ms)
    baseline: float | None = None          # sleepHrvBase — rolling baseline
    standard_deviation: float | None = None  # sleepHrvSd
    interval_list: list[int] | None = None   # sleepHrvIntervalList — percentile bands


class DailyRecord(BaseModel):
    date: str
    avg_sleep_hrv: float | None = None
    baseline: float | None = None
    interval_list: list[int] | None = None
    rhr: int | None = None                      # resting heart rate (bpm)
    training_load: int | None = None
    training_load_ratio: float | None = None    # acute/chronic ratio
    tired_rate: float | None = None
    ati: float | None = None                    # acute training index
    cti: float | None = None                    # chronic training index
    performance: int | None = None              # performance index (-1 = no data)
    training_load_ratio_state: int | None = None  # 1=下滑 2=恢复/竞技 3=维持 4=优化 5=过量
    tired_rate_state: int | None = None           # 1=极度新鲜 2=新鲜 3=正常 4=疲劳 5=极度疲劳
    t7d: float | None = None                    # 近7天总训练负荷
    t28d: float | None = None                   # 近28天总训练负荷
    recommend_tl_min: float | None = None       # COROS 建议训练负荷下限
    recommend_tl_max: float | None = None       # COROS 建议训练负荷上限
    distance: float | None = None               # daily distance (m)
    duration: int | None = None                 # daily duration (s)
    vo2max: int | None = None                   # only from /analyse/query
    lthr: int | None = None                     # lactate threshold HR (bpm)
    ltsp: int | None = None                     # lactate threshold pace (s/km)
    stamina_level: float | None = None          # running fitness score (App "Running Fitness", e.g. 83.5); NOT cti (cti = Base Fitness)
    stamina_level_7d: float | None = None       # 7-day running fitness trend


class ActivitySummary(BaseModel):
    activity_id: str
    name: str | None = None
    sport_type: int | None = None
    sport_name: str | None = None
    start_time: str | None = None  # UTC Unix seconds (seconds since epoch), as returned by Coros API
    end_time: str | None = None    # UTC Unix seconds (seconds since epoch), as returned by Coros API
    duration_seconds: int | None = None
    distance_meters: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    calories: int | None = None
    training_load: int | None = None
    avg_power: int | None = None
    normalized_power: int | None = None
    elevation_gain: int | None = None
    elevation_loss: int | None = None


class StoredAuth(BaseModel):
    access_token: str
    user_id: str
    region: str
    timestamp: int  # Unix milliseconds
    mobile_access_token: str | None = None   # token for apieu.coros.com (sleep data)
    mobile_login_payload: dict | None = None  # encrypted login body for auto-refresh

    def __repr__(self) -> str:
        tok = f"{self.access_token[:8]}…" if self.access_token else "None"
        mob = "present" if self.mobile_access_token else "None"
        return (
            f"StoredAuth(user_id={self.user_id!r}, region={self.region!r}, "
            f"access_token=<{tok}>, mobile_token=<{mob}>)"
        )