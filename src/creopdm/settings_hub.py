"""System Settings hub tiles — order matches the former single settings page."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SettingsHubTile:
    slug: str
    title: str
    blurb: str
    # Template fragment under templates/settings_partials/ (None for custom pages).
    partial: str | None = None
    # Full page template when not using settings_section.html + partial.
    page_template: str | None = None


# Same order as the old monolithic System Settings form (Availability lives under Utilities).
SETTINGS_HUB_TILES: tuple[SettingsHubTile, ...] = (
    SettingsHubTile(
        slug="open",
        title="Open Creo models",
        blurb="Choose OS file association or Embedded Creo Browser for Open.",
        partial="open.html",
    ),
    SettingsHubTile(
        slug="vault",
        title="Vault",
        blurb="Master repository folder for each product’s Git history and vault copies.",
        partial="vault.html",
    ),
    SettingsHubTile(
        slug="creo-models",
        title="Creo Models",
        blurb="Extensions counted and filtered by the Creo Models chip.",
        partial="creo_models.html",
    ),
    SettingsHubTile(
        slug="documents",
        title="Documents",
        blurb="Extensions counted and filtered by the Documents chip.",
        partial="documents.html",
    ),
    SettingsHubTile(
        slug="creo-openable",
        title="Creo-openable models",
        blurb="Types Creo can open from click-to-open.",
        partial="creo_openable.html",
    ),
    SettingsHubTile(
        slug="text-files",
        title="Text files",
        blurb="CAD-like files that open with a text editor, not Creo.",
        partial="text_files.html",
    ),
    SettingsHubTile(
        slug="non-openable-cad",
        title="Non openable CAD",
        blurb="CAD-like files that stay in the product but do not open.",
        partial="non_openable_cad.html",
    ),
    SettingsHubTile(
        slug="numbered-saves",
        title="Numbered saves",
        blurb="Extensions that use Creo-style .ext.N versioning for Add and Purge.",
        partial="numbered_saves.html",
    ),
    SettingsHubTile(
        slug="types",
        title="File type names",
        blurb="Optional labels for the Type column by extension or file name.",
        page_template="settings_types.html",
    ),
    SettingsHubTile(
        slug="ignored-files",
        title="Ignored files",
        blurb="Patterns that never enter the vault or appear in the file list.",
        partial="ignored_files.html",
    ),
    SettingsHubTile(
        slug="network",
        title="Network",
        blurb="TCP port for this CreoPDM server on the LAN.",
        partial="network.html",
    ),
    SettingsHubTile(
        slug="agent",
        title="Local Creo agent",
        blurb="Agent base URL and how often the file list refreshes.",
        partial="agent.html",
    ),
    SettingsHubTile(
        slug="database",
        title="Database",
        blurb="Local SQLite by default, or a Postgres URL.",
        partial="database.html",
    ),
)


def settings_tile(slug: str) -> SettingsHubTile | None:
    key = (slug or "").strip().lower()
    for tile in SETTINGS_HUB_TILES:
        if tile.slug == key:
            return tile
    return None
