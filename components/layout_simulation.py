"""
layout_simulation.py
Frontend für interaktive Bestellsimulation mit Plotly-Visualisierung.
"""

import pandas as pd
import plotly.graph_objects as go
from dash import html, dcc, Input, Output, State, callback
import dash

from utils.demand_simulator import run_simulation, get_product_colors, get_product_names


def layout():
    """Hauptlayout für die Simulationsseite."""
    
    return html.Div([
        html.H2('Bestellsimulation'),
        
        # Kontrollbereich
        html.Div([
            html.Div([
                html.Div([
                    html.Label('Anzahl der Tage:', style={'fontWeight': 'bold', 'color': '#5A9FBF'}),
                    dcc.Input(
                        id='sim-days-input',
                        type='number',
                        min=1,
                        max=365,
                        step=1,
                        value=30,
                        style={
                            'width': '100px',
                            'padding': '8px 12px',
                            'marginRight': '20px',
                            'border': '2px solid #D4E8F0',
                            'borderRadius': '6px',
                            'fontSize': '14px'
                        }
                    )
                ], style={'display': 'inline-block', 'marginRight': '40px'}),
                
                html.Div([
                    html.Label('Trend-Faktor:', style={'fontWeight': 'bold', 'color': '#5A9FBF', 'marginBottom': '10px', 'display': 'block'}),
                    dcc.Slider(
                        id='sim-trend-slider',
                        min=-10,
                        max=10,
                        step=1,
                        value=0,
                        marks={i: str(i) for i in range(-10, 11, 2)},
                        tooltip={"placement": "bottom", "always_visible": True}
                    )
                ], style={'display': 'inline-block', 'marginRight': '40px', 'width': '350px'}),
                
                html.Button(
                    '▶ Simulation ausführen',
                    id='sim-run-button',
                    n_clicks=0,
                    style={
                        'padding': '10px 25px',
                        'marginLeft': '20px',
                        'marginTop': '25px'
                    }
                ),
                html.Button(
                    '✅ Für globale Simulation übernehmen',
                    id='sim-apply-button',
                    n_clicks=0,
                    disabled=True,
                    style={
                        'padding': '10px 25px',
                        'marginLeft': '10px',
                        'marginTop': '25px',
                        'backgroundColor': '#51CF66',
                        'color': 'white',
                        'border': 'none',
                        'borderRadius': '6px',
                        'cursor': 'pointer',
                        'fontWeight': 'bold'
                    }
                )
            ], style={'paddingBottom': '10px'}),
        ], className='control-panel'),
        
        # Status-Nachricht für Übernahme
        html.Div(id='sim-apply-status', style={'marginBottom': '10px'}),
        
        # Zusammenfassung
        html.Div(id='sim-summary', className='summary-container', style={'marginBottom': '20px'}),
        
        # Graph
        html.Div([
            dcc.Graph(id='sim-graph', style={'height': '600px'})
        ], className='graph-container'),
        
        # Store für Simulationsdaten
        dcc.Store(id='sim-data-store')
    ], style={'padding': '20px'})


@callback(
    Output('sim-data-store', 'data'),
    Output('sim-summary', 'children'),
    Output('sim-apply-button', 'disabled'),
    Input('sim-run-button', 'n_clicks'),
    State('sim-days-input', 'value'),
    State('sim-trend-slider', 'value'),
    prevent_initial_call=True
)
def run_sim(n_clicks, num_days, trend):
    """Führt die Simulation aus und speichert die Daten."""
    
    if num_days is None or num_days < 1:
        num_days = 30
    if trend is None:
        trend = 0
    
    # Führe Simulation aus
    df, summary = run_simulation(num_days, trend)
    
    # Konvertiere DataFrame zu JSON für Store
    sim_data = {
        'df': df.to_json(date_format='iso', orient='split'),
        'summary': summary,
        'num_days': num_days,
        'trend': trend
    }
    
    # Erstelle Summary-HTML
    summary_content = html.Div([
        html.H4('📊 Simulationsergebnisse', style={'marginBottom': '15px'}),
        html.Div(id='summary-table', children=_create_summary_table(summary, num_days))
    ])
    
    # Aktiviere "Übernehmen" Button
    return sim_data, summary_content, False


@callback(
    Output('sim-apply-status', 'children'),
    Input('sim-apply-button', 'n_clicks'),
    State('sim-data-store', 'data'),
    State('global-simulation-state', 'data'),
    prevent_initial_call=True
)
def apply_simulation_to_global(n_clicks, sim_data, global_state):
    """Speichere simulierte Bestellungen für die globale Simulation."""
    import pandas as pd
    from io import StringIO
    from pathlib import Path
    
    if sim_data is None:
        return html.Div("⚠️ Keine Simulation vorhanden. Bitte zuerst Simulation ausführen.", 
                       style={'color': '#FF6B6B', 'padding': '10px', 'backgroundColor': '#FFE0E0', 'borderRadius': '6px'})
    
    # Lade Simulationsdaten
    df = pd.read_json(StringIO(sim_data['df']), orient='split')
    num_days = sim_data['num_days']
    
    # Hole aktuellen Tag aus globaler Simulation
    current_day = global_state.get('day', 1) if global_state else 1
    
    # Speichere in CSV - Tage relativ zum aktuellen Tag der globalen Simulation
    output_path = Path(__file__).parent.parent / 'data' / 'simulated_orders.csv'
    
    # Erstelle neues DataFrame mit absoluten Tagen
    output_df = df.copy()
    output_df['Day'] = output_df['Day'] + current_day  # Verschiebe Tage relativ zum aktuellen Tag
    
    # Speichere (überschreibe bestehende Simulation)
    output_df.to_csv(output_path, index=False)
    
    # Erstelle Bestätigungs-Nachricht
    end_day = current_day + num_days
    return html.Div([
        html.Span("✅ ", style={'fontSize': '1.2rem'}),
        html.Span(f"Simulation übernommen! Tage {current_day + 1} bis {end_day} sind jetzt festgelegt.", 
                  style={'fontWeight': 'bold'}),
        html.Br(),
        html.Span(f"Die nächsten {num_days} Tage der globalen Simulation verwenden diese Bestelldaten.", 
                  style={'fontSize': '0.9rem', 'color': '#666'})
    ], style={'color': '#2E7D32', 'padding': '10px', 'backgroundColor': '#E8F5E9', 'borderRadius': '6px', 'marginTop': '10px'})


@callback(
    Output('sim-graph', 'figure'),
    Input('sim-data-store', 'data'),
    State('sim-graph', 'figure')
)
def update_graph(sim_data, current_figure):
    """Aktualisiert das Liniendiagramm mit modernem Styling."""
    
    if sim_data is None:
        return go.Figure()
    
    # Lade Daten
    from io import StringIO
    df = pd.read_json(StringIO(sim_data['df']), orient='split')
    summary = sim_data['summary']
    
    # Erstelle Daten pro Produkt
    products = get_product_names()
    colors = get_product_colors()
    
    fig = go.Figure()
    
    # Füge Linie pro Produkt hinzu
    for product in products:
        fig.add_trace(go.Scatter(
            x=df['Day'],
            y=df[product],
            name=product,
            mode='lines+markers',
            line=dict(
                color=colors[product],
                width=3
            ),
            marker=dict(
                size=6,
                symbol='circle',
                line=dict(width=1, color=colors[product])
            ),
            hovertemplate='<b>%{fullData.name}</b><br>' +
                          'Tag: %{x}<br>' +
                          'Menge: %{y:.0f} Stück<extra></extra>',
            connectgaps=True
        ))
    
    # Update Layout mit modernem Design
    fig.update_layout(
        title={
            'text': 'Zeitlicher Verlauf der simulierten Nachfrage',
            'x': 0.5,
            'xanchor': 'center',
            'font': {'size': 16, 'color': '#5A9FBF', 'family': 'Segoe UI'}
        },
        xaxis=dict(
            title={
                'text': 'Tag',
                'font': {'size': 13, 'color': '#5A9FBF', 'family': 'Segoe UI'}
            },
            tickfont=dict(size=11, color='#5D6D7B'),
            gridcolor='#E8F4F8',
            showgrid=True,
            zeroline=False
        ),
        yaxis=dict(
            title={
                'text': 'Nachfragemenge (Stück)',
                'font': {'size': 13, 'color': '#5A9FBF', 'family': 'Segoe UI'}
            },
            tickfont=dict(size=11, color='#5D6D7B'),
            gridcolor='#E8F4F8',
            showgrid=True,
            zeroline=False
        ),
        hovermode='x unified',
        height=600,
        template='plotly_white',
        plot_bgcolor='rgba(240, 248, 251, 0.5)',
        paper_bgcolor='white',
        margin=dict(l=80, r=80, t=80, b=80),
        legend=dict(
            yanchor="top",
            y=0.98,
            xanchor="right",
            x=0.98,
            bgcolor='rgba(255, 255, 255, 0.9)',
            bordercolor='#D4E8F0',
            borderwidth=1,
            font=dict(size=12, color='#2C3E50', family='Segoe UI')
        ),
        font=dict(family='Segoe UI', size=12, color='#2C3E50')
    )
    
    return fig


def _create_summary_table(summary: dict, num_days: int) -> html.Table:
    """Erstellt eine HTML-Tabelle mit der Zusammenfassung."""
    
    rows = []
    
    # Header-Reihe
    rows.append(html.Tr([
        html.Th('Produkt', style={'textAlign': 'left'}),
        html.Th('Summe', style={'textAlign': 'center'}),
        html.Th('ADU (Ø/Tag)', style={'textAlign': 'center'})
    ]))
    
    # Daten-Reihen
    for product, data in summary.items():
        rows.append(html.Tr([
            html.Td(product, style={'fontWeight': 'bold', 'color': '#5A9FBF'}),
            html.Td(f"{data['Summe']:,.0f}", style={'textAlign': 'center'}),
            html.Td(f"{data['ADU']:.2f}", style={'textAlign': 'center', 'color': '#5A9FBF', 'fontWeight': '500'})
        ]))
    
    return html.Table(rows, style={
        'borderCollapse': 'collapse',
        'marginTop': '15px',
        'width': '100%'
    })