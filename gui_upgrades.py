"""Optional GUI enhancements for the Vector assistant.

This module is intentionally minimal and can be extended with advanced UI components.
"""

from __future__ import annotations

import tkinter as tk


def add_token_display(root: tk.Tk, label: tk.Label) -> None:
    """Attach a reusable token display label to the root window."""
    label.pack(fill=tk.X, padx=8, pady=4)
