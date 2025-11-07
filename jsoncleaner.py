#!/usr/bin/env python3
import json
import os
import glob
import re

def clean_simple_json(input_filename):
    """
    Cleans a simple {url, text} JSON file (from PDF/DOCX)
    and saves the text content to a new .txt file inside
    a 'cleaned' subfolder.
    """
    try:
        # --- 1. Determine Output Filename and Path ---
        input_dir = os.path.dirname(input_filename)
        base_name = os.path.basename(input_filename)
        
        # --- MODIFICATION: Define 'cleaned' output directory ---
        output_dir = os.path.join(input_dir, "cleaned")
        os.makedirs(output_dir, exist_ok=True)
        
        # --- MODIFICATION: Define new base filename (no '-cleaned') ---
        if base_name.endswith("-parsed.json"):
            base_output_name = base_name[:-len("-parsed.json")] + ".txt"
        else:
            base_output_name = os.path.splitext(base_name)[0] + ".txt"
            
        # --- MODIFICATION: Combine new path and filename ---
        output_filename = os.path.join(output_dir, base_output_name)

        # --- 2. Load the JSON data ---
        with open(input_filename, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not isinstance(data, dict):
            print(f"Error: Expected a JSON object, but got {type(data)}")
            return

        # --- 3. Get URL and Text ---
        source_url = data.get("url", "Source URL not found")
        text = data.get("text", "")
        
        output_lines = []
        output_lines.append(f"Source URL: {source_url}")
        output_lines.append("=" * (len(source_url) + 12))
        output_lines.append("")
        output_lines.append(text.strip())

        # --- 4. Write the cleaned content to the .txt file ---
        with open(output_filename, 'w', encoding='utf-8') as f:
            f.write("\n".join(output_lines))
        
        # --- MODIFICATION: Updated print statement ---
        print(f"✔ Processed (Simple): {base_name} -> cleaned/{base_output_name}")

    except Exception as e:
        print(f"An unexpected error occurred while processing {input_filename}: {e}")


def clean_unstructured_json(input_filename):
    """
    Cleans an unstructured JSON output file (from HTML) and saves the 
    text and link content to a new .txt file inside
    a 'cleaned' subfolder.
    """
    
    try:
        # --- 1. Determine Parent URL and Output Filename ---
        input_dir = os.path.dirname(input_filename)
        base_name = os.path.basename(input_filename)
        
        # --- MODIFICATION: Define 'cleaned' output directory ---
        output_dir = os.path.join(input_dir, "cleaned")
        os.makedirs(output_dir, exist_ok=True)
        
        # Determine parent ID (base for new filename)
        if base_name.endswith("-output.json"):
            parent_id = base_name[:-len("-output.json")]
        else:
            parent_id = os.path.splitext(base_name)[0]
        
        # --- MODIFICATION: Define new base filename (no '-cleaned') ---
        base_output_name = f"{parent_id}.txt"
        
        # --- MODIFICATION: Combine new path and filename ---
        output_filename = os.path.join(output_dir, base_output_name)
        
        output_lines = []
        output_lines.append(f"Source Identifier: {parent_id}")
        output_lines.append("=" * (len(parent_id) + 20)) 
        output_lines.append("")

        # --- 2. Load the JSON data ---
        with open(input_filename, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not isinstance(data, list):
            print(f"Error: Expected a JSON list, but got {type(data)}")
            return

        # --- 3. Process each element in order ---
        for element in data:
            text = element.get("text")
            if not text:
                continue

            text = re.sub(r'\{\{.*?\}\}', '', text)
            text = re.sub(r'\s+', ' ', text)
            text = text.strip()
            
            if not text:
                continue
            
            metadata = element.get("metadata", {})
            link_urls = metadata.get("link_urls")
            link_texts = metadata.get("link_texts")
            
            output_lines.append(text)
            
            is_direct_link = False
            if link_texts and text in link_texts:
                is_direct_link = True

            # --- 4. Format links based on context ---
            if is_direct_link and link_urls:
                try:
                    url_index = link_texts.index(text)
                    if url_index < len(link_urls):
                        url = link_urls[url_index]
                        output_lines.append(f"  [{url}]")
                except (ValueError, IndexError):
                    output_lines.append(f"  [Associated Link: {link_urls[0]}]")
            elif link_urls:
                output_lines.append("  (Associated Links):")
                for i, url in enumerate(link_urls):
                    label = link_texts[i] if link_texts and i < len(link_texts) else url
                    output_lines.append(f"  - {label} [{url}]")
            
            output_lines.append("") 

        # --- 5. Write the cleaned content to the .txt file ---
        with open(output_filename, 'w', encoding='utf-8') as f:
            f.write("\n".join(output_lines))
        
        # --- MODIFICATION: Updated print statement ---
        print(f"✔ Processed (Unstructured): {base_name} -> cleaned/{base_output_name}")

    except Exception as e:
        print(f"An unexpected error occurred while processing {input_filename}: {e}")

# --- Run the script ---
if __name__ == "__main__":
    
    target_directory = "results" 
    
    print(f"Scanning recursively for JSON files in '{target_directory}'...")
    
    if not os.path.isdir(target_directory):
        print(f"Error: Directory not found: '{target_directory}'")
        exit()
    
    unstructured_pattern = os.path.join(target_directory, "**", "*-output.json")
    unstructured_files = glob.glob(unstructured_pattern, recursive=True)

    simple_pattern = os.path.join(target_directory, "**", "*-parsed.json")
    simple_files = glob.glob(simple_pattern, recursive=True)

    if not unstructured_files and not simple_files:
        print("No '*-output.json' or '*-parsed.json' files found.")
    else:
        print(f"Found {len(unstructured_files)} unstructured (HTML) files to process...")
        for file_path in unstructured_files:
            try:
                clean_unstructured_json(file_path)
            except Exception as e:
                print(f"[FAIL] Could not process {file_path}: {e}")
        
        print(f"\nFound {len(simple_files)} simple (Doc/PDF) files to process...")
        for file_path in simple_files:
            try:
                clean_simple_json(file_path)
            except Exception as e:
                print(f"[FAIL] Could not process {file_path}: {e}")
        
        print("\nAll files processed.")