"""
Raw data parser for Radiant Precision ferroelectric tester .txt files.

Data columns (tab-separated):
  col 0: Point
  col 1: Time (ms)
  col 2: Drive Voltage (V)        ← X axis for PE loop
  col 3: Measured Polarization    ← Y axis for PE loop
  col 4: Capacitance (uF)
  col 5: Normalized Capacitance
  col 6: Dielectric Constant
  col 7: Instantaneous Current (mA)

Header metadata includes test voltage, frequency, profile type, etc.
"""
import re
import zipfile
import numpy as np
from collections import namedtuple

HysteresisData = namedtuple('HysteresisData',
    ['voltage', 'polarization', 'time', 'capacitance', 'current', 'test_params'])


def read_file_bytes(filepath):
    if '.zip/' in filepath:
        zip_path, inner_path = filepath.split('.zip/', 1)
        zip_path += '.zip'
        with zipfile.ZipFile(zip_path, 'r') as z:
            return z.read(inner_path)
    else:
        with open(filepath, 'rb') as f:
            return f.read()


def parse_test_params(text_lines):
    """Extract test parameters from the header section."""
    params = {}
    key_map = {
        'Task Name:': 'task_name',
        'Volts:': 'test_voltage',
        'Field:': 'test_field_kvcm',
        'DCBias:': 'dc_bias',
        'DCField:': 'dc_field_kvcm',
        'Hysteresis Period (ms):': 'period_ms',
        'Profile:': 'profile',
        'Preset:': 'preset',
        'Preset Delay (ms):': 'preset_delay_ms',
        'Sample Area (cm2):': 'sample_area_cm2',
        'Sample Thickness (microns):': 'sample_thickness_um',
        'Tester Name:': 'tester_name',
    }
    for line in text_lines:
        if re.match(r'^\s*\d+\t', line):
            break  # reached data section
        for key, name in key_map.items():
            if key in line:
                val = line.split('\t')[-1].strip()
                try:
                    params[name] = float(val)
                except ValueError:
                    params[name] = val
    return params


def parse_hysteresis(filepath):
    """
    Parse a Radiant hysteresis .txt file.
    Returns HysteresisData with correct voltage (col2) and polarization (col3).
    """
    raw = read_file_bytes(filepath)
    try:
        text = raw.decode('gbk')
    except (UnicodeDecodeError, LookupError):
        text = raw.decode('latin-1', errors='ignore')

    lines = text.split('\n')
    test_params = parse_test_params(lines)

    voltages = []
    polarizations = []
    times = []
    capacitances = []
    currents = []

    for line in lines:
        line = line.strip()
        if not line or not re.match(r'^\s*\d+\t', line):
            continue
        parts = line.split('\t')
        if len(parts) >= 8:
            try:
                times.append(float(parts[1]))
                voltages.append(float(parts[2]))       # Drive Voltage
                polarizations.append(float(parts[3]))   # Measured Polarization
                capacitances.append(float(parts[4]))    # Capacitance
                currents.append(float(parts[7]))        # Instantaneous Current
            except (ValueError, IndexError):
                continue

    return HysteresisData(
        voltage=np.array(voltages),
        polarization=np.array(polarizations),
        time=np.array(times),
        capacitance=np.array(capacitances),
        current=np.array(currents),
        test_params=test_params,
    )


def parse_filename(filename):
    m = re.match(r'(\d+)#[（(](\d+)-(\d+)[）)]\.txt$', filename)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return None
