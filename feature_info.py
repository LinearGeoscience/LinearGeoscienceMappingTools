"""
Information text content for Linear Geoscience Mapping Tools features
This module contains all the "More Info" text content to keep mainplugin.py clean and maintainable
"""

# Data Management Section - Declination Adjuster
DECLINATION_ADJUSTER_INFO = """
<h1>Add/Subtract Declination</h1>
<p>A powerful tool for adjusting magnetic declination values in azimuth fields with comprehensive filtering and preview capabilities.</p>
<h2>Key Features:</h2>
<ul>
   <li><b>Add or Subtract:</b> Choose to add or subtract declination values from existing azimuth data.</li>
   <li><b>Automatic Modulo 360:</b> Results are automatically normalized to stay within 0-359 degree range.</li>
   <li><b>Live Preview:</b> See the first 100 changes before applying to verify calculations.</li>
   <li><b>Feature Selection Filter:</b> Apply changes only to selected features if needed.</li>
   <li><b>Date-Based Filtering:</b> Filter features by date field (Before/After/Date Range options).</li>
   <li><b>Null Value Protection:</b> Only updates non-null/non-empty values, preserving data integrity.</li>
</ul>
<h2>Common Use Cases:</h2>
<ul>
   <li><b>Correcting Magnetic Declination:</b> Apply declination corrections to field-collected magnetic bearings.</li>
   <li><b>Converting Between Systems:</b> Convert between magnetic and true north orientations.</li>
   <li><b>Temporal Corrections:</b> Apply different declination values to data collected at different times using date filters.</li>
   <li><b>Selective Updates:</b> Update only specific features or date ranges while leaving others unchanged.</li>
</ul>
<h2>Workflow:</h2>
<ol>
   <li><b>Select Layer:</b> Choose the layer containing azimuth/bearing data.</li>
   <li><b>Select Field:</b> Pick the numeric field containing azimuth values (0-360 degrees).</li>
   <li><b>Choose Operation:</b> Select Add or Subtract operation.</li>
   <li><b>Enter Declination:</b> Input the declination value (0-359 degrees).</li>
   <li><b>Apply Filters (Optional):</b>
       <ul>
           <li>Select specific features to update</li>
           <li>Filter by date field (before/after/range)</li>
       </ul>
   </li>
   <li><b>Preview Changes:</b> Review the first 100 calculated changes in the preview table.</li>
   <li><b>Apply:</b> Click Apply Changes to update the layer.</li>
</ol>
<h2>Date Filter Options:</h2>
<ul>
   <li><b>Before:</b> Update only features with dates before the specified date.</li>
   <li><b>After:</b> Update only features with dates after the specified date.</li>
   <li><b>Date Range:</b> Update only features within a specific date range.</li>
</ul>
<h2>Example Scenarios:</h2>
<p><b>Scenario 1 - Apply Modern Declination:</b><br>
Field data was collected using magnetic compass. Current declination is 15° East. Use "Add" operation with value 15 to convert all magnetic bearings to true north.</p>
<p><b>Scenario 2 - Temporal Correction:</b><br>
Historical data from 1990 had declination of 12° East, but current declination is 15° East. Use date filter "Before 1991-01-01" with "Add" operation and value 3 to update only the historical data.</p>
<p><b>Scenario 3 - Selective Update:</b><br>
Only update azimuth values for specific structures. Select those features in the map, check "Apply to selected features only", and apply the declination correction.</p>
<p><b>Safety Features:</b> The tool includes confirmation dialogs showing exactly how many features will be updated and what filters are active before making any changes to your data.</p>
"""

# Setup Mapping Section
INFO_SETUP_MAPPING = """
<h1>Setup Mapping Geopackage</h1>
<p>Setup the Mapping Geopackage Layers ready for <b>QField</b>.</p>
<ol>
<li>Import your Mapping Geopackage from the <b>Project Folder</b>.</li>
<li>Set the <b>Project CRS</b>.</li>
<li>Run the <b>Setup Mapping Geopackage</b> button and select your desired mapping scale:</li>
<ul>
<li>Mapping layers are set to the same as the <b>Project CRS</b>.</li>
<li>Sets the <b>Fixed Reference Scale</b> of each mapping layer.</li>
<li><b>Snapping settings</b> are set for each mapping layer.</li>
<li><b>Labelling distance function</b> is updated to match the chosen scale.</li>
</ul>
</ol>
"""

# Field Photos Section
INFO_GEOREFERENCE_PHOTOS = """
<h1>Georeference Field Photos</h1>
<h2>Field Procedure</h2>
<p>While mapping, record your field photos using the <b>PhotoID</b> field in <i>'1 - FieldNoteBook'</i> as per the following instructions:</p>
<ul>
   <li>Record the <b>last four digits</b> of each photo in the <b>PhotoID</b> field.<br>
   <i>Example:</i> DSC2345.jpg would be recorded as <b>'2345'</b>.</li>
   <li>You can record <b>multiple photos</b> in one point using <b>comma-separated values</b>.<br>
   <i>Example:</i> '2345, 2346, 2348'.</li>
   <li>If your <b>PhotoID's are sequential</b>, you can record a range of photos with the following logic:<br>
       <ul>
           <li><i>Example:</i> 2345, 2346, 2347 would be recorded as <b>'2345/7'</b>.</li>
           <li><i>Example:</i> 3899, 3900, 3901 would be recorded as <b>'3899/901'</b>.</li>
       </ul>
   </li>
   <li>You can also record a <b>combination of ranges and values</b>.<br>
   <i>Example:</i> '2345/7, 2349' would georeference 2345, 2346, 2347, and 2349.</li>
</ul>
<h2>Georeferencing Procedure</h2>
<ol>
   <li>Once mapping is completed, bring your <b>geopackage</b> back into your <b>QGis project</b>. Store field photos in a <b>relevant folder</b>.</li>
   <li>If multiple geologists have been mapping in the same geopackage, store each geologist's field photos in <b>separate folders</b> to prevent any overlap in <b>PhotoIDs</b>.</li>
   <li>Click the <b>'Georeference Field Photos'</b> button.</li>
   <li>A window will appear with each geologist involved in the mapping. Browse for the <b>photo folder</b> for each geologist.</li>
   <li>A <b>photo point layer</b> will be generated, along with a <b>photo table</b> containing:</li>
       <ul>
           <li><b>PhotoID's</b></li>
           <li><b>Eastings</b></li>
           <li><b>Northings</b></li>
           <li><b>Comments</b>, etc.</li>
       </ul>
   <li>Select the <b>photo points layer</b> in the <b>layer panel</b>, and turn on <b>'Map Tips'</b> (in the <i>Attributes toolbar</i>).</li>
   <li>When you hover over each photo point:
       <ul>
           <li>A <b>preview</b> will appear.</li>
           <li>A <b>slideshow</b> will be available for points with multiple photos.</li>
       </ul>
   </li>
</ol>
"""

INFO_VIEW_PHOTOS_PANEL = """
<h1>View Photos Panel</h1>
<p>The Photos Panel provides an interactive way to view and manage your georeferenced field photos:</p>
<ul>
   <li><b>First</b>, make sure you have run the <b>Georeference Field Photos</b> tool.</li>
   <li>The panel displays thumbnails of all georeferenced photos.</li>
   <li>You can filter photos by geologist.</li>
   <li>Click on any thumbnail to view the full-size photo.</li>
   <li>Use the zoom button on each thumbnail to zoom to its location on the map.</li>
   <li>The panel will remain open as you work with your project.</li>
</ul>
"""

INFO_EXPORT_PHOTOS = """
<h1>Export Field Photos</h1>
<p>Follow these steps to export georeferenced field photos:</p>
<ol>
   <li><b>First</b>, Georeference Field Photos.</li>
   <li>After the layers have been loaded into <b>QGis</b>, run this script to export the photos that were successfully georeferenced:</li>
       <ul>
           <li>The photos will be copied to your desired folder.</li>
           <li>A copy of the <b>PhotoTable.csv</b> will also be exported.</li>
       </ul>
</ol>
"""

# Data Management Section
INFO_HARDCODE_DATA = """
<h1>Hardcode Data & Update Legends</h1>
<p>After completing a stage of field mapping, it is good practice to backup certain fields and fill in legend codes before any modifications are made and before the data is exported to a master database or geopackage. This tool combines data hardcoding, legend filling, data-quality reporting and UUID checking in a single preview-then-commit workflow.</p>
<h2>What it does:</h2>
<ul>
   <li><b>Project Metadata:</b> Writes your <b>Project ID</b> and mapping <b>scale</b> to every selected layer. <b>MappedCRS</b> records each layer's own Coordinate System — the CRS its geometry and coordinates are actually stored in (a warning is shown if a layer's CRS differs from the project CRS).</li>
   <li><b>Coordinate Hardcoding (FieldNotebook):</b> Copies <b>Easting</b> and <b>Northing</b> into Mapped* backup fields. Where those columns are empty, the coordinates are <b>computed from the point's geometry</b> instead, so every feature ends up with retrievable coordinates. The <b>Structure Code (SubType1Code)</b> is also backed up.</li>
   <li><b>Field Backups (Basemap):</b> Copies <b>Lithology 1</b> and <b>Lithology 2</b> into Mapped* backup fields.</li>
   <li><b>Legend Filling:</b> Fills the FieldNotebook <b>Legend</b> field (from the <b>FieldNotebookCodes</b> table via Subtype1) and the Basemap <b>Description</b> field (from <b>BasemapCodes</b> via Lithology1). Codes missing from the lookup tables are listed so you can add them.</li>
   <li><b>UUID Checking:</b> Detects each layer's UUID column, <b>fills missing UUIDs</b>, and <b>reports duplicate UUIDs</b> (duplicates are never modified, as that could break links to photos and related tables).</li>
</ul>
<h2>Data Quality Report:</h2>
<p>The preview shows a per-layer table covering <b>every column</b>: how many cells are filled or missing, percentage complete, distinct value counts and sample values. Columns the tool will modify are highlighted.</p>
<h2>Update Modes:</h2>
<ul>
   <li><b>Empty cells only</b> (default) — preserves all existing data.</li>
   <li><b>Overwrite all cells</b> — refreshes everything, e.g. after a codes table changes.</li>
   <li><b>Selected features only</b> — restricts updates to the current selection.</li>
</ul>
<h2>Usage:</h2>
<ol>
   <li>Check the auto-matched layer and lookup-table selections, enter the Project ID and Mapped Scale.</li>
   <li>Click <b>Generate Preview</b> and review each layer's quality report and change list.</li>
   <li>Click <b>Commit Changes</b> to apply exactly what was previewed. Missing fields are created automatically.</li>
</ol>
<p><b>Important:</b> Run this procedure before modifying any mapping layers and before exporting to a master database.</p>
"""

INFO_RECONCILE = """
<h1>Reconcile / Merge Field Data</h1>
<p>A three-way merge between a working QField template and the master GeoPackage. Where the <b>Append Mapping Data</b> tool only ever <i>adds</i> new features, Reconcile also propagates <b>edits</b> and <b>deletes</b>, and lets you re-sync an edited template <b>without losing the edits</b>. Everything is previewed before anything is written.</p>
<h2>How it works:</h2>
<ul>
   <li><b>UUID identity:</b> features are matched by their <b>UUID</b> (never the per-file <b>fid</b>).</li>
   <li><b>Base snapshot:</b> a per-template snapshot is stored as the common ancestor. Working changes and master changes are both compared against it, so the tool can tell a genuine edit from an unchanged feature.</li>
   <li><b>Re-sync without loss:</b> after each accepted reconcile the base advances, so the next sync of the same template applies further edits as <b>updates</b> instead of silently skipping them.</li>
   <li><b>Conflicts:</b> when a feature was changed in <i>both</i> the master and the template, it is shown as a conflict and <b>left for manual handling</b> (it is not overwritten).</li>
</ul>
<h2>One-off setup:</h2>
<p>Click <b>Verify / migrate master</b> once per master GeoPackage. This adds the <code>lgs_*</code> tracking columns, backfills any missing UUIDs, verifies the UUID default expressions and records a baseline. It is safe to re-run.</p>
<h2>Usage:</h2>
<ol>
   <li>Select the <b>master GeoPackage</b> and the <b>working template</b>, and enter the <b>Mapper ID</b> (who collected the data).</li>
   <li>Click <b>Build preview</b> and review the adds / updates / deletes / conflicts per layer.</li>
   <li>Click <b>Apply reconcile</b> to commit the clean changes. Each layer is written in a single transaction; on any error that layer rolls back.</li>
</ol>
<p><b>Tip:</b> run <b>Hardcode Data & Update Legends</b> before reconciling, as you would before appending.</p>
"""

INFO_DECLINATION_ADJUSTER = """
<h1>Add/Subtract Declination</h1>
<p>A powerful tool for adjusting magnetic declination values in azimuth fields with comprehensive filtering and preview capabilities.</p>
<h2>Key Features:</h2>
<ul>
   <li><b>Add or Subtract:</b> Choose to add or subtract declination values from existing azimuth data.</li>
   <li><b>Automatic Modulo 360:</b> Results are automatically normalized to stay within 0-359 degree range.</li>
   <li><b>Live Preview:</b> See the first 100 changes before applying to verify calculations.</li>
   <li><b>Feature Selection Filter:</b> Apply changes only to selected features if needed.</li>
   <li><b>Date-Based Filtering:</b> Filter features by date field (Before/After/Date Range options).</li>
   <li><b>Null Value Protection:</b> Only updates non-null/non-empty values, preserving data integrity.</li>
</ul>
<h2>Common Use Cases:</h2>
<ul>
   <li><b>Correcting Magnetic Declination:</b> Apply declination corrections to field-collected magnetic bearings.</li>
   <li><b>Converting Between Systems:</b> Convert between magnetic and true north orientations.</li>
   <li><b>Temporal Corrections:</b> Apply different declination values to data collected at different times using date filters.</li>
   <li><b>Selective Updates:</b> Update only specific features or date ranges while leaving others unchanged.</li>
</ul>
<h2>Workflow:</h2>
<ol>
   <li><b>Select Layer:</b> Choose the layer containing azimuth/bearing data.</li>
   <li><b>Select Field:</b> Pick the numeric field containing azimuth values (0-360 degrees).</li>
   <li><b>Choose Operation:</b> Select Add or Subtract operation.</li>
   <li><b>Enter Declination:</b> Input the declination value (0-359 degrees).</li>
   <li><b>Apply Filters (Optional):</b>
       <ul>
           <li>Select specific features to update</li>
           <li>Filter by date field (before/after/range)</li>
       </ul>
   </li>
   <li><b>Preview Changes:</b> Review the first 100 calculated changes in the preview table.</li>
   <li><b>Apply:</b> Click Apply Changes to update the layer.</li>
</ol>
<h2>Date Filter Options:</h2>
<ul>
   <li><b>Before:</b> Update only features with dates before the specified date.</li>
   <li><b>After:</b> Update only features with dates after the specified date.</li>
   <li><b>Date Range:</b> Update only features within a specific date range.</li>
</ul>
<h2>Example Scenarios:</h2>
<p><b>Scenario 1 - Apply Modern Declination:</b><br>
Field data was collected using magnetic compass. Current declination is 15° East. Use "Add" operation with value 15 to convert all magnetic bearings to true north.</p>
<p><b>Scenario 2 - Temporal Correction:</b><br>
Historical data from 1990 had declination of 12° East, but current declination is 15° East. Use date filter "Before 1991-01-01" with "Add" operation and value 3 to update only the historical data.</p>
<p><b>Scenario 3 - Selective Update:</b><br>
Only update azimuth values for specific structures. Select those features in the map, check "Apply to selected features only", and apply the declination correction.</p>
<p><b>Safety Features:</b> The tool includes confirmation dialogs showing exactly how many features will be updated and what filters are active before making any changes to your data.</p>
"""

INFO_REPROJECT_GEOPACKAGE = """
<h1>Reproject GeoPackage</h1>
<p>Geopackages have a fixed <b>Coordinate Reference System (CRS)</b> when they are set up. This tool allows you to create a new GeoPackage with a different CRS while preserving all data and styling.</p>
<p><b>Why Reproject?</b></p>
<ul>
   <li>It is good practice to reproject your mapping geopackage if working in a significantly different CRS to your current mapping template.</li>
   <li>Reprojection is also useful when setting up a master geopackage to store data from multiple coordinate reference systems.</li>
</ul>
<h2>How to Reproject Your Mapping Template:</h2>
<ol>
   <li>Click the <b>'Reproject GeoPackage'</b> button.</li>
   <li>Select your input Geopackage template.</li>
   <li>Check the <b>'Reproject to new CRS'</b> box, then select your desired coordinate reference system.</li>
   <li>Select your output location and enter an output name for the new geopackage.</li>
   <li>Click <b>'Process'</b> to create the new GeoPackage.</li>
</ol>
<h2>After Reprojection:</h2>
<ul>
   <li>A new geopackage will be created with all layers from the original.</li>
   <li>All data will be correctly reprojected to the target CRS.</li>
   <li>All styling, including layer styles and categories, will be preserved.</li>
   <li>All non-spatial tables and attributes will be copied over exactly as they were.</li>
   <li>The new GeoPackage can be used immediately with all styling and configuration intact.</li>
</ul>
"""


INFO_APPEND_DATA = """
<h1>Enhanced GeoPackage Append Tool with Advanced Recoding</h1>
<p>A comprehensive tool for appending data between GeoPackage files with advanced recoding capabilities, duplicate detection, and data transformation features.</p>
<h2>Core Features:</h2>
<ul>
   <li><b>Layer Mapping:</b> Map source layers to different target layers in the master GeoPackage.</li>
   <li><b>Field Mapping:</b> Remap source fields to different field names in the target layer.</li>
   <li><b>Value Recoding:</b> Manually recode field values using lookup tables from master layers or attribute tables.</li>
   <li><b>Preserve Original Values:</b> Keep original values in separate fields while applying recodings.</li>
   <li><b>Global Date Filtering:</b> Filter records across all layers by date/time ranges.</li>
   <li><b>Duplicate Detection:</b> Intelligent duplicate analysis with visual indicators and date-based cutoff detection.</li>
   <li><b>UUID Field Detection:</b> Auto-detect UUID fields with fuzzy matching and manual override options.</li>
</ul>
<h2>Advanced Recoding Capabilities:</h2>
<ul>
   <li><b>Manual Value Mapping:</b> Create custom mappings for field values using dropdown interfaces.</li>
   <li><b>Lookup Table Integration:</b> Use existing master layers or attribute tables as value lookup sources.</li>
   <li><b>Visual Field Selection:</b> Integrated tree view for selecting layers, fields, and configuring recodings.</li>
   <li><b>Type Compatibility Checking:</b> Visual indicators for field type compatibility between source and master.</li>
   <li><b>Batch Configuration:</b> Configure multiple layers and fields simultaneously with visual feedback.</li>
</ul>
<h2>Workflow Process:</h2>
<ol>
   <li><b>File Selection:</b> Choose source and master GeoPackages with validation.</li>
   <li><b>Load & Analyze:</b> Automatically load layers, detect UUID fields, and analyze duplicates.</li>
   <li><b>Layer Configuration:</b> Select layers and configure target mapping, field mapping, and value recoding.</li>
   <li><b>Value Recoding Setup:</b> For each field requiring recoding:
       <ul>
           <li>Select a lookup table or layer from the master GeoPackage.</li>
           <li>Choose the value field to use for mapping.</li>
           <li>Manually map each unique source value to target values.</li>
           <li>Optionally preserve original values in separate fields.</li>
       </ul>
   </li>
   <li><b>Global Filtering:</b> Apply date/time filters across all layers if needed.</li>
   <li><b>Preview Changes:</b> Review detailed preview showing all transformations, mappings, and new records.</li>
   <li><b>Execute:</b> Apply changes with transaction safety and progress tracking.</li>
</ol>
<h2>Key Benefits:</h2>
<ul>
   <li><b>Data Standardization:</b> Harmonize field values across different data sources using lookup tables.</li>
   <li><b>Flexible Mapping:</b> Handle complex data integration scenarios with different schemas.</li>
   <li><b>Quality Control:</b> Preview all changes before committing to prevent data issues.</li>
   <li><b>Duplicate Management:</b> Intelligent handling of duplicate records with UUID tracking.</li>
   <li><b>Date-based Filtering:</b> Process only recent data or specific time ranges globally.</li>
   <li><b>Visual Feedback:</b> Clear indicators for configured recodings, duplicates, and mapping status.</li>
</ul>
<p><b>Use Cases:</b> Ideal for merging field mapping data from multiple sources, standardizing geological codes, harmonizing attribute values, and managing complex data integration workflows with different naming conventions and value systems.</p>
"""

# Structural Domains Section
INFO_CREATE_DOMAIN_LAYER = """
<h1>Create Domain Layer</h1>
<p>This process adds a temporary polygon layer to the project called <b>Domain</b>. The layer contains a single field named <b>Domain</b>.</p>
<h2>How to Use:</h2>
<ol>
   <li>To classify structural domains in the <b>FieldNotebook</b> layer:</li>
       <ul>
           <li>Draw polygons around your structural data.</li>
           <li>Use different domain names in the <b>Domain</b> field to properly classify the data.</li>
       </ul>
   </li>
   <li>Once the polygons are drawn and classified, select the <b>'Run Domain Classification'</b> button.</li>
   <li>This will hardcode the domain classifications into the <b>FieldNotebook</b> layer.</li>
</ol>
"""

INFO_RUN_DOMAIN_CLASSIFICATION = """
<h1>Run Domain Classification</h1>
<p>After creating your structural domain layer, use this process to hardcode the domains into the <b>FieldNotebook</b>.</p>
<h2>Steps:</h2>
<ol>
   <li>Ensure that your structural domain layer is complete and accurately classified.</li>
   <li>Run the <b>'Run Domain Classification'</b> process.</li>
   <li>The domains will be hardcoded into the <b>FieldNotebook</b>.</li>
   <li>Once hardcoded, you can compare structural domains by launching the inbuilt stereonet under the <b>'Domains'</b> tab.</li>
</ol>
"""

# Layout & Mapsheets Section
INFO_MAPSHEET_GENERATOR = """
<h1>Mapsheet Generator</h1>
<p>Generate systematic mapsheets for your geological mapping project with automatic grid creation and naming.</p>
<h2>Features:</h2>
<ul>
   <li>Creates a <b>regular grid</b> of mapsheets covering your area of interest.</li>
   <li>Automatically generates <b>systematic naming</b> for each mapsheet.</li>
   <li>Configurable <b>grid size</b> and <b>overlap</b> between adjacent sheets.</li>
   <li>Option to clip mapsheets to your <b>study area boundary</b>.</li>
   <li>Exports mapsheet <b>index layer</b> for reference and layout generation.</li>
</ul>
<h2>Workflow:</h2>
<ol>
   <li>Define your <b>area of interest</b> using a polygon layer or by drawing an extent.</li>
   <li>Configure mapsheet <b>dimensions</b> and <b>scale</b> requirements.</li>
   <li>Set <b>naming convention</b> and grid parameters.</li>
   <li>Generate the mapsheet grid and review coverage.</li>
   <li>Use the generated index with the <b>Create Layouts</b> tool for automated layout generation.</li>
</ol>
<p><b>Note:</b> The mapsheet generator creates the spatial framework for systematic mapping coverage.
Use this before running the Create Layouts tool for best results.</p>
"""

INFO_CREATE_LAYOUTS = """
<h1>Create Layouts</h1>
<p>Batch-generate print layouts from a mapsheet polygon layer and .qpt templates, with
automatic label population, legend cleanup, and optional export.</p>
<h2>Features:</h2>
<ul>
   <li><b>Label auto-population:</b> Set Item IDs in your template (title, author, drafter, map_number)
       and enter values in the panel — they are applied to every layout automatically.</li>
   <li><b>Legend automation:</b> Refreshes each legend to match visible layers, then removes
       layers you exclude via the layer checklist.</li>
   <li><b>Batch export:</b> Optionally export all generated layouts as georeferenced PDF,
       GeoTIFF (with world file), or PNG at a configurable DPI.</li>
   <li>Supports <b>portrait and landscape</b> templates selected per-feature via the polygon
       layer's <code>orientation</code> field.</li>
   <li>Configurable <b>map scale</b> and <b>buffer percentage</b>.</li>
   <li><b>Selective generation</b> for a specific range of features.</li>
</ul>
<h2>Workflow:</h2>
<ol>
   <li>Run the <b>Mapsheet Generator</b> first to create your mapsheet polygon layer
       (must have <code>name</code> and <code>orientation</code> fields).</li>
   <li>In your .qpt templates, set <b>Item IDs</b> on labels you want auto-filled
       (Layout Designer &rarr; Item Properties &rarr; Item ID).</li>
   <li>Open <b>Create Layouts</b>, select your polygon layer, templates, and fill in
       project info (name, author, drafter).</li>
   <li>Configure <b>legend settings</b> — uncheck layers to exclude from the legend.</li>
   <li>Optionally enable <b>export</b>, choose formats and output directory.</li>
   <li>Click <b>Generate Map Layouts</b>.</li>
</ol>
<p><b>Supported template label IDs:</b> <code>title</code>, <code>author</code>,
<code>drafter</code>, <code>map_number</code>. Labels using QGIS expressions
(date, scale, CRS) are left untouched.</p>
"""

# Declination Section
INFO_DECLINATION_CALCULATOR = """
<h1>Calculate Magnetic Declination (WMM)</h1>
<p>Calculate magnetic declination values for point features using the World Magnetic Model (WMM). This tool automatically transforms coordinates and calculates accurate declination values based on location, elevation, and date.</p>
<h2>Key Features:</h2>
<ul>
   <li><b>World Magnetic Model:</b> Uses the official WMM to calculate accurate declination values.</li>
   <li><b>Automatic CRS Transformation:</b> Converts from any coordinate system to WGS84 for calculations.</li>
   <li><b>Flexible Coordinate Input:</b> Use layer geometry or coordinate fields (Easting/Northing).</li>
   <li><b>Elevation Support:</b> Optional elevation field or default value for improved accuracy.</li>
   <li><b>Date Support:</b> Optional date field or default date for temporal declination calculation.</li>
   <li><b>Feature Selection Filter:</b> Calculate for all features or selected features only.</li>
   <li><b>Live Preview:</b> Preview declination values for the first 50 features before applying.</li>
   <li><b>Field Creation:</b> Automatically create a new declination field if needed.</li>
</ul>
<h2>Common Use Cases:</h2>
<ul>
   <li><b>Structural Data:</b> Calculate declination for each station point to later correct magnetic bearings.</li>
   <li><b>Historical Data:</b> Use date fields to calculate declination for data collected at different times.</li>
   <li><b>Multi-Region Projects:</b> Automatically handle different declination values across large study areas.</li>
   <li><b>Elevation Correction:</b> Improve accuracy for high-altitude or subsea measurements.</li>
</ul>
<h2>Workflow:</h2>
<ol>
   <li><b>Select Layer:</b> Choose the vector layer containing your point features.</li>
   <li><b>Coordinate Source:</b>
       <ul>
           <li>Use layer geometry (automatic) - Recommended for most cases</li>
           <li>Use coordinate fields - For layers with stored Easting/Northing values</li>
       </ul>
   </li>
   <li><b>Output Field:</b> Select an existing numeric field or create a new "Declination" field.</li>
   <li><b>Optional Parameters:</b>
       <ul>
           <li>Enable elevation field if available, or use default elevation (0m)</li>
           <li>Enable date field for temporal variations, or use current date</li>
       </ul>
   </li>
   <li><b>Feature Selection:</b> Optionally calculate for selected features only.</li>
   <li><b>Preview:</b> Click "Generate Preview" to see calculated values for first 50 features.</li>
   <li><b>Apply:</b> Click "Calculate and Apply" to write declination values to the layer.</li>
</ol>
<h2>Technical Details:</h2>
<ul>
   <li><b>CRS Handling:</b> The tool displays your layer's CRS and automatically transforms to EPSG:4326 (WGS84) for WMM calculations.</li>
   <li><b>Geometry Support:</b> Works with Point and MultiPoint geometries.</li>
   <li><b>Date Formats:</b> Automatically parses common date formats (YYYY-MM-DD, DD/MM/YYYY, etc.).</li>
   <li><b>Elevation Units:</b> Input elevation in meters; automatically converted to feet for WMM calculations.</li>
</ul>
<h2>Example Scenario:</h2>
<p><b>Correcting Field Structural Measurements:</b><br>
You have a layer of field stations with magnetic compass bearings collected in 2023. Calculate declination for each station point using the station coordinates and date. Then use the "Add/Subtract Declination" tool to apply these calculated values to your bearing measurements, converting them from magnetic to true north.</p>
<h2>Requirements:</h2>
<ul>
   <li><b>Layer Type:</b> Vector layer with point geometry or coordinate fields</li>
   <li><b>CRS:</b> Layer must have a valid Coordinate Reference System defined</li>
   <li><b>Output Field:</b> Existing numeric field or ability to create new field</li>
   <li><b>Python Library:</b> geomag library (installed in vendor folder)</li>
</ul>
<p><b>Note:</b> The World Magnetic Model is updated every 5 years by NOAA. The geomag library includes the latest WMM coefficients for accurate global declination calculations.</p>
"""

INFO_STATIC_MAPPING_EXPORT = """
<h1>Mapping Export</h1>
<p>Exports a whole mapping job in one run. The <b>core</b> export takes selected layers from your working GeoPackage into a clean, client-ready <b>Mapping.gpkg</b> &mdash; only <b>symbology and labelling</b> are carried across; field forms, constraints, and default values are stripped out. Optional sections bundle photos, sampling, the mapsheet grid, rasters, and structural data alongside it.</p>
<h2>How to Export:</h2>
<ol>
   <li>Click the <b>'Mapping Export'</b> button.</li>
   <li>(Core layers) Select your source GeoPackage and tick the layers to export. Names are auto-numbered (1_, 2_, ...) and can be edited. Set the post-processing options and <b>reference scale</b>.</li>
   <li>Tick any <b>additional exports</b> you want (they read from the current QGIS project).</li>
   <li>Choose a <b>parent folder</b> and export-folder name, then click <b>'Run Export'</b>.</li>
</ol>
<h2>Output folder (one per run):</h2>
<ul>
   <li><b>Mapping.gpkg</b> &mdash; the styled vector layers (core export).</li>
   <li><b>Photos/</b> &mdash; field photo points + table + a copy of every photo.</li>
   <li><b>Samples/</b> &mdash; the same, but only photos with Type = 'Sample' (optionally renamed by SampleID).</li>
   <li><b>Mapsheets.gpkg</b> &mdash; the mapsheet grid.</li>
   <li><b>Imagery.gpkg</b> &mdash; selected rasters (DEM / satellite / other), optionally reprojected.</li>
   <li><b>Layouts/</b> &mdash; selected finalised print layouts as PDF / GeoTIFF / PNG at the chosen DPI (georeferenced, with worldfiles).</li>
   <li><b>Structural/</b> &mdash; opens the Stereonet Export tab (Leapfrog + Stereonet11); choose a format and click Export there.</li>
</ul>
<h2>Post-Processing (core layers only):</h2>
<ul>
   <li><b>Remove unused symbology:</b> Category values with no matching features are pruned.</li>
   <li><b>Remove empty fields:</b> Fields where every value is NULL or blank are deleted. The primary key and fields used by symbology are kept.</li>
   <li><b>Reference scale:</b> The chosen fixed reference scale is set on each layer's renderer.</li>
</ul>
<p><b>Note:</b> The source GeoPackage and project layers are never modified.</p>
"""


# Symbology Section
INFO_RECODE_WORKFLOW = """
<h1>Recode & Restyle Wizard</h1>
<p>A guided wizard that combines three tools for efficiently recoding and restyling your mapping GeoPackage.</p>
<h2>Step 1: Update Code Tables</h2>
<ul>
   <li>Import a <b>CSV file</b> to update non-spatial code/lookup tables in your project.</li>
   <li><b>Export Template:</b> Save the current table as a CSV to use as a starting template.</li>
   <li><b>Append Mode:</b> Add new rows while keeping existing data (duplicates skipped by key).</li>
   <li><b>Replace Mode:</b> Clear the table and replace with CSV contents.</li>
   <li>Preview changes side-by-side before applying.</li>
</ul>
<h2>Step 2: Plot Symbol Features</h2>
<ul>
   <li>Creates <b>sample features</b> (one per category in each code table) so you can restyle symbology.</li>
   <li>Default mappings are provided for Overlay, Basemap, Linework, and FieldNotebook layers.</li>
   <li>Add or remove custom layer mappings as needed.</li>
   <li>After plotting, open the <b>Symbology</b> tab and click <b>Classify</b> to pick up the new categories.</li>
   <li>Previously plotted features can be removed with one click.</li>
</ul>
<h2>Step 3: Remove Unused Symbology</h2>
<ul>
   <li>Scans categorized layers for symbology categories that have <b>no matching features</b>.</li>
   <li>Preview how many categories will be removed before processing.</li>
   <li>Cleans up your layer styling by removing unused categories.</li>
</ul>
<h2>Typical Workflow:</h2>
<ol>
   <li>Update code tables with any new classifications (Step 1).</li>
   <li>Plot sample features so QGIS can classify the new codes (Step 2).</li>
   <li>Open the Symbology tab, click Classify, and style the new categories.</li>
   <li>Remove unused symbology categories to clean up (Step 3).</li>
   <li>Save styles as Default to the Datasource Database.</li>
</ol>
"""
