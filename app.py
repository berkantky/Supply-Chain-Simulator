"""
app.py
Dash-App mit globaler Navigationsleiste für Tages-Simulation.
Tabs: DDMRP, Heijunka, Bestellsimulation
"""

from dash import Dash, dcc, html, callback, Input, Output, State, ctx
from components import layout_dashboard, layout_ddmrp, layout_heijunka, layout_simulation, layout_einkauf, layout_finanzen, layout_csv_editor, layout_production
from utils.overflow_simulator import load_or_create_simulation_state, simulate_next_day, reset_simulation, jump_to_day, get_max_simulated_day, execute_production_for_today

app = Dash(__name__, assets_folder='assets', suppress_callback_exceptions=True)
app.title = "Supply Chain Dashboard"
server = app.server




def _planned_snapshot_from_board_state(board_state: dict) -> dict:
    snapshot = {}
    for product, data in (board_state or {}).items():
        snapshot[product] = int((data or {}).get('current_total', 0) or 0)
    return snapshot


def _current_day_execution_state(state) -> dict:
    executed_days = set(getattr(state, 'production_executed_days', []) or [])
    current_day_executed = state.current_day in executed_days
    if not current_day_executed:
        return {
            'production_executed': {},
            'production_executed_a': {},
            'production_shortages': {},
            'production_shortages_a': {},
        }
    return {
        'production_executed': state.daily_production_executed[-1] if getattr(state, 'daily_production_executed', None) else {},
        'production_executed_a': state.daily_production_executed_a[-1] if getattr(state, 'daily_production_executed_a', None) else {},
        'production_shortages': state.daily_production_shortages[-1] if getattr(state, 'daily_production_shortages', None) else {},
        'production_shortages_a': state.daily_production_shortages_a[-1] if getattr(state, 'daily_production_shortages_a', None) else {},
    }

def build_initial_state_data():
    """Lade den aktuellen Zustand aus dem Speicher für konsistente Page-Reloads."""
    state = load_or_create_simulation_state()
    exec_state = _current_day_execution_state(state)

    # Hole letzte daily_orders falls vorhanden
    last_daily_orders = {}
    if state.daily_orders_history and len(state.daily_orders_history) > 0:
        last_daily_orders = state.daily_orders_history[-1]
    else:
        # Initialisiere ersten Tag, damit Charts nicht leer bleiben
        state, daily_orders, daily_production = simulate_next_day(state)
        last_daily_orders = daily_orders

    # Hole letzten Materialverbrauch
    last_consumption = {}
    if hasattr(state, 'material_consumption') and state.material_consumption.daily_consumption:
        last_day = state.current_day - 1
        if last_day in state.material_consumption.daily_consumption:
            last_consumption = state.material_consumption.daily_consumption[last_day]

    state_data = {
        'day': state.current_day,
        'board': state.board.to_dict() if state.board else {},
        'board_a': state.board_a.to_dict() if getattr(state, 'board_a', None) else {},
        'daily_orders': last_daily_orders,
        'daily_production': state.daily_production_history[-1] if state.daily_production_history else {},
        'daily_replenishment': state.daily_replenishment_history[-1] if getattr(state, 'daily_replenishment_history', None) else {},
        'daily_replenishment_a': state.daily_replenishment_history_a[-1] if getattr(state, 'daily_replenishment_history_a', None) else {},
        'replenishment_cards': state.daily_replenishment_cards_history[-1] if getattr(state, 'daily_replenishment_cards_history', None) else [],
        'replenishment_cards_a': state.daily_replenishment_cards_history_a[-1] if getattr(state, 'daily_replenishment_cards_history_a', None) else [],
        'material_consumption': last_consumption,
        'daily_production_a': state.daily_production_history_a[-1] if getattr(state, 'daily_production_history_a', None) else {},
        'production_executed': exec_state['production_executed'],
        'production_executed_a': exec_state['production_executed_a'],
        'production_shortages': exec_state['production_shortages'],
        'production_shortages_a': exec_state['production_shortages_a'],
        'production_consumption': state.booked_material_consumption.daily_consumption.get(state.current_day, {}) if hasattr(state, 'booked_material_consumption') else {},
        'planned_snapshot': _planned_snapshot_from_board_state(state.board.to_dict() if state.board else {}),
        'planned_snapshot_a': _planned_snapshot_from_board_state(state.board_a.to_dict() if getattr(state, 'board_a', None) else {}),
        'production_status': ''
    }
    return state, state_data

# Layout mit globaler Navigationsleiste und Tabs
def serve_layout():
    state, initial_state_data = build_initial_state_data()

    return html.Div([
        # Global Store für Simulationszustand - mit initialem Zustand
        dcc.Store(id='global-simulation-state', data=initial_state_data),
        dcc.Interval(id='global-simulation-interval', interval=500, n_intervals=0),
        
        # Header mit globaler Navigationsleiste
        html.Div([
            html.Div([
                # Logo und Titel
                html.Div([
                    html.H1('Supply Chain Dashboard', className='header-title', style={'display': 'block', 'color': 'white', 'marginBottom': '0', 'fontSize': '2rem', 'fontWeight': '700', 'letterSpacing': '-0.5px'}),
                ], style={'marginRight': '2rem'}),
                html.Div([
                    html.Span("Tag: ", style={'fontWeight': 'bold', 'marginRight': '0.5rem', 'color': 'white'}),
                    html.Span(id='global-day-display', children=str(state.current_day), style={'fontSize': '1.2rem', 'color': '#FFD700', 'fontWeight': 'bold', 'marginRight': '1rem', 'textShadow': '0 0 10px rgba(255,215,0,0.5)'})
                ], style={'display': 'flex', 'alignItems': 'center'}),
                
                # Tag-Auswahl
                html.Div([
                    dcc.Input(
                        id='jump-to-day-input',
                        type='number',
                        min=1,
                        placeholder='Tag',
                        style={
                            'width': '70px',
                            'padding': '0.5rem',
                            'borderRadius': '4px',
                            'border': '2px solid #FFD700',
                            'fontSize': '0.9rem',
                            'marginRight': '0.5rem'
                        }
                    ),
                    html.Button(
                        '⏩ Gehe zu Tag',
                        id='btn-jump-to-day',
                        className='btn btn-primary',
                        style={
                            'padding': '0.6rem 1.2rem',
                            'background': 'linear-gradient(135deg, #4A90D9 0%, #3A7BC8 100%)',
                            'color': 'white',
                            'border': 'none',
                            'borderRadius': '8px',
                            'cursor': 'pointer',
                            'fontWeight': '600',
                            'fontSize': '0.85rem',
                            'marginRight': '1.5rem',
                            'boxShadow': '0 4px 12px rgba(74, 144, 217, 0.3)',
                            'transition': 'all 0.25s ease'
                        }
                    )
                ], style={'display': 'flex', 'alignItems': 'center'}),
                
                html.Div([
                    html.Button(
                        '▶️ Nächster Tag',
                        id='btn-global-next-day',
                        className='btn btn-success',
                        style={
                            'padding': '0.7rem 1.4rem',
                            'background': 'linear-gradient(135deg, #51CF66 0%, #40C057 100%)',
                            'color': 'white',
                            'border': 'none',
                            'borderRadius': '8px',
                            'cursor': 'pointer',
                            'fontWeight': '600',
                            'fontSize': '0.9rem',
                            'marginRight': '0.75rem',
                            'boxShadow': '0 4px 12px rgba(81, 207, 102, 0.3)',
                            'transition': 'all 0.25s ease'
                        }
                    ),
                    html.Button(
                        '🔄 Reset',
                        id='btn-reset-simulation',
                        className='btn btn-danger',
                        style={
                            'padding': '0.7rem 1.4rem',
                            'background': 'linear-gradient(135deg, #FF6B6B 0%, #F03E3E 100%)',
                            'color': 'white',
                            'border': 'none',
                            'borderRadius': '8px',
                            'cursor': 'pointer',
                            'fontWeight': '600',
                            'fontSize': '0.9rem',
                            'boxShadow': '0 4px 12px rgba(255, 107, 107, 0.3)',
                            'transition': 'all 0.25s ease'
                        }
                    )
                ], style={'display': 'flex'})
            ], style={'display': 'flex', 'alignItems': 'center', 'justifyContent': 'space-between', 'flexWrap': 'wrap', 'gap': '1rem'})
        ], className='app-header', style={
            'background': 'linear-gradient(135deg, #5A9FBF 0%, #2C5F7C 100%)',
            'padding': '1.25rem 2rem',
            'marginBottom': '1rem',
            'borderRadius': '12px',
            'boxShadow': '0 6px 20px rgba(0,0,0,0.12)',
            'position': 'relative'
        }),
        
        # Status-Meldung für Tag-Sprung
        html.Div(
            id='jump-status-message',
            children=html.Button('x', id='dismiss-status', n_clicks=0, style={'display': 'none'}),
            style={'marginBottom': '1rem'}
        ),
        
        # Tabs
        dcc.Tabs([
            dcc.Tab(label='📊 Übersicht', children=[
                layout_dashboard.layout()
            ]),
            dcc.Tab(label='🟩 DDMRP', children=[
                layout_ddmrp.layout()
            ]),
            dcc.Tab(label='🛒 Einkauf', children=[
                layout_einkauf.layout()
            ]),
            dcc.Tab(label='🗓️ Heijunka', children=[
                layout_heijunka.layout()
            ]),
            dcc.Tab(label='🏭 Produktion', children=[
                layout_production.layout()
            ]),
            dcc.Tab(label='🎲 Bestellsimulation', children=[
                layout_simulation.layout()
            ]),
            dcc.Tab(label='💰 Finanzen', children=[
                layout_finanzen.layout()
            ]),
            dcc.Tab(label='🧾 CSV Editor', children=[
                layout_csv_editor.layout()
            ]),
        ], style={'marginTop': '1rem'})
    ], style={'padding': '1rem'})

app.layout = serve_layout


def _wrap_status_message(content, style):
    return html.Div([
        html.Div(content, style={'flex': '1'}),
        html.Button('x', id='dismiss-status', n_clicks=0, style={
            'background': 'transparent',
            'border': 'none',
            'fontSize': '1.1rem',
            'fontWeight': 'bold',
            'cursor': 'pointer',
            'color': style.get('color', '#333')
        })
    ], style={
        **style,
        'display': 'flex',
        'alignItems': 'center',
        'gap': '0.75rem'
    })


# ============================================================================
# Global Callbacks
# ============================================================================

@callback(
    [Output('global-simulation-state', 'data'),
     Output('global-day-display', 'children'),
     Output('jump-status-message', 'children')],
    [Input('btn-global-next-day', 'n_clicks'),
     Input('btn-reset-simulation', 'n_clicks'),
     Input('btn-jump-to-day', 'n_clicks'),
     Input('btn-execute-production', 'n_clicks'),
     Input('dismiss-status', 'n_clicks')],
    [State('jump-to-day-input', 'value'),
     State('global-simulation-state', 'data')],
    prevent_initial_call=True
)
def update_global_simulation(n_clicks_next, n_clicks_reset, n_clicks_jump, n_clicks_production, n_clicks_dismiss, target_day, state_data):
    """Globale Simulation - wird ausgeführt und aktualisiert alle Tabs"""
    
    triggered_id = ctx.triggered_id
    if triggered_id == 'dismiss-status':
        if not isinstance(state_data, dict):
            state = load_or_create_simulation_state()
            exec_state = _current_day_execution_state(state)
            state_data = {
                'day': state.current_day,
                'board': state.board.to_dict() if state.board else {},
                'board_a': state.board_a.to_dict() if getattr(state, 'board_a', None) else {},
                'daily_orders': state.daily_orders_history[-1] if state.daily_orders_history else {},
                'daily_production': state.daily_production_history[-1] if state.daily_production_history else {},
                'daily_replenishment': state.daily_replenishment_history[-1] if getattr(state, 'daily_replenishment_history', None) else {},
                'daily_replenishment_a': state.daily_replenishment_history_a[-1] if getattr(state, 'daily_replenishment_history_a', None) else {},
                'replenishment_cards': state.daily_replenishment_cards_history[-1] if getattr(state, 'daily_replenishment_cards_history', None) else [],
                'replenishment_cards_a': state.daily_replenishment_cards_history_a[-1] if getattr(state, 'daily_replenishment_cards_history_a', None) else [],
                'material_consumption': state.material_consumption.daily_consumption.get(state.current_day - 1, {}),
                'daily_production_a': state.daily_production_history_a[-1] if getattr(state, 'daily_production_history_a', None) else {},
                'production_executed': exec_state['production_executed'],
                'production_executed_a': exec_state['production_executed_a'],
                'production_shortages': exec_state['production_shortages'],
                'production_shortages_a': exec_state['production_shortages_a'],
                'production_consumption': state.booked_material_consumption.daily_consumption.get(state.current_day, {}) if hasattr(state, 'booked_material_consumption') else {},
                'planned_snapshot': state_data.get('planned_snapshot') if isinstance(state_data, dict) else _planned_snapshot_from_board_state(state.board.to_dict() if state.board else {}),
                'planned_snapshot_a': state_data.get('planned_snapshot_a') if isinstance(state_data, dict) else _planned_snapshot_from_board_state(state.board_a.to_dict() if getattr(state, 'board_a', None) else {}),
                'production_status': ''
            }
        return state_data, str(state_data.get('day', 1)), ''

    
    if triggered_id == 'btn-reset-simulation':
        # Reset Simulation - startet bei Tag 1 mit Bestellungen
        state, daily_orders, daily_production = reset_simulation()
        exec_state = _current_day_execution_state(state)
        state_data = {
            'day': state.current_day,
            'board': state.board.to_dict() if state.board else {},
            'board_a': state.board_a.to_dict() if getattr(state, 'board_a', None) else {},
            'daily_orders': daily_orders,
            'daily_production': daily_production,
            'daily_replenishment': state.daily_replenishment_history[-1] if getattr(state, 'daily_replenishment_history', None) else {},
            'daily_replenishment_a': state.daily_replenishment_history_a[-1] if getattr(state, 'daily_replenishment_history_a', None) else {},
            'replenishment_cards': state.daily_replenishment_cards_history[-1] if getattr(state, 'daily_replenishment_cards_history', None) else [],
            'replenishment_cards_a': state.daily_replenishment_cards_history_a[-1] if getattr(state, 'daily_replenishment_cards_history_a', None) else [],
            'material_consumption': state.material_consumption.daily_consumption.get(state.current_day - 1, {}),
            'daily_production_a': state.daily_production_history_a[-1] if getattr(state, 'daily_production_history_a', None) else {},
            'production_executed': exec_state['production_executed'],
            'production_executed_a': exec_state['production_executed_a'],
            'production_shortages': exec_state['production_shortages'],
            'production_shortages_a': exec_state['production_shortages_a'],
            'production_consumption': state.booked_material_consumption.daily_consumption.get(state.current_day, {}) if hasattr(state, 'booked_material_consumption') else {},
            'planned_snapshot': _planned_snapshot_from_board_state(state.board.to_dict() if state.board else {}),
            'planned_snapshot_a': _planned_snapshot_from_board_state(state.board_a.to_dict() if getattr(state, 'board_a', None) else {}),
            'production_status': ''
        }
        return state_data, str(state.current_day), _wrap_status_message("Simulation zurückgesetzt auf Tag 1.",
            {'color': '#2E7D32', 'padding': '10px', 'backgroundColor': '#E8F5E9', 'borderRadius': '6px', 'margin': '0 2rem'})
    
    if triggered_id == 'btn-jump-to-day':
        # Springe zu einem bestimmten Tag
        if target_day is None or target_day < 1:
            state = load_or_create_simulation_state()
            exec_state = _current_day_execution_state(state)
            state_data = {
                'day': state.current_day,
                'board': state.board.to_dict() if state.board else {},
                'board_a': state.board_a.to_dict() if getattr(state, 'board_a', None) else {},
                'daily_orders': state.daily_orders_history[-1] if state.daily_orders_history else {},
                'daily_production': state.daily_production_history[-1] if state.daily_production_history else {},
                'daily_replenishment': state.daily_replenishment_history[-1] if getattr(state, 'daily_replenishment_history', None) else {},
                'daily_replenishment_a': state.daily_replenishment_history_a[-1] if getattr(state, 'daily_replenishment_history_a', None) else {},
                'replenishment_cards': state.daily_replenishment_cards_history[-1] if getattr(state, 'daily_replenishment_cards_history', None) else [],
                'replenishment_cards_a': state.daily_replenishment_cards_history_a[-1] if getattr(state, 'daily_replenishment_cards_history_a', None) else [],
                'material_consumption': state.material_consumption.daily_consumption.get(state.current_day - 1, {}),
                'daily_production_a': state.daily_production_history_a[-1] if getattr(state, 'daily_production_history_a', None) else {},
                'production_executed': exec_state['production_executed'],
                'production_executed_a': exec_state['production_executed_a'],
                'production_shortages': exec_state['production_shortages'],
                'production_shortages_a': exec_state['production_shortages_a'],
                'production_consumption': state.booked_material_consumption.daily_consumption.get(state.current_day, {}) if hasattr(state, 'booked_material_consumption') else {},
                'planned_snapshot': state_data.get('planned_snapshot') if isinstance(state_data, dict) else _planned_snapshot_from_board_state(state.board.to_dict() if state.board else {}),
                'planned_snapshot_a': state_data.get('planned_snapshot_a') if isinstance(state_data, dict) else _planned_snapshot_from_board_state(state.board_a.to_dict() if getattr(state, 'board_a', None) else {}),
                'production_status': ''
            }
            return state_data, str(state.current_day), _wrap_status_message("Bitte gib einen gueltigen Tag ein (mindestens 1).",
                {'color': '#FF6B6B', 'padding': '10px', 'backgroundColor': '#FFE0E0', 'borderRadius': '6px', 'margin': '0 2rem'})
        
        state, daily_orders, daily_production, error_msg = jump_to_day(int(target_day))
        exec_state = _current_day_execution_state(state)

        state_data = {
            'day': state.current_day,
            'board': state.board.to_dict() if state.board else {},
            'board_a': state.board_a.to_dict() if getattr(state, 'board_a', None) else {},
            'daily_orders': daily_orders,
            'daily_production': daily_production,
            'daily_replenishment': state.daily_replenishment_history[-1] if getattr(state, 'daily_replenishment_history', None) else {},
            'daily_replenishment_a': state.daily_replenishment_history_a[-1] if getattr(state, 'daily_replenishment_history_a', None) else {},
            'replenishment_cards': state.daily_replenishment_cards_history[-1] if getattr(state, 'daily_replenishment_cards_history', None) else [],
            'replenishment_cards_a': state.daily_replenishment_cards_history_a[-1] if getattr(state, 'daily_replenishment_cards_history_a', None) else [],
            'material_consumption': state.material_consumption.daily_consumption.get(state.current_day - 1, {}),
            'daily_production_a': state.daily_production_history_a[-1] if getattr(state, 'daily_production_history_a', None) else {},
            'production_executed': exec_state['production_executed'],
            'production_executed_a': exec_state['production_executed_a'],
            'production_shortages': exec_state['production_shortages'],
            'production_shortages_a': exec_state['production_shortages_a'],
            'production_consumption': state.booked_material_consumption.daily_consumption.get(state.current_day, {}) if hasattr(state, 'booked_material_consumption') else {},
            'planned_snapshot': _planned_snapshot_from_board_state(state.board.to_dict() if state.board else {}),
            'planned_snapshot_a': _planned_snapshot_from_board_state(state.board_a.to_dict() if getattr(state, 'board_a', None) else {}),
            'production_status': ''
        }
        
        if error_msg:
            return state_data, str(state.current_day), _wrap_status_message(error_msg,
                {'color': '#FF6B6B', 'padding': '10px', 'backgroundColor': '#FFE0E0', 'borderRadius': '6px', 'margin': '0 2rem'})
        
        max_sim = get_max_simulated_day()
        return state_data, str(state.current_day), _wrap_status_message([
            html.Span(f"Erfolgreich zu Tag {state.current_day} gesprungen. "),
            html.Span(f"(Vorausberechnete Tage bis: {max_sim})", style={'color': '#666', 'fontSize': '0.9rem'})
        ], {'color': '#2E7D32', 'padding': '10px', 'backgroundColor': '#E8F5E9', 'borderRadius': '6px', 'margin': '0 2rem'})
    
    if triggered_id == 'btn-execute-production':
        state = load_or_create_simulation_state()
        planned_b = int(getattr(state, 'heijunka_planned_day_b', 0) or 0)
        planned_a = int(getattr(state, 'heijunka_planned_day_a', 0) or 0)
        if not (planned_b == state.current_day and planned_a == state.current_day):
            message = "Bitte zuerst Heijunka planen (Loop A und Loop B), bevor Produzieren erlaubt ist."
            exec_state = _current_day_execution_state(state)
            state_data = {
                'day': state.current_day,
                'board': state.board.to_dict() if state.board else {},
                'board_a': state.board_a.to_dict() if getattr(state, 'board_a', None) else {},
                'daily_orders': state.daily_orders_history[-1] if state.daily_orders_history else {},
                'daily_production': state.daily_production_history[-1] if state.daily_production_history else {},
                'daily_replenishment': state.daily_replenishment_history[-1] if getattr(state, 'daily_replenishment_history', None) else {},
                'daily_replenishment_a': state.daily_replenishment_history_a[-1] if getattr(state, 'daily_replenishment_history_a', None) else {},
                'replenishment_cards': state.daily_replenishment_cards_history[-1] if getattr(state, 'daily_replenishment_cards_history', None) else [],
                'replenishment_cards_a': state.daily_replenishment_cards_history_a[-1] if getattr(state, 'daily_replenishment_cards_history_a', None) else [],
                'material_consumption': state.material_consumption.daily_consumption.get(state.current_day - 1, {}),
                'daily_production_a': state.daily_production_history_a[-1] if getattr(state, 'daily_production_history_a', None) else {},
                'production_executed': exec_state['production_executed'],
                'production_executed_a': exec_state['production_executed_a'],
                'production_shortages': exec_state['production_shortages'],
                'production_shortages_a': exec_state['production_shortages_a'],
                'production_consumption': state.booked_material_consumption.daily_consumption.get(state.current_day, {}) if hasattr(state, 'booked_material_consumption') else {},
                'planned_snapshot': state_data.get('planned_snapshot') if isinstance(state_data, dict) else _planned_snapshot_from_board_state(state.board.to_dict() if state.board else {}),
                'planned_snapshot_a': state_data.get('planned_snapshot_a') if isinstance(state_data, dict) else _planned_snapshot_from_board_state(state.board_a.to_dict() if getattr(state, 'board_a', None) else {}),
                'production_status': message
            }
            msg_style = {'color': '#FF6B6B', 'padding': '10px', 'backgroundColor': '#FFE0E0', 'borderRadius': '6px', 'margin': '0 2rem'}
            return state_data, str(state.current_day), _wrap_status_message(message, msg_style)
        result = execute_production_for_today(state)
        exec_state = _current_day_execution_state(state)
        state_data = {
            'day': state.current_day,
            'board': state.board.to_dict() if state.board else {},
            'board_a': state.board_a.to_dict() if getattr(state, 'board_a', None) else {},
            'daily_orders': state.daily_orders_history[-1] if state.daily_orders_history else {},
            'daily_production': state.daily_production_history[-1] if state.daily_production_history else {},
            'daily_replenishment': state.daily_replenishment_history[-1] if getattr(state, 'daily_replenishment_history', None) else {},
            'daily_replenishment_a': state.daily_replenishment_history_a[-1] if getattr(state, 'daily_replenishment_history_a', None) else {},
            'replenishment_cards': state.daily_replenishment_cards_history[-1] if getattr(state, 'daily_replenishment_cards_history', None) else [],
            'replenishment_cards_a': state.daily_replenishment_cards_history_a[-1] if getattr(state, 'daily_replenishment_cards_history_a', None) else [],
            'material_consumption': state.material_consumption.daily_consumption.get(state.current_day - 1, {}),
            'daily_production_a': state.daily_production_history_a[-1] if getattr(state, 'daily_production_history_a', None) else {},
            'production_executed': exec_state['production_executed'],
            'production_executed_a': exec_state['production_executed_a'],
            'production_shortages': exec_state['production_shortages'],
            'production_shortages_a': exec_state['production_shortages_a'],
            'production_consumption': state.booked_material_consumption.daily_consumption.get(state.current_day, {}) if hasattr(state, 'booked_material_consumption') else {},
            'planned_snapshot': state_data.get('planned_snapshot') if isinstance(state_data, dict) else _planned_snapshot_from_board_state(state.board.to_dict() if state.board else {}),
            'planned_snapshot_a': state_data.get('planned_snapshot_a') if isinstance(state_data, dict) else _planned_snapshot_from_board_state(state.board_a.to_dict() if getattr(state, 'board_a', None) else {}),
            'production_status': result.get('message', '')
        }
        if result.get('status') == 'already':
            msg_style = {'color': '#F57C00', 'padding': '10px', 'backgroundColor': '#FFF3E0', 'borderRadius': '6px', 'margin': '0 2rem'}
        else:
            msg_style = {'color': '#2E7D32', 'padding': '10px', 'backgroundColor': '#E8F5E9', 'borderRadius': '6px', 'margin': '0 2rem'}
        return state_data, str(state.current_day), _wrap_status_message(result.get('message', ''), msg_style)

    # Normale Simulation (nächster Tag)
    state = load_or_create_simulation_state()
    if triggered_id == 'btn-global-next-day':
        executed_days = set(getattr(state, 'production_executed_days', []) or [])
        if state.current_day not in executed_days:
            exec_state = _current_day_execution_state(state)
            state_data = {
                'day': state.current_day,
                'board': state.board.to_dict() if state.board else {},
                'board_a': state.board_a.to_dict() if getattr(state, 'board_a', None) else {},
                'daily_orders': state.daily_orders_history[-1] if state.daily_orders_history else {},
                'daily_production': state.daily_production_history[-1] if state.daily_production_history else {},
                'daily_replenishment': state.daily_replenishment_history[-1] if getattr(state, 'daily_replenishment_history', None) else {},
                'daily_replenishment_a': state.daily_replenishment_history_a[-1] if getattr(state, 'daily_replenishment_history_a', None) else {},
                'replenishment_cards': state.daily_replenishment_cards_history[-1] if getattr(state, 'daily_replenishment_cards_history', None) else [],
                'replenishment_cards_a': state.daily_replenishment_cards_history_a[-1] if getattr(state, 'daily_replenishment_cards_history_a', None) else [],
                'material_consumption': state.material_consumption.daily_consumption.get(state.current_day - 1, {}),
                'daily_production_a': state.daily_production_history_a[-1] if getattr(state, 'daily_production_history_a', None) else {},
                'production_executed': exec_state['production_executed'],
                'production_executed_a': exec_state['production_executed_a'],
                'production_shortages': exec_state['production_shortages'],
                'production_shortages_a': exec_state['production_shortages_a'],
                'production_consumption': state.booked_material_consumption.daily_consumption.get(state.current_day, {}) if hasattr(state, 'booked_material_consumption') else {},
                'planned_snapshot': state_data.get('planned_snapshot') if isinstance(state_data, dict) else _planned_snapshot_from_board_state(state.board.to_dict() if state.board else {}),
                'planned_snapshot_a': state_data.get('planned_snapshot_a') if isinstance(state_data, dict) else _planned_snapshot_from_board_state(state.board_a.to_dict() if getattr(state, 'board_a', None) else {}),
                'production_status': ''
            }
            status_msg = _wrap_status_message(
                f"Produktion für Tag {state.current_day} wurde noch nicht gebucht. Bitte erst Produzieren ausführen.",
                {'color': '#FF6B6B', 'padding': '10px', 'backgroundColor': '#FFE0E0', 'borderRadius': '6px', 'margin': '0 2rem'}
            )
            return state_data, str(state.current_day), status_msg
    state, daily_orders, daily_production = simulate_next_day(state)
    
    # Prüfe ob wir vorausberechnete Daten nutzen
    max_sim = get_max_simulated_day()
    using_simulated = state.current_day <= max_sim
    
    executed_days = set(getattr(state, 'production_executed_days', []) or [])
    current_day_executed = state.current_day in executed_days
    exec_state = _current_day_execution_state(state)
    state_data = {
        'day': state.current_day,
        'board': state.board.to_dict() if state.board else {},
        'board_a': state.board_a.to_dict() if getattr(state, 'board_a', None) else {},
        'daily_orders': daily_orders,
        'daily_production': daily_production,
        'daily_replenishment': state.daily_replenishment_history[-1] if getattr(state, 'daily_replenishment_history', None) else {},
        'daily_replenishment_a': state.daily_replenishment_history_a[-1] if getattr(state, 'daily_replenishment_history_a', None) else {},
        'replenishment_cards': state.daily_replenishment_cards_history[-1] if getattr(state, 'daily_replenishment_cards_history', None) else [],
        'replenishment_cards_a': state.daily_replenishment_cards_history_a[-1] if getattr(state, 'daily_replenishment_cards_history_a', None) else [],
        'material_consumption': state.material_consumption.daily_consumption.get(state.current_day - 1, {}),
        'daily_production_a': state.daily_production_history_a[-1] if getattr(state, 'daily_production_history_a', None) else {},
        'production_executed': exec_state['production_executed'],
        'production_executed_a': exec_state['production_executed_a'],
        'production_shortages': exec_state['production_shortages'],
        'production_shortages_a': exec_state['production_shortages_a'],
        'production_consumption': state.booked_material_consumption.daily_consumption.get(state.current_day, {}) if hasattr(state, 'booked_material_consumption') else {},
        'planned_snapshot': _planned_snapshot_from_board_state(state.board.to_dict() if state.board else {}),
        'planned_snapshot_a': _planned_snapshot_from_board_state(state.board_a.to_dict() if getattr(state, 'board_a', None) else {}),
        'production_status': ''
    }
    
    prev_day = state.current_day - 1
    production_note = None
    if prev_day >= 1:
        if prev_day in executed_days:
            production_note = html.Span(
                f"Produktion für Tag {prev_day} ist gebucht.",
                style={'color': '#2E7D32', 'fontSize': '0.9rem'}
            )
        else:
            production_note = html.Span(
                f"Achtung: Produktion für Tag {prev_day} wurde noch nicht gebucht.",
                style={'color': '#D84315', 'fontSize': '0.9rem', 'fontWeight': 'bold'}
            )

    if using_simulated:
        content = [html.Span(f"Tag {state.current_day} simuliert (aus Bestellsimulation bis Tag {max_sim}).")]
        if production_note:
            content.extend([html.Br(), production_note])
        status_msg = _wrap_status_message(content,
            {'color': '#1976D2', 'padding': '10px', 'backgroundColor': '#E3F2FD', 'borderRadius': '6px', 'margin': '0 2rem'})
    else:
        content = [html.Span(f"Tag {state.current_day} simuliert (Zufallswerte - keine Bestellsimulation vorhanden).")]
        if production_note:
            content.extend([html.Br(), production_note])
        status_msg = _wrap_status_message(content,
            {'color': '#F57C00', 'padding': '10px', 'backgroundColor': '#FFF3E0', 'borderRadius': '6px', 'margin': '0 2rem'})
    
    return state_data, str(state.current_day), status_msg


if __name__ == '__main__':
    app.run(debug=True)
