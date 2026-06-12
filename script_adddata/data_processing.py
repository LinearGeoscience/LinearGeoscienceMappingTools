#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Data processing worker thread with UUID tracking integration.

This module handles:
- Preview generation with enhanced statistics (up to 1000 records)
- Layer creation and appending with UUID tracking
- Temporal overlap detection
- Metadata logging
"""

import os
import uuid as uuid_module
from datetime import datetime, timezone

# DEBUG: Enable detailed logging
DEBUG_UUID_PROCESSING = False

def debug_log(message: str):
    """Log debug message if debugging is enabled"""
    if DEBUG_UUID_PROCESSING:
        QgsMessageLog.logMessage(f"[DEBUG] {message}", 'Linear Geoscience', Qgis.Info)
from typing import Dict, List, Optional
from qgis.PyQt.QtCore import QThread, pyqtSignal, QVariant
from qgis.core import (QgsVectorLayer, QgsFeature, QgsVectorFileWriter,
                       QgsField, QgsCoordinateTransform, QgsProject,
                       QgsFields, QgsFeatureRequest, QgsMessageLog, Qgis)
from .utils import (LayerRecoding, is_date_field, find_matching_field, to_python_datetime, NO_UUID_FIELD,
                    FILTER_TYPE_AFTER, FILTER_TYPE_BEFORE, FILTER_TYPE_BETWEEN)
from .metadata import UUIDTracker, MetadataManager


class WorkerThread(QThread):
    """
    Worker thread to handle data processing tasks without freezing the GUI.

    Enhanced with:
    - UUID tracking via JSON file
    - Metadata logging
    - Enhanced preview (up to 1000 records)
    - Temporal overlap detection
    """

    update_progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)
    preview_ready = pyqtSignal(dict)

    def __init__(self, source_gpkg: str, master_gpkg: str, uuid_field: str = "UUID",
                 selected_layers: Optional[List[str]] = None,
                 field_selections: Optional[Dict] = None,
                 uuid_field_map: Optional[Dict] = None,
                 layer_crs_map: Optional[Dict] = None,
                 layer_recodings: Optional[Dict] = None,
                 global_date_filter: Optional[Dict] = None,
                 preview_only: bool = False):
        QThread.__init__(self)
        self.source_gpkg = source_gpkg
        self.master_gpkg = master_gpkg
        self.default_uuid_field = uuid_field
        self.selected_layers = selected_layers or []
        self.field_selections = field_selections or {}
        self.uuid_field_map = uuid_field_map or {}
        self.layer_crs_map = layer_crs_map or {}
        self.layer_recodings = layer_recodings or {}
        self.global_date_filter = global_date_filter
        self.preview_only = preview_only
        self.abort = False

        # Initialize UUID tracker and metadata manager
        self.uuid_tracker = UUIDTracker(master_gpkg) if master_gpkg else None
        self.metadata_manager = MetadataManager(master_gpkg) if master_gpkg else None

    def run(self):
        """Main thread execution"""
        try:
            if self.preview_only:
                self.generate_preview()
            else:
                self.process_layers()
        except Exception as e:
            import traceback
            self.finished.emit(False, f"Error: {str(e)}\nTraceback: {traceback.format_exc()}")

    def generate_preview(self):
        """
        Generate enhanced preview data without making actual changes.

        Enhanced to:
        - Collect up to 1000 sample records (vs. 10 before)
        - Include comprehensive statistics
        - Detect temporal overlaps
        - Show UUID tracker statistics
        """
        preview_data = {}

        for layer_name in self.selected_layers:
            if self.abort:
                return

            self.update_progress.emit(0, f"Generating preview for layer: {layer_name}")

            # Get recoding configuration
            recoding = self.layer_recodings.get(layer_name, LayerRecoding())
            target_layer_name = recoding.target_layer or layer_name

            # Open source layer
            source_uri = f"{self.source_gpkg}|layername={layer_name}"
            source_layer = QgsVectorLayer(source_uri, layer_name, "ogr")

            if not source_layer.isValid():
                continue

            # Get UUID field
            uuid_field = self.uuid_field_map.get(layer_name, self.default_uuid_field)
            selected_fields = self.field_selections.get(layer_name, [])

            # Check if "No UUID" mode is enabled
            no_uuid_mode = (uuid_field == NO_UUID_FIELD or not uuid_field)

            # Check master layer
            master_uri = f"{self.master_gpkg}|layername={target_layer_name}"
            master_layer = QgsVectorLayer(master_uri, target_layer_name, "ogr")

            # Get existing UUIDs from BOTH master layer AND UUID tracker
            existing_uuids = set()
            master_record_count = 0

            if master_layer.isValid():
                master_record_count = master_layer.featureCount()
                if not no_uuid_mode:
                    uuid_field_in_master = find_matching_field(
                        [f.name() for f in master_layer.fields()], uuid_field
                    )
                    if uuid_field_in_master:
                        # Provider-side DISTINCT - avoids iterating every master feature
                        master_uuid_idx = master_layer.fields().lookupField(uuid_field_in_master)
                        if master_uuid_idx >= 0:
                            existing_uuids.update(
                                str(v) for v in master_layer.uniqueValues(master_uuid_idx) if v)

            # CRITICAL: Also check UUID tracker for deleted/merged features (only if UUID mode)
            if self.uuid_tracker and not no_uuid_mode:
                tracked_uuids = self.uuid_tracker.get_layer_uuids(target_layer_name)
                existing_uuids.update(tracked_uuids)
                self.update_progress.emit(0,
                    f"Found {len(tracked_uuids)} tracked UUIDs (includes deleted/merged features)")
            elif no_uuid_mode:
                self.update_progress.emit(0,
                    f"No UUID mode - all features will be added without duplicate checking")

            # Collect preview data
            total_records = source_layer.featureCount()
            new_records = 0
            duplicate_records = 0
            sample_records = []
            source_date_range = [None, None]
            master_date_range = [None, None]

            # BUG 5 fix: Find date field for range tracking
            preview_date_field = None
            for field in source_layer.fields():
                if is_date_field(field):
                    preview_date_field = field.name()
                    break

            # BUG 5 fix: Get master date range
            if master_layer.isValid() and preview_date_field:
                master_date_field = find_matching_field(
                    [f.name() for f in master_layer.fields()], preview_date_field
                )
                if master_date_field:
                    master_date_idx = master_layer.fields().lookupField(master_date_field)
                    date_request = (QgsFeatureRequest()
                                    .setFlags(QgsFeatureRequest.NoGeometry)
                                    .setSubsetOfAttributes([master_date_idx]))
                    master_dates = []
                    for mf in master_layer.getFeatures(date_request):
                        dv = mf[master_date_idx]
                        if dv:
                            pdt = to_python_datetime(dv)
                            if pdt:
                                master_dates.append(pdt)
                    if master_dates:
                        master_date_range = [min(master_dates).strftime("%Y-%m-%d %H:%M"),
                                             max(master_dates).strftime("%Y-%m-%d %H:%M")]

            # DEBUG: Track unique UUIDs in source for accurate counting
            seen_source_uuids = set()
            debug_log(f"=== PREVIEW for layer: {layer_name} -> {target_layer_name} ===")
            debug_log(f"Total features in source: {total_records}")
            debug_log(f"UUID field: {uuid_field}")
            debug_log(f"No UUID mode: {no_uuid_mode}")
            if not no_uuid_mode:
                debug_log(f"Existing UUIDs count (master + tracker): {len(existing_uuids)}")
                if existing_uuids:
                    debug_log(f"Sample existing UUIDs: {list(existing_uuids)[:5]}")

            # Apply global date filter if enabled
            # Preview only needs attributes, never geometry
            feature_request = QgsFeatureRequest().setFlags(QgsFeatureRequest.NoGeometry)
            date_filter_applied = False
            filter_expression = None
            if self.global_date_filter and self.global_date_filter.get('enabled'):
                filter_expression = self.build_global_date_filter_expression(source_layer)
                if filter_expression:
                    feature_request.setFilterExpression(filter_expression)
                    date_filter_applied = True
                    self.update_progress.emit(0, f"Applying date filter: {filter_expression}")

            # Collect up to 1000 sample records (NEW: was 10 before)
            feature_iterator = source_layer.getFeatures(feature_request)
            sample_limit = 1000
            collected_samples = 0

            # DEBUG: Track reasons for duplicates
            duplicate_in_master = 0
            duplicate_in_source = 0
            no_uuid_count = 0

            source_dates_collected = []

            for feature in feature_iterator:
                # BUG 5 fix: track source date range
                if preview_date_field:
                    date_val = feature[preview_date_field]
                    if date_val:
                        pdt = to_python_datetime(date_val)
                        if pdt:
                            source_dates_collected.append(pdt)

                # Handle "No UUID" mode - all features are new
                if no_uuid_mode:
                    is_duplicate = False
                    record_status = "New"
                    new_records += 1
                else:
                    feature_uuid = str(feature[uuid_field]) if feature[uuid_field] else None

                    # DEBUG: Detailed tracking
                    # Determine record status for accurate counting
                    if not feature_uuid:
                        no_uuid_count += 1
                        # Features without UUID will be SKIPPED - don't count as new
                        is_duplicate = True  # Treat as "not addable" for counting purposes
                        record_status = "No UUID"
                    elif feature_uuid in existing_uuids:
                        duplicate_in_master += 1
                        is_duplicate = True
                        record_status = "Duplicate"
                    elif feature_uuid in seen_source_uuids:
                        duplicate_in_source += 1
                        is_duplicate = True  # FIX: Count as duplicate if already seen in source
                        record_status = "Duplicate"
                    else:
                        is_duplicate = False
                        seen_source_uuids.add(feature_uuid)  # FIX: Track seen UUIDs
                        record_status = "New"

                    if is_duplicate:
                        duplicate_records += 1
                    else:
                        new_records += 1

                # Collect sample (up to 1000)
                if collected_samples < sample_limit:
                    record_data = {
                        "status": record_status,  # Use detailed status: "New", "Duplicate", or "No UUID"
                        "values": {},
                        "recoded": {}
                    }

                    for field_name in selected_fields:
                        value = feature[field_name]
                        record_data["values"][field_name] = value

                        # Apply value recoding if configured
                        if field_name in recoding.value_recodings:
                            value_recoding = recoding.value_recodings[field_name]
                            fallback = value_recoding.default_value if value_recoding.default_value is not None else value
                            recoded_value = value_recoding.manual_mappings.get(str(value), fallback)
                            record_data["recoded"][field_name] = recoded_value

                    sample_records.append(record_data)
                    collected_samples += 1

            # BUG 5 fix: populate source_date_range from collected dates
            if source_dates_collected:
                source_date_range = [min(source_dates_collected).strftime("%Y-%m-%d %H:%M"),
                                     max(source_dates_collected).strftime("%Y-%m-%d %H:%M")]

            # DEBUG: Summary of preview analysis
            debug_log(f"=== PREVIEW SUMMARY for {layer_name} ===")
            debug_log(f"Total features processed: {new_records + duplicate_records}")
            debug_log(f"Unique UUIDs in source: {len(seen_source_uuids)}")
            debug_log(f"Features with no UUID: {no_uuid_count}")
            debug_log(f"Duplicates (in master/tracker): {duplicate_in_master}")
            debug_log(f"Duplicates (within source): {duplicate_in_source}")
            debug_log(f"New records to add: {new_records}")
            debug_log(f"Total duplicates: {duplicate_records}")
            if seen_source_uuids:
                debug_log(f"Sample source UUIDs: {list(seen_source_uuids)[:5]}")

            # Analyze temporal overlap (reuses dates already collected in the
            # main loop above - no need to iterate the source a second time)
            temporal_overlap = None
            if self.uuid_tracker and new_records > 0 and source_dates_collected:
                date_range = (min(source_dates_collected), max(source_dates_collected))
                overlap_analysis = self.uuid_tracker.analyze_temporal_overlap(
                    target_layer_name, date_range, tolerance_hours=24
                )
                if overlap_analysis['has_overlap']:
                    temporal_overlap = overlap_analysis

            # Get UUID tracker statistics
            tracker_stats = None
            if self.uuid_tracker:
                tracker_stats = self.uuid_tracker.get_statistics(target_layer_name)

            preview_data[layer_name] = {
                "target_layer": target_layer_name,
                "total_records": total_records,
                "new_records": new_records,
                "duplicate_records": duplicate_records,
                "master_records": master_record_count,
                "fields": selected_fields,
                "field_mappings": recoding.field_mappings,
                "value_recodings": {k: v.to_dict() for k, v in recoding.value_recodings.items()},
                "sample_records": sample_records,
                "date_filter_applied": date_filter_applied,
                # Records that passed the filter = everything we iterated
                "filtered_records": (new_records + duplicate_records) if date_filter_applied else total_records,
                "filtered_out": max(0, total_records - (new_records + duplicate_records)) if date_filter_applied else 0,
                "filter_description": filter_expression or "",
                "temporal_overlap": temporal_overlap,
                "tracker_stats": tracker_stats,
                "unique_uuids": len(seen_source_uuids),  # Use actual tracked unique UUIDs
                "features_without_uuid": no_uuid_count,  # NEW: Track features without UUID
                "duplicates_in_master": duplicate_in_master,  # NEW: Detailed duplicate breakdown
                "duplicates_in_source": duplicate_in_source,  # NEW: Duplicates within source
                "source_date_range": source_date_range,
                "master_date_range": master_date_range,
                "no_uuid_mode": no_uuid_mode,  # NEW: Flag for no UUID duplicate checking
                "default_values": recoding.default_values  # Field-level default values
            }

        self.preview_ready.emit(preview_data)
        self.finished.emit(True, "Preview generated successfully")

    def process_layers(self):
        """
        Process layers with actual data copying.

        Enhanced with:
        - UUID tracking to JSON file
        - Metadata logging
        - Batch ID generation
        """
        if not self.selected_layers:
            self.finished.emit(False, "No layers selected for processing")
            return

        # Generate batch ID for this processing run
        batch_id = f"batch_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid_module.uuid4().hex[:8]}"

        total_layers = len(self.selected_layers)
        processed_layers = 0

        for idx, layer_name in enumerate(self.selected_layers):
            if self.abort:
                self.finished.emit(False, "Operation aborted by user")
                return

            progress = int((idx / total_layers) * 100)
            self.update_progress.emit(progress, f"Processing layer: {layer_name}")

            # Get recoding configuration
            recoding = self.layer_recodings.get(layer_name, LayerRecoding())
            target_layer_name = recoding.target_layer or layer_name

            # Open source layer
            source_uri = f"{self.source_gpkg}|layername={layer_name}"
            source_layer = QgsVectorLayer(source_uri, layer_name, "ogr")

            if not source_layer.isValid():
                self.update_progress.emit(progress, f"Could not open layer {layer_name}")
                continue

            # Get configuration
            uuid_field = self.uuid_field_map.get(layer_name, self.default_uuid_field)
            # Copy so appending the UUID field below doesn't mutate the UI's config
            selected_fields = list(self.field_selections.get(layer_name, []))

            # Check if "No UUID" mode is enabled
            no_uuid_mode = (uuid_field == NO_UUID_FIELD or not uuid_field)

            # Check UUID field (only if not in No UUID mode)
            source_field_names = [field.name() for field in source_layer.fields()]
            uuid_field_in_source = None

            if not no_uuid_mode:
                uuid_field_in_source = find_matching_field(source_field_names, uuid_field)

                if not uuid_field_in_source:
                    self.update_progress.emit(progress,
                        f"UUID field '{uuid_field}' not found in layer {layer_name}, skipping")
                    continue

                uuid_field = uuid_field_in_source
            else:
                self.update_progress.emit(progress,
                    f"No UUID mode enabled for layer {layer_name} - all features will be added")

            if not selected_fields:
                selected_fields = list(source_field_names)

            if uuid_field_in_source and uuid_field not in selected_fields:
                selected_fields.append(uuid_field)

            # Check if master layer exists
            master_uri = f"{self.master_gpkg}|layername={target_layer_name}"
            master_layer = QgsVectorLayer(master_uri, target_layer_name, "ogr")

            if not master_layer.isValid():
                # Create new layer
                records_added = self.create_new_layer(source_layer, target_layer_name,
                                                      selected_fields, recoding, progress, batch_id,
                                                      no_uuid_mode, uuid_field)
                processed_layers += 1

                # BUG 6 fix: Log metadata for new layer creation
                if self.metadata_manager and records_added > 0:
                    timezone_name = self.global_date_filter.get('timezone_name', 'UTC') if self.global_date_filter else 'UTC'
                    self.metadata_manager.log_batch(
                        batch_id=f"{batch_id}_{layer_name}",
                        layer_name=target_layer_name,
                        records_added=records_added,
                        records_duplicates=0,
                        timezone_used=timezone_name,
                        recoding_template=recoding.template_name or ""
                    )
            else:
                # Append to existing layer
                success, records_added, records_duplicates = self.append_to_existing_layer(
                    source_layer, master_layer, layer_name, target_layer_name,
                    uuid_field, selected_fields, recoding, progress, batch_id,
                    no_uuid_mode
                )
                if success:
                    processed_layers += 1

                    # Log to metadata
                    if self.metadata_manager:
                        timezone_name = self.global_date_filter.get('timezone_name', 'UTC') if self.global_date_filter else 'UTC'
                        self.metadata_manager.log_batch(
                            batch_id=f"{batch_id}_{layer_name}",
                            layer_name=target_layer_name,
                            records_added=records_added,
                            records_duplicates=records_duplicates,
                            timezone_used=timezone_name,
                            recoding_template=recoding.template_name or ""
                        )

        self.update_progress.emit(100, "Processing complete")
        self.finished.emit(True, f"Successfully processed {processed_layers} of {total_layers} layers\nBatch ID: {batch_id}")

    def create_new_layer(self, source_layer, target_layer_name, selected_fields,
                        recoding, progress, batch_id, no_uuid_mode=False,
                        uuid_field=None):
        """
        Create a new layer in the master GeoPackage.

        Enhanced with:
        - UUID tracking to JSON
        - Data addition timestamp field
        - No UUID mode support
        """
        self.update_progress.emit(progress,
            f"Creating new layer {target_layer_name} in master GeoPackage")

        # Create fields structure
        fields_to_add = QgsFields()

        # Add data_added_timestamp field (NEW)
        timestamp_field = QgsField("data_added_timestamp", QVariant.String)
        fields_to_add.append(timestamp_field)

        # Add data_added_batch_id field (NEW)
        batch_field = QgsField("data_added_batch_id", QVariant.String)
        fields_to_add.append(batch_field)

        # Add selected fields with proper mapping
        for field_name in selected_fields:
            target_field_name = recoding.field_mappings.get(field_name, field_name)
            source_field_index = source_layer.fields().lookupField(field_name)
            if source_field_index != -1:
                source_field = source_layer.fields().at(source_field_index)
                new_field = QgsField(target_field_name, source_field.type(),
                                   source_field.typeName(), source_field.length(),
                                   source_field.precision())
                fields_to_add.append(new_field)

        # Add preserve original fields
        for field_name, value_recoding in recoding.value_recodings.items():
            if value_recoding.preserve_original_field and field_name in selected_fields:
                source_field_index = source_layer.fields().lookupField(field_name)
                if source_field_index != -1:
                    source_field = source_layer.fields().at(source_field_index)
                    preserve_field = QgsField(value_recoding.preserve_original_field,
                                            source_field.type(), source_field.typeName(),
                                            source_field.length(), source_field.precision())
                    fields_to_add.append(preserve_field)

        # Create writer. CreateOrOverwriteLayer requires the file to already
        # exist (it opens it in update mode); for a brand-new master the file
        # itself must be created
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = target_layer_name
        if os.path.exists(self.master_gpkg):
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        else:
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

        if source_layer.crs().isValid():
            options.destinationCrs = source_layer.crs()

        # NOTE: the 5th argument is the coordinate transform context, NOT the
        # driver name (the driver comes from options). Passing a string here
        # raised TypeError and made layer creation fail every time.
        writer = QgsVectorFileWriter.create(
            self.master_gpkg,
            fields_to_add,
            source_layer.wkbType(),
            source_layer.crs(),
            QgsProject.instance().transformContext(),
            options
        )

        if writer is None or writer.hasError() != QgsVectorFileWriter.NoError:
            error_msg = writer.errorMessage() if writer is not None else "writer not created"
            self.update_progress.emit(progress,
                f"Error creating layer {target_layer_name}: {error_msg}")
            del writer
            return 0

        # Apply date filter if enabled
        feature_request = QgsFeatureRequest()
        if self.global_date_filter and self.global_date_filter.get('enabled'):
            date_expression = self.build_global_date_filter_expression(source_layer)
            if date_expression:
                feature_request.setFilterExpression(date_expression)

        # Copy features with UUID tracking
        features_added = 0
        duplicates_skipped = 0
        added_uuids = []
        date_values = {}  # {uuid: date_iso} for temporal overlap detection
        seen_uuids = set()  # BUG 9 fix: track UUIDs within source to skip duplicates
        timestamp = datetime.now(timezone.utc).isoformat()

        # BUG 1 fix: resolve UUID field index once before loop
        uuid_field_idx = -1
        if uuid_field and not no_uuid_mode:
            actual_uuid_field = find_matching_field(
                [f.name() for f in source_layer.fields()], uuid_field
            )
            if actual_uuid_field:
                uuid_field_idx = source_layer.fields().lookupField(actual_uuid_field)

        # Check the UUID tracker too - the layer may have been deleted from the
        # master after its features were already merged once
        tracked_uuids = set()
        if self.uuid_tracker and not no_uuid_mode:
            tracked_uuids = self.uuid_tracker.get_layer_uuids(target_layer_name)

        # Date field so tracked UUIDs carry a date (enables temporal overlap
        # detection on later runs)
        tracker_date_field = None
        for field in source_layer.fields():
            if is_date_field(field):
                tracker_date_field = field.name()
                break

        aborted = False
        for feature in source_layer.getFeatures(feature_request):
            if self.abort:
                aborted = True
                break

            # Get UUID; treat NULL/empty as missing rather than the string "NULL"
            feature_uuid = None
            if uuid_field_idx >= 0:
                uuid_val = feature.attribute(uuid_field_idx)
                if uuid_val:
                    feature_uuid = str(uuid_val)

            if not no_uuid_mode:
                # Consistent with the append path and the preview: features
                # without a UUID are skipped, as are duplicates
                if not feature_uuid:
                    duplicates_skipped += 1
                    continue
                if feature_uuid in tracked_uuids or feature_uuid in seen_uuids:
                    duplicates_skipped += 1
                    continue
                seen_uuids.add(feature_uuid)

            new_feature = QgsFeature(fields_to_add)

            # Set timestamp and batch ID (NEW)
            new_feature.setAttribute("data_added_timestamp", timestamp)
            new_feature.setAttribute("data_added_batch_id", batch_id)

            for field_name in selected_fields:
                source_field_index = feature.fieldNameIndex(field_name)
                if source_field_index >= 0:
                    value = feature.attribute(source_field_index)
                    target_field_name = recoding.field_mappings.get(field_name, field_name)
                    target_field_index = new_feature.fieldNameIndex(target_field_name)

                    if target_field_index >= 0:
                        if field_name in recoding.value_recodings:
                            value_recoding = recoding.value_recodings[field_name]
                            if value_recoding.preserve_original_field:
                                orig_field_index = new_feature.fieldNameIndex(
                                    value_recoding.preserve_original_field)
                                if orig_field_index >= 0:
                                    new_feature.setAttribute(orig_field_index, value)
                            # BUG 3 fix: use default_value as fallback for unmapped values
                            fallback = value_recoding.default_value if value_recoding.default_value is not None else value
                            recoded_value = value_recoding.manual_mappings.get(str(value), fallback)
                            new_feature.setAttribute(target_field_index, recoded_value)
                        else:
                            new_feature.setAttribute(target_field_index, value)

                        # BUG 2 fix: apply default_values for NULL/missing values
                        if (value is None or (hasattr(value, 'isNull') and value.isNull())):
                            default_val = recoding.default_values.get(target_field_name)
                            if default_val is not None:
                                new_feature.setAttribute(target_field_index, default_val)

            if feature.hasGeometry():
                new_feature.setGeometry(feature.geometry())

            # QgsVectorFileWriter.addFeature() returns a bool (QgsFeatureSink
            # API), NOT a WriterError enum - comparing to NoError counted every
            # success as a failure and never tracked the UUIDs
            if writer.addFeature(new_feature):
                features_added += 1
                if feature_uuid:
                    added_uuids.append(feature_uuid)
                    if tracker_date_field:
                        pdt = to_python_datetime(feature[tracker_date_field])
                        if pdt:
                            date_values[feature_uuid] = pdt.isoformat()
            else:
                self.update_progress.emit(progress, "Error adding feature")

        del writer

        # Track UUIDs in JSON - even on abort, so anything already written is
        # still known to the duplicate detection on the next run
        if self.uuid_tracker and added_uuids and not no_uuid_mode:
            self.uuid_tracker.add_uuids(target_layer_name, added_uuids, batch_id, date_values)
            self.update_progress.emit(progress, f"Tracked {len(added_uuids)} UUIDs to JSON file")

        if aborted:
            self.update_progress.emit(progress,
                f"Aborted - {features_added} features were already added to {target_layer_name}")
        elif duplicates_skipped:
            self.update_progress.emit(progress,
                f"Added {features_added} features to new layer {target_layer_name}, "
                f"skipped {duplicates_skipped} duplicates/missing UUIDs")
        else:
            self.update_progress.emit(progress,
                f"Added {features_added} features to new layer {target_layer_name}")
        return features_added

    def append_to_existing_layer(self, source_layer, master_layer, source_layer_name,
                                target_layer_name, uuid_field, selected_fields,
                                recoding, progress, batch_id, no_uuid_mode=False):
        """
        Append non-duplicate features to existing layer.

        Enhanced with:
        - UUID tracker checking (prevents re-adding deleted/merged features)
        - Data addition timestamp
        - No UUID mode support (adds all features without duplicate checking)
        """
        self.update_progress.emit(progress, f"Appending to existing layer {target_layer_name}")

        # Check UUID field in master (skip if no_uuid_mode)
        master_field_names = [field.name() for field in master_layer.fields()]
        uuid_field_in_master = None

        if not no_uuid_mode:
            uuid_field_in_master = find_matching_field(master_field_names, uuid_field)

            if not uuid_field_in_master:
                mapped_uuid = recoding.field_mappings.get(uuid_field, uuid_field)
                uuid_field_in_master = find_matching_field(master_field_names, mapped_uuid)

                if not uuid_field_in_master:
                    # Add UUID field via the data provider (no edit buffer -
                    # faster and safe to use from a worker thread)
                    source_uuid_field_index = source_layer.fields().lookupField(uuid_field)
                    if source_uuid_field_index != -1:
                        field_to_add = source_layer.fields().at(source_uuid_field_index)
                        field_to_add.setName(mapped_uuid)
                        if master_layer.dataProvider().addAttributes([field_to_add]):
                            master_layer.updateFields()
                            uuid_field_in_master = mapped_uuid

        # Re-capture after the possible UUID field addition above
        master_field_names = [field.name() for field in master_layer.fields()]

        # Add timestamp/batch ID fields and any missing mapped fields in a
        # single provider call (no edit buffer, no layer reloads)
        new_attributes = []
        if not find_matching_field(master_field_names, "data_added_timestamp"):
            new_attributes.append(QgsField("data_added_timestamp", QVariant.String))
        if not find_matching_field(master_field_names, "data_added_batch_id"):
            new_attributes.append(QgsField("data_added_batch_id", QVariant.String))

        for field_name in selected_fields:
            target_field_name = recoding.field_mappings.get(field_name, field_name)
            if not find_matching_field(master_field_names, target_field_name):
                source_field_idx = source_layer.fields().indexFromName(field_name)
                if source_field_idx >= 0:
                    source_field = source_layer.fields().at(source_field_idx)
                    new_attributes.append(QgsField(target_field_name, source_field.type(),
                                                   source_field.typeName(), source_field.length(),
                                                   source_field.precision()))

        if new_attributes:
            master_layer.dataProvider().addAttributes(new_attributes)
            master_layer.updateFields()
        master_field_names = [field.name() for field in master_layer.fields()]

        # Get existing UUIDs from master layer (skip if no_uuid_mode)
        existing_uuids = set()
        master_layer_uuids = set()
        tracked_uuids = set()

        if not no_uuid_mode and uuid_field_in_master:
            # Provider-side DISTINCT - avoids iterating every master feature
            master_uuid_idx = master_layer.fields().lookupField(uuid_field_in_master)
            if master_uuid_idx >= 0:
                master_layer_uuids = {str(v) for v in master_layer.uniqueValues(master_uuid_idx) if v}
            existing_uuids.update(master_layer_uuids)

        debug_log(f"=== APPEND to {target_layer_name} ===")
        debug_log(f"No UUID mode: {no_uuid_mode}")
        debug_log(f"UUID field in source: {uuid_field}")
        debug_log(f"UUID field in master: {uuid_field_in_master}")
        debug_log(f"UUIDs in master layer: {len(master_layer_uuids)}")
        if master_layer_uuids:
            debug_log(f"Sample master UUIDs: {list(master_layer_uuids)[:5]}")

        # CRITICAL: Also check UUID tracker (NEW) - skip if no_uuid_mode
        if not no_uuid_mode and self.uuid_tracker:
            tracked_uuids = self.uuid_tracker.get_layer_uuids(target_layer_name)
            existing_uuids.update(tracked_uuids)
            self.update_progress.emit(progress,
                f"Checking against {len(tracked_uuids)} tracked UUIDs (includes deleted/merged features)")
        elif no_uuid_mode:
            self.update_progress.emit(progress,
                f"No UUID mode - skipping duplicate checking, all features will be added")

        debug_log(f"UUIDs in tracker: {len(tracked_uuids)}")
        debug_log(f"Total existing UUIDs to check: {len(existing_uuids)}")

        # Handle CRS transformation
        transform = None
        source_crs = source_layer.crs()
        master_crs = master_layer.crs()
        if source_crs.isValid() and master_crs.isValid() and source_crs != master_crs:
            transform = QgsCoordinateTransform(source_crs, master_crs, QgsProject.instance())

        # Apply date filter
        feature_request = QgsFeatureRequest()
        if self.global_date_filter and self.global_date_filter.get('enabled'):
            date_expression = self.build_global_date_filter_expression(source_layer)
            if date_expression:
                feature_request.setFilterExpression(date_expression)

        # Copy features in batches straight through the data provider: no edit
        # buffer means far less memory, much faster commits, and no
        # GUI-thread-bound QgsVectorLayer editing from this worker thread
        provider = master_layer.dataProvider()
        features_added = 0
        duplicates_skipped = 0
        added_uuids = []
        date_values = {}  # {uuid: date_iso} for temporal overlap detection
        timestamp = datetime.now(timezone.utc).isoformat()

        # Date field so tracked UUIDs carry a date
        tracker_date_field = None
        for field in source_layer.fields():
            if is_date_field(field):
                tracker_date_field = field.name()
                break

        batch_size = 1000
        pending_features = []
        pending_uuids = []

        def flush_pending():
            """Write the pending batch via the provider; returns success."""
            nonlocal features_added
            if not pending_features:
                return True
            success, _ = provider.addFeatures(pending_features)
            if success:
                features_added += len(pending_features)
                added_uuids.extend(pending_uuids)
            pending_features.clear()
            pending_uuids.clear()
            return success

        # DEBUG: Track skip reasons
        skip_no_uuid = 0
        skip_in_master = 0
        skip_in_tracker = 0
        skip_already_added = 0  # Duplicates within source
        source_uuids_seen = set()
        first_few_features = []

        debug_log(f"Starting feature copy loop...")

        aborted = False
        write_ok = True
        for feature in source_layer.getFeatures(feature_request):
            if self.abort:
                aborted = True
                break

            # Handle No UUID mode - add all features without checking
            if no_uuid_mode:
                feature_uuid = None
                feature_uuid_val = None
            else:
                feature_uuid_val = feature[uuid_field]
                feature_uuid = str(feature_uuid_val) if feature_uuid_val else None

            # DEBUG: Collect info on first few features
            if len(first_few_features) < 10:
                first_few_features.append({
                    'uuid': feature_uuid,
                    'uuid_raw': repr(feature_uuid_val) if not no_uuid_mode else 'N/A (no UUID mode)',
                    'fid': feature.id()
                })

            # Skip duplicate checking if in no_uuid_mode
            if not no_uuid_mode:
                # DEBUG: Detailed skip reason tracking
                if not feature_uuid:
                    skip_no_uuid += 1
                    duplicates_skipped += 1
                    continue
                elif feature_uuid in master_layer_uuids:
                    skip_in_master += 1
                    duplicates_skipped += 1
                    continue
                elif feature_uuid in tracked_uuids:
                    skip_in_tracker += 1
                    duplicates_skipped += 1
                    continue
                elif feature_uuid in source_uuids_seen:
                    skip_already_added += 1
                    duplicates_skipped += 1
                    continue

                # Track this UUID as seen in source
                source_uuids_seen.add(feature_uuid)

            new_feature = QgsFeature(master_layer.fields())

            # Set timestamp and batch ID (NEW)
            timestamp_idx = new_feature.fieldNameIndex("data_added_timestamp")
            if timestamp_idx >= 0:
                new_feature.setAttribute(timestamp_idx, timestamp)
            batch_idx = new_feature.fieldNameIndex("data_added_batch_id")
            if batch_idx >= 0:
                new_feature.setAttribute(batch_idx, batch_id)

            for field_name in selected_fields:
                source_field_idx = feature.fieldNameIndex(field_name)
                if source_field_idx >= 0:
                    value = feature.attribute(source_field_idx)
                    target_field_name = recoding.field_mappings.get(field_name, field_name)
                    master_field_idx = new_feature.fieldNameIndex(target_field_name)

                    if master_field_idx >= 0:
                        if field_name in recoding.value_recodings:
                            value_recoding = recoding.value_recodings[field_name]
                            if value_recoding.preserve_original_field:
                                orig_field_idx = new_feature.fieldNameIndex(
                                    value_recoding.preserve_original_field)
                                if orig_field_idx >= 0:
                                    new_feature.setAttribute(orig_field_idx, value)
                            # BUG 3 fix: use default_value as fallback for unmapped values
                            fallback = value_recoding.default_value if value_recoding.default_value is not None else value
                            recoded_value = value_recoding.manual_mappings.get(str(value), fallback)
                            new_feature.setAttribute(master_field_idx, recoded_value)
                        else:
                            new_feature.setAttribute(master_field_idx, value)

                        # BUG 2 fix: apply default_values for NULL/missing values
                        if (value is None or (hasattr(value, 'isNull') and value.isNull())):
                            default_val = recoding.default_values.get(target_field_name)
                            if default_val is not None:
                                new_feature.setAttribute(master_field_idx, default_val)

            if feature.hasGeometry():
                geom = feature.geometry()
                if transform:
                    geom.transform(transform)
                new_feature.setGeometry(geom)

            pending_features.append(new_feature)
            if feature_uuid:
                pending_uuids.append(feature_uuid)
                if tracker_date_field:
                    pdt = to_python_datetime(feature[tracker_date_field])
                    if pdt:
                        date_values[feature_uuid] = pdt.isoformat()

            if len(pending_features) >= batch_size:
                if not flush_pending():
                    write_ok = False
                    break

        if write_ok and not aborted:
            write_ok = flush_pending()
        master_layer.updateExtents()

        # DEBUG: Summary
        debug_log(f"=== APPEND SUMMARY for {target_layer_name} ===")
        debug_log(f"First 10 features processed: {first_few_features}")
        debug_log(f"Skipped - no UUID: {skip_no_uuid}")
        debug_log(f"Skipped - in master layer: {skip_in_master}")
        debug_log(f"Skipped - in tracker: {skip_in_tracker}")
        debug_log(f"Skipped - duplicate in source: {skip_already_added}")
        debug_log(f"Total skipped: {duplicates_skipped}")
        debug_log(f"Features to add: {features_added}")
        debug_log(f"UUIDs to track: {len(added_uuids)}")
        if added_uuids:
            debug_log(f"Sample added UUIDs: {added_uuids[:5]}")

        # Track whatever was successfully written - even on abort or a failed
        # batch - so duplicate detection stays correct on the next run
        if self.uuid_tracker and added_uuids and not no_uuid_mode:
            self.uuid_tracker.add_uuids(target_layer_name, added_uuids, batch_id, date_values)
            self.update_progress.emit(progress, f"Tracked {len(added_uuids)} new UUIDs to JSON file")

        if aborted:
            self.update_progress.emit(progress,
                f"Aborted - {features_added} features were already added to {target_layer_name}")
            return False, features_added, duplicates_skipped

        if not write_ok:
            debug_log(f"Provider addFeatures FAILED!")
            self.update_progress.emit(progress,
                f"Failed to add features to {target_layer_name} "
                f"({features_added} added before the failure)")
            return False, features_added, duplicates_skipped

        if no_uuid_mode:
            self.update_progress.emit(progress,
                f"Added {features_added} features (no duplicate checking)")
        else:
            self.update_progress.emit(progress,
                f"Added {features_added} features, skipped {duplicates_skipped} duplicates")
        return True, features_added, duplicates_skipped

    def build_global_date_filter_expression(self, layer, date_field=None):
        """Build QGIS expression for global date filtering"""
        if not self.global_date_filter or not self.global_date_filter.get('enabled'):
            return None

        if not date_field:
            for field in layer.fields():
                if is_date_field(field):
                    date_field = field.name()
                    break

        if not date_field:
            return None

        filter_type = self.global_date_filter['type']
        start_dt = self.global_date_filter['start_datetime']
        end_dt = self.global_date_filter.get('end_datetime')

        if filter_type == FILTER_TYPE_AFTER and start_dt:
            return f'"{date_field}" >= \'{start_dt.strftime("%Y-%m-%d %H:%M:%S")}\''
        elif filter_type == FILTER_TYPE_BEFORE and start_dt:
            return f'"{date_field}" <= \'{start_dt.strftime("%Y-%m-%d %H:%M:%S")}\''
        elif filter_type == FILTER_TYPE_BETWEEN and start_dt and end_dt:
            return f'"{date_field}" >= \'{start_dt.strftime("%Y-%m-%d %H:%M:%S")}\' AND "{date_field}" <= \'{end_dt.strftime("%Y-%m-%d %H:%M:%S")}\''

        return None
