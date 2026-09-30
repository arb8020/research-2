"""Tests for Modal Sandbox adapter.

Pure tests for anomalies. @live for real sandbox operations.
Modal has no external API for search — catalog is static, not worth testing.
"""

from __future__ import annotations

import pytest

from box.providers.modal import Modal, ModalBox


# -- anomalies --


class TestAnomalies:
    def test_search_no_match(self):
        """Search for nonexistent GPU → empty list, not crash."""
        provider = Modal.__new__(Modal)
        provider.name = "modal"
        offerings = provider.search(gpu_model="NONEXISTENT", gpu_count=1)
        assert offerings == []

    def test_gpu_count_passthrough(self):
        """gpu_count requested is gpu_count in the offering."""
        provider = Modal.__new__(Modal)
        provider.name = "modal"
        offerings = provider.search(gpu_model="H100", gpu_count=4)
        assert len(offerings) == 1
        assert offerings[0].gpu_count == 4

    def test_vram_values(self):
        """Regression guard: catalog VRAM matches real hardware."""
        provider = Modal.__new__(Modal)
        provider.name = "modal"
        offerings = provider.search(gpu_count=1)
        vram = {o.id: o.gpu_memory_gb for o in offerings}
        assert vram["T4"] == 16
        assert vram["A100-80GB"] == 80
        assert vram["H100"] == 80
        assert vram["H200"] == 141


# -- live tests --


@pytest.mark.live
class TestLive:
    @pytest.fixture
    def provider(self):
        try:
            return Modal(profile="arb8020")
        except Exception as e:
            pytest.skip(f"Modal not configured: {e}")

    def test_roundtrip(self, provider):
        """Launch sandbox, exec echo, verify stdout, terminate."""
        offerings = provider.search(gpu_model="T4", gpu_count=1)
        assert len(offerings) >= 1

        box = provider.launch(offerings[0])
        try:
            box.wait()
            result = box.exec("echo hello")
            assert result.stdout.strip() == "hello"
            assert result.returncode == 0

            result = box.exec("nvidia-smi --query-gpu=name,memory.total --format=csv,noheader")
            print(f"GPU: {result.stdout.strip()}")

            # Exec failure propagation: nonzero exit code + stderr survive
            result = box.exec("echo fail >&2 && exit 1")
            assert result.returncode == 1
            assert "fail" in result.stderr
        finally:
            box.terminate()
