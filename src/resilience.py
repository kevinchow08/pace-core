"""
熔断器（Circuit Breaker），手写不引入额外的库。

熔断和重试是配合关系，分工不同：
- 重试（调用方用 tenacity）：应对偶发瞬时故障，隔一段时间再试几次。
- 熔断（这个模块）：应对持续性故障，连续失败次数超过阈值就直接拒绝，
  不再浪费时间重试一个大概率已经挂了的依赖；冷却一段时间后放一个试探
  请求，成功则恢复正常，失败则重新熔断。

状态机三态：
  CLOSED（正常）→ 连续失败超过阈值 → OPEN（熔断，直接拒绝）
  OPEN → 冷却时间到 → HALF_OPEN（放一个试探请求）
  HALF_OPEN → 试探成功 → CLOSED；试探失败 → 重新 OPEN，冷却计时重新开始

单进程内的状态，不做跨进程共享（不需要 Redis）——这个项目是单进程运行，
状态放在内存里就够。
"""
import logging
import time
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """熔断器处于打开状态，直接拒绝，不做真正的调用"""


class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 5, recovery_timeout: float = 60):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._state = CircuitState.CLOSED
        self._opened_at: float | None = None

    def _maybe_recover(self) -> None:
        """OPEN 状态下，冷却时间到了就切到 HALF_OPEN，放行下一次调用去试探"""
        if self._state == CircuitState.OPEN and time.monotonic() - self._opened_at >= self.recovery_timeout:
            self._state = CircuitState.HALF_OPEN
            logger.warning("CircuitBreaker[%s]: OPEN -> HALF_OPEN，放行一次试探请求", self.name)

    def before_call(self) -> None:
        """每次真正调用前先检查熔断状态；OPEN 就直接拒绝，不发起请求"""
        self._maybe_recover()
        if self._state == CircuitState.OPEN:
            raise CircuitOpenError(f"{self.name} 熔断中，暂停调用")

    def record_success(self) -> None:
        if self._state != CircuitState.CLOSED:
            logger.warning("CircuitBreaker[%s]: %s -> CLOSED，恢复正常", self.name, self._state.value)
        self._failure_count = 0
        self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        self._failure_count += 1
        if self._state == CircuitState.HALF_OPEN:
            # 试探请求也失败了，重新打开，冷却计时重新开始
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            logger.warning("CircuitBreaker[%s]: 试探请求失败，HALF_OPEN -> OPEN", self.name)
        elif self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            logger.warning(
                "CircuitBreaker[%s]: 连续失败 %d 次，CLOSED -> OPEN，冷却 %.0f 秒",
                self.name, self._failure_count, self.recovery_timeout,
            )
