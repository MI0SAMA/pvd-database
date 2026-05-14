"""
PE Loop plotter v2 - uses corrected column mapping from processor.
"""
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import streamlit as st

from processor.parse import parse_hysteresis


@st.cache_data
def plot_pe_loop(filepath, sample_id=""):
    """
    Generate PE hysteresis loop from raw data.
    Uses corrected Drive Voltage (col2) vs Polarization (col3).
    """
    try:
        hdata = parse_hysteresis(filepath)
    except Exception:
        fig, ax = plt.subplots(figsize=(6, 5))
        ax.text(0.5, 0.5, "Parse Error", ha="center", va="center", transform=ax.transAxes)
        return fig

    if len(hdata.voltage) < 10:
        fig, ax = plt.subplots(figsize=(6, 5))
        ax.text(0.5, 0.5, "No Data", ha="center", va="center", transform=ax.transAxes)
        return fig

    v = hdata.voltage
    p = hdata.polarization
    tp = hdata.test_params

    fig, ax = plt.subplots(figsize=(6, 5))
    ax.plot(v, p, "b-", linewidth=1.0, alpha=0.85)
    ax.axhline(y=0, color="gray", linewidth=0.5, linestyle="--")
    ax.axvline(x=0, color="gray", linewidth=0.5, linestyle="--")
    ax.set_xlabel("Voltage (V)")
    ax.set_ylabel("Polarization (uC/cm2)")

    # Build informative title
    title = sample_id
    if tp.get('test_voltage'):
        title += " | {:.0f}V".format(float(tp['test_voltage']))
    if tp.get('period_ms'):
        freq = 1000.0 / float(tp['period_ms']) / 2.0
        title += " | {:.0f}Hz".format(freq)
    if tp.get('profile'):
        title += " | {}".format(tp['profile'])
    ax.set_title(title, fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


@st.cache_data
def plot_pe_loops_multi(filepaths, labels=None):
    """Overlay multiple PE loops for comparison."""
    fig, ax = plt.subplots(figsize=(8, 6))
    colors = plt.cm.tab10(range(len(filepaths)))

    for i, fp in enumerate(filepaths):
        try:
            hdata = parse_hysteresis(fp)
        except Exception:
            continue
        if len(hdata.voltage) < 10:
            continue
        label = labels[i] if labels and i < len(labels) else "C{}".format(i + 1)
        ax.plot(hdata.voltage, hdata.polarization, color=colors[i],
                linewidth=1.0, alpha=0.8, label=label)

    ax.axhline(y=0, color="gray", linewidth=0.5, linestyle="--")
    ax.axvline(x=0, color="gray", linewidth=0.5, linestyle="--")
    ax.set_xlabel("Voltage (V)")
    ax.set_ylabel("Polarization (uC/cm2)")
    ax.set_title("PE Loop Comparison")
    ax.legend(fontsize=8, loc="lower right")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig
