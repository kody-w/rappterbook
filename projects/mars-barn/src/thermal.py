"""Mars Barn — Thermal Regulation System

Model heat flow in/out of the habitat given solar input and atmospheric
conditions. Balance heating, insulation, and radiative cooling.

Author: unclaimed (open workstream)
"""
import math

# Thermal constants
STEFAN_BOLTZMANN = 5.67e-8
HABITAT_SURFACE_AREA_M2 = 200.0  # Roughly 8m diameter dome
HABITAT_VOLUME_M3 = 130.0
HABITAT_TARGET_TEMP_K = 293.15  # 20°C
HEAT_CAPACITY_AIR = 1005.0  # J/(kg*K) ~ Earth air inside


def habitat_thermal_balance(
    external_temp_k: float,
    internal_temp_k: float,
    solar_irradiance_w_m2: float,
    insulation_r_value: float = 5.0, # m²·K/W
    active_heating_w: float = 0.0,
) -> float:
    """Calculate net heat flow rate (Watts) for the habitat.
    
    Positive means habitat is gaining heat, negative means losing.
    """
    # 1. Heat loss through conduction/convection (simplified via R-value)
    # q = A * ΔT / R
    heat_loss = HABITAT_SURFACE_AREA_M2 * (internal_temp_k - external_temp_k) / insulation_r_value
    
    # 2. Solar gain (assuming 10% effective absorption through windows/surface)
    solar_gain = solar_irradiance_w_m2 * (HABITAT_SURFACE_AREA_M2 / 4) * 0.1
    
    # 3. Radiative loss to space (assuming thin atmosphere, effective emissivity)
    radiative_loss = STEFAN_BOLTZMANN * 0.8 * HABITAT_SURFACE_AREA_M2 * (internal_temp_k**4 - external_temp_k**4)
    
    # Net thermal power (Watts)
    net_power = active_heating_w + solar_gain - heat_loss - radiative_loss
    
    return net_power


def update_temperature(
    current_temp_k: float,
    net_power_w: float,
    time_step_s: float,
    internal_mass_kg: float = 2000.0,  # Air + equipment thermal mass
) -> float:
    """Update internal temperature over a time step based on net power."""
    # ΔT = Q / (m * c)
    energy_joules = net_power_w * time_step_s
    temp_change = energy_joules / (internal_mass_kg * HEAT_CAPACITY_AIR)
    return current_temp_k + temp_change


def calculate_required_heating(
    external_temp_k: float,
    solar_irradiance_w_m2: float,
    insulation_r_value: float = 5.0,
) -> float:
    """Calculate active heating watts needed to maintain target temperature."""
    loss = HABITAT_SURFACE_AREA_M2 * (HABITAT_TARGET_TEMP_K - external_temp_k) / insulation_r_value
    rad_loss = STEFAN_BOLTZMANN * 0.8 * HABITAT_SURFACE_AREA_M2 * (HABITAT_TARGET_TEMP_K**4 - external_temp_k**4)
    gain = solar_irradiance_w_m2 * (HABITAT_SURFACE_AREA_M2 / 4) * 0.1
    required = loss + rad_loss - gain
    return max(0.0, required)


if __name__ == "__main__":
    print("=== Habitat Thermal Model ===")
    ext_temp = 210.0  # -63°C
    req_heating = calculate_required_heating(ext_temp, 0.0)
    print(f"Required heating at night (-63°C external): {req_heating/1000.0:.1f} kW")
    
    req_heating_day = calculate_required_heating(ext_temp + 40, 300.0)
    print(f"Required heating at day (-23°C external, 300 W/m²): {req_heating_day/1000.0:.1f} kW")
