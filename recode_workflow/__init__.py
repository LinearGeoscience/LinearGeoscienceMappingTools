"""
Recode & Restyle Workflow package.

Combines Update Tables, Plot Symbols, and Remove Unused Symbology
into a single sidebar wizard.
"""

from .panel import RecodeWorkflowWizard

__all__ = ["run_recode_workflow", "RecodeWorkflowWizard"]


def run_recode_workflow(iface, owner=None):
    """Singleton launcher – called from mainplugin.py.

    The singleton wizard is stored on `owner` (the plugin instance) as
    `owner.recode_wizard`; unload() tears it down. Without an owner the
    wizard is shown without singleton tracking.
    """
    existing = getattr(owner, 'recode_wizard', None) if owner else None
    if existing is not None:
        try:
            existing.show()
            existing.activateWindow()
            existing.raise_()
            return existing
        except RuntimeError:
            # C++ object deleted
            owner.recode_wizard = None

    wizard = RecodeWorkflowWizard(iface, parent=iface.mainWindow())
    if owner is not None:
        owner.recode_wizard = wizard
    wizard.show()
    wizard.activateWindow()
    wizard.raise_()
    return wizard
