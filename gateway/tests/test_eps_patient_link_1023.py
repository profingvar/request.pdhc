"""#1023: the patient link on the service-request view follows the configured
EPS address instead of a literal ips.pdhc.se host.

The view needs a full order to render, so the link cell is rendered on its own
from the real template source, and the route is checked on its parse tree.
"""
import ast
import os
import re

from jinja2 import Environment

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, '..', 'app', 'templates', 'service_requests', 'view.html')
ROUTE = os.path.join(HERE, '..', 'app', 'routes', 'service_requests.py')


def _link_cell():
    src = open(TEMPLATE).read()
    m = re.search(r'<td>\{% if eps_admin_base and patient_id %\}.*?\{% endif %\}</td>', src)
    assert m, 'patient link cell not found in view.html'
    return m.group(0)


def _render(**ctx):
    return Environment(autoescape=True).from_string(_link_cell()).render(**ctx)


def test_no_literal_ips_host_left_in_the_view():
    assert 'ips.pdhc.se' not in open(TEMPLATE).read()


def test_link_uses_the_configured_base():
    html = _render(eps_admin_base='https://eps.pdhc.se', patient_id='p-1')
    assert 'href="https://eps.pdhc.se/admin/patients/p-1"' in html


def test_old_base_still_works_during_the_transition():
    html = _render(eps_admin_base='https://ips.pdhc.se', patient_id='p-1')
    assert 'href="https://ips.pdhc.se/admin/patients/p-1"' in html


def test_unset_base_shows_no_link_rather_than_a_guessed_host():
    assert '<a ' not in _render(eps_admin_base='', patient_id='p-1')


def test_route_passes_eps_admin_base_from_config():
    tree = ast.parse(open(ROUTE).read())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, 'id', '') == 'render_template'
             and n.args and isinstance(n.args[0], ast.Constant)
             and n.args[0].value == 'service_requests/view.html']
    assert calls, 'render_template for view.html not found'
    kw = {k.arg: k.value for k in calls[0].keywords}
    assert 'eps_admin_base' in kw
    assert "'IPS_BASE_URL'" in ast.unparse(kw['eps_admin_base'])
