"""
Constants for the Recode & Restyle Workflow wizard.

Layer configuration, grid sizing, and page metadata.
"""
try:
    from ..lgs_layers import BASEMAP, FIELDNOTEBOOK, LINEWORK, OVERLAY
except ImportError:
    from lgs_layers import BASEMAP, FIELDNOTEBOOK, LINEWORK, OVERLAY

# Default layer-to-code-table mappings
# Format: { layer_name: (code_table_name, key_field_in_table, field_on_layer) }
# Keyed by the canonical names; look up with lgs_layers.lookup() so a layer
# carrying pre-Aug-2026 numbering still resolves.
LAYER_CONFIG = {
    OVERLAY:       ('OverlayCodes',       'Code', 'SubType1'),
    BASEMAP:       ('BasemapCodes',       'Code', 'Lithology1'),
    LINEWORK:      ('LineworkCodes',      'Code', 'Type'),
    FIELDNOTEBOOK: ('FieldNotebookCodes', 'Code', 'Subtype1'),
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
