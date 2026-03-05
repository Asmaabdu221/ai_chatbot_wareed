# Fix encoding
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd
from app.core.paths import EXCEL_FAQ_PATH

df = pd.read_excel(EXCEL_FAQ_PATH)
print('Shape:', df.shape)
print('\nColumns:', df.columns.tolist())
print('\nAll FAQs:')
print('='*70)
for i, row in df.iterrows():
    print(f'\nQ{i+1}: {row.iloc[0]}')
    print(f'A{i+1}: {row.iloc[1]}')
    print('-'*70)
