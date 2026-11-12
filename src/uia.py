"""The UI Automation client, created one thread at a time (2026-11-11).

uiautomation makes its COM client on first use (`_AutomationClient.instance()`, no lock). The first time on a PC,
comtypes writes the wrapper module comtypes/gen/_944DE083_..._0_1_0.py while doing so. The UI magnet and the
scroll-target finder start their threads together, both wrote that file at once, and one read it half written:
"cannot import name 'IUIAutomationElementArray' ... Can not load UIAutomationCore.dll" (printed by uiautomation,
three tries each). Call `create_client()` in the thread after `UIAutomationInitializerInThread()`.
"""
from __future__ import annotations

import threading

_LOCK = threading.Lock()


def create_client():
    """Import uiautomation and make its client under one lock; returns the module. Raises when it cannot load."""
    import uiautomation as auto
    import uiautomation.uiautomation as core

    with _LOCK:
        core._AutomationClient.instance()
    return auto
