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
<h1>Set Mapping Scale</h1>
<p>Setup the Mapping Geopackage Layers ready for <b>QField</b>.</p>
<ol>
<li>Import your Mapping Geopackage from the <b>Project Folder</b>.</li>
<li>Set the <b>Project CRS</b>.</li>
<li>Run the <b>Set Mapping Scale</b> button and select your desired mapping scale:</li>
<ul>
<li>Mapping layers are set to the same as the <b>Project CRS</b>.</li>
<li>Sets the <b>Fixed Reference Scale</b> of each mapping layer.</li>
<li><b>Snapping settings</b> are set for each mapping layer.</li>
<li><b>Labelling distance function</b> is updated to match the chosen scale.</li>
</ul>
</ol>
"""

INFO_COVER_OPACITY = """
<h1>Transported Cover Opacity</h1>
<p>Fades or hides <b>Transported Cover</b> polygons in the
<i>'4 - Basemap'</i> layer, so the bedrock and regolith geology mapped
beneath cover can be seen without deleting or re-styling anything.</p>
<ul>
<li>Each press steps around a four-rung ladder:
<b>100% &rarr; 50% &rarr; 25% &rarr; Hidden</b>, and the button label says
where it currently sits.</li>
<li><b>50% and 25%</b> fade every polygon whose <b>TypeLith1</b> is
<i>'Transported Cover'</i> (all the T-prefixed lithology codes), so the
cover reads as a wash over the geology beneath it. Their labels stay at
full strength.</li>
<li><b>Hidden</b> applies a layer filter instead — both the polygons
<b>and their labels</b> disappear.</li>
<li>Polygons with <b>no lithology type set</b> stay visible, so features
being digitised are never hidden.</li>
<li>Works alongside the <b>Pit/Underground Z filter</b> — the cover state
survives applying, changing and clearing elevation levels.</li>
<li>The state is carried into <b>QField exports</b>: the same four buttons
appear under <i>'4 - Basemap'</i> in the sidecar's Layer Opacity popup.</li>
</ul>
"""

# Field Photos Section
INFO_GEOREFERENCE_PHOTOS = """
<h1>Georeference Field Photos</h1>
<h2>Field Procedure</h2>
<p>While mapping, record your field photos using the <b>PhotoID</b> field in <i>'1 - FieldNotebook'</i> as per the following instructions:</p>
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
<p>A three-way merge between a working QField template and the master GeoPackage. Where the <b>Import Mapping Data</b> tool only ever <i>adds</i> new features, Reconcile also propagates <b>edits</b> and <b>deletes</b>, and lets you re-sync an edited template <b>without losing the edits</b>. Everything is previewed before anything is written.</p>
<h2>How it works:</h2>
<ul>
   <li><b>UUID identity:</b> features are matched by their <b>UUID</b> (never the per-file <b>fid</b>).</li>
   <li><b>Base snapshot:</b> a per-template snapshot is stored as the common ancestor. Working changes and master changes are both compared against it, so the tool can tell a genuine edit from an unchanged feature.</li>
   <li><b>Re-sync without loss:</b> after each accepted reconcile the base advances, so the next sync of the same template applies further edits as <b>updates</b> instead of silently skipping them.</li>
   <li><b>Field-level merge:</b> when a feature was edited on both sides but in <i>different</i> fields, the edits are combined automatically (shown under <b>Auto-merged</b>). Only a genuine same-field clash becomes a conflict.</li>
   <li><b>Conflict resolution:</b> for each real conflict choose <b>Field-merge</b> (keep both sides' independent edits, the template wins a true clash), <b>Take working</b> (the template's version), <b>Take master</b> or <b>Skip</b>. The clashing fields and their rival values are shown beneath each conflict. <i>Take master and Skip write nothing this sync; because the template still differs, the conflict re-appears next sync until the template itself is updated.</i></li>
   <li><b>Splits &amp; merges:</b> when one polygon becomes many (or many become one), the geometry overlap is detected and proposed for <b>confirm/reject</b>. On accept the lineage is recorded (<code>lgs_parent_uuid</code> / <code>lgs_merged_from</code>) and the parent's attributes are carried into the new feature's empty fields.</li>
   <li><b>Safe deletes:</b> every propagated delete is saved as a recoverable <b>tombstone</b> beside the master.</li>
   <li><b>Two people at once:</b> an advisory lock plus a master-version check stop two simultaneous reconciles from clashing; if the master moved since your preview you are asked to rebuild it.</li>
</ul>
<h2>One-off setup:</h2>
<p>Click <b>Verify / migrate master</b> once per master GeoPackage. This adds the <code>lgs_*</code> tracking columns, backfills any missing UUIDs, verifies the UUID default expressions and records a baseline. It is safe to re-run.</p>
<h2>Usage:</h2>
<ol>
   <li>Select the <b>master GeoPackage</b> and the <b>working template</b>, and enter the <b>Mapper ID</b> (who collected the data).</li>
   <li>Click <b>Build preview</b> and review the adds / updates / deletes / auto-merged / conflicts / splits / merges per layer.</li>
   <li><b>Click any feature</b> in the preview to zoom and flash it on the map — <b>amber = template version</b>, <b>grey = master version</b> — so you can see exactly which feature it is and what changed.</li>
   <li>Pick a resolution for any conflict and tick the splits / merges you want to accept.</li>
   <li>Click <b>Apply reconcile</b> to commit. Each layer is written in a single transaction; on any error that layer rolls back and keeps its previous base for a clean retry.</li>
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


INFO_IMPORT_DATA = """
<h1>Import Mapping Data</h1>
<p>Brings existing mapping into a current LGS template. Since Aug 2026 that is a migration rather than a copy: layers were renumbered, fields were added, and the code lists were audited &mdash; codes renamed, retired, and a whole <i>- Major</i>/<i>- Minor</i> convention replaced by the <b>Weight</b> field. This tool works all of that out for you and asks only where a real decision is needed.</p>
<p>It also handles the other direction: point it at a filtered layer already open in QGIS &mdash; a database subset, say &mdash; and it lands that in the mapping layers so it can be styled and viewed.</p>
<h2>The five steps</h2>
<ol>
   <li><b>What are you importing?</b> A GeoPackage, or layers open in QGIS (with their current filter and, if you want, just the selected features). Into this project, or into another GeoPackage. Both ends are read straight away and everything that can be matched is matched before you press Next.</li>
   <li><b>Which layers go where?</b> Matched on geometry first, then on the layer name (tolerating a different number in front of it) and on how much the two column sets overlap &mdash; which is what pairs <i>1_Structures</i> with <i>1 - FieldNotebook</i> despite the names sharing nothing. Code tables and styles are excluded.</li>
   <li><b>Which columns go where?</b> Identical names pair themselves; known renames such as <i>SubType1Code</i> &rarr; <i>MappedSubType1</i> are applied; anything else is offered as a suggestion to confirm. Retired free-text columns can be kept in Comments. The destination's own columns are never added to or altered.</li>
   <li><b>What do the old codes become?</b> Every distinct value of every coded column, with what it became and why: matched outright, matched through a rename (<i>FAP</i> is now <i>FAPL</i>), matched by name (<i>Hematite</i> is the code <i>Hem</i>), or split into a code plus a Weight (<i>Fault - Minor</i> becomes <i>Fault</i> with Weight <i>Minor</i>). Whatever is left gets an existing code, a brand-new code added to this project's code table, or a blank &mdash; your call, per value.</li>
   <li><b>Ready to import.</b> Everything that will happen, with blocking problems kept apart from things merely worth knowing. Save the decisions so the next import of the same shape is three clicks, or export them for a colleague.</li>
</ol>
<h2>What it does for you while writing</h2>
<ul>
   <li><b>Fills the template's own defaults.</b> Confidence, Weight, Intensity, the Basemap Description looked up from BasemapCodes, Easting/Northing, a UUID &mdash; all set the way the form would set them, so the symbology renders correctly instead of falling through to "other".</li>
   <li><b>Works out the group values.</b> Category, Type and TypeLith1 are derived from the code beneath them, so the cascading dropdowns work on imported features.</li>
   <li><b>Leaves the destination's schema alone.</b> No columns are added, ever. A column with nowhere to go is dropped or folded into Comments.</li>
   <li><b>Reprojects, and handles 3D.</b> Z values go into Elevation where the destination layer is 2D.</li>
   <li><b>Skips what is already there</b>, matched on UUID, including features you imported once and then deleted on purpose.</li>
   <li><b>Copies the destination first</b>, so any run can be undone by restoring that copy.</li>
</ul>
<p><b>Afterwards:</b> run <i>Hardcode Data &amp; Update Legends</i> to fill the Mapped* columns and legend text. If you added any new codes, run <i>Recode &amp; Restyle</i> so they get symbols.</p>
"""


INFO_MINING_IMPORT = """
<h1>Import Mining Survey Data</h1>
<p>Imports mine survey and design data — floor strings, drive pickups, survey stations and level triangulations — and merges it all into a single GeoPackage the <b>Z Filter</b> panel can drive. Built to be re-run: as each new survey drop arrives, it imports only what actually changed.</p>
<h2>How to Use:</h2>
<ol>
   <li>Click <b>'Import Mining Survey Data'</b>, then <b>'Add folder…'</b> to scan a folder of survey files (subfolders included), or <b>'Add files…'</b> to pick individual ones.</li>
   <li>Choose the output GeoPackage. Every discovered file is compared against what that GeoPackage already holds and tagged <b>New</b>, <b>Changed</b> or <b>Unchanged</b> — only new and changed files come pre-checked, so re-importing after a survey drop is a single click.</li>
   <li>The <b>Level</b> is read from the trailing digits of the filename (e.g. <i>mga_floor_1164.str</i> &rarr; 1164) and can be edited in the table.</li>
   <li>Confirm the CRS of the files (survey exports do not record one) and click <b>'Import'</b>.</li>
</ol>
<h2>What You Get:</h2>
<ul>
   <li><b>MineStrings</b> — linework with true 3D geometry, tagged with Level, string number, Z range, source file, surveyor and survey date.</li>
   <li><b>MineStations</b> — survey stations, pegs and pickups, each carrying <i>its own</i> point id, code, instrument and survey date rather than the string's.</li>
   <li><b>MineLevelOutlines</b> — where a file has a matching triangulation (<b>.dtm</b>) alongside it, the triangles are dissolved into a footprint polygon per level, which works well as a backdrop or clip shape.</li>
</ul>
<h2>Re-importing and Merging:</h2>
<p>The default policy is <b>replace each file's previous data</b>: re-importing a file removes exactly what that file contributed last time and writes it fresh, leaving every other file's data untouched. Strings that were deleted or renamed between surveys disappear correctly, and re-running an import never duplicates anything.</p>
<p>Other policies are available for particular situations — replace a whole level (when one level is assembled from several files that are always imported together), append only, or rebuild the layer from scratch.</p>
<h2>Good to Know:</h2>
<ul>
   <li><b>Z Filter ready:</b> the imported layers are picked up automatically; the <b>Level</b> field becomes the level label, while filtering uses the real elevations — so the nominal level name (e.g. 1164) need not match the actual Z values.</li>
   <li><b>Safe to interrupt:</b> new features are written <i>before</i> anything is removed, so a failure part-way can never leave you with the old data deleted and the new data missing. A backup of the GeoPackage is taken before each run.</li>
   <li><b>Provenance is recorded:</b> each import is logged inside the GeoPackage itself — which file, when, from where, and how many features — which is what lets the tool tell new work from work already done.</li>
   <li><b>Currently reads</b> Surpac strings (.str) and triangulations (.dtm). Further formats (DXF, CSV/XYZ pickups, and native strings from other mine packages) plug into the same merge and change-detection machinery.</li>
</ul>
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


# Pit / Underground Section
INFO_Z_FILTER = """
<h1>Z Filter — Level Mapping</h1>
<p>Filter the display of the standard mapping layers to a single bench or level elevation, for mapping in open pits and underground. All selected layers are filtered simultaneously, so the map only shows the level you are working on.</p>
<h2>Key Features:</h2>
<ul>
   <li><b>Multi-Layer Filtering:</b> FieldNotebook, Overlay, Linework and Basemap are filtered together with one control.</li>
   <li><b>Level &plusmn; Tolerance:</b> Shows features whose Elevation lies within the tolerance band around the chosen level (e.g. 1250 &plusmn; 5 m).</li>
   <li><b>Bench Stepping:</b> Step up/down through the known levels with one click as you move between benches.</li>
   <li><b>Level List from Data:</b> Harvest the distinct Elevation values already in your layers, or type a new level (e.g. a fresh bench RL) — it is remembered in the project.</li>
   <li><b>No-Elevation Features:</b> By default, features with an empty Elevation stay visible at every level (values are entered manually, so blanks are common). Untick the option for strict filtering.</li>
   <li><b>Safe &amp; Reversible:</b> Pre-existing layer filters are preserved and restored; the filter state is saved with the project.</li>
   <li><b>QField Companion:</b> The QField export ships a companion plugin so the same level switching works on the device in the field.</li>
</ul>
<h2>Workflow:</h2>
<ol>
   <li>Open the panel and confirm the four layer selections.</li>
   <li>Click <i>Refresh levels from data</i>, or type your first bench/level elevation.</li>
   <li>Set the tolerance to roughly half your bench height.</li>
   <li>Toggle the filter on and map; step levels as you move.</li>
   <li>Toggle off (or <i>Clear all filters</i>) to see everything again.</li>
</ol>
<p><b>Note:</b> Data is never modified or deleted — filtering only changes what is displayed. Tools that read whole tables (Reconcile, Append, exports) will offer to suspend the filter while they run.</p>
"""

INFO_ADD_ELEVATION = """
<h1>Add Elevation Field</h1>
<p>Adds the numeric <b>Elevation</b> field used by the Z Filter to the standard mapping layers of projects created before the field existed in the template.</p>
<h2>Key Features:</h2>
<ul>
   <li><b>Safe &amp; Idempotent:</b> Layers that already have the field are left untouched; nothing else is modified.</li>
   <li><b>Manual Entry:</b> The field has no default value — geologists enter the bench/level RL in the feature form while mapping.</li>
   <li><b>Edit-Session Aware:</b> Layers with unsaved edits are skipped with a warning (save first, then re-run).</li>
   <li><b>Custom Forms:</b> If a layer uses a drag-and-drop designer form, you are reminded to add the new field to the form manually.</li>
</ul>
<p><b>Note:</b> New projects created from the current mapping template already include the Elevation field on all four layers.</p>
"""

INFO_GENERATE_CONTOURS = """
<h1>Generate Contours</h1>
<p>Generate smooth, cartographically styled contour lines from a DEM raster (GeoTIFF and
similar). Unlike the built-in contour tools, the surface is smoothed and resampled before
tracing and each line is spline-fitted afterwards, so contours follow the terrain without
pixel stair-stepping.</p>
<h2>Features:</h2>
<ul>
   <li><b>Auto-suggested intervals:</b> A sensible minor interval and major (index) multiple
       are picked from the DEM's elevation range &mdash; override either in the dialog.</li>
   <li><b>Smoothing levels:</b> Off / Light / Medium / Strong control how much the surface is
       relaxed before contouring. Medium suits most 10&ndash;30&nbsp;m DEMs; Strong helps
       noisy data at the cost of positional fidelity.</li>
   <li><b>Cartographic styles:</b> <i>Subtle grey</i> (default) recedes behind geology
       colours; <i>Classic topo brown</i> gives a traditional sepia look. Major contours are
       heavier and carry curved elevation labels with a white halo; minors stay unlabelled.</li>
   <li><b>Self-contained output:</b> Contours are written to their own GeoPackage beside the
       DEM (never the mapping template), with the style embedded so it travels with the
       file.</li>
</ul>
<h2>Workflow:</h2>
<ol>
   <li>Load your DEM in the project (or Browse to the file directly).</li>
   <li>Accept or adjust the suggested minor interval and major multiple.</li>
   <li>Pick a smoothing level and colour scheme, then <b>Generate Contours</b>.</li>
   <li>The styled layer is added to the project when generation finishes.</li>
</ol>
<p><b>Note:</b> Elevation labels repeat about every 15&nbsp;cm of screen/paper at any zoom
&mdash; standard topographic-sheet behaviour. Re-running into the same GeoPackage replaces
the contour layer but leaves any other layers in that file alone.</p>
"""

INFO_VIEW_3D = """
<h1>View in 3D</h1>
<p>Open a 3D terrain view with your geological mapping draped on top &mdash; one click,
no configuration. The DEM is auto-detected (a pit-surface DEM is preferred when one
exists), becomes the project's terrain, and the native QGIS 3D view opens framed on your
current map extent.</p>
<h2>Features:</h2>
<ul>
   <li><b>Zero-config DEM choice:</b> a pinned project choice, then a Pit-Surface-to-DEM
       output, then Z-filter&ndash;tied rasters, then name hints (pit, bench, drone...).
       Only a genuinely ambiguous project asks you to pick.</li>
   <li><b>Vertical exaggeration:</b> live on/off toggle and factor (e.g. 2x) in the
       control panel &mdash; terrain height changes immediately in the open view.</li>
   <li><b>Detail control:</b> QGIS drapes the map as a texture on terrain tiles, and its
       default 512&nbsp;px tiles leave pit linework visibly smeared. <i>High</i> (the
       default here) uses 1024&nbsp;px tiles and tighter subdivision; <i>Ultra</i> doubles
       it again. Terrain geometry detail is capped at the DEM's own pixel size
       automatically.</li>
   <li><b>Pit mode:</b> frames the pit-surface DEM so mapping drapes onto bench faces
       and walls. The Z filter's bench subsetting carries into the 3D view
       automatically.</li>
   <li><b>Underground mode:</b> terrain is hidden and imported mine survey layers
       (MineStrings / MineStations) render at their true RL. Desktop only; exaggeration
       applies to terrain, not to these absolute-elevation layers.</li>
   <li><b>QField carries the same view:</b> the chosen DEM is written as the project
       terrain, and the QField export can bake it (with a chosen exaggeration) so
       QField 4.1+'s 3D map view works fully offline in the field.</li>
</ul>
<h2>Workflow:</h2>
<ol>
   <li>Load a DEM (or create one with <b>Pit Surface to DEM</b>).</li>
   <li>Click <b>View in 3D</b> &mdash; the 3D view opens with mapping draped.</li>
   <li>Adjust exaggeration or switch mode in the control panel as needed.</li>
</ol>
<p><b>Note:</b> the 3D view requires QGIS's 3D support (standard in OSGeo4W installs).
On devices, the 3D map view requires QField 4.1 or newer.</p>
"""

INFO_PIT_SURFACE_DEM = """
<h1>Pit Surface to DEM</h1>
<p>Rasterize a triangulated pit surface &mdash; a Surpac <code>.str</code>/<code>.dtm</code>
pair or a DXF with 3DFACE / polyface meshes &mdash; into a GeoTIFF DEM. The result is the
terrain the 3D view (and QField) drapes your mapping onto when no drone/photogrammetry
DEM exists.</p>
<h2>Features:</h2>
<ul>
   <li><b>True mesh sampling:</b> every pixel gets its elevation interpolated on the
       triangulation plane &mdash; bench crests, batters and toes are preserved at the
       chosen cell size, not stair-stepped from strings.</li>
   <li><b>Auto cell size:</b> defaults to half the median triangle edge, clamped to
       0.1&ndash;10&nbsp;m &mdash; override in the dialog.</li>
   <li><b>Self-registering output:</b> written beside the source as
       <code>&lt;name&gt;_dem.tif</code>, added to the project and tagged as a pit
       surface, so <b>View in 3D</b> and the QField export prefer it automatically.</li>
</ul>
<p><b>Note:</b> Surpac and DXF files carry no CRS &mdash; the project CRS is assumed,
matching the mining survey importer. Sources without a triangulation (strings only)
cannot make a DEM.</p>
"""
