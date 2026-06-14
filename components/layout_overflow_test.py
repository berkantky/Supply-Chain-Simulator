"""
components/layout_overflow_test.py

Test-Tab mit Tages-Simulator und Heutige Bestellungen/Produktion.
Zeigt die simulierten Daten aus dem globalen Simulator.
"""

import pandas as pd
import numpy as np
from dash import html, dcc, callback, Input, Output, State
import plotly.graph_objects as go
from pathlib import Path

from utils.overflow_simulator import (
    load_or_create_simulation_state, simulate_next_day, 
    save_simulation_to_csv, reset_simulation
)

# ============================================================================
# Chart Creation Functions
# ============================================================================

def create_board_status_chart(board_state: dict = None):
    """Erstelle Chart mit aktuellem Overflow-Board Status"""
    
    if not board_state:
        board_state = {}
    
    if not board_state:
        return go.Figure().add_annotation(text="Kein Board-Status verfügbar")
    
    products = list(board_state.keys())
    greens = [board_state[p]['green_current'] for p in products]
    yellows = [board_state[p]['yellow_current'] for p in products]
    reds = [board_state[p]['red_current'] for p in products]
    
    fig = go.Figure(data=[
        go.Bar(name='Grün', x=products, y=greens, 
               marker_color='#51CF66', hovertemplate='%{x}<br>Grün: %{y}<extra></extra>'),
        go.Bar(name='Gelb', x=products, y=yellows, 
               marker_color='#FFD700', hovertemplate='%{x}<br>Gelb: %{y}<extra></extra>'),
        go.Bar(name='Rot', x=products, y=reds, 
               marker_color='#FF6B6B', hovertemplate='%{x}<br>Rot: %{y}<extra></extra>')
    ])
    
    fig.update_layout(
        barmode='stack',
        title='Aktueller Overflow-Board Status (Kanban-Verteilung)',
        xaxis_title='Produkte',
        yaxis_title='Kanban-Anzahl',
        hovermode='x unified',
        height=350,
        margin=dict(b=80, l=50, r=20, t=50),
        xaxis_tickangle=-45,
        font=dict(size=10),
        showlegend=True,
        legend=dict(yanchor='top', y=0.99, xanchor='right', x=0.99)
    )
    
    return fig


# ============================================================================
# Main Layout
# ============================================================================

def layout():
    """Overflow-Board Test Layout mit Tages-Simulator"""
    
    # Lade aktuellen Simulationszustand
    try:
        state = load_or_create_simulation_state()
        board_state = state.board.to_dict() if state.board else {}
        current_day = state.current_day
    except:
        board_state = {}
        current_day = 1
    
    return html.Div([
        # Store für Simulationszustand
        dcc.Store(id='overflow-test-simulation-state', data={'day': current_day, 'board': board_state}),
        
        html.H2(
            '🧪 Overflow-Board Test & Tages-Simulator',
            style={'marginBottom': '1rem', 'color': '#2c3e50'}
        ),
        
        html.Div(
            'Tägliche Simulation der Kanban-Verwaltung mit Verbrauch → Produktion. Zeigt simulierte Bestellungen und Produktionspläne pro Tag.',
            style={'marginBottom': '2rem', 'color': '#666', 'fontStyle': 'italic'}
        ),
        
        # Steuerungselemente
        html.Div([
            html.Div([
                html.Div([
                    html.Span("Aktueller Tag: ", style={'fontWeight': 'bold', 'marginRight': '0.5rem'}),
                    html.Span(id='overflow-test-day-display', children=str(current_day), style={'fontSize': '1.2rem', 'color': '#5A9FBF', 'fontWeight': 'bold'})
                ], style={'marginBottom': '1rem', 'display': 'flex', 'alignItems': 'center'}),
                
                html.Label('Tagesweise Simulation:', style={'fontWeight': 'bold', 'marginBottom': '0.5rem', 'display': 'block'}),
                html.Div([
                    html.Button(
                        '▶️ Nächster Tag simulieren',
                        id='btn-overflow-test-next-day',
                        style={
                            'padding': '0.75rem 1.5rem',
                            'backgroundColor': '#5A9FBF',
                            'color': 'white',
                            'border': 'none',
                            'borderRadius': '4px',
                            'cursor': 'pointer',
                            'fontWeight': 'bold',
                            'marginRight': '1rem'
                        }
                    ),
                    html.Button(
                        '💾 Daten speichern (CSV)',
                        id='btn-overflow-test-export-csv',
                        style={
                            'padding': '0.75rem 1.5rem',
                            'backgroundColor': '#51CF66',
                            'color': 'white',
                            'border': 'none',
                            'borderRadius': '4px',
                            'cursor': 'pointer',
                            'fontWeight': 'bold',
                            'marginRight': '1rem'
                        }
                    ),
                    html.Button(
                        '🔄 Simulation zurücksetzen',
                        id='btn-overflow-test-reset-simulation',
                        style={
                            'padding': '0.75rem 1.5rem',
                            'backgroundColor': '#999',
                            'color': 'white',
                            'border': 'none',
                            'borderRadius': '4px',
                            'cursor': 'pointer',
                            'fontWeight': 'bold'
                        }
                    )
                ], style={'display': 'flex', 'alignItems': 'center'})
            ], style={'marginBottom': '1rem'})
        ], style={
            'backgroundColor': 'white',
            'padding': '1.5rem',
            'borderRadius': '8px',
            'boxShadow': '0 2px 4px rgba(0,0,0,0.1)',
            'marginBottom': '1.5rem'
        }),
        
        # Tages-Status: Heutige Bestellungen und Produktion
        html.Div(id='overflow-test-daily-summary-container', children=[
            html.Div([
                html.Div([
                    html.H4('📦 Heutige Bestellungen', style={'marginBottom': '0.5rem', 'color': '#2c3e50'}),
                    html.Div(id='overflow-test-today-orders-text', children="Keine Simulation gestartet")
                ], style={'flex': 1, 'marginRight': '1rem', 'backgroundColor': '#f8f9fa', 'padding': '1rem', 'borderRadius': '6px', 'borderLeft': '3px solid #5A9FBF'}),
                html.Div([
                    html.H4("⚙️ Heutige Produktion", style={'marginBottom': '0.5rem', 'color': '#2c3e50'}),
                    html.Div(id='overflow-test-today-production-text', children="Keine Simulation gestartet")
                ], style={'flex': 1, 'backgroundColor': '#f8f9fa', 'padding': '1rem', 'borderRadius': '6px', 'borderLeft': '3px solid #51CF66'})
            ], style={'display': 'flex', 'marginBottom': '1.5rem'})
        ]),
        
        # Board Status Chart
        html.Div([
            dcc.Graph(id='overflow-test-board-status-chart', figure=create_board_status_chart(board_state))
        ], style={
            'backgroundColor': 'white',
            'padding': '1.5rem',
            'borderRadius': '8px',
            'boxShadow': '0 2px 6px rgba(0,0,0,0.08)'
        })
    ], style={'padding': '2rem'})


# ============================================================================
# Callbacks
# ============================================================================

@callback(
    [Output('overflow-test-simulation-state', 'data'),
     Output('overflow-test-day-display', 'children'),
     Output('overflow-test-board-status-chart', 'figure'),
     Output('overflow-test-today-orders-text', 'children'),
     Output('overflow-test-today-production-text', 'children')],
    [Input('btn-overflow-test-next-day', 'n_clicks'),
     Input('btn-overflow-test-reset-simulation', 'n_clicks'),
     Input('btn-overflow-test-export-csv', 'n_clicks')],
    prevent_initial_call=True
)
def update_overflow_test_simulation(n_next, n_reset, n_export):
    """Aktualisiere Overflow-Test Simulationszustand basierend auf Button-Klicks"""
    from dash import callback_context
    
    ctx = callback_context
    if not ctx.triggered:
        raise Exception("Kein Trigger")
    
    trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    # Lade aktuellen Zustand
    state = load_or_create_simulation_state()
    
    if trigger_id == 'btn-overflow-test-reset-simulation':
        # Setze zurück
        state = reset_simulation()
        today_orders_html = html.Div("Simulation zurückgesetzt", style={'color': '#999', 'fontStyle': 'italic'})
        today_production_html = html.Div("Simulation zurückgesetzt", style={'color': '#999', 'fontStyle': 'italic'})
    
    elif trigger_id == 'btn-overflow-test-next-day':
        # Simuliere nächsten Tag
        state, daily_orders, daily_production = simulate_next_day(state)
        
        # Formatiere Bestellungen
        if daily_orders:
            orders_text = html.Div([
                html.Div(f"{prod}: {qty} Stück", style={'fontSize': '0.9rem', 'marginBottom': '0.3rem'})
                for prod, qty in sorted(daily_orders.items())
            ])
        else:
            orders_text = html.Div("Keine Bestellungen", style={'color': '#999', 'fontStyle': 'italic'})
        
        today_orders_html = orders_text
        
        # Formatiere Produktion
        if daily_production:
            production_text = html.Div([
                html.Div(f"{prod}: {qty} Kanbans", style={'fontSize': '0.9rem', 'marginBottom': '0.3rem'})
                for prod, qty in sorted(daily_production.items())
            ])
        else:
            production_text = html.Div("Keine Produktion", style={'color': '#999', 'fontStyle': 'italic'})
        
        today_production_html = production_text
    
    elif trigger_id == 'btn-overflow-test-export-csv':
        # Exportiere zu CSV
        save_simulation_to_csv(state)
        today_orders_html = html.Div("✓ Daten in outputs/ gespeichert (daily_orders_log.csv, daily_production_log.csv, current_board_state.csv)", style={'color': '#51CF66', 'fontWeight': 'bold'})
        today_production_html = html.Div("")
    
    # Aktualisiere Charts
    board_state = state.board.to_dict() if state.board else {}
    board_chart = create_board_status_chart(board_state)
    
    state_data = {
        'day': state.current_day,
        'board': board_state
    }
    
    return state_data, str(state.current_day), board_chart, today_orders_html, today_production_html
