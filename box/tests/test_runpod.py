"""Tests for RunPod adapter.

Recorded fixtures for offline parsing tests. @live for real API.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from box.provider import Offering, Status
from box.providers.runpod import RunPod, RunPodBox, _RunPodAPI

FIXTURES = Path(__file__).parent / "fixtures" / "runpod"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def _mock_gql(fixture_name: str):
    data = _load_fixture(fixture_name)

    def _gql(self, query, variables=None):
        return data

    return _gql


def _make_box(fixture: str = "get_pod_pending.json") -> RunPodBox:
    """Build a RunPodBox wired to a fixture, without constructing a real API client."""
    from box.provider import Offering

    api = _RunPodAPI.__new__(_RunPodAPI)
    offering = Offering(
        provider="runpod", id="H100", gpu_model="H100",
        gpu_count=1, gpu_memory_gb=80, price_hr=2.89,
    )
    return RunPodBox(api=api, pod_id="pod-abc", offering=offering)


# -- check() functions --


def check_search(offerings, *, expected_ids):
    """Assert search returned exactly these offering IDs in this order."""
    actual_ids = [o.id for o in offerings]
    assert actual_ids == expected_ids


# -- parsing external responses (priority 1) --


class TestParseResponses:
    """Does our code survive RunPod's actual response shapes?"""

    def test_parse_search_response(self):
        """Fixture has 4 GPUs: 3 secure (H100, A100, RTX 4090), 1 not secure (RTX A5000).
        Non-secure and unavailable are filtered. Sorted by price."""
        with patch.object(_RunPodAPI, "gql", _mock_gql("search_gpu_types.json")):
            rp = RunPod(api_key="fake")
            offerings = rp.search(gpu_count=1)
            check_search(offerings, expected_ids=[
                "NVIDIA GeForce RTX 4090",
                "NVIDIA A100 80GB",
                "NVIDIA H100 80GB HBM3",
            ])

    def test_parse_search_with_filter(self):
        with patch.object(_RunPodAPI, "gql", _mock_gql("search_gpu_types.json")):
            rp = RunPod(api_key="fake")
            offerings = rp.search(gpu_model="H100", gpu_count=1)
            check_search(offerings, expected_ids=["NVIDIA H100 80GB HBM3"])

    def test_parse_running_pod_ssh(self):
        """Running pod with public SSH port → extract host and port."""
        box = _make_box()
        with patch.object(_RunPodAPI, "gql", _mock_gql("get_pod_running.json")):
            box._refresh()
        assert box.status == Status.RUNNING
        assert box._ssh_host == "194.68.245.11"
        assert box._ssh_port == 43612

    def test_parse_pending_pod(self):
        """Pending pod with null runtime → no SSH info."""
        box = _make_box()
        with patch.object(_RunPodAPI, "gql", _mock_gql("get_pod_pending.json")):
            box._refresh()
        assert box.status == Status.PENDING
        assert box._ssh_host is None
        assert box._ssh_port is None

    def test_parse_null_pod(self):
        """Null pod (terminated/deleted) → terminated status.
        RunPod returns null for pods that no longer exist."""
        box = _make_box()
        with patch.object(_RunPodAPI, "gql", _mock_gql("get_pod_terminated.json")):
            box._refresh()
        assert box.status == Status.TERMINATED

    def test_parse_running_proxy_only(self):
        """Running pod with only proxy SSH (ssh.runpod.io) → SSH fields stay None.
        Proxy is not a direct transport — broker explicitly rejected it."""
        box = _make_box()
        with patch.object(_RunPodAPI, "gql", _mock_gql("get_pod_running_proxy_only.json")):
            box._refresh()
        assert box.status == Status.RUNNING
        assert box._ssh_host is None
        assert box._ssh_port is None

    def test_parse_launch_response(self):
        """Launch mutation returns pod ID → RunPodBox with correct ID and PENDING status."""
        with patch.object(_RunPodAPI, "gql", _mock_gql("launch_pod.json")):
            rp = RunPod(api_key="fake")
            offering = Offering(
                provider="runpod", id="NVIDIA H100 80GB HBM3", gpu_model="H100",
                gpu_count=1, gpu_memory_gb=80, price_hr=2.89,
            )
            box = rp.launch(offering, ssh_pubkey="ssh-ed25519 AAAA...")
            assert box.provider_id == "pod-xyz789"
            assert box.status == Status.PENDING

    def test_parse_unknown_status(self):
        """Unknown desiredStatus from RunPod → falls back to PENDING."""
        box = _make_box()
        with patch.object(_RunPodAPI, "gql", _mock_gql("get_pod_unknown_status.json")):
            box._refresh()
        assert box.status == Status.PENDING

    def test_parse_running_no_ssh_port(self):
        """Running pod with ports but no port 22 → SSH fields stay None."""
        box = _make_box()
        with patch.object(_RunPodAPI, "gql", _mock_gql("get_pod_running_no_ssh.json")):
            box._refresh()
        assert box.status == Status.RUNNING
        assert box._ssh_host is None
        assert box._ssh_port is None


# -- anomalies (priority 3) --


class TestAnomalies:
    """Does the system fail honestly on bad input?"""

    def test_api_error_raises(self):
        """RunPod returns errors array → RuntimeError with context."""
        def _gql_error(self, query, variables=None):
            raise RuntimeError("RunPod API error: [{'message': 'rate limited'}]")

        with patch.object(_RunPodAPI, "gql", _gql_error):
            rp = RunPod(api_key="fake")
            with pytest.raises(RuntimeError, match="RunPod API error"):
                rp.search(gpu_count=1)

    def test_exec_before_ready(self):
        """Exec on a box that hasn't been waited on → honest error, not silent failure."""
        box = _make_box()
        with pytest.raises(RuntimeError, match="not ready"):
            box.exec("nvidia-smi")

    def test_search_no_matches(self):
        """Search for a GPU that doesn't exist → empty list, not an error."""
        with patch.object(_RunPodAPI, "gql", _mock_gql("search_gpu_types.json")):
            rp = RunPod(api_key="fake")
            offerings = rp.search(gpu_model="NONEXISTENT_GPU", gpu_count=1)
            assert offerings == []

    def test_wait_timeout(self):
        """Pod never becomes ready → TimeoutError with pod ID."""
        box = _make_box()
        with patch.object(_RunPodAPI, "gql", _mock_gql("get_pod_pending.json")):
            with pytest.raises(TimeoutError, match="pod-abc"):
                box.wait(timeout=0.01)

    def test_wait_on_failed_pod(self):
        """Pod fails during wait → RuntimeError with pod ID."""
        box = _make_box()
        with patch.object(_RunPodAPI, "gql", _mock_gql("get_pod_failed.json")):
            with pytest.raises(RuntimeError, match="failed"):
                box.wait(timeout=5)

    def test_wait_on_terminated_pod(self):
        """Pod terminates during wait → RuntimeError with pod ID."""
        box = _make_box()
        with patch.object(_RunPodAPI, "gql", _mock_gql("get_pod_terminated.json")):
            with pytest.raises(RuntimeError, match="terminated"):
                box.wait(timeout=5)

    def test_malformed_ports_no_crash(self):
        """Ports entry missing keys → no crash, SSH stays None."""
        box = _make_box()
        with patch.object(_RunPodAPI, "gql", _mock_gql("get_pod_running_malformed_ports.json")):
            box._refresh()
        assert box.status == Status.RUNNING
        assert box._ssh_host is None
        assert box._ssh_port is None

    def test_terminate_idempotent(self):
        """Terminate twice → no error on second call."""
        box = _make_box()
        # First terminate
        with patch.object(_RunPodAPI, "gql", lambda self, q, v=None: {"podTerminate": None}):
            box.terminate()
        assert box.status == Status.TERMINATED
        # Second terminate — should not raise
        with patch.object(_RunPodAPI, "gql", lambda self, q, v=None: {"podTerminate": None}):
            box.terminate()


# -- live tests (priority 2: round-trip features) --


@pytest.mark.live
class TestLive:
    @pytest.fixture
    def rp(self):
        import os

        key = os.environ.get("RUNPOD_API_KEY")
        if not key:
            pytest.skip("RUNPOD_API_KEY not set")
        return RunPod(api_key=key)

    def test_search_returns_real_offerings(self, rp):
        """Search hits real API and returns parseable offerings."""
        offerings = rp.search(gpu_model="H100", gpu_count=1)
        assert len(offerings) >= 1
        o = offerings[0]
        assert "H100" in o.gpu_model or "h100" in o.gpu_model.lower()
        assert o.price_hr > 0
        assert o.gpu_memory_gb > 0
        print(f"Found {len(offerings)} H100 offerings, cheapest ${o.price_hr}/hr")

    # TODO: round-trip test (launch → wait → exec("echo hello") → terminate)
    # Requires RunPod credits. Uncomment when ready to spend ~$0.10:
    #
    # def test_roundtrip(self, rp):
    #     offerings = rp.search(gpu_model="RTX 4090", gpu_count=1)
    #     assert len(offerings) >= 1
    #     box = rp.launch(offerings[0], ssh_pubkey=open(
    #         os.path.expanduser("~/.ssh/id_ed25519.pub")).read().strip())
    #     try:
    #         box.wait(timeout=600)
    #         result = box.exec("echo hello")
    #         assert result.stdout.strip() == "hello"
    #         assert result.returncode == 0
    #     finally:
    #         box.terminate()
