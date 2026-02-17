"""
Excel to JSON Converter for Wareed Knowledge Base
Converts Excel file with multiple sheets into structured JSON
"""

import pandas as pd
import json
import sys
from pathlib import Path

# Fix encoding for Windows console
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

def convert_excel_to_json(excel_path, output_json_path=None):
    """
    Convert Excel file to structured JSON
    
    Args:
        excel_path: Path to Excel file
        output_json_path: Path to save JSON (optional)
    
    Returns:
        Dictionary containing all sheets data
    """
    try:
        print(f"[*] Reading Excel file: {excel_path}")
        
        # Read all sheets from Excel
        excel_file = pd.ExcelFile(excel_path)
        sheet_names = excel_file.sheet_names
        
        print(f"[*] Found {len(sheet_names)} sheets: {sheet_names}")
        
        # Dictionary to store all data
        all_data = {}
        
        # Process each sheet
        for sheet_name in sheet_names:
            print(f"\n[*] Processing sheet: {sheet_name}")
            
            # Read sheet
            df = pd.read_excel(excel_path, sheet_name=sheet_name)
            
            # Clean data
            # 1. Remove completely empty rows
            df = df.dropna(how='all')
            
            # 2. Remove completely empty columns
            df = df.dropna(axis=1, how='all')
            
            # 3. Replace NaN with None (will become null in JSON)
            df = df.where(pd.notnull(df), None)
            
            # 4. Remove duplicate rows
            initial_rows = len(df)
            df = df.drop_duplicates()
            duplicates_removed = initial_rows - len(df)
            
            if duplicates_removed > 0:
                print(f"   [-] Removed {duplicates_removed} duplicate rows")
            
            # Convert to list of dictionaries (records)
            records = df.to_dict('records')
            
            print(f"   [+] Processed {len(records)} records")
            print(f"   [*] Columns: {list(df.columns)}")
            
            # Store with cleaned sheet name
            clean_sheet_name = sheet_name.strip()
            all_data[clean_sheet_name] = {
                "total_records": len(records),
                "columns": list(df.columns),
                "data": records
            }
        
        # Save to JSON if output path provided
        if output_json_path:
            print(f"\n[*] Saving to JSON: {output_json_path}")
            
            with open(output_json_path, 'w', encoding='utf-8') as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)
            
            print(f"[+] JSON file saved successfully!")
            
            # Print file size
            file_size = Path(output_json_path).stat().st_size
            print(f"[*] File size: {file_size / 1024:.2f} KB")
        
        return all_data
    
    except Exception as e:
        print(f"[ERROR] Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def generate_schema(data_dict):
    """
    Generate JSON schema from converted data
    
    Args:
        data_dict: Dictionary containing converted Excel data
    
    Returns:
        Schema dictionary
    """
    schema = {
        "version": "1.0",
        "sheets": {}
    }
    
    for sheet_name, sheet_data in data_dict.items():
        schema["sheets"][sheet_name] = {
            "total_records": sheet_data["total_records"],
            "columns": [
                {
                    "name": col,
                    "type": "string"  # Default to string, can be enhanced
                }
                for col in sheet_data["columns"]
            ]
        }
    
    return schema


if __name__ == "__main__":
    # Excel file path
    excel_path = r"c:\Users\asmaa\Downloads\testing.xlsx"
    
    # Output JSON path (in app/data folder)
    output_json = r"c:\Users\asmaa\OneDrive\Documents\work\ai_chatbot_wareed\app\data\excel_data.json"
    schema_json = r"c:\Users\asmaa\OneDrive\Documents\work\ai_chatbot_wareed\app\data\excel_schema.json"
    
    print("=" * 60)
    print("Excel to JSON Converter for Wareed Knowledge Base")
    print("=" * 60)
    
    # Convert Excel to JSON
    result = convert_excel_to_json(excel_path, output_json)
    
    if result:
        print("\n" + "=" * 60)
        print("CONVERSION SUMMARY")
        print("=" * 60)
        
        total_records = 0
        for sheet_name, sheet_data in result.items():
            records = sheet_data["total_records"]
            total_records += records
            print(f"  * {sheet_name}: {records} records")
        
        print(f"\n  [*] Total records across all sheets: {total_records}")
        
        # Generate and save schema
        schema = generate_schema(result)
        with open(schema_json, 'w', encoding='utf-8') as f:
            json.dump(schema, f, ensure_ascii=False, indent=2)
        
        print(f"\n  [*] Schema saved: {schema_json}")
        print("\n[+] Conversion completed successfully!")
        print("=" * 60)
    else:
        print("\n[ERROR] Conversion failed!")
        sys.exit(1)
