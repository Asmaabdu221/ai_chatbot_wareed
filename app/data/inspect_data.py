# Fix encoding for Windows console
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd

print("="*70)
print("INSPECTING DATA FILES")
print("="*70)

# Load main file
df_main = pd.read_excel("analyses_main.xlsx")
print("\n=== MAIN FILE (analyses_main.xlsx) ===")
print(f"Shape: {df_main.shape}")
print(f"Columns: {df_main.columns.tolist()}")
print("\nFirst 5 rows:")
print(df_main.head().to_string())

# Load prices file
df_prices = pd.read_excel("analyses_prices.xls")
print("\n\n=== PRICES FILE (analyses_prices.xls) ===")
print(f"Shape: {df_prices.shape}")
print(f"Columns: {df_prices.columns.tolist()}")
print("\nFirst 5 rows:")
print(df_prices.head().to_string())

print("\n\n=== SAMPLE ANALYSIS NAMES ===")
print("\nFrom MAIN file (first 5):")
for i, name in enumerate(df_main.iloc[:, 0].head(), 1):
    print(f"{i}. {name}")

print("\nFrom PRICES file (first 5):")
for i, name in enumerate(df_prices.iloc[:, 0].head(), 1):
    print(f"{i}. {name}")
