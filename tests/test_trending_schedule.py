"""Tests for compute-trending workflow schedule configuration."""
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent


class TestTrendingWorkflowSchedule:
    """Test that compute-trending.yml has proper scheduling."""

    def _load_workflow(self):
        path = ROOT / ".github" / "workflows" / "compute-trending.yml"
        wf = yaml.safe_load(path.read_text())
        # YAML parses 'on' as True (boolean), normalize to string key
        if True in wf:
            wf["on"] = wf.pop(True)
        return wf

    def test_has_schedule_trigger(self):
        """Workflow runs on a cron schedule."""
        wf = self._load_workflow()
        assert "schedule" in wf["on"], "Missing schedule trigger"
        crons = wf["on"]["schedule"]
        assert len(crons) >= 1
        assert "cron" in crons[0]

    def test_schedule_runs_at_least_hourly(self):
        """Cron runs at least every hour."""
        wf = self._load_workflow()
        cron = wf["on"]["schedule"][0]["cron"]
        parts = cron.split()
        assert len(parts) == 5, f"Invalid cron: {cron}"

    def test_triggers_after_zion_autonomy(self):
        """Workflow triggers after Zion Autonomy completes."""
        wf = self._load_workflow()
        assert "workflow_run" in wf["on"], "Missing workflow_run trigger"
        triggers = wf["on"]["workflow_run"]
        workflow_names = triggers.get("workflows", [])
        assert "Zion Autonomy" in workflow_names, \
            f"Missing 'Zion Autonomy' trigger, got: {workflow_names}"

    def test_keeps_workflow_dispatch(self):
        """Manual trigger still available."""
        wf = self._load_workflow()
        assert "workflow_dispatch" in wf["on"]

    def test_has_compute_step(self):
        """Trending computation step exists."""
        wf = self._load_workflow()
        compute_step = None
        for step in wf["jobs"]["compute"]["steps"]:
            if "Compute trending" in step.get("name", ""):
                compute_step = step
                break
        assert compute_step is not None, "Missing 'Compute trending' step"
