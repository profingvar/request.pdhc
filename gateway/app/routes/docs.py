"""Documentation page for request.pdhc — mirrors contract.pdhc's
card-grid layout. Lists manuals at the top level of `docs/` and
runbooks under `docs/runbooks/`. All Markdown files are downloadable.
"""
import os
from flask import Blueprint, render_template, send_from_directory, abort
from flask_login import login_required

docs_bp = Blueprint("docs", __name__)

DOCS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "docs"
)


# Curated metadata for the card view. Files NOT listed here still appear
# at the bottom under "Other documents" if they exist on disk.
MANUAL_META = {
    "operator-manual.md": {
        "icon":  "settings",
        "title": "Operator Manual",
        "desc":  "Start/stop, backup/restore, troubleshoot.",
    },
    "admin-manual.md": {
        "icon":  "shield",
        "title": "Admin Manual",
        "desc":  "Auth, user lifecycle, service-request CRUD.",
    },
    "api.md": {
        "icon":  "code",
        "title": "API Reference",
        "desc":  "Endpoint reference with examples.",
    },
    "architecture.md": {
        "icon":  "boxes",
        "title": "Architecture",
        "desc":  "Container topology, data model, security.",
    },
}

RUNBOOK_META = {
    "credential-rotation.md": {
        "icon":  "key-round",
        "title": "Credential Rotation",
        "desc":  "Rotate keys, passwords, PATs.",
    },
    "incident-response.md": {
        "icon":  "alert-triangle",
        "title": "Incident Response",
        "desc":  "Triage and recovery.",
    },
    "upgrade-procedure.md": {
        "icon":  "arrow-up-circle",
        "title": "Upgrade Procedure",
        "desc":  "Deploy steps and rollback.",
    },
}


def _scan(dir_path: str, meta: dict) -> tuple[list[dict], list[dict]]:
    """Return (curated, others) lists of {filename, title, icon, desc}.
    `curated` keeps the order of `meta`; `others` are leftover .md files
    not in `meta`, sorted alphabetically.
    """
    if not os.path.isdir(dir_path):
        return [], []
    on_disk = {f for f in os.listdir(dir_path) if f.endswith(".md")}
    curated = [
        {"filename": fn, **meta[fn]} for fn in meta if fn in on_disk
    ]
    others = [
        {
            "filename": fn,
            "icon":  "file-text",
            "title": fn.replace(".md", "").replace("-", " ").replace("_", " ").title(),
            "desc":  "",
        }
        for fn in sorted(on_disk - set(meta))
    ]
    return curated, others


@docs_bp.get("/docs")
@login_required
def docs_index():
    abs_dir = os.path.abspath(DOCS_DIR)
    manuals_curated, manuals_other = _scan(abs_dir, MANUAL_META)
    runbooks_curated, runbooks_other = _scan(
        os.path.join(abs_dir, "runbooks"), RUNBOOK_META
    )
    return render_template(
        "docs.html",
        manuals=manuals_curated,
        manuals_other=manuals_other,
        runbooks=runbooks_curated,
        runbooks_other=runbooks_other,
    )


@docs_bp.get("/docs/download/<path:filename>")
@login_required
def download_doc(filename: str):
    """Serve a Markdown file by relative path under DOCS_DIR.

    Accepts both top-level (`api.md`) and runbook (`runbooks/credential-rotation.md`)
    paths. Rejects anything outside DOCS_DIR or not ending in .md.
    """
    abs_dir = os.path.abspath(DOCS_DIR)
    target = os.path.abspath(os.path.join(abs_dir, filename))
    if not target.startswith(abs_dir + os.sep):
        abort(404)
    if not target.endswith(".md") or not os.path.isfile(target):
        abort(404)
    rel = os.path.relpath(target, abs_dir)
    rel_dir = os.path.dirname(rel)
    serve_dir = os.path.join(abs_dir, rel_dir) if rel_dir else abs_dir
    return send_from_directory(serve_dir, os.path.basename(rel), as_attachment=True)
