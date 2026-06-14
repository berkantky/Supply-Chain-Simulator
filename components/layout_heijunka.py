"""
layout_heijunka.py
Heijunka-Ansicht mit Overflow-Board Integration.
"""

from dash import html, dcc
from components import layout_overflow


def layout():
    """Heijunka-Tab mit Overflow-Board"""
    return html.Div([
        dcc.Tabs([
            dcc.Tab(label='🅰️ Loop A (Antiebswelle)', children=[
                layout_overflow.layout_loop_a()
            ]),
            dcc.Tab(label='🅱️ Loop B (Autogetriebe)', children=[
                layout_overflow.layout_loop_b()
            ])
        ], style={'borderRadius': '10px', 'overflow': 'hidden', 'backgroundColor': 'white'},
           colors={'border': '#d7e3ef', 'primary': '#5A9FBF', 'background': '#ffffff'})
    ], style={'padding': '1rem', 'backgroundColor': '#f4f7fb', 'borderRadius': '12px'})
