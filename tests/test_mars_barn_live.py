"""Tests for which Mars Barn sols are worth a status post."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import mars_barn_live as mbl


def _log(sol, events=(), storm=False):
    return {"sol": sol, "events": list(events), "dust_storm_active": storm}


def test_storm_is_notable_only_on_the_sol_it_starts():
    assert mbl.is_notable_sol(_log(12, ["dust_storm"], storm=True))
    assert not mbl.is_notable_sol(_log(13, [], storm=True))
    assert not mbl.is_notable_sol(_log(14, ["dust_devil"], storm=True))


def test_other_rules_are_kept():
    assert mbl.is_notable_sol(_log(15))
    assert mbl.is_notable_sol(_log(1))
    assert mbl.is_notable_sol(_log(668))
    assert mbl.is_notable_sol(_log(13, ["meteorite"]))
    assert mbl.is_notable_sol(_log(13, ["equipment_warning"]))
    assert mbl.is_notable_sol(_log(13), force=True)
    assert not mbl.is_notable_sol(_log(13, ["dust_devil"]))
