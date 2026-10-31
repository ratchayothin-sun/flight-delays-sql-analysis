"""
04_charts.py
Build the README charts from results/*.csv (run run_analysis.py and 03_robustness.py first).

Chart rules (dataviz skill): one series = one colour, two series = palette slots 1-2 with a
legend, thin bars (<= 24 px) with rounded data-ends, hairline solid grid, value labels only
where the story is, text in ink colours (never the series colour). Titles are built from the
numbers in results/, so they stay true whichever file (sample or full) the analysis ran on.
If the analysis ran on the 3% sample, every chart says so in its footer.
Sizes are in logical px (100 dpi) and saved at 2x for sharp README images.
"""
import json
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon

ROOT = Path(__file__).resolve().parent
RES, OUT = ROOT / "results", ROOT / "charts"
OUT.mkdir(exist_ok=True)

SURFACE, INK, INK2, MUTED = "#fcfcfb", "#0b0b0b", "#52514e", "#898781"
GRID, AXIS = "#e1e0d9", "#c3c2b7"
BLUE, ORANGE = "#2a78d6", "#eb6834"  # categorical slots 1 and 2 (validated pair)

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Helvetica", "Arial", "DejaVu Sans"]
DPI = 100
PX = 0.72  # 1 logical px in points (1 px = 0.72 pt at 100 dpi)
LH = 18.8  # px per subtitle line (9.2 pt text at 1.45 line spacing)

INFO = json.loads((RES / "run_info.json").read_text())
OVERVIEW = pd.read_csv(RES / "q01_overview.csv").iloc[0]
SOURCE = (
    f"Source: Kaggle '2015 Flight Delays and Cancellations' (US Department of Transportation), "
    f"{int(OVERVIEW.scheduled_flights):,} scheduled domestic US flights in 2015. Late = arrived 15+ "
    f"minutes after schedule, counted among flights that were not cancelled or diverted."
)
if not INFO["is_full_file"]:
    SOURCE = ("PREVIEW ON A 3% SAMPLE - not the final numbers. " + SOURCE).replace(
        "3%", f"{INFO['thresholds']['scale'] * 100:.0f}%")

SHORT = {"WN": "Southwest", "DL": "Delta", "OO": "SkyWest", "EV": "Atlantic Southeast",
         "AA": "American", "UA": "United", "MQ": "American Eagle", "B6": "JetBlue",
         "US": "US Airways", "AS": "Alaska", "NK": "Spirit", "F9": "Frontier",
         "HA": "Hawaiian", "VX": "Virgin America"}
REGIONAL = {"OO", "EV", "MQ"}  # regional carriers flying under a bigger airline's brand
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def nice_axis(vmax, max_ticks=6):
    """(axis max, ticks) with round steps, leaving room for value labels."""
    for step in [0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100]:
        top = np.ceil(vmax * 1.12 / step) * step
        if top / step <= max_ticks:
            return top, [round(i * step, 4) for i in range(int(round(top / step)) + 1)]
    return vmax * 1.1, [0, vmax]


def prep(title, subtitle, sub_width=98, title_width=60):
    """Wrap title and subtitle; return them with the y (px) where the subtitle starts."""
    t = textwrap.fill(title, title_width)
    return t, textwrap.fill(subtitle, sub_width), 29 + 23 * (t.count("\n") + 1)


def header(fig, w, h, title, subtitle, top):
    fig.text(24 / w, 1 - 26 / h, title, fontsize=13.5, fontweight="bold", color=INK, va="top",
             linespacing=1.2)
    fig.text(24 / w, 1 - top / h, subtitle, fontsize=9.2, color=INK2, va="top", linespacing=1.45)
    fig.text(24 / w, 12 / h, textwrap.fill(SOURCE, 118), fontsize=7.2, color=MUTED, va="bottom",
             linespacing=1.4)


def rbar(ax, x_end, y_top, t, color, dpx, r=4):
    """Horizontal bar: square at the baseline (x=0), 4 px rounded at the data end."""
    if not x_end or x_end <= 0:
        return
    rx = min(r * dpx, x_end)
    th_a, th_b = np.linspace(-np.pi / 2, 0, 8), np.linspace(0, np.pi / 2, 8)
    cx, cy_top, cy_bot = x_end - rx, y_top + r, y_top + t - r
    pts = [(0, y_top)]
    pts += [(cx + rx * np.cos(a), cy_top + r * np.sin(a)) for a in th_a]
    pts += [(cx + rx * np.cos(a), cy_bot + r * np.sin(a)) for a in th_b]
    pts += [(0, y_top + t)]
    ax.add_patch(Polygon(pts, closed=True, facecolor=color, edgecolor="none", zorder=3))


def legend_row(fig, w, h, y_px, items, x=24.0):
    y = 1 - y_px / h
    for kind, color, label in items:
        hollow = kind == "hollow"
        fig.add_artist(Line2D([(x + 4) / w], [y], marker="o", markersize=8 * PX,
                              mfc=(SURFACE if hollow else color), mec=color,
                              mew=(2 * PX if hollow else 0), ls="none", transform=fig.transFigure))
        fig.text((x + 14) / w, y, label, fontsize=8.6, color=INK2, va="center")
        x += 14 + 6.2 * len(label) + 20


def hbar_chart(fname, title, subtitle, cats, series, xmax, xticks, ref=None, ref_label=None,
               subs=None, label_cats=None, w=760, bar_t=20, left_px=190,
               fmt="{v:.1f}%", xfmt="{t:g}%"):
    """series = [(name, values, colour), ...]; one series -> no legend box."""
    k, n = len(series), len(cats)
    gap = 2
    group_h = k * bar_t + (k - 1) * gap
    pitch = group_h + (22 if subs is not None else 20)
    title, sub, top = prep(title, subtitle)
    sub_lines = sub.count("\n") + 1
    left, right = left_px, 70
    plot_top = top + sub_lines * LH + 12 + (24 if k > 1 else 0) + (18 if ref else 6)
    plot_h = n * pitch
    h = int(plot_top + plot_h + 26 + 62)

    fig = plt.figure(figsize=(w / DPI, h / DPI), dpi=DPI, facecolor=SURFACE)
    header(fig, w, h, title, sub, top)
    ax = fig.add_axes([left / w, 1 - (plot_top + plot_h) / h, (w - left - right) / w, plot_h / h],
                      facecolor=SURFACE)
    ax.set_xlim(0, xmax)
    ax.set_ylim(plot_h, 0)  # y in px, top-down
    dpx = xmax / (w - left - right)  # data units per px
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_yticks([])
    ax.set_xticks(xticks)
    ax.set_xticklabels([xfmt.format(t=t) for t in xticks], fontsize=8.3, color=MUTED)
    ax.tick_params(axis="x", length=0, pad=8)
    for t in xticks:
        if ref is not None and abs(t - ref) < xmax * 0.025:  # the reference line replaces this gridline
            continue
        ax.axvline(t, color=GRID, lw=PX, zorder=0)
    ax.axvline(0, color=AXIS, lw=PX, zorder=1)
    if ref is not None:
        ax.axvline(ref, color=INK2, lw=PX, zorder=1)
        ax.text(ref, -7, ref_label or f"Overall {ref:.1f}%", ha="center", va="bottom",
                fontsize=8, color=INK2, clip_on=False)

    for i, cat in enumerate(cats):
        y0 = i * pitch + (pitch - group_h) / 2
        yc = y0 + group_h / 2
        if subs is not None:
            ax.text(-12 * dpx, yc - 6, cat, ha="right", va="center", fontsize=9.4, color=INK2,
                    clip_on=False)
            ax.text(-12 * dpx, yc + 8, subs[i], ha="right", va="center", fontsize=7.6, color=MUTED,
                    clip_on=False)
        else:
            ax.text(-12 * dpx, yc, cat, ha="right", va="center", fontsize=9.4, color=INK2,
                    clip_on=False)
        for j, (_, vals, color) in enumerate(series):
            v = vals[i]
            if pd.isna(v):
                continue
            yj = y0 + j * (bar_t + gap)
            rbar(ax, v, yj, bar_t, color, dpx)
            if label_cats is None or i in label_cats:
                ax.text(v + 7 * dpx, yj + bar_t / 2, fmt.format(v=v), ha="left", va="center",
                        fontsize=8.8, color=INK, clip_on=False, zorder=5,
                        bbox=dict(facecolor=SURFACE, edgecolor="none", pad=1.5))

    if k > 1:  # legend row (always present for >= 2 series)
        legend_row(fig, w, h, top + sub_lines * LH + 14, [("fill", c, nme) for nme, _, c in series])
    fig.savefig(OUT / fname, dpi=DPI * 2, facecolor=SURFACE)
    plt.close(fig)


def airline_forest(fname):
    """Fair comparison: gap to the other airlines on the same routes, with bootstrap intervals."""
    t = pd.read_csv(RES / "r01_fair_ci.csv").sort_values("diff_late_pp").reset_index(drop=True)
    better = int((t.late_clear == "better than others").sum())
    worse = int((t.late_clear == "worse than others").sum())
    n = len(t)
    title = (f"On the same routes, {worse} airlines run clearly later than their rivals "
             f"and {better} clearly earlier")
    title, sub, top = prep(title, (
        "Gap in the share of flights arriving 15+ min late versus all other airlines flying the same "
        "route in the same month, in percentage points, averaged over the airline's own flights "
        "(95% interval from resampling airport pairs). Negative = better than the others. Under each "
        "name: the share of the airline's flights that had a rival on the same route to compare with."))
    sub_lines = sub.count("\n") + 1
    w, pitch = 760, 32
    left, right = 215, 70
    plot_top = top + sub_lines * LH + 12 + 24 + 18
    plot_h = n * pitch
    h = int(plot_top + plot_h + 118)

    lo = min(t.late_lo.min(), t.diff_late_pp.min()) - 1.0
    hi = max(t.late_hi.max(), t.diff_late_pp.max()) + 1.5
    step = 5 if hi - lo > 22 else 2 if hi - lo > 10 else 1
    ticks = [x for x in range(int(np.floor(lo / step) * step), int(np.ceil(hi / step) * step) + 1, step)
             if lo <= x <= hi]
    fig = plt.figure(figsize=(w / DPI, h / DPI), dpi=DPI, facecolor=SURFACE)
    header(fig, w, h, title, sub, top)
    ax = fig.add_axes([left / w, 1 - (plot_top + plot_h) / h, (w - left - right) / w, plot_h / h],
                      facecolor=SURFACE)
    ax.set_xlim(lo, hi)
    ax.set_ylim(plot_h, 0)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_yticks([])
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{x:+g}" if x else "0" for x in ticks], fontsize=8.3, color=MUTED)
    ax.tick_params(axis="x", length=0, pad=8)
    for x in ticks:
        if x != 0:
            ax.axvline(x, color=GRID, lw=PX, zorder=0)
    ax.axvline(0, color=INK2, lw=PX, zorder=1)
    dpx = (hi - lo) / (w - left - right)

    for i, r in t.iterrows():
        yc = i * pitch + pitch / 2
        clear = r.late_clear != "not clearly different"
        c = BLUE if clear else MUTED
        ax.plot([r.late_lo, r.late_hi], [yc, yc], color=c, lw=2 * PX, solid_capstyle="round", zorder=3)
        ax.plot([r.diff_late_pp], [yc], marker="o", ms=9 * PX, mfc=(c if clear else SURFACE), mec=c,
                mew=(0 if clear else 2 * PX), ls="none", zorder=4, clip_on=False)
        ax.text(lo - 12 * dpx, yc - 5, SHORT.get(r.airline, r.airline), ha="right", va="center",
                fontsize=9.4, color=INK2, clip_on=False)
        tag = ("regional · " if r.airline in REGIONAL else "")
        ax.text(lo - 12 * dpx, yc + 8, f"{tag}{r.coverage_pct:.0f}% of flights compared", ha="right",
                va="center", fontsize=7.6, color=MUTED, clip_on=False)
        ax.text(r.late_hi + 8 * dpx, yc, f"{r.diff_late_pp:+.1f}", ha="left", va="center",
                fontsize=8.8, color=INK, clip_on=False, zorder=5,
                bbox=dict(facecolor=SURFACE, edgecolor="none", pad=1.5))  # keeps the 0 line off the number

    legend_row(fig, w, h, top + sub_lines * LH + 14,
               [("fill", BLUE, "Clearly different from the others (interval excludes 0)"),
                ("hollow", MUTED, "Cannot rule out no difference")])
    y_note = 1 - (plot_top + plot_h + 44) / h
    fig.text(left / w, y_note, "< earlier than the others", fontsize=8.2, color=MUTED, va="center")
    fig.text((w - right) / w, y_note, "later than the others >", fontsize=8.2, color=MUTED,
             va="center", ha="right")
    fig.savefig(OUT / fname, dpi=DPI * 2, facecolor=SURFACE)
    plt.close(fig)


def hour_chart(fname):
    d = pd.read_csv(RES / "q04_hourly.csv")
    d = d[d.scheduled_flights >= 0.005 * d.scheduled_flights.sum()].reset_index(drop=True)
    first, worst = d.iloc[0], d.loc[d.late_pct.idxmax()]
    hr = lambda x: f"{(int(x) % 12) or 12}{'am' if int(x) < 12 else 'pm'}"
    title = (f"A flight scheduled for {hr(worst.scheduled_hour)} is {worst.late_pct / first.late_pct:.1f}x as "
             f"likely to arrive late as one scheduled for {hr(first.scheduled_hour)}")
    title, sub, top = prep(title, (
        "By scheduled departure hour: the share of flights arriving 15+ min late, and the share of those late "
        "flights whose biggest cause was the same aircraft arriving late from its previous flight. Delays "
        "pile up as the day goes on. Hours with under 0.5% of all flights are left out."))
    sub_lines = sub.count("\n") + 1
    w = 760
    left, right = 52, 150
    plot_top = top + sub_lines * LH + 12 + 24 + 10
    plot_h = 250
    h = int(plot_top + plot_h + 28 + 62)
    ymax, yticks = nice_axis(max(d.late_pct.max(), d.late_aircraft_share_of_late_pct.max()))

    fig = plt.figure(figsize=(w / DPI, h / DPI), dpi=DPI, facecolor=SURFACE)
    header(fig, w, h, title, sub, top)
    ax = fig.add_axes([left / w, 1 - (plot_top + plot_h) / h, (w - left - right) / w, plot_h / h],
                      facecolor=SURFACE)
    x = d.scheduled_hour.to_numpy()
    ax.set_xlim(x.min() - 0.3, x.max() + 0.3)
    ax.set_ylim(0, ymax)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_yticks(yticks)
    ax.set_yticklabels([f"{v:g}%" for v in yticks], fontsize=8.3, color=MUTED)
    ax.tick_params(axis="y", length=0, pad=8)
    for v in yticks[1:]:
        ax.axhline(v, color=GRID, lw=PX, zorder=0)
    ax.axhline(0, color=AXIS, lw=PX, zorder=1)
    xt = [hh for hh in x if hh % 3 == 0]
    ax.set_xticks(xt)
    ax.set_xticklabels([hr(v) for v in xt], fontsize=8.3, color=MUTED)
    ax.tick_params(axis="x", length=0, pad=8)

    for col, color, name in [("late_pct", BLUE, "Arrived 15+ min late"),
                             ("late_aircraft_share_of_late_pct", ORANGE, "Of those, blamed on the previous flight")]:
        y = d[col].to_numpy()
        ax.plot(x, y, color=color, lw=2 * PX, solid_capstyle="round", solid_joinstyle="round", zorder=3)
        ax.plot([x[-1]], [y[-1]], marker="o", ms=8 * PX, mfc=color, mec=SURFACE, mew=2 * PX, ls="none",
                zorder=4, clip_on=False)
        ax.plot([x[0]], [y[0]], marker="o", ms=8 * PX, mfc=color, mec=SURFACE, mew=2 * PX, ls="none",
                zorder=4, clip_on=False)
        ax.text(x[-1] + 0.35, y[-1], f"{y[-1]:.0f}% at {hr(x[-1])}", va="center", ha="left", fontsize=8.8,
                color=INK, clip_on=False)
        k = int(np.argmax(y))
        if 0 < k < len(y) - 1:  # label the peak
            ax.text(x[k], y[k] + ymax * 0.035, f"{y[k]:.0f}%", va="bottom", ha="center", fontsize=8.8,
                    color=INK, clip_on=False)
        if col == "late_pct":  # and where the blue line starts
            ax.text(x[0] - 0.1, y[0] + ymax * 0.035, f"{y[0]:.0f}%", va="bottom", ha="left", fontsize=8.8,
                    color=INK, clip_on=False)
    legend_row(fig, w, h, top + sub_lines * LH + 14,
               [("fill", BLUE, "Arrived 15+ min late"),
                ("fill", ORANGE, "Share of late flights blamed on the previous flight")])
    fig.savefig(OUT / fname, dpi=DPI * 2, facecolor=SURFACE)
    plt.close(fig)


# ------------------------------------------------------------------ build charts
ov_late = float(OVERVIEW.late_pct)

# 1) raw airline ranking
a = pd.read_csv(RES / "q05_airline_raw.csv").sort_values("late_pct").reset_index(drop=True)
xmax, xt = nice_axis(a.late_pct.max())
hbar_chart(
    "01_airlines_raw.png",
    f"Taken at face value, {SHORT.get(a.airline.iloc[-1], a.airline.iloc[-1])} is late "
    f"{a.late_pct.iloc[-1] / a.late_pct.iloc[0]:.1f}x as often as {SHORT.get(a.airline.iloc[0], a.airline.iloc[0])}",
    "Share of completed flights that arrived 15+ min late, by airline, with no adjustment for routes, "
    "airports or season. Cancellations are shown under each name because a cancelled flight is never "
    "counted as late. The next chart compares airlines on the same routes instead.",
    [SHORT.get(c, c) for c in a.airline], [("Arrived 15+ min late", a.late_pct.tolist(), BLUE)],
    xmax=xmax, xticks=xt, ref=ov_late, ref_label=f"All airlines {ov_late:.1f}%",
    subs=[f"{c:.1f}% cancelled · avg trip {d:,.0f} mi" for c, d in zip(a.cancel_pct, a.avg_distance_mi)],
    label_cats={0, 1, len(a) - 2, len(a) - 1}, left_px=250,
)

# 2) fair comparison with intervals
airline_forest("02_airlines_fair.png")

# 3) months
m = pd.read_csv(RES / "q02_monthly.csv")
m["late_of_scheduled"] = m.problem_pct - m.cancel_pct - m.divert_pct  # late flights / all scheduled flights
m["cancel_or_divert"] = m.cancel_pct + m.divert_pct
w_i = m.problem_pct.idxmax()
xmax, xt = nice_axis(m[["late_of_scheduled", "cancel_or_divert"]].max().max())
hbar_chart(
    "03_months.png",
    f"{MONTHS[int(m.month[w_i]) - 1]} was the worst month: {m.problem_pct[w_i]:.0f}% of scheduled flights "
    f"were late, cancelled or diverted",
    "Share of all scheduled flights that arrived 15+ min late, and that were cancelled or diverted, by month "
    "of 2015. Both use all scheduled flights as the base so the two bars can be added.",
    MONTHS,
    [("Arrived 15+ min late", m.late_of_scheduled.tolist(), BLUE),
     ("Cancelled or diverted", m.cancel_or_divert.tolist(), ORANGE)],
    xmax=xmax, xticks=xt, label_cats={int(m.problem_pct.idxmax()), int(m.problem_pct.idxmin())},
    left_px=70,
)

# 4) time of day
hour_chart("04_time_of_day.png")

# 5) causes
c = pd.read_csv(RES / "q10_causes_overall.csv")
c["share_pct"] = 100 * c.minutes / c.minutes.sum()  # from minutes, not from the rounded column
c = c.sort_values("share_pct", ascending=False).reset_index(drop=True)
pc = pd.read_csv(RES / "q11_primary_cause.csv").set_index("primary_cause").share_pct
key = lambda s: next(k for k in ["Late aircraft", "Airline", "Air system", "Weather", "Security"] if s.startswith(k))
pct = lambda v: f"{v:.0f}%" if v >= 1 else f"{v:.1f}%"
xmax, xt = nice_axis(c.share_pct.max())
hbar_chart(
    "05_delay_causes.png",
    f"{key(c.cause[0])} and {key(c.cause[1]).lower()} problems cause most of the lost minutes; "
    f"extreme weather only {c.share_pct[c.cause.map(key) == 'Weather'].iloc[0]:.0f}%",
    "Share of all delay minutes on flights that arrived 15+ min late, by the cause the airlines reported. "
    "Late aircraft = the plane's previous flight arrived late. Airline = crew, maintenance, cleaning, "
    "fuelling. Air system = air traffic control, airport congestion and non-extreme weather. Weather = "
    "extreme weather, as judged by the airline. Under each name: the share of late "
    "flights where it was the single biggest cause (ties are left out, so shares do not add to 100%).",
    [key(x) for x in c.cause], [("Share of delay minutes", c.share_pct.tolist(), BLUE)],
    xmax=xmax, xticks=xt, left_px=230,
    subs=[f"biggest cause of {pct(pc.get(key(x), 0))} of late flights" for x in c.cause],
)

# 6) worst days
dd = pd.read_csv(RES / "q16_daily.csv")
dd = dd[dd.scheduled_flights >= 0.5 * dd.scheduled_flights.median()].nlargest(10, "cancel_pct").reset_index(drop=True)
dd["label"] = [f"{t.strftime('%a')} {t.day} {t.strftime('%b')}" for t in pd.to_datetime(dd.flight_date)]  # no %-d (Windows)
xmax, xt = nice_axis(dd[["cancel_pct", "late_pct"]].max().max())
hbar_chart(
    "06_worst_days.png",
    f"The {len(dd)} days with the most cancellations: up to {dd.cancel_pct.max():.0f}% of flights cancelled",
    "Share of scheduled flights cancelled, and of completed flights that arrived 15+ min late, on the days "
    "with the highest cancellation rate (days with fewer than half the usual number of flights are skipped).",
    dd.label.tolist(),
    [("Cancelled", dd.cancel_pct.tolist(), BLUE), ("Arrived 15+ min late", dd.late_pct.tolist(), ORANGE)],
    xmax=xmax, xticks=xt, left_px=110, label_cats={0, 1, 2},
)

# 7) airports
ap = pd.read_csv(RES / "q07_airport_departures.csv").sort_values("departed_late_pct", ascending=False)
n_big = len(ap)
show = pd.concat([ap.head(10), pd.DataFrame([{"airport": "", "city": ""}]), ap.tail(10)], ignore_index=True)
cats = [("" if not a_ else f"{a_} · {c_}") for a_, c_ in zip(show.airport, show.city)]
subs = ["" if pd.isna(s) else f"{int(s):,} departures · {cr:.1f}% cancelled"
        for s, cr in zip(show.scheduled_departures, show.cancel_pct)]
xmax, xt = nice_axis(ap.departed_late_pct.max())
hbar_chart(
    "07_airports.png",
    f"Departure delays by airport: the 10 worst and 10 best of {n_big} large airports",
    f"Share of departures that left 15+ min after schedule, for airports with at least "
    f"{INFO['thresholds']['min_airport']:,} scheduled departures. Departure delay is used because an arrival "
    f"delay also reflects the airport you left. Flights from airports whose October code could not be rebuilt "
    f"are not counted.",
    cats, [("Departed 15+ min late", show.departed_late_pct.tolist(), BLUE)],
    xmax=xmax, xticks=xt, subs=subs, left_px=220, label_cats={0, 1, 2, 18, 19, 20},
)

print("charts written:", sorted(p.name for p in OUT.glob("*.png")))
