"""Technical content blocks for presenter.

Provides builders for waveform plots, LaTeX equations, and PVT/spec tables.
All builders return plain JSON-serializable dicts conforming to the presenter
shared block contract.
"""

from __future__ import annotations

from .equation import (
    build_equation,
    build_equation_from_sympy,
    latex_from_sympy,
    render_latex_to_png,
)
from .plot import (
    Figure,
    PlotTrace,
    build_plot,
    build_plot_from_arrays,
    build_plot_from_csv,
    build_waveform_plot,
    format_axis_label,
)
from .tables import (
    ColumnSpec,
    PVTCorner,
    SpecItem,
    build_pvt_table,
    build_spec_table,
    build_table,
    format_decimals,
    format_engineering,
    format_number,
    format_sigfigs,
)

__all__ = [
    # Figure & Plot
    "ColumnSpec",
    "Figure",
    "PVTCorner",
    "PlotTrace",
    "SpecItem",
    "build_equation",
    "build_equation_from_sympy",
    "build_plot",
    "build_plot_from_arrays",
    "build_plot_from_csv",
    "build_pvt_table",
    "build_spec_table",
    "build_table",
    "build_waveform_plot",
    "format_axis_label",
    "format_decimals",
    "format_engineering",
    "format_number",
    "format_sigfigs",
    "latex_from_sympy",
    "render_latex_to_png",
]
