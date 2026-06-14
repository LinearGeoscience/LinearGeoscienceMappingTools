"""
Path utilities for cross-platform compatibility.
Ensures paths work correctly when exporting from Windows to mobile devices.
"""

import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Union, List, Optional

from qgis.core import QgsMessageLog, Qgis

PathLike = Union[Path, str]


def to_posix_path(path: PathLike) -> str:
    """
    Convert any path to POSIX format (forward slashes).

    Args:
        path: Path string or Path object to convert

    Returns:
        Path string with forward slashes
    """
    return Path(path).as_posix()


def normalize_for_mobile(path: str) -> str:
    """
    Normalize a path string for mobile devices (Android/iOS).

    - Converts backslashes to forward slashes
    - Removes Windows drive letters for relative paths
    - Ensures paths are in POSIX format

    Args:
        path: Path string to normalize

    Returns:
        Normalized path string suitable for mobile devices
    """
    # Replace backslashes with forward slashes
    normalized = path.replace('\\', '/')

    # Remove Windows drive letters (C:/, D:/, etc.) for relative paths
    # But keep URLs and special protocols intact
    if len(normalized) > 1 and normalized[1] == ':':
        # Check if it's not a URL protocol
        if not any(normalized.startswith(proto) for proto in ['http:', 'https:', 'file:', 'ftp:']):
            # Remove drive letter and colon, keep the path
            normalized = normalized[2:].lstrip('/')

    return normalized


def clean_csv_uri_to_path(uri: str) -> Optional[str]:
    """
    Extract and clean the actual file path from a CSV/delimited text layer URI.

    QGIS stores CSV layers with query parameters and file protocols:
    - file:\C:\path\file.csv?type=csv&maxFields=10000&...
    - file:///C:/path%20with%20spaces/file.csv?type=csv&...

    This function:
    1. Strips query parameters (everything after '?')
    2. Removes file protocol prefix (file:\ or file:///)
    3. URL-decodes the path (%20 → space, %2B → +, etc.)
    4. Normalizes path separators

    Args:
        uri: CSV layer URI string from QGIS

    Returns:
        Clean file path string, or None if URI is invalid

    Examples:
        >>> clean_csv_uri_to_path("file:\C:\path\file.csv?type=csv&...")
        "C:\\path\\file.csv"

        >>> clean_csv_uri_to_path("file:///C:/path%20with%20spaces/file.csv?...")
        "C:\\path with spaces\\file.csv"  # (on Windows)
    """
    if not uri:
        return None

    # Step 1: Strip query parameters (everything after '?')
    if '?' in uri:
        uri = uri.split('?')[0]

    # Step 2: Remove file protocol prefix using urlparse for robustness
    # Handle: file:/// (standard), file:// (2-slash variant), file:\ (QGIS quirk), file:/
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme == 'file':
        # urlparse handles file:/// correctly, giving us the path
        # For Windows paths like file:///C:/path, parsed.path is /C:/path
        file_path = parsed.path
        # On Windows, strip leading slash before drive letter (e.g., /C:/path -> C:/path)
        if len(file_path) > 2 and file_path[0] == '/' and file_path[2] == ':':
            file_path = file_path[1:]
        uri = file_path
    elif uri.startswith('file:\\'):
        # QGIS quirk: file:\ with backslash - urlparse won't handle this
        uri = uri[6:]
    elif uri.startswith('file:'):
        uri = uri[5:]

    # Step 3: URL decode the path
    try:
        uri = urllib.parse.unquote(uri)
    except Exception:
        QgsMessageLog.logMessage(
            f"Failed to URL-decode CSV path: {uri}",
            "LGS QField Exporter",
            Qgis.Warning
        )

    # Step 4: Normalize path separators for current OS
    path = Path(uri)

    return str(path)


def ensure_relative_to_project(path: PathLike, project_dir: Path) -> str:
    """
    Ensure a path is relative to the project directory.

    Returns POSIX-style relative path for cross-platform compatibility.
    If the path cannot be made relative to the project, returns the
    original path in POSIX format.

    Args:
        path: Path to make relative
        project_dir: Project directory to be relative to

    Returns:
        POSIX-style relative path if possible, otherwise POSIX absolute path
    """
    path_obj = Path(path)
    project_dir = Path(project_dir)

    if path_obj.is_absolute():
        try:
            # Try to make it relative to project
            rel_path = path_obj.relative_to(project_dir)
            return rel_path.as_posix()
        except ValueError:
            # Path is not under project directory
            # Return as POSIX absolute path
            return path_obj.as_posix()

    # Already relative, just ensure POSIX format
    return path_obj.as_posix()


def _normalize_path_string(text: str) -> str:
    """
    Normalize a path string from a project XML element.

    Converts backslashes to forward slashes and removes Windows drive
    letters for paths that should be relative in the exported project.

    Args:
        text: Raw path string from project XML

    Returns:
        Normalized path string
    """
    normalized = text.replace('\\', '/')

    # Remove Windows drive letters for non-URL paths
    if ':/' in normalized and not any(normalized.startswith(proto)
                                     for proto in ['http:', 'https:', 'file:', 'ftp:']):
        if len(normalized) > 1 and normalized[1] == ':':
            parts = normalized.split(':/')
            if len(parts) > 1:
                normalized = parts[1].lstrip('/')

    return normalized


def normalize_project_file_paths(project_file: Path) -> bool:
    """
    Normalize all paths in a QGIS project file for mobile compatibility.

    This function modifies the project file in place, converting all
    Windows-style paths to POSIX format that works on mobile devices.

    Args:
        project_file: Path to the .qgs project file

    Returns:
        True if modifications were made, False otherwise
    """
    if not project_file.exists():
        return False

    try:
        # Parse the QGS project file (XML format)
        tree = ET.parse(str(project_file))
        root = tree.getroot()
        modified = False

        # Normalize datasource elements (vector layers) and file elements (raster layers)
        for tag in ('datasource', 'file'):
            for elem in root.iter(tag):
                if elem.text:
                    original = elem.text
                    normalized = _normalize_path_string(original)
                    if original != normalized:
                        elem.text = normalized
                        modified = True

        # Also check provider elements which may contain paths
        for provider in root.iter('provider'):
            if provider.text and '\\' in provider.text:
                provider.text = provider.text.replace('\\', '/')
                modified = True

        # Save the normalized project if any changes were made
        if modified:
            tree.write(str(project_file), encoding='UTF-8', xml_declaration=True)

        return modified

    except Exception as e:
        # Don't fail the export if normalization fails
        QgsMessageLog.logMessage(
            f"Failed to normalize paths in project file: {e}",
            "LGS QField Exporter",
            Qgis.Warning
        )
        return False