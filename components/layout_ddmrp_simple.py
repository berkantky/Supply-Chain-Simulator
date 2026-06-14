"""
components/layout_ddmrp_simple.py

DDMRP Pufferzonen Anzeige - zeigt dynamische Füllstände und Pufferzonen.
Keine Simulationsfunktionen (die sind jetzt im Overflow-Board Test Tab).
"""

import pandas as pd
import numpy as np
from dash import html, dcc, callback, Input, Output
import plotly.graph_objects as go
from pathlib import Path
import json

from utils.overflow_simulator import (
    load_or_create_material_fill_levels,
    get_material_zone, get_material_fill_percentage, load_material_buffer_zones,
    get_daily_material_consumption, load_material_buffer_zones as get_material_zones_with_values
)

# ============================================================================
# Data Loading
# ============================================================================

def load_buffer_profile_data():
    """Lade Buffer-Profile aus CSV"""
    csv_path = Path(__file__).parent.parent / 'data' / 'raw' / 'pufferzonen.csv'
    
    df = pd.read_csv(csv_path, index_col=0)
    
    # Extrahiere wichtige Zeilen
    try:
        komponenten = df.loc['Item', :].iloc[1:].tolist()  # Skip erste 2 Spalten
        green_zones = df.loc['Green Zone [pcs]', :].iloc[1:].tolist()
        yellow_zones = df.loc['Yellow Zone [pcs]', :].iloc[1:].tolist()
        red_zones = df.loc['Total Red Zone [pcs]', :].iloc[1:].tolist()
        
        # Bereinige None/NaN
        data = []
        for i, (name, g, y, r) in enumerate(zip(komponenten, green_zones, yellow_zones, red_zones)):
            if pd.notna(name) and str(name).strip():
                try:
                    data.append({
                        'name': str(name).strip(),
                        'green': float(g) if pd.notna(g) else 0,
                        'yellow': float(y) if pd.notna(y) else 0,
                        'red': float(r) if pd.notna(r) else 0,
                        'total': float(g) + float(y) + float(r) if pd.notna(g) and pd.notna(y) and pd.notna(r) else 0
                    })
                except:
                    pass
        
        return data
    except Exception as e:
        print(f"Fehler beim Laden der Buffer-Profile: {e}")
        return []
        current_fill = fill_levels.get(material, zones['green'])
    """Erstelle gestapeltes Balkendiagramm für Buffer-Profile (Sollzustände)"""
    
    data = load_buffer_profile_data()
    
    if not data:
        return go.Figure().add_annotation(text="Keine Daten verfügbar")
    
    names = [d['name'] for d in data]
    green_vals = [d['green'] for d in data]
    yellow_vals = [d['yellow'] for d in data]
    red_vals = [d['red'] for d in data]
    
    fig = go.Figure(data=[
        go.Bar(name='Grüne Zone (Cycle Stock)', x=names, y=green_vals, 
               marker_color='#51CF66', hovertemplate='%{x}<br>Grün: %{y}<extra></extra>'),
        go.Bar(name='Gelbe Zone (Cycle Stock)', x=names, y=yellow_vals, 
               marker_color='#FFD700', hovertemplate='%{x}<br>Gelb: %{y}<extra></extra>'),
        go.Bar(name='Rote Zone (Safety Stock)', x=names, y=red_vals, 
               marker_color='#FF6B6B', hovertemplate='%{x}<br>Rot: %{y}<extra></extra>')
    ])
    
    fig.update_layout(
        barmode='stack',
        title='Pufferzonen Sollstände: Grün–Gelb–Rot pro Komponente',
        xaxis_title='Komponenten',
        yaxis_title='Kanban-Anzahl [pcs]',
        hovermode='x unified',
        height=400,
        autosize=true,
        margin=dict(b=100, l=50, r=20, t=50),
        xaxis_tickangle=-45,
        font=dict(size=10),
        showlegend=True,
        legend=dict(yanchor='top', y=0.99, xanchor='right', x=0.99)
    )
    
    return fig


def create_puffer_zones_with_fill_chart(daily_orders: dict = None):
    """
    Erstelle gestapeltes Diagramm mit statischen Pufferzonen (Rot unten → Gelb → Grün oben)
    und horizontalen Linien die den aktuellen Füllstand anzeigen.
    
    Dies ist das OBERE Diagramm - zeigt Rohstoffe (Wellrohlinge, Aluminiumblock).
    """
    
    if not daily_orders:
        daily_orders = {}
    
    # Lade Material-Pufferzonen und Füllstände
    try:
        material_zones = load_material_buffer_zones()
        fill_levels = load_or_create_material_fill_levels()
    except:
        return go.Figure().add_annotation(text="Fehler beim Laden der Pufferzonen")
    
    if not material_zones:
        return go.Figure().add_annotation(text="Keine Pufferzonen definiert")
    
    # Filter: Nur Rohstoffe (Raw Materials)
    raw_materials = ['Wellrohlinge', 'Aluminiumblock']
    materials = [m for m in sorted(material_zones.keys()) if m in raw_materials]
    
    red_vals = []
    yellow_vals = []
    green_vals = []
    fill_positions = []
    
    for material in materials:
        zones = material_zones[material]
        red_vals.append(zones['red'])
        yellow_vals.append(zones['yellow'])
        green_vals.append(zones['green'])

        current_fill = fill_levels.get(material, zones['green'])
        fill_positions.append(current_fill)
    
    # Erstelle gestackeltes Bar-Diagramm: Rot (unten) → Gelb → Grün (oben)
    fig = go.Figure(data=[
        go.Bar(
            name='Rote Zone (Safety Stock)',
            x=materials,
            y=red_vals,
            marker_color='#FF6B6B',
            hovertemplate='%{x}<br>Rot-Zone: %{y} pcs<extra></extra>'
        ),
        go.Bar(
            name='Gelbe Zone (Elevated)',
            x=materials,
            y=yellow_vals,
            marker_color='#FFD700',
            hovertemplate='%{x}<br>Gelb-Zone: %{y} pcs<extra></extra>'
        ),
        go.Bar(
            name='Grüne Zone (Cycle Stock)',
            x=materials,
            y=green_vals,
            marker_color='#51CF66',
            hovertemplate='%{x}<br>Grün-Zone: %{y} pcs<extra></extra>'
        )
    ])
    
    # Füge horizontale SHAPE-Linien und Text-Annotations hinzu
    bar_width = 0.4
    
    for i, material in enumerate(materials):
        current_fill = fill_positions[i]
        
        # Horizontale schwarze Linie innerhalb des Balkens
        fig.add_shape(
            type="line",
            x0=i - bar_width,
            x1=i + bar_width,
            y0=current_fill,
            y1=current_fill,
            line=dict(color="black", width=3),
            layer="above"
        )
        
        # Text-Annotation mit Füllstand-Wert
        fig.add_annotation(
            x=i + bar_width + 0.05,
            y=current_fill,
            text=f"{int(current_fill)}",
            showarrow=False,
            font=dict(size=10, color="black", family="Arial Black"),
            bgcolor="rgba(255, 255, 255, 0.7)",
            bordercolor="black",
            borderwidth=1,
            borderpad=3,
            xanchor="left",
            yanchor="middle"
        )
    
    fig.update_layout(
        barmode='stack',
        title='📦 Rohstoffe (Raw Materials)',
        xaxis_title='Materialien',
        yaxis_title='Menge [pcs]',
        hovermode='x unified',
        height=400,
        margin=dict(b=80, l=50, r=200, t=60),
        xaxis_tickangle=-45,
        font=dict(size=10),
        showlegend=False,
        uniformtext_minsize=9,
        uniformtext_mode='hide'
    )
    
    fig.update_xaxes(tickmode='linear', tick0=0, dtick=1)
    
    return fig


def create_semi_finished_products_chart(daily_orders: dict = None):
    """
    Erstelle gestapeltes Diagramm für Halbfertigprodukte (Antriebswellen).
    Dies ist das RECHTE Diagramm - zeigt nur die 4 Antriebswellen.
    """
    
    if not daily_orders:
        daily_orders = {}
    daily_orders_norm = {str(k).strip(): v for k, v in daily_orders.items()} if isinstance(daily_orders, dict) else {}
    
    # Lade Material-Pufferzonen und Füllstände
    try:
        material_zones = load_material_buffer_zones()
        fill_levels = load_or_create_material_fill_levels()
    except:
        return go.Figure().add_annotation(text="Fehler beim Laden der Pufferzonen")
    
    if not material_zones:
        return go.Figure().add_annotation(text="Keine Pufferzonen definiert")
    
    # Filter: Nur Halbfertigprodukte (Semi-Finished)
    semi_finished = [m for m in sorted(material_zones.keys()) if m.startswith('Antriebswelle')]
    materials = semi_finished
    
    red_vals = []
    yellow_vals = []
    green_vals = []
    fill_positions = []
    
    for material in materials:
        zones = material_zones[material]
        red_vals.append(zones['red'])
        yellow_vals.append(zones['yellow'])
        green_vals.append(zones['green'])
        
        current_fill = fill_levels.get(material, zones['green'])
        fill_positions.append(current_fill)
    
    # Erstelle gestackeltes Bar-Diagramm: Rot (unten) → Gelb → Grün (oben)
    fig = go.Figure(data=[
        go.Bar(
            name='Rote Zone (Safety Stock)',
            x=materials,
            y=red_vals,
            marker_color='#FF6B6B',
            hovertemplate='%{x}<br>Rot-Zone: %{y} pcs<extra></extra>'
        ),
        go.Bar(
            name='Gelbe Zone (Elevated)',
            x=materials,
            y=yellow_vals,
            marker_color='#FFD700',
            hovertemplate='%{x}<br>Gelb-Zone: %{y} pcs<extra></extra>'
        ),
        go.Bar(
            name='Grüne Zone (Cycle Stock)',
            x=materials,
            y=green_vals,
            marker_color='#51CF66',
            hovertemplate='%{x}<br>Grün-Zone: %{y} pcs<extra></extra>'
        )
    ])
    
    # Füge horizontale SHAPE-Linien und Text-Annotations hinzu
    bar_width = 0.4
    
    for i, material in enumerate(materials):
        current_fill = fill_positions[i]
        
        # Horizontale schwarze Linie innerhalb des Balkens
        fig.add_shape(
            type="line",
            x0=i - bar_width,
            x1=i + bar_width,
            y0=current_fill,
            y1=current_fill,
            line=dict(color="black", width=3),
            layer="above"
        )
        
        # Text-Annotation mit Füllstand-Wert
        fig.add_annotation(
            x=i + bar_width + 0.05,
            y=current_fill,
            text=f"{int(current_fill)}",
            showarrow=False,
            font=dict(size=10, color="black", family="Arial Black"),
            bgcolor="rgba(255, 255, 255, 0.7)",
            bordercolor="black",
            borderwidth=1,
            borderpad=3,
            xanchor="left",
            yanchor="middle"
        )
    
    fig.update_layout(
        barmode='stack',
        title='⚙️ Halbfertigprodukte (Semi-Finished Products)',
        xaxis_title='Antriebswellen',
        yaxis_title='Menge [pcs]',
        hovermode='x unified',
        height=400,
        margin=dict(b=100, l=50, r=200, t=60),
        xaxis_tickangle=-45,
        font=dict(size=10),
        showlegend=False,
        uniformtext_minsize=9,
        uniformtext_mode='hide'
    )
    
    fig.update_xaxes(tickmode='linear', tick0=0, dtick=1)
    
    return fig


def create_finished_goods_chart(daily_orders: dict = None):
    """
    Erstelle gestapeltes Diagramm für Fertigwaren (Finished Goods).
    """
    
    if not daily_orders:
        daily_orders = {}
    daily_orders_norm = {str(k).strip(): v for k, v in daily_orders.items()} if isinstance(daily_orders, dict) else {}
    
    # Lade Material-Pufferzonen und Füllstände
    try:
        material_zones = load_material_buffer_zones()
        fill_levels = load_or_create_material_fill_levels()
    except:
        return go.Figure().add_annotation(text="Fehler beim Laden der Pufferzonen")
    
    if not material_zones:
        return go.Figure().add_annotation(text="Keine Pufferzonen definiert")
    
    # Filter: Nur Fertigwaren (FG)
    fg_order = ['CT5', 'CT6', 'CT7', 'TT6', 'TT7', 'TT8']
    fg_set = set(fg_order)
    finished_goods = [
        m for m in sorted(material_zones.keys())
        if (m in fg_set) or ('fg' in m.lower()) or ('getriebe' in m.lower()) or ('fertig' in m.lower())
    ]
    # Prefer fixed FG order, then append any remaining matches
    materials = [m for m in fg_order if m in finished_goods] + [m for m in finished_goods if m not in fg_set]
    display_labels = [m.split('-')[0] if '-' in m else m for m in materials]

    if not materials:
        return go.Figure().add_annotation(text="Keine Fertigwaren definiert")
    
    red_vals = []
    yellow_vals = []
    green_vals = []
    fill_positions = []
    
    for material in materials:
        zones = material_zones[material]
        red_vals.append(zones['red'])
        yellow_vals.append(zones['yellow'])
        green_vals.append(zones['green'])
        
        current_fill = fill_levels.get(material, zones['green'])
        fill_positions.append(current_fill)
    
    fig = go.Figure(data=[
        go.Bar(
            name='Rote Zone (Safety Stock)',
            x=display_labels,
            y=red_vals,
            marker_color='#FF6B6B',
            hovertemplate='%{x}<br>Rot-Zone: %{y} pcs<extra></extra>'
        ),
        go.Bar(
            name='Gelbe Zone (Elevated)',
            x=display_labels,
            y=yellow_vals,
            marker_color='#FFD700',
            hovertemplate='%{x}<br>Gelb-Zone: %{y} pcs<extra></extra>'
        ),
        go.Bar(
            name='Grüne Zone (Cycle Stock)',
            x=display_labels,
            y=green_vals,
            marker_color='#51CF66',
            hovertemplate='%{x}<br>Grüne Zone: %{y} pcs<extra></extra>'
        )
    ])
    
    bar_width = 0.4
    for i, material in enumerate(materials):
        current_fill = fill_positions[i]
        fig.add_shape(
            type="line",
            x0=i - bar_width,
            x1=i + bar_width,
            y0=current_fill,
            y1=current_fill,
            line=dict(color="black", width=3),
            layer="above"
        )
        fig.add_annotation(
            x=i + bar_width + 0.05,
            y=current_fill,
            text=f"{int(current_fill)}",
            showarrow=False,
            font=dict(size=10, color="black", family="Arial Black"),
            bgcolor="rgba(255, 255, 255, 0.7)",
            bordercolor="black",
            borderwidth=1,
            borderpad=3,
            xanchor="left",
            yanchor="middle"
        )
    
    fig.update_layout(
        barmode='stack',
        title='Fertigwaren (Finished Goods)',
        xaxis_title='Produkte',
        yaxis_title='Menge [pcs]',
        hovermode='x unified',
        height=400,
        margin=dict(b=100, l=50, r=200, t=60),
        xaxis_tickangle=-45,
        font=dict(size=10),
        showlegend=False,
        uniformtext_minsize=9,
        uniformtext_mode='hide'
    )
    
    fig.update_xaxes(tickmode='linear', tick0=0, dtick=1)
    
    return fig


def create_material_fill_levels_chart():

    """Erstelle Chart mit aktuellen Material-Füllständen - gestapelt von Rot→Gelb→Grün (ALTE VERSION - WIRD NICHT MEHR GENUTZT)"""
    
    try:
        fill_levels = load_or_create_material_fill_levels()
        material_zones = load_material_buffer_zones()
    except:
        return go.Figure().add_annotation(text="Fehler beim Laden der Material-Füllstände")
    
    if not fill_levels:
        return go.Figure().add_annotation(text="Keine Füllstände verfügbar")
    
    materials = []
    red_levels = []
    yellow_levels = []
    green_levels = []
    
    for material, fill_level in sorted(fill_levels.items()):
        materials.append(material)
        
        if material not in material_zones:
            continue
        
        zones = material_zones[material]
        red_cap = zones['red']
        yellow_cap = zones['yellow']
        green_cap = zones['green']
        total_cap = zones['total']
        
        # Berechne wie viel in jeder Zone ist (von unten nach oben)
        # Rot Zone: 0 bis red_cap
        if fill_level <= red_cap:
            red_levels.append(fill_level)
            yellow_levels.append(0)
            green_levels.append(0)
        # Gelbe Zone: red_cap bis red_cap+yellow_cap
        elif fill_level <= red_cap + yellow_cap:
            red_levels.append(red_cap)
            yellow_levels.append(fill_level - red_cap)
            green_levels.append(0)
        # Grüne Zone: alles über red_cap+yellow_cap
        else:
            red_levels.append(red_cap)
            yellow_levels.append(yellow_cap)
            green_levels.append(fill_level - red_cap - yellow_cap)
    
    fig = go.Figure(data=[
        go.Bar(
            name='Rote Zone (Safety Stock)',
            x=materials,
            y=red_levels,
            marker_color='#FF6B6B',
            hovertemplate='%{x}<br>Rote Zone: %{y} pcs<extra></extra>'
        ),
        go.Bar(
            name='Gelbe Zone (Elevated)',
            x=materials,
            y=yellow_levels,
            marker_color='#FFD700',
            hovertemplate='%{x}<br>Gelbe Zone: %{y} pcs<extra></extra>'
        ),
        go.Bar(
            name='Grüne Zone (Cycle Stock)',
            x=materials,
            y=green_levels,
            marker_color='#51CF66',
            hovertemplate='%{x}<br>Grüne Zone: %{y} pcs<extra></extra>'
        )
    ])
    
    fig.update_layout(
        barmode='stack',
        title='Aktuelle Material-Füllstände nach Zonen (Rot→Gelb→Grün)',
        xaxis_title='Materialien',
        yaxis_title='Füllstand [pcs]',
        height=350,
        margin=dict(b=100, l=50, r=20, t=50),
        xaxis_tickangle=-45,
        font=dict(size=10),
        showlegend=True,
        hovermode='x unified',
        legend=dict(yanchor='top', y=0.99, xanchor='right', x=0.99)
    )
    
    return fig


def create_zone_summary_table(daily_orders: dict = None):
    """Erstelle Zusammenfassungs-Tabelle mit aktuellen Zonen"""
    if not daily_orders:
        daily_orders = {}
    daily_orders_norm = {str(k).strip(): v for k, v in daily_orders.items()} if isinstance(daily_orders, dict) else {}
    
    try:
        fill_levels = load_or_create_material_fill_levels()
        material_zones = load_material_buffer_zones()
    except:
        return html.Div("Fehler beim Laden der Daten")
    
    rows = []
    materials = sorted(material_zones.keys())
    for i, material in enumerate(materials):
        fill_level = fill_levels.get(material, material_zones[material]['green'])
        
        zones = material_zones[material]
        zone = get_material_zone(material, fill_level)
        fill_pct = get_material_fill_percentage(material, fill_level)
        
        bg_color = '#f8f9fa' if i % 2 == 0 else 'white'
        
        zone_color_map = {'RED': '#FF6B6B', 'YELLOW': '#FFD700', 'GREEN': '#51CF66'}
        zone_color = zone_color_map.get(zone, '#999')
        
        rows.append(html.Tr([
            html.Td(material, style={'padding': '0.6rem', 'fontWeight': 'bold', 'color': '#2c3e50'}),
            html.Td(f"{fill_level}/{zones['total']}", style={'padding': '0.6rem', 'textAlign': 'center', 'fontWeight': 'bold'}),
            html.Td(f"{fill_pct*100:.1f}%", style={'padding': '0.6rem', 'textAlign': 'center'}),
            html.Td(html.Span(zone, style={'backgroundColor': zone_color, 'color': 'white', 'padding': '0.3rem 0.6rem', 'borderRadius': '3px', 'fontSize': '0.8rem', 'fontWeight': 'bold'}), style={'padding': '0.6rem', 'textAlign': 'center'}),
            html.Td(f"{zones['green']}", style={'padding': '0.6rem', 'textAlign': 'center', 'backgroundColor': '#E8F8F5', 'fontSize': '0.85rem'}),
            html.Td(f"{zones['yellow']}", style={'padding': '0.6rem', 'textAlign': 'center', 'backgroundColor': '#FEF9E7', 'fontSize': '0.85rem'}),
            html.Td(f"{zones['red']}", style={'padding': '0.6rem', 'textAlign': 'center', 'backgroundColor': '#FADBD8', 'fontSize': '0.85rem'})
        ], style={'backgroundColor': bg_color, 'borderBottom': '1px solid #e0e0e0'}))
    
    header = html.Tr([
        html.Th('Material', style={'padding': '0.7rem', 'textAlign': 'left', 'fontWeight': 'bold', 'backgroundColor': '#5A9FBF', 'color': 'white'}),
        html.Th('Aktuell [pcs]', style={'padding': '0.7rem', 'textAlign': 'center', 'fontWeight': 'bold', 'backgroundColor': '#5A9FBF', 'color': 'white'}),
        html.Th('Füllstand %', style={'padding': '0.7rem', 'textAlign': 'center', 'fontWeight': 'bold', 'backgroundColor': '#5A9FBF', 'color': 'white'}),
        html.Th('Zone', style={'padding': '0.7rem', 'textAlign': 'center', 'fontWeight': 'bold', 'backgroundColor': '#5A9FBF', 'color': 'white'}),
        html.Th('Grün', style={'padding': '0.7rem', 'textAlign': 'center', 'fontWeight': 'bold', 'backgroundColor': '#5A9FBF', 'color': 'white'}),
        html.Th('Gelb', style={'padding': '0.7rem', 'textAlign': 'center', 'fontWeight': 'bold', 'backgroundColor': '#5A9FBF', 'color': 'white'}),
        html.Th('Rot', style={'padding': '0.7rem', 'textAlign': 'center', 'fontWeight': 'bold', 'backgroundColor': '#5A9FBF', 'color': 'white'})
    ])
    
    return html.Table([header] + rows, style={
        'width': '100%',
        'borderCollapse': 'collapse',
        'borderRadius': '6px',
        'overflow': 'hidden',
        'boxShadow': '0 2px 6px rgba(0,0,0,0.08)',
        'fontSize': '0.9rem'
    })


# ============================================================================
# Main Layout
# ============================================================================

def layout():
    """DDMRP Pufferzonen Anzeige Layout"""
    
    return html.Div([
        html.Div([
            html.H2(
                '📊 DDMRP Pufferzonen Übersicht',
                style={
                    'marginBottom': '0.5rem', 
                    'color': '#1a1a2e',
                    'fontWeight': '700',
                    'fontSize': '1.75rem'
                }
            ),
            html.Div(
                "Schneller Überblick über heutige Bestellungen und den resultierenden Materialverbrauch.",
                style={'color': '#6a6a7a', 'fontSize': '0.95rem'}
            ),
        ], style={'marginBottom': '2rem'}),
        
        html.Div(
            "Zeigt die konfigurierten Pufferzonen (Grün = Cycle Stock, Gelb = erhöhter Cycle Stock, Rot = Safety Stock) pro Komponente. Die aktuellen Füllstände werden durch die Simulation aktualisiert.",
            style={'marginBottom': '2rem', 'color': '#666', 'fontStyle': 'italic'}
        ),
        
        # Store für Tracking von Simulation Changes
        dcc.Store(id='ddmrp-last-update-store', data=0),
        
        # Zwei Diagramme NEBENEINANDER: Rohstoffe + Halbfertigprodukte
        html.Div([
            # LINKES Diagramm: Rohstoffe
            html.Div([
                dcc.Graph(
                    id='puffer-zones-chart',
                    figure=create_puffer_zones_with_fill_chart(),
                    config={'responsive': False, 'displayModeBar': False},
                    style={'height': '360px'}
                )
            ], style={
                'flex': '1',
                'minWidth': '0',
                'backgroundColor': 'white',
                'padding': '1.5rem',
                'borderRadius': '8px',
                'boxShadow': '0 2px 6px rgba(0,0,0,0.08)',
                'marginRight': '1rem',
                'height': '420px',
                'display': 'flex',
                'flexDirection': 'column',
                'justifyContent': 'center'
            }),
            
            # RECHTES Diagramm: Halbfertigprodukte
            html.Div([
                dcc.Graph(
                    id='semi-finished-chart',
                    figure=create_semi_finished_products_chart(),
                    config={'responsive': False, 'displayModeBar': False},
                    style={'height': '360px'}
                )
            ], style={
                'flex': '1',
                'minWidth': '0',
                'backgroundColor': 'white',
                'padding': '1.5rem',
                'borderRadius': '8px',
                'boxShadow': '0 2px 6px rgba(0,0,0,0.08)',
                'height': '420px',
                'display': 'flex',
                'flexDirection': 'column',
                'justifyContent': 'center'
            })
        ], style={'display': 'flex', 'marginBottom': '1.5rem', 'gap': '1rem', 'alignItems': 'stretch'}),

        # Drittes Diagramm UNTERHALB: Fertigwaren
        html.Div([
            html.Div([
                dcc.Graph(
                    id='finished-goods-chart',
                    figure=create_finished_goods_chart(),
                    config={'responsive': False, 'displayModeBar': False},
                    style={'height': '360px'}
                )
            ], style={
                'backgroundColor': 'white',
                'padding': '1.5rem',
                'borderRadius': '8px',
                'boxShadow': '0 2px 6px rgba(0,0,0,0.08)',
                'height': '420px',
                'display': 'flex',
                'flexDirection': 'column',
                'justifyContent': 'center'
            })
        ], style={'marginBottom': '1.5rem'}),
        
        # Detaillierte Tabelle
        html.Div([
            html.H3('Detaillierte Material-Übersicht', style={'marginBottom': '1rem', 'color': '#2c3e50', 'fontSize': '1rem'}),
            html.Div(id='material-table-container', children=[create_zone_summary_table()], style={'overflowX': 'auto'})
        ], style={
            'backgroundColor': 'white',
            'padding': '1.5rem',
            'borderRadius': '8px',
            'boxShadow': '0 2px 6px rgba(0,0,0,0.08)'
        })
    ], style={'padding': '2rem'})


# ============================================================================
# Callbacks - Update nur wenn globale Simulation sich ändert
# ============================================================================

@callback(
    Output('puffer-zones-chart', 'figure'),
    Output('semi-finished-chart', 'figure'),
    Output('finished-goods-chart', 'figure'),
    Output('ddmrp-last-update-store', 'data'),
    Input('global-simulation-state', 'data'),
    prevent_initial_call=False
)
def update_puffer_zones_charts(global_state_data):
    """Aktualisiere beide Puffer-Zonen Charts wenn Simulation sich ändert"""
    
    daily_orders = {}
    if global_state_data and isinstance(global_state_data, dict):
        daily_orders = global_state_data.get('daily_orders', {})
    
    return (
        create_puffer_zones_with_fill_chart(daily_orders),
        create_semi_finished_products_chart(daily_orders),
        create_finished_goods_chart(daily_orders),
        (global_state_data or 0)
    )


@callback(
    Output('material-table-container', 'children'),
    Input('global-simulation-state', 'data'),
    prevent_initial_call=False
)
def update_table(global_state_data):
    """Aktualisiere Tabelle nur wenn Simulation sich ändert"""
    daily_orders = {}
    if global_state_data and isinstance(global_state_data, dict):
        daily_orders = global_state_data.get('daily_orders', {})
    return create_zone_summary_table(daily_orders)
