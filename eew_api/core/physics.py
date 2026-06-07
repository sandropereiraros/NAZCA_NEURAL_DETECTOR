"""
Motor físico EEW: distancia epicentral (Haversine) y tiempos de arribo de ondas P/S.
"""
import math
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0
V_P_KM_S = 6.5
V_S_KM_S = 3.5
V_INFO_KM_S = 300_000.0
ALERT_COEFF_S_PER_KM = (1.0 / V_S_KM_S) - (1.0 / V_P_KM_S)  # ≈ 0.131868


@dataclass(frozen=True)
class WaveArrival:
    distance_km: float
    eta_p_seconds: float
    eta_s_seconds: float
    useful_alert_window_seconds: float
    network_latency_seconds: float


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def calculate_wave_arrival(lat_epicenter: float, lon_epicenter: float, lat_target: float, lon_target: float) -> WaveArrival:
    d = haversine_distance_km(lat_epicenter, lon_epicenter, lat_target, lon_target)
    eta_p = d / V_P_KM_S
    eta_s = d / V_S_KM_S
    t_alerta = d * ALERT_COEFF_S_PER_KM
    network_latency = d / V_INFO_KM_S
    return WaveArrival(
        distance_km=round(d, 3),
        eta_p_seconds=round(eta_p, 2),
        eta_s_seconds=round(eta_s, 2),
        useful_alert_window_seconds=round(t_alerta, 2),
        network_latency_seconds=network_latency,
    )


def estimate_pga_g(magnitude_mw: float, distance_km: float, depth_km: float = 10.0) -> float:
    """
    Estimación simplificada de PGA (Peak Ground Acceleration) en fracción de g.
    Modelo de atenuación logarítmica para alertas industriales IoT.
    """
    if distance_km < 1.0:
        distance_km = 1.0
    log_pga = 0.55 * magnitude_mw - 1.1 * math.log10(distance_km) - 0.004 * depth_km - 0.8
    return round(max(0.001, 10 ** log_pga), 4)


def recommended_action(pga_g: float, alert_window_s: float, magnitude_mw: float) -> str:
    if magnitude_mw >= 6.5 and alert_window_s >= 10 and pga_g >= 0.15:
        return "AUTOMATIC_VALVE_SHUTDOWN_RECOMMENDED"
    if magnitude_mw >= 5.5 and alert_window_s >= 5:
        return "EVACUATION_PROTOCOL_ADVISORY"
    if magnitude_mw >= 4.5:
        return "MONITORING_ESCALATION"
    return "NO_ACTION_REQUIRED"
