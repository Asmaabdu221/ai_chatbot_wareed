# Fix encoding for Windows console
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd

# Load files
df_main = pd.read_excel("analyses_main.xlsx")
df_prices = pd.read_excel("analyses_prices.xls")

# Check columns in main file
print("="*70)
print("MAIN FILE COLUMNS:")
print("="*70)
for i, col in enumerate(df_main.columns):
    print(f"{i}: {col}")
    print(f"   Sample values: {df_main[col].head(3).tolist()}")
    print()

print("\n" + "="*70)
print("PRICES FILE COLUMNS:")
print("="*70)
for i, col in enumerate(df_prices.columns):
    print(f"{i}: {col}")
    print(f"   Sample values: {df_prices[col].head(3).tolist()}")
    print()

# Check if there are any English names in main file
print("\n" + "="*70)
print("CHECKING FOR ENGLISH TEXT IN MAIN FILE:")
print("="*70)
for col in df_main.columns:
    if df_main[col].dtype == 'object':
        # Check if any value contains English letters
        english_count = df_main[col].astype(str).str.contains('[a-zA-Z]', regex=True, na=False).sum()
        if english_count > 0:
            print(f"Column '{col}': {english_count} rows with English text")
            print(f"   Samples: {df_main[col][df_main[col].astype(str).str.contains('[a-zA-Z]', regex=True, na=False)].head(3).tolist()}")
            print()

# Check the 'Service' column in prices
print("\n" + "="*70)
print("PRICES 'Service' COLUMN (first 20):")
print("="*70)
for i, service in enumerate(df_prices['Service'].head(20)):
    print(f"{i+1}. {service}")
