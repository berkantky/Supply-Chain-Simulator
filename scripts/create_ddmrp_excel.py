"""
Script zum Erstellen der DDMRP-Excel-Datei mit Beispieldaten
"""
import pandas as pd

# Definiere die Daten als Dictionary
data = {
    'Item': ['Wellenrohling', 'Aluminiumblock', 'Antiebswelle 5', 'Antiebswelle 6', 
            'Antiebswelle 7', 'Antiebswelle 8', 'Autogetriebe 5', 'Autogetriebe 6',
            'Autogetriebe 7', 'LKW-Getriebe 6', 'LKW-Getriebe 7', 'LKW-Getriebe 8'],
    'Green_Zone': [143.0, 178.0, 27.0, 28.0, 16.0, 2.0, 18.0, 4.0, 5.0, 16.0, 6.0, 1.0],
    'Yellow_Zone': [475.0, 712.0, 89.0, 93.0, 52.0, 5.0, 36.0, 7.0, 10.0, 31.0, 12.0, 2.0],
    'Red_Zone': [214.0, 303.0, 40.0, 42.0, 24.0, 3.0, 23.0, 5.0, 7.0, 20.0, 8.0, 2.0],
    'Total_Buffer': [832.0, 1193.0, 156.0, 163.0, 92.0, 10.0, 77.0, 16.0, 22.0, 67.0, 26.0, 5.0]
}

# Erstelle DataFrame
df = pd.DataFrame(data)

# Speichere als Excel
df.to_excel('data/ddmrp.xlsx', index=False)