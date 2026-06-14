# Demand-Driven Supply Chain Simulator

A browser-based simulation dashboard for demand-driven supply chain planning, built around a realistic automotive manufacturing scenario. The tool combines two methodologies that are rarely seen implemented together in a single interactive environment: **DDMRP** (Demand-Driven Material Requirements Planning) and **Heijunka** (production leveling from the Toyota Production System).

This project was developed as part of the course *Demand driven Supply Chain Management* at Hochschule Reutlingen (Faculty of Informatics).

---

## What it simulates

A fictional manufacturer produces six transmission variants — three for passenger cars (5, 6, 7-speed) and three for trucks (6, 7, 8-speed). The full production structure is modeled end-to-end:

```
Shaft blank → Grinding → Polishing → Shaft ─┐
                                   Gears ────┼──→ Drive shaft ─┐
                                Bearings ────┘                  │
                                                                 ├──→ Final Assembly → Quality Check → Transmission
Aluminium block → Milling → Housing ───────────────────────────┤
                                              Seal rings ───────┤
                                                 Screws ────────┘
```

**Key simulation parameters:**
- 2-shift operation, Monday to Friday (6am–2pm and 2pm–10pm, with breaks)
- One resource per operation type
- Stochastic demand generation based on 12 months of historical data (Poisson process)
- Procurement lead times range from 2 working days (seal rings, screws) to 15 working days (aluminium blocks)

### Products and prices

| Product | Unit Price |
|---|---|
| Car transmission (5-speed) | €1,000 |
| Car transmission (6-speed) | €1,500 |
| Car transmission (7-speed) | €3,000 |
| Truck transmission (6-speed) | €14,000 |
| Truck transmission (7-speed) | €18,000 |
| Truck transmission (8-speed) | €25,000 |

### Raw material lead times

| Material | Purchasing Lead Time |
|---|---|
| Seal rings, Screws | 2 working days |
| Gears, Bearings | 5 working days |
| Shaft blanks | 10 working days |
| Aluminium blocks | 15 working days |

---

## Dashboard Modules

| Tab | Description |
|---|---|
| **Overflow Board** | Kanban-style buffer status for each finished product — green/yellow/red zone visualization, net flow position, and replenishment signals |
| **DDMRP** | Buffer zone calculation per SKU based on lead time factor and variability factor; decoupling point logic |
| **Heijunka** | Production leveling across two production loops (Loop A and Loop B); pitch-based scheduling |
| **Einkauf (Procurement)** | Open purchase orders, incoming deliveries, reorder point monitoring with EOQ for consumption-based materials |
| **Finanzen (Finance)** | Day-by-day revenue, raw material costs, and contribution margin; running totals and trend charts |
| **Produktion (Production)** | Daily production execution — scheduled quantities, actual output, material shortages, and throughput per shift |

The simulation runs day by day, so you step through it manually and observe how the supply chain reacts to demand variability, procurement delays, and resource constraints.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | [Dash](https://dash.plotly.com/) (Python) |
| Charts | [Plotly](https://plotly.com/python/) |
| Data processing | pandas, numpy |
| Excel integration | openpyxl |
| State persistence | pickle (local, not committed) |

No database, no frontend build step — it runs as a local web server.

---

## Getting Started

**Requirements:** Python 3.9+

```bash
# Clone the repository
git clone https://github.com/your-username/your-repo.git
cd demand-driven-supply-chain

# Create a virtual environment
python -m venv venv

# Activate it
# Windows:
venv\Scripts\activate
# macOS / Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the app
python app.py
```

Open your browser at `http://127.0.0.1:8050` — the dashboard loads with pre-configured simulation data and you can start stepping through days immediately.

---

## Project Structure

```
├── app.py                    # Dash app entry point and main callbacks
├── components/               # Layout modules (one file per dashboard tab)
│   ├── layout_overflow.py    # Overflow/Kanban board
│   ├── layout_ddmrp.py       # DDMRP module
│   ├── layout_heijunka.py    # Heijunka module
│   ├── layout_einkauf.py     # Procurement module
│   ├── layout_finanzen.py    # Finance module
│   └── layout_production.py  # Production execution module
├── utils/                    # Business logic
│   ├── overflow_simulator.py # Core simulation engine (~2500 lines)
│   ├── demand_simulator.py   # Poisson-based demand generation
│   ├── calc_ddmrp.py         # DDMRP buffer zone calculations
│   └── calc_heijunka.py      # Heijunka scheduling logic
├── data/
│   └── raw/                  # Static input data (BOM, routing, demand params)
├── outputs/                  # Generated logs and reports (not committed)
└── requirements.txt
```

---

## Disclaimer

All company names, products, financial figures, and demand data used in this simulation are entirely fictional and were created for educational purposes. This project does not represent any real company or real supply chain data.

---

## License

MIT License — feel free to use, adapt, or build on it.
