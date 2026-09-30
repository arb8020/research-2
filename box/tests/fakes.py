"""Test doubles for box — FakeBox and FakeProvider.

No tests of the fakes themselves. These exist for other code
that consumes a Box/Provider to test against.
"""

from __future__ import annotations

from box.provider import ExecResult, Offering, Status


def _offering(
    *,
    gpu_model: str = "H100",
    gpu_count: int = 1,
    price_hr: float = 2.89,
) -> Offering:
    return Offering(
        provider="fake",
        id=f"fake-{gpu_model}",
        gpu_model=gpu_model,
        gpu_count=gpu_count,
        gpu_memory_gb=80,
        price_hr=price_hr,
    )


class FakeBox:
    """In-memory Box for testing."""

    def __init__(
        self,
        *,
        offering: Offering | None = None,
        fail: bool = False,
    ):
        self.provider_id = "fake-123"
        self.offering = offering or _offering()
        self.status = Status.PENDING
        self._fail = fail
        self._commands: list[str] = []

    def wait(self, timeout: float = 900.0) -> None:
        if self._fail:
            self.status = Status.FAILED
            raise RuntimeError(f"Box {self.provider_id} failed")
        self.status = Status.RUNNING

    def exec(self, cmd: str, *, env=None, stream=False, timeout=None) -> ExecResult:
        if self.status != Status.RUNNING:
            raise RuntimeError("Box not ready")
        self._commands.append(cmd)
        return ExecResult(stdout=f"ran: {cmd}\n", stderr="", returncode=0)

    def upload(self, local: str, remote: str) -> None:
        if self.status != Status.RUNNING:
            raise RuntimeError("Box not ready")

    def download(self, remote: str, local: str) -> None:
        if self.status != Status.RUNNING:
            raise RuntimeError("Box not ready")

    def terminate(self) -> None:
        self.status = Status.TERMINATED


class FakeProvider:
    """In-memory provider for testing."""

    name = "fake"

    def __init__(self, *, fail_launch: bool = False):
        self._fail_launch = fail_launch
        self.launched: list[Offering] = []

    def search(self, *, gpu_model=None, gpu_count=1):
        return [_offering(gpu_model=gpu_model or "H100", gpu_count=gpu_count)]

    def launch(self, offering, **kwargs):
        self.launched.append(offering)
        return FakeBox(offering=offering, fail=self._fail_launch)
