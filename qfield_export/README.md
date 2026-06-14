# LGS QField Exporter

A streamlined QGIS plugin for exporting projects to QField mobile app with enhanced layer selection and mobile compatibility.

## Features

- **Layer Selection**: Choose specific layers to export instead of the entire project
- **Mobile-Optimized**: Automatic path normalization for Android/iOS compatibility
- **Simple Interface**: Clean, intuitive dialog with progress feedback
- **Reliable Export**: Focused on stability and consistent results
- **No Cloud Dependencies**: Pure cable/offline export functionality

## Installation

### Method 1: From ZIP file
1. Download the latest release ZIP file
2. In QGIS, go to `Plugins` → `Manage and Install Plugins...`
3. Click `Install from ZIP`
4. Select the downloaded ZIP file
5. Click `Install Plugin`

### Method 2: Manual Installation
1. Clone or download this repository
2. Copy the `LGS_QField_Exporter` folder to your QGIS plugins directory:
   - Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
   - macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
   - Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
3. Restart QGIS
4. Enable the plugin in `Plugins` → `Manage and Install Plugins...`

## Usage

1. Open your QGIS project
2. Click the **Export to QField** button in the toolbar or go to `Plugins` → `LGS QField Exporter` → `Export to QField`
3. Select the layers you want to export
4. Choose an export directory
5. Click **Export**
6. Transfer the exported folder to your mobile device
7. Open the project in QField

## Layer Selection Options

- **Select All**: Export all valid layers
- **Select None**: Clear all selections
- **Vector Only**: Export only vector layers
- **Raster Only**: Export only raster layers
- Manual selection via checkboxes

## Export Process

1. **Vector Layers**: Automatically converted to GeoPackage format for optimal mobile performance
2. **Raster Layers**: Copied with auxiliary files (world files, projections, etc.)
3. **Path Normalization**: All paths converted to forward slashes for cross-platform compatibility
4. **Attachment Folders**: Optional copying of standard attachment directories (DCIM, photos, etc.)

## Requirements

- QGIS 3.16 or higher
- QField app on mobile device (Android/iOS)

## Supported Layer Types

✅ **Supported:**
- Shapefiles
- GeoPackage layers
- PostGIS layers (converted to GeoPackage)
- SpatiaLite layers
- GeoTIFF rasters
- Other GDAL-supported raster formats

❌ **Not Supported:**
- WMS/WMTS layers
- WFS layers
- Online basemaps
- Temporary/scratch layers

## Troubleshooting

### Layers not showing in QField
- Ensure all paths use forward slashes (handled automatically)
- Check that layer files were exported to the correct directory
- Verify the .qgs project file is in the export directory

### Export fails
- Check that you have write permissions to the export directory
- Ensure enough disk space is available
- Review invalid layers in your project

## License

This plugin is released under the GNU General Public License v2.0 or later.

## Support

For issues, feature requests, or questions:
- Create an issue on [GitHub](https://github.com/LinearGeoscience/LGS_QField_Exporter/issues)
- Contact: contact@lineargeoscience.com

## Credits

Developed by Linear Geoscience for reliable field data collection workflows.

Based on concepts from QFieldSync but simplified and focused on cable export functionality.