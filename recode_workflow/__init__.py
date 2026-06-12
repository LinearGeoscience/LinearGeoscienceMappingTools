"""
Recode & Restyle Workflow package.

Combines Update Tables, Plot Symbols, and Remove Unused Symbology
into a single sidebar wizard.
"""

from .panel import RecodeWorkflowWizard

__all__ = ["run_recode_workflow", "RecodeWorkflowWizard"]


def run_recode_workflow(iface):
    """Singleton launcher – called from mainplugin.py."""
    existing = getattr(iface, '_recode_wizard', None)
    if existing is not None:
        try:
            existing.show()
            existing.activateWindow()
            existing.raise_()
            return existing
        except RuntimeError:
            # C++ object deleted
            iface._recode_wizard = None

    wizard = RecodeWorkflowWizard(iface, parent=iface.mainWindow())
    iface._recode_wizard = wizard
    wizard.show()
    wizard.activateWindow()
    wizard.raise_()
    return wizard
