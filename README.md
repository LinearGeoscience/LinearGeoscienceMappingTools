# Linear Geoscience Mapping Tools

A QGIS plugin for geological mapping, built around the Linear Geoscience QField mapping template GeoPackage.

Version 3.3 | [GitHub](https://github.com/LinearGeoscience/LinearGeoscienceMappingTools) | [Issues](https://github.com/LinearGeoscience/LinearGeoscienceMappingTools/issues)

## Features

- **Setup Mapping** - load the LGS mapping template and configure CRS, snapping, and scales
- **Data Management** - import and append field data into the mapping template, merge and reproject GeoPackages, export mapping for distribution. 
- **Stereonet Analysis** - interactive plotting of structural data, with export to Stereonet 11 and Leapfrog formats
- **Field Photos** - georeference, browse, and export field photos
- **Declination Tools** - calculate magnetic declination per point (WMM2025) and batch-adjust structural measurements
- **Map Production** - generate mapsheets and print layouts
- **Map Cleaning** - spline reshape and digitising tools, polygon clipping, overlap/sliver finders, geometry fixer, and Lines/Polygons to Splines Processing algorithms

## Installation

**From the QGIS Plugin Repository:** Plugins → Manage and Install Plugins → search "Linear Geoscience Mapping Tools" → Install.

**Manual:** download from [GitHub Releases](https://github.com/LinearGeoscience/LinearGeoscienceMappingTools/releases), and in QGIS install from ZIP, selecting the zipped plugin. 

## Requirements

- QGIS 3.40 LTR or higher
- Windows, macOS, or Linux
- Python packages: numpy, matplotlib, and pandas. These are included in standard QGIS installations on Windows and macOS; on Linux they may need to be installed separately (e.g. `python3-matplotlib` and `python3-pandas` via your package manager, or pip in the QGIS Python environment). If matplotlib or pandas is missing, the plugin still loads and the stereonet and symbology tools show an installation hint instead.
- All other required libraries (mplstereonet, geomag, fuzzywuzzy) are bundled with the plugin

## License

GNU General Public License v3.0. Copyright (C) 2024-2026 Harry West, Linear Geoscience. See [LICENSE](LICENSE).

Bundled third-party components (see [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES) and `map_cleaning/THIRD_PARTY_LICENSES.txt`):

| Component | License | Author |
|-----------|---------|--------|
| mplstereonet v0.6.3 | MIT | Joe Kington |
| geomag v0.9.2015 | MIT | Christopher Weiss |
| fuzzywuzzy | MIT | Various contributors |
| WMM2025 model data | Public Domain | NOAA/NGA |
| Spline Plugin (map cleaning) | GPLv2+ | Radim Blazek |
| Polygon Clipper (map cleaning) | GPLv2+ | Giuseppe De Marco |

## Support

- Bug reports: [GitHub Issues](https://github.com/LinearGeoscience/LinearGeoscienceMappingTools/issues)
- Email: harry@lineargeoscience.au
