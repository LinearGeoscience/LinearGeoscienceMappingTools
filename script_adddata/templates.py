#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Template management for recoding configurations.

Allows users to save and load recoding configurations for reuse.
Stores templates in JSON files in the adddata_metadata folder.
"""

import os
import json
from datetime import datetime, timezone
from typing import List, Optional, Dict
from qgis.core import QgsMessageLog, Qgis
from .utils import LayerRecoding


class TemplateManager:
    """
    Manages recoding templates using JSON files in the adddata_metadata folder.

    Example:
        If master is at: C:/data/master.gpkg
        Templates will be: C:/data/adddata_metadata/master_templates.json
    """

    def __init__(self, master_gpkg_path: str):
        """
        Initialize template manager.

        Args:
            master_gpkg_path: Path to the master GeoPackage
        """
        self.master_gpkg_path = master_gpkg_path
        self.templates_json_path = self._get_templates_json_path()
        self.templates_data = self._load_or_create_templates()

    def _get_metadata_folder(self) -> str:
        """Get or create the metadata folder"""
        master_dir = os.path.dirname(self.master_gpkg_path)
        metadata_folder = os.path.join(master_dir, "adddata_metadata")

        if not os.path.exists(metadata_folder):
            try:
                os.makedirs(metadata_folder)
                QgsMessageLog.logMessage(f"Created metadata folder: {metadata_folder}", 'Linear Geoscience', Qgis.Info)
            except OSError as e:
                QgsMessageLog.logMessage(f"Warning: Could not create metadata folder: {e}", 'Linear Geoscience', Qgis.Warning)
                # Fallback to master directory
                return master_dir

        return metadata_folder

    def _get_templates_json_path(self) -> str:
        """Get path to the templates JSON file"""
        master_filename = os.path.splitext(os.path.basename(self.master_gpkg_path))[0]
        metadata_folder = self._get_metadata_folder()
        return os.path.join(metadata_folder, f"{master_filename}_templates.json")

    def _load_or_create_templates(self) -> dict:
        """Load existing templates JSON or create new structure"""
        if os.path.exists(self.templates_json_path):
            try:
                with open(self.templates_json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if 'version' not in data:
                        data['version'] = '1.0'
                    if 'templates' not in data:
                        data['templates'] = {}
                    return data
            except (json.JSONDecodeError, IOError) as e:
                QgsMessageLog.logMessage(f"Warning: Could not load templates file: {e}", 'Linear Geoscience', Qgis.Warning)
                QgsMessageLog.logMessage("Creating new templates file", 'Linear Geoscience', Qgis.Info)

        # Create new structure
        return {
            'version': '1.0',
            'created': datetime.now(timezone.utc).isoformat(),
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'master_gpkg': os.path.basename(self.master_gpkg_path),
            'templates': {}  # {template_name: {template_data}}
        }

    def _save_templates(self):
        """Save templates data to JSON file"""
        self.templates_data['last_updated'] = datetime.now(timezone.utc).isoformat()
        try:
            with open(self.templates_json_path, 'w', encoding='utf-8') as f:
                json.dump(self.templates_data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            QgsMessageLog.logMessage(f"Error saving templates file: {e}", 'Linear Geoscience', Qgis.Warning)
            raise

    def save_template(self, template_name: str, source_layer: str,
                      target_layer: str, recoding: LayerRecoding) -> bool:
        """
        Save a recoding configuration as a template.

        Args:
            template_name: Name for the template
            source_layer: Source layer name
            target_layer: Target layer name
            recoding: LayerRecoding object

        Returns:
            True if successful
        """
        try:
            # Generate template ID
            template_id = f"{template_name.lower().replace(' ', '_')}_{int(datetime.now().timestamp())}"

            # Check if template exists and preserve created_date
            existing = self.templates_data['templates'].get(template_name)
            created_date = existing['created_date'] if existing else datetime.now(timezone.utc).isoformat()

            # Create template entry
            template_entry = {
                'template_id': template_id,
                'template_name': template_name,
                'source_layer': source_layer,
                'target_layer': target_layer,
                'configuration': recoding.to_dict(),
                'created_date': created_date,
                'modified_date': datetime.now(timezone.utc).isoformat()
            }

            self.templates_data['templates'][template_name] = template_entry
            self._save_templates()
            return True
        except Exception as e:
            QgsMessageLog.logMessage(f"Error saving template: {e}", 'Linear Geoscience', Qgis.Warning)
            return False

    def load_template(self, template_name: str) -> Optional[Dict]:
        """
        Load a recoding template.

        Args:
            template_name: Name of the template

        Returns:
            Dictionary with template data or None
        """
        return self.templates_data['templates'].get(template_name)

    def list_templates(self, source_layer: Optional[str] = None) -> List[Dict]:
        """
        List all available templates.

        Args:
            source_layer: Optional filter by source layer

        Returns:
            List of template info dictionaries (sorted by modified_date, newest first)
        """
        templates = list(self.templates_data['templates'].values())

        if source_layer:
            templates = [t for t in templates if t.get('source_layer') == source_layer]

        # Sort by modified_date descending
        templates.sort(key=lambda x: x.get('modified_date', ''), reverse=True)

        return templates

    def delete_template(self, template_name: str) -> bool:
        """
        Delete a template.

        Args:
            template_name: Name of the template

        Returns:
            True if successful
        """
        try:
            if template_name in self.templates_data['templates']:
                del self.templates_data['templates'][template_name]
                self._save_templates()
                return True
            return False
        except Exception as e:
            QgsMessageLog.logMessage(f"Error deleting template: {e}", 'Linear Geoscience', Qgis.Warning)
            return False

    def export_template_to_file(self, template_name: str, file_path: str) -> bool:
        """
        Export a template to a JSON file.

        Args:
            template_name: Name of the template
            file_path: Path to save the JSON file

        Returns:
            True if successful
        """
        template_data = self.load_template(template_name)
        if not template_data:
            return False

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(template_data, f, indent=2, ensure_ascii=False)
            return True
        except IOError as e:
            QgsMessageLog.logMessage(f"Error exporting template: {e}", 'Linear Geoscience', Qgis.Warning)
            return False

    def import_template_from_file(self, file_path: str, template_name: Optional[str] = None) -> bool:
        """
        Import a template from a JSON file.

        Args:
            file_path: Path to the JSON file
            template_name: Optional new name for the template

        Returns:
            True if successful
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                template_data = json.load(f)

            # Use provided name or original name
            name = template_name or template_data.get('template_name', 'Imported Template')
            source_layer = template_data.get('source_layer', '')
            target_layer = template_data.get('target_layer', '')
            configuration = template_data.get('configuration', {})

            # Convert configuration to LayerRecoding
            recoding = LayerRecoding.from_dict(configuration)

            return self.save_template(name, source_layer, target_layer, recoding)
        except (IOError, json.JSONDecodeError) as e:
            QgsMessageLog.logMessage(f"Error importing template: {e}", 'Linear Geoscience', Qgis.Warning)
            return False
