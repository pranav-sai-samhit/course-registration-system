"""Helpers shared by the role blueprints."""
from flask import render_template

import navigation
import security


def dashboard_view(role):
    @security.role_required(role)
    def dashboard():
        return render_template("dashboard.html", role=role)
    return dashboard


def register_placeholders(bp, role):
    """Give every not-yet-built nav item a real route and page.

    Items with ``phase=None`` are implemented by hand in the blueprint. A later
    phase replaces a placeholder by defining the real view and setting its
    ``phase`` to None in navigation.py.
    """
    for item in navigation.items(role):
        if item["phase"] is None:
            continue

        def make(item=item):
            @security.role_required(role)
            def placeholder():
                return render_template("placeholder.html", role=role, item=item)
            placeholder.__name__ = item["key"]
            return placeholder

        bp.add_url_rule(item["path"], endpoint=item["key"], view_func=make())
