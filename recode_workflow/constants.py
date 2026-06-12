"""
Constants for the Recode & Restyle Workflow wizard.

Layer configuration, grid sizing, and page metadata.
"""

# Default layer-to-code-table mappings
# Format: { layer_name: (code_table_name, key_field_in_table, field_on_layer) }
LAYER_CONFIG = {
    '2 - Overlay':       ('OverlayCodes',       'Code', 'SubType1'),
    '4 - Basemap':       ('BasemapCodes',       'Code', 'Lithology1'),
    '3 - Linework':      ('LineworkCodes',       'Code', 'Type'),
    '1 - FieldNotebook': ('FieldNotebookCodes', 'Code', 'Subtype1'),
}

# Grid sizing — fixed values in map units (meters for projected CRS).
FEATURE_SIZE = 10
SPACING = 15
BLOCK_GAP = 200
ROW_WRAP_COUNT = 7

# Wizard page indices
PAGE_UPDATE_TABLES = 0
PAGE_PLOT_SYMBOLS = 1
PAGE_REMOVE_UNUSED = 2

# Page metadata: (title, subtitle)
PAGE_INFO = {
    PAGE_UPDATE_TABLES: (
        "Update Code Tables",
        "Import a CSV to append or replace rows in non-spatial code/lookup tables."
    ),
    PAGE_PLOT_SYMBOLS: (
        "Plot Symbol Features",
        "Create sample features for each code category so you can reclassify symbology."
    ),
    PAGE_REMOVE_UNUSED: (
        "Remove Unused Symbology",
        "Clean up categorized renderers by removing categories with no matching features."
    ),
}

LOG_TAG = "RecodeWorkflow"
