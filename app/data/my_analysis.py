"""
Medical Analysis Data Cleaning and Price Matching Script
=========================================================
This script loads medical analysis data and prices, cleans them,
and matches analysis names using fuzzy matching to link prices.

Author: Smart Coding Assistant
Date: 2026-02-05
"""

# Fix encoding for Windows console
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd
import os
from rapidfuzz import fuzz, process
import warnings
warnings.filterwarnings('ignore')

# ============================================
# Configuration
# ============================================
SIMILARITY_THRESHOLD = 80  # Minimum similarity score for matching (80%)
DATA_FOLDER = os.path.dirname(os.path.abspath(__file__))

print("=" * 70)
print("🏥 Medical Analysis Data Cleaning & Price Matching Tool")
print("=" * 70)
print()

# ============================================
# Step 1️⃣: Load Data Files
# ============================================
print("📂 Step 1: Loading data files...")
print("-" * 70)

try:
    # Load main analyses file
    df_main_path = os.path.join(DATA_FOLDER, "analyses_main.xlsx")
    df_main = pd.read_excel(df_main_path)
    print(f"✅ Loaded analyses_main.xlsx: {len(df_main)} rows")
    
    # Load prices file (note: it's .xls not .xlsx)
    df_prices_path = os.path.join(DATA_FOLDER, "analyses_prices.xls")
    df_prices = pd.read_excel(df_prices_path)
    print(f"✅ Loaded analyses_prices.xls: {len(df_prices)} rows")
    
    # Load FAQ file
    df_faq_path = os.path.join(DATA_FOLDER, "faq.xlsx")
    df_faq = pd.read_excel(df_faq_path)
    print(f"✅ Loaded faq.xlsx: {len(df_faq)} rows")
    
    print()
    print("📊 Main Analyses Columns:", df_main.columns.tolist())
    print("📊 Prices Columns:", df_prices.columns.tolist())
    print("📊 FAQ Columns:", df_faq.columns.tolist())
    
except FileNotFoundError as e:
    print(f"❌ Error: File not found - {e}")
    exit(1)
except Exception as e:
    print(f"❌ Error loading files: {e}")
    exit(1)

print()

# ============================================
# Step 2️⃣: Data Cleaning and Preparation
# ============================================
print("🧹 Step 2: Data cleaning and preparation...")
print("-" * 70)

# Display original data structure
print("📋 Original Prices Data (first 5 rows):")
print(df_prices.head())
print()

# Clean prices dataframe
print("🔧 Cleaning prices data...")

# Identify the correct column names (they might vary)
# Common patterns: 'التحليل', 'اسم التحليل', 'Analysis Name', etc.
# and 'السعر', 'Price', 'price', etc.

# Use the correct columns: 'Service' for analysis name and 'Fee' for price
analysis_col = 'Service'
price_col = 'Fee'

if analysis_col not in df_prices.columns or price_col not in df_prices.columns:
    print(f"❌ ERROR: Could not find required columns!")
    print(f"   Available columns: {df_prices.columns.tolist()}")
    exit(1)

print(f"   📌 Analysis column: '{analysis_col}'")
print(f"   📌 Price column: '{price_col}'")

# Create cleaned dataframe with standardized column names
df_prices_clean = df_prices[[analysis_col, price_col]].copy()
df_prices_clean.columns = ['analysis_name', 'price']

# Remove rows with missing values
original_count = len(df_prices_clean)
df_prices_clean = df_prices_clean.dropna()
print(f"   ✅ Removed {original_count - len(df_prices_clean)} rows with missing values")

# Clean analysis names in prices
def clean_text(text):
    """Clean text by removing special characters and extra spaces"""
    if pd.isna(text):
        return ""
    text = str(text)
    # Remove asterisks and other special characters
    text = text.replace('*', '').replace('#', '').replace('@', '')
    # Remove extra spaces
    text = ' '.join(text.split())
    # Strip leading/trailing spaces
    text = text.strip()
    return text

df_prices_clean['analysis_name'] = df_prices_clean['analysis_name'].apply(clean_text)

# Remove empty rows after cleaning
df_prices_clean = df_prices_clean[df_prices_clean['analysis_name'] != '']

print(f"   ✅ Cleaned {len(df_prices_clean)} analysis names")
print()

# Clean main dataframe analysis names
print("🔧 Cleaning main analyses data...")

# Use 'Unnamed: 0' column which contains English names
main_analysis_col = 'Unnamed: 0'

if main_analysis_col not in df_main.columns:
    print(f"❌ ERROR: Could not find '{main_analysis_col}' column in main file!")
    print(f"   Available columns: {df_main.columns.tolist()}")
    exit(1)
    
print(f"   📌 Main analysis column: '{main_analysis_col}'")

# Store original column for reference (use the Arabic name column)
arabic_name_col = df_main.columns[0]  # First column is the Arabic name
df_main['original_name'] = df_main[arabic_name_col]
df_main['english_name'] = df_main[main_analysis_col]
df_main['analysis_name_clean'] = df_main[main_analysis_col].apply(clean_text)

print(f"   ✅ Cleaned {len(df_main)} main analysis names")
print()

print("📋 Cleaned Prices Data (first 5 rows):")
print(df_prices_clean.head())
print()

# ============================================
# Step 3️⃣: Fuzzy Matching
# ============================================
print("🔍 Step 3: Name matching using fuzzy matching...")
print("-" * 70)
print(f"   ⚙️  Similarity threshold: {SIMILARITY_THRESHOLD}%")
print()

# Create a list of price analysis names for matching
price_names = df_prices_clean['analysis_name'].tolist()

def find_best_match(query, choices, threshold=SIMILARITY_THRESHOLD):
    """
    Find the best match for a query string in a list of choices
    using fuzzy matching with rapidfuzz
    """
    if not query or pd.isna(query):
        return None, 0
    
    # Use rapidfuzz to find best match
    result = process.extractOne(
        query, 
        choices, 
        scorer=fuzz.ratio,
        score_cutoff=threshold
    )
    
    if result:
        return result[0], result[1]  # (matched_name, score)
    return None, 0

# Apply fuzzy matching
print("🔄 Matching analysis names (this may take a moment)...")
matches = []
scores = []

for idx, analysis_name in enumerate(df_main['analysis_name_clean']):
    if (idx + 1) % 50 == 0:
        print(f"   Progress: {idx + 1}/{len(df_main)} analyses processed...")
    
    matched_name, score = find_best_match(analysis_name, price_names)
    matches.append(matched_name)
    scores.append(score)

df_main['matched_name'] = matches
df_main['match_score'] = scores

# Count successful matches
successful_matches = df_main['matched_name'].notna().sum()
failed_matches = len(df_main) - successful_matches

print()
print(f"✅ Matching complete!")
print(f"   📊 Successfully matched: {successful_matches} analyses")
print(f"   ⚠️  Not matched: {failed_matches} analyses")
print()

# ============================================
# Step 4️⃣: Merge Prices
# ============================================
print("💰 Step 4: Merging prices with main data...")
print("-" * 70)

# Merge prices based on matched names
df_main = df_main.merge(
    df_prices_clean,
    left_on='matched_name',
    right_on='analysis_name',
    how='left',
    suffixes=('', '_from_prices')
)

# Count how many got prices
analyses_with_price = df_main['price'].notna().sum()
analyses_without_price = len(df_main) - analyses_with_price

print(f"✅ Merge complete!")
print(f"   💵 Analyses with price: {analyses_with_price}")
print(f"   ❌ Analyses without price: {analyses_without_price}")
print()

# ============================================
# Step 5️⃣: Display Results
# ============================================
print("=" * 70)
print("📊 FINAL RESULTS")
print("=" * 70)
print()

print("🏆 Top 5 Analyses with Prices:")
print("-" * 70)
display_columns = ['original_name', 'matched_name', 'match_score', 'price']
existing_display_cols = [col for col in display_columns if col in df_main.columns]

# Show top 5 with prices
df_with_prices = df_main[df_main['price'].notna()].head()
if len(df_with_prices) > 0:
    print(df_with_prices[existing_display_cols].to_string(index=True))
else:
    print("⚠️  No analyses found with prices")

print()
print()

print("📈 Summary Statistics:")
print("-" * 70)
print(f"📋 Total analyses in main file: {len(df_main)}")
print(f"💵 Total analyses with prices: {analyses_with_price}")
print(f"❌ Analyses without prices: {analyses_without_price}")
print(f"📊 Match rate: {(analyses_with_price/len(df_main)*100):.1f}%")
print()

if analyses_without_price > 0:
    print("⚠️  Analyses NOT Matched (first 10):")
    print("-" * 70)
    unmatched = df_main[df_main['price'].isna()][['original_name']].head(10)
    for idx, row in unmatched.iterrows():
        print(f"   • {row['original_name']}")
    print()

print("💡 Match Score Distribution:")
print("-" * 70)
if analyses_with_price > 0:
    print(df_main[df_main['price'].notna()]['match_score'].describe())
else:
    print("⚠️  No matches to display statistics")

print()

# ============================================
# Step 6️⃣: Save Results
# ============================================
print("💾 Saving results...")
print("-" * 70)

# Save to Excel
output_file = os.path.join(DATA_FOLDER, "analyses_with_prices.xlsx")
df_main.to_excel(output_file, index=False)
print(f"✅ Results saved to: {output_file}")

# Save summary statistics
summary_file = os.path.join(DATA_FOLDER, "matching_summary.txt")
with open(summary_file, 'w', encoding='utf-8') as f:
    f.write("Medical Analysis Price Matching Summary\n")
    f.write("=" * 70 + "\n\n")
    f.write(f"Total analyses: {len(df_main)}\n")
    f.write(f"Successfully matched: {analyses_with_price}\n")
    f.write(f"Not matched: {analyses_without_price}\n")
    f.write(f"Match rate: {(analyses_with_price/len(df_main)*100):.1f}%\n")
    f.write(f"Similarity threshold used: {SIMILARITY_THRESHOLD}%\n")

print(f"✅ Summary saved to: {summary_file}")
print()

print("=" * 70)
print("✨ Process Complete!")
print("=" * 70)
