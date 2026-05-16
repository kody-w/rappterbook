#!/usr/bin/env python3
from __future__ import annotations

"""Mars Digital Twin — real Martian weather flowing through the pump.

Pulls real telemetry from NASA APIs every tick:
- Curiosity/REMS: temperature, pressure, UV, wind
- InSight: seismic + weather (if available)
- Latest rover photos

Processes the data, detects anomalies, generates forecasts,
writes twin state. This is a physical world twin, not a social
media adapter.

Usage:
    python scripts/mars_twin.py              # one sync
    python scripts/mars_twin.py --forecast   # generate forecast
    python scripts/mars_twin.py --anomalies  # detect anomalies
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "scripts"))
from state_io import load_json, save_json, now_iso, append_event

STATE_DIR = Path(os.environ.get("STATE_DIR", str(_REPO_ROOT / "state")))
ECHOES_DIR = STATE_DIR / "twin_echoes"
MARS_PATH = ECHOES_DIR / "mars.json"
NASA_API_KEY = os.environ.get("NASA_API_KEY", "DEMO_KEY")

# ── NASA API endpoints ─────────────────────────────────────────────────

REMS_URL = "https://mars.nasa.gov/rss/api/?feed=weather&category=msl&feedtype=json"
INSIGHT_URL = (
    f"https://api.nasa.gov/insight_weather/"
    f"?api_key={NASA_API_KEY}&feedtype=json&ver=1.0"
)
CURIOSITY_PHOTOS_URL = (
    f"https://api.nasa.gov/mars-photos/api/v1/rovers/curiosity/latest_photos"
    f"?api_key={NASA_API_KEY}"
)


# ── HTTP helper ────────────────────────────────────────────────────────

def _fetch_json(url: str, timeout: int = 30) -> dict | None:
    """Fetch JSON from a URL. Returns None on any failure."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "RappterMars/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"  Fetch failed ({url[:60]}...): {exc}", file=sys.stderr)
        return None


# ── REMS data (Curiosity weather) ──────────────────────────────────────

def _parse_rems(raw: dict) -> list[dict]:
    """Parse REMS weather data into standardized sol records."""
    sols = raw.get("soles") or raw.get("sols") or []
    if not sols:
        return []

    results = []
    for sol_data in sols[:10]:
        record = {
            "sol": _int(sol_data.get("sol")),
            "earth_date": sol_data.get("terrestrial_date", ""),
            "min_temp_c": _float(sol_data.get("min_temp")),
            "max_temp_c": _float(sol_data.get("max_temp")),
            "pressure_pa": _float(sol_data.get("pressure")),
            "uv_index": sol_data.get("atmo_opacity", "unknown"),
            "season": sol_data.get("season", "unknown"),
            "sunrise": sol_data.get("sunrise", ""),
            "sunset": sol_data.get("sunset", ""),
            "min_gts_temp_c": _float(sol_data.get("min_gts_temp")),
            "max_gts_temp_c": _float(sol_data.get("max_gts_temp")),
        }
        results.append(record)
    return results


# ── InSight data ───────────────────────────────────────────────────────

def _parse_insight(raw: dict) -> list[dict]:
    """Parse InSight weather data. InSight ended Dec 2022 — data may be static."""
    sol_keys = raw.get("sol_keys", [])
    if not sol_keys:
        return []

    results = []
    for sol_key in sol_keys[-10:]:
        sol_data = raw.get(sol_key, {})
        at = sol_data.get("AT", {})
        pre = sol_data.get("PRE", {})
        hws = sol_data.get("HWS", {})
        record = {
            "sol": _int(sol_key),
            "source": "insight",
            "min_temp_c": _float(at.get("mn")),
            "max_temp_c": _float(at.get("mx")),
            "avg_temp_c": _float(at.get("av")),
            "pressure_pa": _float(pre.get("av")),
            "wind_speed_ms": _float(hws.get("av")),
            "season": sol_data.get("Season", "unknown"),
        }
        results.append(record)
    return results


# ── Curiosity photos ──────────────────────────────────────────────────

def _parse_photos(raw: dict) -> list[dict]:
    """Parse latest Curiosity photos into compact records."""
    photos = raw.get("latest_photos", [])
    results = []
    for photo in photos[:3]:
        results.append({
            "id": photo.get("id"),
            "camera": photo.get("camera", {}).get("full_name", "unknown"),
            "camera_abbr": photo.get("camera", {}).get("name", ""),
            "earth_date": photo.get("earth_date", ""),
            "sol": photo.get("sol"),
            "img_src": photo.get("img_src", ""),
        })
    return results


# ── Anomaly detection ─────────────────────────────────────────────────

def detect_anomalies(sols: list[dict]) -> list[dict]:
    """Compare latest sol to 10-sol rolling average. Flag deviations."""
    if len(sols) < 2:
        return []

    latest = sols[0]
    history = sols[1:]
    anomalies = []

    # Temperature anomaly: deviation > 15K from mean
    temps = [s["max_temp_c"] for s in history if s.get("max_temp_c") is not None]
    if temps and latest.get("max_temp_c") is not None:
        avg_temp = sum(temps) / len(temps)
        dev = abs(latest["max_temp_c"] - avg_temp)
        if dev > 15:
            anomalies.append({
                "type": "thermal_anomaly",
                "severity": "high" if dev > 25 else "moderate",
                "detail": f"Max temp {latest['max_temp_c']:.1f}C deviates {dev:.1f}K from {len(temps)}-sol avg {avg_temp:.1f}C",
                "sol": latest.get("sol"),
                "detected_at": now_iso(),
            })

    # Pressure anomaly: deviation > 50 Pa from mean
    pressures = [s["pressure_pa"] for s in history if s.get("pressure_pa") is not None]
    if pressures and latest.get("pressure_pa") is not None:
        avg_pressure = sum(pressures) / len(pressures)
        dev = abs(latest["pressure_pa"] - avg_pressure)
        if dev > 50:
            anomalies.append({
                "type": "pressure_anomaly",
                "severity": "high" if dev > 100 else "moderate",
                "detail": f"Pressure {latest['pressure_pa']:.0f} Pa deviates {dev:.0f} Pa from avg {avg_pressure:.0f} Pa",
                "sol": latest.get("sol"),
                "detected_at": now_iso(),
            })

    # Dust event: UV index change > 2 levels
    uv_levels = {"sunny": 0, "moderate": 1, "high": 2, "very high": 3, "extreme": 4}
    latest_uv = uv_levels.get((latest.get("uv_index") or "").lower(), -1)
    recent_uvs = [
        uv_levels.get((s.get("uv_index") or "").lower(), -1)
        for s in history
    ]
    recent_uvs = [u for u in recent_uvs if u >= 0]
    if latest_uv >= 0 and recent_uvs:
        avg_uv = sum(recent_uvs) / len(recent_uvs)
        if abs(latest_uv - avg_uv) > 2:
            anomalies.append({
                "type": "dust_event",
                "severity": "high",
                "detail": f"UV shifted to '{latest.get('uv_index')}' — possible dust storm activity",
                "sol": latest.get("sol"),
                "detected_at": now_iso(),
            })

    return anomalies


# ── Forecast generation (LLM) ─────────────────────────────────────────

def generate_forecast(sols: list[dict], anomalies: list[dict]) -> str:
    """Use LLM to produce a natural language Mars weather forecast."""
    try:
        from github_llm import generate
    except ImportError:
        return "LLM unavailable — forecast skipped."

    if not sols:
        return "No sol data available for forecast."

    latest = sols[0]
    sol_summary = "\n".join(
        f"Sol {s.get('sol')}: {s.get('min_temp_c')}C to {s.get('max_temp_c')}C, "
        f"pressure {s.get('pressure_pa')} Pa, UV: {s.get('uv_index')}, season: {s.get('season')}"
        for s in sols[:5]
    )
    anomaly_text = ""
    if anomalies:
        anomaly_text = "\nActive anomalies:\n" + "\n".join(
            f"- {a['type']}: {a['detail']}" for a in anomalies
        )

    system = (
        "You are a Mars weather forecaster for mission control. "
        "Write a concise 2-3 sentence forecast based on recent sol data. "
        "Be specific about temperatures, pressure trends, and dust risk. "
        "Tone: professional, operational, data-driven."
    )
    user = f"Recent Martian weather:\n{sol_summary}{anomaly_text}\n\nForecast:"

    try:
        return generate(system=system, user=user, max_tokens=200, temperature=0.7)
    except Exception as exc:
        return f"Forecast generation failed: {exc}"


# ── Main sync ─────────────────────────────────────────────────────────

def sync(do_forecast: bool = False, do_anomalies: bool = True) -> dict:
    """Pull NASA data, process, detect anomalies, write state."""
    print("Mars Twin — syncing...")
    ECHOES_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing state
    existing = load_json(MARS_PATH)

    # Fetch REMS data
    print("  Fetching REMS (Curiosity weather)...")
    rems_raw = _fetch_json(REMS_URL)
    rems_sols = _parse_rems(rems_raw) if rems_raw else []
    print(f"  REMS: {len(rems_sols)} sols")

    # Fetch InSight data
    print("  Fetching InSight...")
    insight_raw = _fetch_json(INSIGHT_URL)
    insight_sols = _parse_insight(insight_raw) if insight_raw else []
    print(f"  InSight: {len(insight_sols)} sols")

    # Fetch latest photos
    print("  Fetching Curiosity photos...")
    photos_raw = _fetch_json(CURIOSITY_PHOTOS_URL)
    photos = _parse_photos(photos_raw) if photos_raw else []
    print(f"  Photos: {len(photos)}")

    # Prefer REMS data (Curiosity is active), fall back to InSight
    sols = rems_sols or insight_sols
    if not sols:
        print("  WARNING: No sol data from any source")
        sols = existing.get("recent_sols", [])

    current_sol = sols[0] if sols else {}

    # Detect anomalies
    anomalies = detect_anomalies(sols) if do_anomalies else []
    if anomalies:
        print(f"  ANOMALIES: {len(anomalies)} detected")
        for a in anomalies:
            print(f"    [{a['severity'].upper()}] {a['type']}: {a['detail']}")

    # Generate forecast
    forecast = ""
    if do_forecast:
        print("  Generating forecast...")
        forecast = generate_forecast(sols, anomalies)
        print(f"  Forecast: {forecast[:80]}...")

    # Build history entry
    history_entry = {
        "sol": current_sol.get("sol"),
        "synced_at": now_iso(),
        "anomaly_count": len(anomalies),
        "data_sources": [],
    }
    if rems_sols:
        history_entry["data_sources"].append("rems")
    if insight_sols:
        history_entry["data_sources"].append("insight")
    if photos:
        history_entry["data_sources"].append("photos")

    # Merge history (keep last 100 entries)
    history = existing.get("history", [])
    history.append(history_entry)
    if len(history) > 100:
        history = history[-100:]

    # Merge insight data if available
    insight_current = {}
    if insight_sols:
        insight_current = {
            "available": True,
            "latest_sol": insight_sols[0].get("sol"),
            "avg_temp_c": insight_sols[0].get("avg_temp_c"),
            "wind_speed_ms": insight_sols[0].get("wind_speed_ms"),
        }

    # Build state
    state = {
        "_meta": {
            "updated_at": now_iso(),
            "source": "NASA REMS + InSight",
            "platform": "mars",
            "type": "physical_twin",
            "nasa_api_key": "DEMO_KEY",
        },
        "current_sol": current_sol,
        "recent_sols": sols[:10],
        "anomalies": anomalies,
        "latest_photos": photos,
        "forecast": forecast,
        "insight": insight_current,
        "history": history,
    }

    # Write state
    save_json(MARS_PATH, state)
    print(f"  State written to {MARS_PATH}")

    # Log event
    append_event(
        "twin.mars.sync",
        data={
            "sol": current_sol.get("sol"),
            "anomaly_count": len(anomalies),
            "photo_count": len(photos),
            "data_sources": history_entry["data_sources"],
            "has_forecast": bool(forecast),
        },
    )

    # Summary
    if current_sol:
        print(
            f"\n  Sol {current_sol.get('sol')} | "
            f"{current_sol.get('min_temp_c')}C to {current_sol.get('max_temp_c')}C | "
            f"Pressure: {current_sol.get('pressure_pa')} Pa | "
            f"UV: {current_sol.get('uv_index')} | "
            f"Season: {current_sol.get('season')}"
        )

    return state


# ── Helpers ────────────────────────────────────────────────────────────

def _int(val) -> int | None:
    """Safe int conversion."""
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _float(val) -> float | None:
    """Safe float conversion."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ── CLI ────────────────────────────────────────────────────────────────

def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Mars Digital Twin — real Martian weather through the pump"
    )
    parser.add_argument(
        "--forecast", action="store_true", help="Generate LLM forecast"
    )
    parser.add_argument(
        "--anomalies", action="store_true", help="Detect and report anomalies only"
    )
    parser.add_argument(
        "--status", action="store_true", help="Show current Mars state"
    )
    args = parser.parse_args()

    if args.status:
        state = load_json(MARS_PATH)
        if not state:
            print("No Mars state yet. Run: python scripts/mars_twin.py")
            return
        cs = state.get("current_sol", {})
        print(f"Mars Twin Status")
        print(f"  Sol:         {cs.get('sol')}")
        print(f"  Earth date:  {cs.get('earth_date')}")
        print(f"  Temperature: {cs.get('min_temp_c')}C to {cs.get('max_temp_c')}C")
        print(f"  Pressure:    {cs.get('pressure_pa')} Pa")
        print(f"  UV:          {cs.get('uv_index')}")
        print(f"  Season:      {cs.get('season')}")
        print(f"  Anomalies:   {len(state.get('anomalies', []))}")
        print(f"  Photos:      {len(state.get('latest_photos', []))}")
        print(f"  Last sync:   {state.get('_meta', {}).get('updated_at', 'never')}")
        return

    if args.anomalies:
        state = load_json(MARS_PATH)
        sols = state.get("recent_sols", [])
        anomalies = detect_anomalies(sols)
        if anomalies:
            print(f"Anomalies detected: {len(anomalies)}")
            for a in anomalies:
                print(f"  [{a['severity'].upper()}] {a['type']}: {a['detail']}")
        else:
            print("No anomalies detected.")
        return

    sync(do_forecast=args.forecast)


if __name__ == "__main__":
    main()
