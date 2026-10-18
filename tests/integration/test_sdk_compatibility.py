"""The installed SDK accepts each managed harness configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

from band_wezterm.agent.adapters import build_adapter
from band_wezterm.harnesses.models import AgentTuning
from band_wezterm.identity import HarnessId


class TestInstalledSdkCompatibility:
    @pytest.mark.parametrize(
        ("harness", "effort_field"),
        [
            (HarnessId.CLAUDE_SDK, "effort"),
            (HarnessId.CODEX, "reasoning_effort"),
            (HarnessId.COPILOT_SDK, "reasoning_effort"),
            (HarnessId.OPENCODE, "variant"),
        ],
    )
    def test_managed_harness_keeps_persona_model_and_effort(
        self, harness: HarnessId, effort_field: str, tmp_path: Path
    ) -> None:
        adapter = build_adapter(
            harness,
            cwd=tmp_path,
            persona="Synthetic instructions.",
            tuning=AgentTuning(model="synthetic-model", reasoning="high"),
        )
        config = adapter.config
        assert config.custom_section == "Synthetic instructions."
        assert getattr(config, effort_field) == "high"
        assert (
            getattr(config, "model_id" if harness is HarnessId.OPENCODE else "model")
            == "synthetic-model"
        )
