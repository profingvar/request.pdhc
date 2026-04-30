"""Rendered API reference page for request.pdhc.

Mirrors the content of `docs/api.md` but in a navigable HTML page.
The Markdown file remains the canonical source for downloads via the
`/docs` page; this page is for reading in-browser.
"""
from flask import Blueprint, render_template
from flask_login import login_required


api_docs_bp = Blueprint("api_docs", __name__)


@api_docs_bp.get("/api")
@login_required
def api_reference():
    return render_template("api_reference.html")
