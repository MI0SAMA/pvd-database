"""
Extract key metrics from ferroelectric hysteresis loop data.
Uses correct Drive Voltage (col2) and Polarization (col3) from Radiant files.
"""
import numpy as np


def _safe(v):
    """Convert numpy scalar to native Python float, or None."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def extract_all_metrics(voltage, polarization):
    """
    Extract comprehensive metrics from a PE hysteresis loop.
    voltage = Drive Voltage (corrected column)
    polarization = Measured Polarization (corrected column)
    """
    if len(voltage) < 10:
        return _empty()

    v = np.array(voltage, dtype=np.float64)
    p = np.array(polarization, dtype=np.float64)

    v_max = _safe(np.max(v))
    v_min = _safe(np.min(v))
    pmax = _safe(np.max(p))
    pmin = _safe(np.min(p))

    # Remnant polarization: |P| at V≈0
    zero_idx = np.argsort(np.abs(v))[:8]
    p_near_zero = p[zero_idx]
    pr = _safe(np.mean(np.abs(p_near_zero)))

    pos_nz = p_near_zero[p_near_zero > 0]
    neg_nz = p_near_zero[p_near_zero < 0]
    pr_pos = _safe(np.mean(pos_nz)) if len(pos_nz) > 0 else None
    pr_neg = _safe(np.mean(np.abs(neg_nz))) if len(neg_nz) > 0 else None

    ec_pos, ec_neg = _find_coercive(v, p)

    # Saturation: P at max |V|
    top_idx = np.argsort(np.abs(v))[-10:]
    ps_pos = _safe(np.max(p[top_idx]))
    ps_neg = _safe(np.abs(np.min(p[top_idx])))
    loop_area = _loop_area(v, p)

    return {
        'pr': pr, 'pr_pos': pr_pos, 'pr_neg': pr_neg,
        'ec_pos': ec_pos, 'ec_neg': ec_neg,
        'pmax': pmax, 'pmin': pmin,
        'ps_pos': ps_pos, 'ps_neg': ps_neg,
        'loop_area': loop_area,
        'v_max': v_max, 'v_min': v_min,
        'data_points': len(v),
    }


def _find_coercive(v, p):
    ec_pos = None
    ec_neg = None
    for i in range(len(v) - 1):
        if p[i] * p[i + 1] <= 0 and p[i] != p[i + 1]:
            v_cross = v[i] + (v[i + 1] - v[i]) * (0 - p[i]) / (p[i + 1] - p[i])
            if v_cross > 0:
                if ec_pos is None or abs(v_cross) < abs(ec_pos):
                    ec_pos = abs(float(v_cross))
            else:
                if ec_neg is None or abs(v_cross) < abs(ec_neg):
                    ec_neg = abs(float(v_cross))
    return ec_pos, ec_neg


def _loop_area(v, p):
    try:
        x = np.array(v)
        y = np.array(p)
        return _safe(0.5 * np.abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))))
    except Exception:
        return None


def _empty():
    return {
        'pr': None, 'pr_pos': None, 'pr_neg': None,
        'ec_pos': None, 'ec_neg': None,
        'pmax': None, 'pmin': None,
        'ps_pos': None, 'ps_neg': None,
        'loop_area': None, 'v_max': None, 'v_min': None,
        'data_points': 0,
    }
