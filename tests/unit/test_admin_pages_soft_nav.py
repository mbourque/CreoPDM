"""Admin pages must not depend on <script> tags in the page: soft navigation never runs them."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "src" / "creopdm" / "templates"

# Every page that is reached by clicking a link inside the app (not a full-page document like the
# login page) must get its behaviour from a client module that app.js starts after each swap.
_SOFT_NAV_PAGES = sorted(
    p.name
    for p in TEMPLATES.glob("*.html")
    if p.name not in {"base.html", "auth_login.html", "auth_setup.html", "auth_forgot_password.html",
                      "auth_reset_password.html", "auth_password.html", "auth_no_access.html",
                      "site_unavailable.html", "help_agent_tray.html",
                      # Standalone documents (their own <html>, loaded in Creo's embedded browser or
                      # opened directly), not content swapped into the app shell.
                      "embed_explorer.html"}
)


@pytest.mark.parametrize("name", _SOFT_NAV_PAGES)
def test_a_page_has_no_executable_inline_script(name):
    text = (TEMPLATES / name).read_text(encoding="utf-8")
    scripts = re.findall(r"<script\b([^>]*)>", text)
    executable = [attrs for attrs in scripts if "application/json" not in attrs]
    assert not executable, (
        f"{name} has an executable <script>: it only runs after a full reload, never after a soft "
        "navigation. Put the behaviour in a client module that app.js starts."
    )


def test_the_audit_toggle_and_email_form_run_from_the_admin_module():
    admin = (ROOT / "src" / "creopdm" / "static" / "js" / "admin.js").read_text(encoding="utf-8")
    assert 'document.getElementById("utilities-audit-table")' in admin and "audit-more-toggle" in admin
    assert 'document.getElementById("email-settings-form")' in admin and "data-email-transport" in admin
    boot = (ROOT / "src" / "creopdm" / "static" / "js" / "app.js").read_text(encoding="utf-8")
    assert '$("#utilities-audit-table")' in boot and '$("#email-settings-form")' in boot
