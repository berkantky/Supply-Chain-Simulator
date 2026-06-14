"""
navigation.py
Einfache Navigation / Tabs für das Dashboard.
"""

from dash import html, dcc

# Importiere Layouts der Module (Platzhalter)
from . import layout_ddmrp, layout_heijunka, layout_case


def layout(app):
    """Gibt ein einfaches Tab-Layout zurück. App wird als Parameter übergeben, falls Callbacks benötigt werden."""
    tabs = dcc.Tabs([
        dcc.Tab(label='🟩 DDMRP', children=[layout_ddmrp.layout()]),
        dcc.Tab(label='🗓️ Heijunka', children=[layout_heijunka.layout()]),
        dcc.Tab(label='📚 Case Study', children=[layout_case.layout()]),
    ])

    return html.Div([
        html.Header(html.H1('Supply Chain Dashboard')),
        html.Div(tabs, style={'marginTop': '1rem'})
    ])
