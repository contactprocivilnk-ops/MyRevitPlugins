# -*- coding: utf-8 -*-
"""Creates a structural grid layout from user-supplied coordinates -
numbered vertical grids (1, 2, 3, ...) and lettered horizontal grids
(A, B, C, ...) - and turns on the bubble at both ends of every grid in
the active view.

Vertical and horizontal X/Y lists are entered as comma-separated meters
through two native forms.ask_for_string dialogs. Each grid's extents are
derived automatically from the *other* axis's min/max, padded by 5 m so
every line clears the outermost intersection.

Coordinates are converted with UnitUtils, so the values stored in the
model are exact (no hardcoded foot multipliers).
"""

__title__ = "Create\nGrids"
__author__ = "Your Name"
__doc__ = "Creates a structural grid layout from user-supplied coordinates."

from pyrevit import revit, DB, forms

from Autodesk.Revit.DB import (
    UnitUtils, UnitTypeId, XYZ, Line, Grid, DatumEnds, Transaction,
    FilteredElementCollector, BuiltInParameter,
)

doc = revit.doc

DEFAULT_VERTICAL_X = "0, 3.13, 8.98, 13.18, 19.54, 22.67"
DEFAULT_HORIZONTAL_Y = "6.13, 11.53, 16.13, 22.13, 25.97, 30.57"

PADDING_M = 5.0


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def to_internal(value_m):
    """Convert a value in meters to Revit's internal decimal feet."""
    return UnitUtils.ConvertToInternalUnits(value_m, UnitTypeId.Meters)


def parse_coord_list(raw, field_name):
    """Parse a comma-separated string of meter values into a sorted list
    of floats. Raises ValueError with a user-facing message on bad input."""
    if raw is None or not raw.strip():
        raise ValueError("{0}: no coordinates were entered.".format(field_name))

    values = []
    for chunk in raw.split(","):
        text = chunk.strip()
        if not text:
            continue
        try:
            values.append(float(text.replace(",", ".")))
        except (ValueError, TypeError):
            raise ValueError(
                "{0}: '{1}' is not a valid number.".format(field_name, text))

    if not values:
        raise ValueError("{0}: no coordinates were entered.".format(field_name))

    values.sort()
    return values


def number_name(index):
    """0-based index -> '1', '2', '3', ..."""
    return str(index + 1)


def letter_name(index):
    """0-based index -> 'A', 'B', ..., 'Z', 'AA', 'AB', ... (Excel-style)."""
    n = index + 1
    letters = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def get_grid_name(grid):
    """Read a Grid's name through its parameter (safer than Element.Name
    across API versions)."""
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


def unique_name(base, taken):
    """Return 'base', or 'base (2)', 'base (3)'... if already used."""
    if base not in taken:
        return base
    counter = 2
    while "{0} ({1})".format(base, counter) in taken:
        counter += 1
    return "{0} ({1})".format(base, counter)


def set_grid_name_safely(grid, desired_name, taken_names):
    """Assign a name to a grid, resolving collisions instead of letting
    Revit's duplicate-name exception crash the script."""
    name = unique_name(desired_name, taken_names)
    try:
        grid.Name = name
    except Exception:
        # Fall back to whatever Revit assigned by default and keep going.
        name = get_grid_name(grid)
        name = unique_name(name, taken_names - {name})
    taken_names.add(name)
    return name


def show_both_bubbles(grid, view):
    try:
        grid.ShowBubbleInView(DatumEnds.End0, view)
    except Exception:
        pass
    try:
        grid.ShowBubbleInView(DatumEnds.End1, view)
    except Exception:
        pass


def create_grid_line(x1_m, y1_m, x2_m, y2_m):
    p1 = XYZ(to_internal(x1_m), to_internal(y1_m), 0.0)
    p2 = XYZ(to_internal(x2_m), to_internal(y2_m), 0.0)
    return Line.CreateBound(p1, p2)


# ----------------------------------------------------------------------------
# Input - sequential native pyRevit dialogs (no FlexForm, no WPF, no XAML)
# ----------------------------------------------------------------------------

def collect_inputs():
    """Ask for the vertical X list and horizontal Y list. Returns
    (x_raw, y_raw), or None if the user cancels either dialog."""
    x_raw = forms.ask_for_string(
        default=DEFAULT_VERTICAL_X,
        prompt="Vertical Grid X Coordinates (meters, comma-separated):",
        title="Create Grids - Step 1 of 2")
    if x_raw is None:
        return None

    y_raw = forms.ask_for_string(
        default=DEFAULT_HORIZONTAL_Y,
        prompt="Horizontal Grid Y Coordinates (meters, comma-separated):",
        title="Create Grids - Step 2 of 2")
    if y_raw is None:
        return None

    return x_raw, y_raw


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main():
    if doc is None or doc.IsFamilyDocument:
        forms.alert("Open a project document before running this tool.",
                    title="Wrong document type")
        return

    active_view = doc.ActiveView
    if active_view is None:
        forms.alert("There is no active view to show grid bubbles in.",
                    title="No active view")
        return

    try:
        inputs = collect_inputs()
    except Exception as ui_error:
        forms.alert("The input dialog could not be displayed.\n\n"
                    "{0}".format(ui_error), title="Input dialog failed")
        return

    if not inputs:
        return

    x_raw, y_raw = inputs

    try:
        x_values = parse_coord_list(x_raw, "Vertical Grid X Coordinates")
        y_values = parse_coord_list(y_raw, "Horizontal Grid Y Coordinates")
    except ValueError as input_error:
        forms.alert("{0}\n\nPlease enter numeric values and run the tool "
                    "again.".format(input_error), title="Invalid input")
        return

    # Each axis's line extent is padded off the *other* axis's min/max so
    # every grid clears the outermost intersection.
    y_start, y_end = y_values[0] - PADDING_M, y_values[-1] + PADDING_M
    x_start, x_end = x_values[0] - PADDING_M, x_values[-1] + PADDING_M

    existing_names = set(
        get_grid_name(g)
        for g in FilteredElementCollector(doc).OfClass(Grid).ToElements())

    transaction = Transaction(doc, "Create Complete Grids")
    transaction.Start()
    try:
        created = []

        for index, x in enumerate(x_values):
            line = create_grid_line(x, y_start, x, y_end)
            grid = Grid.Create(doc, line)
            final_name = set_grid_name_safely(
                grid, number_name(index), existing_names)
            show_both_bubbles(grid, active_view)
            created.append(final_name)

        for index, y in enumerate(y_values):
            line = create_grid_line(x_start, y, x_end, y)
            grid = Grid.Create(doc, line)
            final_name = set_grid_name_safely(
                grid, letter_name(index), existing_names)
            show_both_bubbles(grid, active_view)
            created.append(final_name)

        transaction.Commit()
    except Exception as error:
        if transaction.HasStarted() and not transaction.HasEnded():
            transaction.RollBack()
        forms.alert("Nothing was created - all changes were rolled back.\n\n"
                    "{0}".format(error), title="Grid creation failed")
        return

    forms.alert("Structural Grids Created Successfully!", title="Success")


if __name__ == "__main__":
    main()
