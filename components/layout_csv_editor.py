"""
components/layout_csv_editor.py

Simple CSV editor for files under data/.
"""

from pathlib import Path

import pandas as pd
from dash import html, dcc, callback, Input, Output, State, dash_table


DATA_ROOT = Path(__file__).parent.parent / "data"


def _list_csv_files():
    """List CSV files under data/ as relative paths."""
    if not DATA_ROOT.exists():
        return []
    files = sorted([p for p in DATA_ROOT.rglob("*.csv") if p.is_file()])
    return [str(p.relative_to(DATA_ROOT)) for p in files]


def _safe_csv_path(rel_path: str) -> Path:
    """Resolve a csv path under data/ and block path traversal."""
    if not rel_path:
        return None
    candidate = (DATA_ROOT / rel_path).resolve()
    try:
        candidate.relative_to(DATA_ROOT.resolve())
    except ValueError:
        return None
    return candidate


def layout():
    options = [{"label": p, "value": p} for p in _list_csv_files()]
    default_value = options[0]["value"] if options else None

    return html.Div(
        [
            html.H2("CSV Editor", style={"marginBottom": "0.5rem", "color": "#1a1a2e"}),
            html.Div(
                "Editiere CSV Dateien unter data/.",
                style={"marginBottom": "1.5rem", "color": "#666"},
            ),
            html.Div(
                [
                    dcc.Dropdown(
                        id="csv-editor-file-select",
                        options=options,
                        value=default_value,
                        placeholder="CSV Datei auswaehlen",
                        style={"minWidth": "280px"},
                    ),
                    html.Button(
                        "Load",
                        id="csv-editor-load-btn",
                        style={
                            "marginLeft": "0.75rem",
                            "padding": "0.5rem 0.9rem",
                            "backgroundColor": "#5A9FBF",
                            "color": "white",
                            "border": "none",
                            "borderRadius": "6px",
                            "cursor": "pointer",
                        },
                    ),
                    html.Button(
                        "Add Row",
                        id="csv-editor-add-row-btn",
                        style={
                            "marginLeft": "0.5rem",
                            "padding": "0.5rem 0.9rem",
                            "backgroundColor": "#6C757D",
                            "color": "white",
                            "border": "none",
                            "borderRadius": "6px",
                            "cursor": "pointer",
                        },
                    ),
                    html.Button(
                        "Save",
                        id="csv-editor-save-btn",
                        style={
                            "marginLeft": "0.5rem",
                            "padding": "0.5rem 0.9rem",
                            "backgroundColor": "#51CF66",
                            "color": "white",
                            "border": "none",
                            "borderRadius": "6px",
                            "cursor": "pointer",
                        },
                    ),
                ],
                style={"display": "flex", "alignItems": "center", "flexWrap": "wrap"},
            ),
            dcc.Store(id="csv-editor-current-file", data=default_value),
            html.Div(id="csv-editor-status", style={"marginTop": "0.75rem"}),
            dash_table.DataTable(
                id="csv-editor-table",
                columns=[],
                data=[],
                editable=True,
                row_deletable=True,
                page_size=20,
                style_table={"overflowX": "auto", "marginTop": "1rem"},
                style_cell={
                    "fontSize": "0.9rem",
                    "padding": "0.4rem",
                    "minWidth": "80px",
                    "maxWidth": "220px",
                    "whiteSpace": "normal",
                },
                style_header={"backgroundColor": "#5A9FBF", "color": "white"},
            ),
        ],
        style={"padding": "2rem"},
    )


@callback(
    Output("csv-editor-table", "columns"),
    Output("csv-editor-table", "data"),
    Output("csv-editor-current-file", "data"),
    Output("csv-editor-status", "children"),
    Input("csv-editor-load-btn", "n_clicks"),
    State("csv-editor-file-select", "value"),
    prevent_initial_call=True,
)
def load_csv(n_clicks, rel_path):
    if not rel_path:
        return [], [], None, "Bitte eine CSV Datei auswaehlen."

    csv_path = _safe_csv_path(rel_path)
    if not csv_path or not csv_path.exists():
        return [], [], None, "CSV Datei nicht gefunden."

    try:
        df = pd.read_csv(csv_path)
    except Exception as exc:
        return [], [], rel_path, f"Fehler beim Laden: {exc}"

    df = df.fillna("")
    columns = [{"name": c, "id": c} for c in df.columns]
    data = df.to_dict("records")
    return columns, data, rel_path, f"Geladen: data/{rel_path}"


@callback(
    Output("csv-editor-table", "data", allow_duplicate=True),
    Input("csv-editor-add-row-btn", "n_clicks"),
    State("csv-editor-table", "data"),
    State("csv-editor-table", "columns"),
    prevent_initial_call=True,
)
def add_row(n_clicks, data, columns):
    if data is None:
        data = []
    if not columns:
        return data
    new_row = {col["id"]: "" for col in columns}
    return data + [new_row]


@callback(
    Output("csv-editor-status", "children", allow_duplicate=True),
    Input("csv-editor-save-btn", "n_clicks"),
    State("csv-editor-table", "data"),
    State("csv-editor-table", "columns"),
    State("csv-editor-current-file", "data"),
    prevent_initial_call=True,
)
def save_csv(n_clicks, data, columns, rel_path):
    if not rel_path:
        return "Bitte zuerst eine Datei laden."

    csv_path = _safe_csv_path(rel_path)
    if not csv_path:
        return "Ungueltiger Dateipfad."

    col_order = [c["id"] for c in columns] if columns else []
    df = pd.DataFrame(data or [])
    if col_order:
        df = df.reindex(columns=col_order)

    try:
        df.to_csv(csv_path, index=False)
    except Exception as exc:
        return f"Fehler beim Speichern: {exc}"

    return f"Gespeichert: data/{rel_path}"
