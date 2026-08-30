# -*- coding: utf-8 -*-
"""BIM Auditor - reads every Grid in the active document and reports all
pairwise intersections as candidate column locations, ready for an
upcoming automated column-placement tool.

Intersections are computed with pure 2D analytical geometry (the classic
determinant line-line intersection formula) instead of Revit's
Curve.Intersect, whose 'out' parameter binding is unreliable under
IronPython and can silently return zero intersections even when grids
clearly cross. Coordinates are converted from internal decimal feet to
meters with UnitUtils for clear engineering reporting.
"""

__title__ = "Grid\nAuditor"
__author__ = "Your Name"
__doc__ = ("Extracts grid intersections (candidate column locations) and "
           "reports them in the pyRevit output window.")

import itertools

from pyrevit import revit, script, forms

from Autodesk.Revit.DB import (
    UnitUtils, UnitTypeId, Grid, FilteredElementCollector, BuiltInParameter,
)

doc = revit.doc
output = script.get_output()

PARALLEL_TOLERANCE = 1e-6


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def get_grid_name(grid):
    """Read a Grid's name through its parameter (safer than Element.Name
    across API versions/engines)."""
    try:
        param = grid.get_Parameter(BuiltInParameter.DATUM_TEXT)
        if param and param.AsString():
            return param.AsString()
    except Exception:
        pass
    try:
        return grid.Name
    except Exception:
        return "<unnamed>"


def get_grid_endpoints(grid):
    """Return (name, x1, y1, x2, y2) for a grid's curve endpoints, in
    internal decimal feet."""
    curve = grid.Curve
    pt0 = curve.GetEndPoint(0)
    pt1 = curve.GetEndPoint(1)
    return get_grid_name(grid), pt0.X, pt0.Y, pt1.X, pt1.Y


def intersect_lines_2d(x1, y1, x2, y2, x3, y3, x4, y4):
    """Pure 2D analytical intersection of the infinite lines through
    (x1, y1)-(x2, y2) and (x3, y3)-(x4, y4). Returns (ix, iy), or None if
    the lines are parallel (or coincident)."""
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < PARALLEL_TOLERANCE:
        return None

    a = x1 * y2 - y1 * x2
    b = x3 * y4 - y3 * x4

    ix = (a * (x3 - x4) - (x1 - x2) * b) / denom
    iy = (a * (y3 - y4) - (y1 - y2) * b) / denom
    return ix, iy


def to_meters(value_ft):
    """Convert internal decimal feet to meters."""
    return UnitUtils.ConvertFromInternalUnits(value_ft, UnitTypeId.Meters)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    if doc is None:
        forms.alert("No active document to audit.", title="No document")
        return

    grids = list(
        FilteredElementCollector(doc)
        .OfClass(Grid)
        .WhereElementIsNotElementType()
        .ToElements())
    total_grids = len(grids)

    grid_endpoints = []
    for grid in grids:
        try:
            grid_endpoints.append(get_grid_endpoints(grid))
        except Exception:
            continue

    intersections = []
    for grid_a, grid_b in itertools.combinations(grid_endpoints, 2):
        name_a, x1, y1, x2, y2 = grid_a
        name_b, x3, y3, x4, y4 = grid_b

        point = intersect_lines_2d(x1, y1, x2, y2, x3, y3, x4, y4)
        if point is None:
            continue

        ix, iy = point
        intersections.append({
            "grid_a": name_a,
            "grid_b": name_b,
            "x": to_meters(ix),
            "y": to_meters(iy),
        })

    intersections.sort(key=lambda item: (item["grid_a"], item["grid_b"]))

    output.print_md("# BIM Auditor - Grid Intersection Report")
    output.print_md("**Total Grids Found:** {0}".format(total_grids))
    output.print_md("**Total Intersections Found (Candidate Column "
                     "Locations):** {0}".format(len(intersections)))

    if not intersections:
        output.print_md("_No grid intersections were found in this model._")
        return

    rows = []
    for item in intersections:
        rows.append([
            item["grid_a"],
            item["grid_b"],
            "{0:.3f}".format(item["x"]),
            "{0:.3f}".format(item["y"]),
        ])

    output.print_table(
        table_data=rows,
        title="Grid Intersections",
        columns=["Grid A", "Grid B", "X (m)", "Y (m)"])


if __name__ == "__main__":
    main()
