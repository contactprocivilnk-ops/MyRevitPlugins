# -*- coding: utf-8 -*-
"""Creates a stack of Levels from metric input and a matching Structural Plan
view for each one.

Inputs are collected with pyRevit's native, WPF/XAML-free dialogs
(forms.ask_for_string, asked sequentially). No FlexForm, no custom WPF
Window, no .xaml resource is involved anywhere in this script - that was the
cause of the blank white window some environments were hitting.

Elevations are entered in METERS and converted with UnitUtils, so the values
stored in the model are exact.
"""

__title__ = "Level +\nStruct Plan"
__author__ = "Your Name"
__doc__ = ("Creates evenly spaced Levels from metric input and a Structural "
           "Plan view for each level.")

from pyrevit import revit, DB, forms, script

doc = revit.doc
output = script.get_output()

MAX_LEVELS = 200

DEFAULTS = {
    "base_elev": "0.0",
    "floor_height": "3.2",
    "floor_count": "4",
    "name_prefix": "Level",
}


# ----------------------------------------------------------------------------
# Units
# ----------------------------------------------------------------------------

def to_internal_feet(meters):
    """Convert meters to Revit's internal decimal feet.

    UnitTypeId is the Revit 2021+ API. DisplayUnitType was removed in later
    releases (it is already gone in 2027), so the legacy call is only attempted
    if the enum actually exists.
    """
    if hasattr(DB, "UnitTypeId"):
        return DB.UnitUtils.ConvertToInternalUnits(meters, DB.UnitTypeId.Meters)
    if hasattr(DB, "DisplayUnitType"):
        return DB.UnitUtils.ConvertToInternalUnits(
            meters, DB.DisplayUnitType.DUT_METERS)
    raise RuntimeError("This Revit version exposes neither UnitTypeId nor "
                       "DisplayUnitType; cannot convert units safely.")


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------

def alert(message, title="Level Generator", exit_script=False):
    """forms.alert, with a Revit TaskDialog fallback if the WPF layer is broken."""
    try:
        forms.alert(message, title=title, exitscript=exit_script)
        return
    except Exception:
        pass
    try:
        from Autodesk.Revit.UI import TaskDialog
        TaskDialog.Show(title, message)
    except Exception:
        print("{0}: {1}".format(title, message))
    if exit_script:
        script.exit()


def get_name(element):
    """Return an element's name.

    Element.Name is shadowed by the base class under the IronPython engine, so
    a plain attribute read returns nothing useful for Level / View /
    ViewFamilyType. Read the underlying parameter instead.
    """
    if element is None:
        return "<none>"
    for bip in (DB.BuiltInParameter.VIEW_NAME,
                DB.BuiltInParameter.DATUM_TEXT,
                DB.BuiltInParameter.SYMBOL_NAME_PARAM):
        try:
            param = element.get_Parameter(bip)
            if param and param.AsString():
                return param.AsString()
        except Exception:
            pass
    try:
        return DB.Element.Name.GetValue(element)
    except Exception:
        return "<unnamed>"


def id_value(element_id):
    """ElementId.IntegerValue was removed in Revit 2024 in favour of .Value."""
    value = getattr(element_id, "Value", None)
    if value is None:
        value = getattr(element_id, "IntegerValue", None)
    return value


def unique_name(base, taken):
    """Return 'base', or 'base (2)', 'base (3)'... if already used."""
    if base not in taken:
        return base
    counter = 2
    while "{0} ({1})".format(base, counter) in taken:
        counter += 1
    return "{0} ({1})".format(base, counter)


def parse_float(raw, field):
    try:
        return float(str(raw).strip().replace(",", "."))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("{0}: '{1}' is not a valid number.".format(field, raw))


def parse_int(raw, field):
    text = str(raw).strip()
    try:
        value = float(text.replace(",", "."))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("{0}: '{1}' is not a valid whole number.".format(field, raw))
    if abs(value - int(value)) > 1e-9:
        raise ValueError("{0}: '{1}' must be a whole number.".format(field, raw))
    return int(value)


def get_structural_plan_type():
    """Return the first Structural Plan ViewFamilyType, or None."""
    collector = DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
    for vft in collector:
        if vft.ViewFamily == DB.ViewFamily.StructuralPlan:
            return vft
    return None


# ----------------------------------------------------------------------------
# Input - sequential native pyRevit dialogs (no FlexForm, no WPF, no XAML)
# ----------------------------------------------------------------------------

def collect_inputs():
    """Collect the three required values with plain forms.ask_for_string
    dialogs, asked one after another. Returns a dict, or None if the user
    cancels any one of them (so the caller can exit cleanly)."""
    base_elev = forms.ask_for_string(
        default=DEFAULTS["base_elev"],
        prompt="Base Level Elevation (meters):",
        title="Level Generator - Step 1 of 3")
    if base_elev is None:
        return None

    floor_height = forms.ask_for_string(
        default=DEFAULTS["floor_height"],
        prompt="Typical Floor Height (meters):",
        title="Level Generator - Step 2 of 3")
    if floor_height is None:
        return None

    floor_count = forms.ask_for_string(
        default=DEFAULTS["floor_count"],
        prompt="Number of Floors:",
        title="Level Generator - Step 3 of 3")
    if floor_count is None:
        return None

    return {
        "base_elev": base_elev,
        "floor_height": floor_height,
        "floor_count": floor_count,
        "name_prefix": DEFAULTS["name_prefix"],
    }


# ----------------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------------

def build_entries(values):
    """Turn raw form strings into a validated [(name, elevation_m)] list."""
    base_elev = parse_float(values.get("base_elev"), "Base level elevation")
    floor_height = parse_float(values.get("floor_height"), "Typical floor height")
    floor_count = parse_int(values.get("floor_count"), "Total number of floors")
    prefix = (values.get("name_prefix") or DEFAULTS["name_prefix"]).strip()

    if not prefix:
        prefix = DEFAULTS["name_prefix"]
    if floor_count < 1:
        raise ValueError("Total number of floors must be at least 1.")
    if floor_count > MAX_LEVELS:
        raise ValueError("Total number of floors is capped at {0}.".format(MAX_LEVELS))
    if floor_count > 1 and abs(floor_height) < 1e-6:
        raise ValueError("Typical floor height cannot be zero - every level "
                         "would land on the same elevation.")

    entries = []
    for step in range(floor_count):
        elevation = base_elev + (step * floor_height)
        entries.append(("{0:02d} - {1}".format(step, prefix), elevation))
    return entries


# ----------------------------------------------------------------------------
# Model creation
# ----------------------------------------------------------------------------

def create_levels_and_plans(entries):
    """Create every level and its Structural Plan. Returns report rows."""
    used_level_names = set(
        get_name(lvl)
        for lvl in DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements())

    used_view_names = set()
    levels_with_plan = set()
    for view in DB.FilteredElementCollector(doc).OfClass(DB.View).ToElements():
        used_view_names.add(get_name(view))
        if isinstance(view, DB.ViewPlan) and not view.IsTemplate:
            gen_level = view.GenLevel
            # A Structural Plan reports its ViewType as EngineeringPlan.
            if gen_level is not None and view.ViewType == DB.ViewType.EngineeringPlan:
                levels_with_plan.add(id_value(gen_level.Id))

    plan_type = get_structural_plan_type()
    if plan_type is None:
        alert("This project has no Structural Plan view type, so no plan views "
              "will be created.\n\nThe levels will still be generated.",
              title="Structural Plan type missing")

    rows = []
    transaction = DB.Transaction(doc, "Create Levels and Structural Plans")
    transaction.Start()
    try:
        for raw_name, elev_m in entries:
            elev_ft = to_internal_feet(elev_m)
            level = DB.Level.Create(doc, elev_ft)

            level_name = unique_name(raw_name, used_level_names)
            try:
                level.Name = level_name
            except Exception:
                level_name = get_name(level)   # keep Revit's default name
            used_level_names.add(level_name)

            plan_name = "-"
            if plan_type is not None and id_value(level.Id) not in levels_with_plan:
                try:
                    plan = DB.ViewPlan.Create(doc, plan_type.Id, level.Id)
                    plan_name = unique_name(level_name, used_view_names)
                    try:
                        plan.Name = plan_name
                    except Exception:
                        plan_name = get_name(plan)
                    used_view_names.add(plan_name)
                except Exception as plan_error:
                    plan_name = "FAILED: {0}".format(plan_error)

            rows.append([level_name,
                         "{0:.3f}".format(elev_m),
                         "{0:.6f}".format(elev_ft),
                         plan_name])

        transaction.Commit()
    except Exception:
        if transaction.HasStarted() and not transaction.HasEnded():
            transaction.RollBack()
        raise

    return rows


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------

def main():
    if doc is None or doc.IsFamilyDocument:
        alert("Open a project document before running this tool.",
              title="Wrong document type", exit_script=True)
        return

    try:
        values = collect_inputs()
    except Exception as ui_error:
        alert("The input dialog could not be displayed.\n\n{0}".format(ui_error),
              title="Input dialog failed", exit_script=True)
        return

    if not values:
        script.exit()
        return

    try:
        entries = build_entries(values)
    except ValueError as input_error:
        alert("{0}\n\nPlease enter numeric values and run the tool "
              "again.".format(input_error), title="Invalid input")
        return

    try:
        rows = create_levels_and_plans(entries)
    except Exception as model_error:
        alert("Nothing was created - all changes were rolled back.\n\n"
              "{0}".format(model_error), title="Level creation failed")
        return

    output.print_md("### Created {0} level(s)".format(len(rows)))
    output.print_table(
        table_data=rows,
        columns=["Level", "Elevation (m)", "Internal (ft)", "Structural Plan"])

    failures = len([row for row in rows if row[3].startswith("FAILED")])
    summary = "{0} level(s) created.\n{1} structural plan(s) created.".format(
        len(rows), len(rows) - failures)
    if failures:
        summary += "\n{0} plan(s) failed - see the output window.".format(failures)
    alert(summary, title="Done")


if __name__ == "__main__":
    main()