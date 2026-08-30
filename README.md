# MyRevitPlugins (pyRevit Extension)

Custom pyRevit automation tools designed for Autodesk Revit (2024 - 2027) to streamline structural modeling workflows.

## Features
- **Levels & Structural Plans Generator:** Dynamically creates project levels and corresponding structural plan views from interactive prompts.
- **Parametric Grid Generator:** Generates full 2D grid systems with automatic extents, metric precision conversion (`UnitUtils`), and dual bubble visibility on all ends.
- **Grid Auditor:** Computes exact 2D analytical intersection coordinates $(X, Y)$ for automated column placement and QA/QC verification.

## Installation
1. Install [pyRevit](https://github.com/pyrevitlabs/pyRevit).
2. Download or clone this repository.
3. Copy the `MyTools.extension` directory into your pyRevit extensions folder:
   `%APPDATA%\pyRevit\Extensions\`
4. In Revit, navigate to `pyRevit` tab and click **Reload**.

## Tech Stack
- Autodesk Revit API
- IronPython / pyRevit
