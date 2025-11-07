import os
import re
import json
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
import glob 

# --- Configuration ---
# This is still correct, we want to search *from* the results folder
TXT_FILES_DIR = "results" 

INDEX_DIR = "faiss_index"
MODEL_NAME = "all-MiniLM-L6-v2" # A popular model for semantic search

# ---------------- Data Loading (MODIFIED) ----------------
def load_data_from_directory(directory_path):
    """
    Loads all .txt files from all 'cleaned' subdirectories
    within the main directory_path.
    """
    print(f"Loading .txt files from '{directory_path}'...")
    documents = [] # This will be our metadata
    
    # --- MODIFICATION 1: Search recursively for .txt files *inside* any 'cleaned' folder ---
    search_pattern = os.path.join(directory_path, "**", "cleaned", "*.txt")
    
    # --- MODIFICATION 2: Add 'recursive=True' to the glob search ---
    txt_files = glob.glob(search_pattern, recursive=True)

    if not txt_files:
        print(f"❌ ERROR: No .txt files found in any 'cleaned' subfolders under '{directory_path}'.")
        print("Please run the jsoncleaner.py script first.")
        return None

    print(f"Found {len(txt_files)} .txt files to index...")

    for filepath in txt_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # --- MODIFICATION 3: Use the relative path as the source for better tracking ---
            # This will store "mosdac.gov.in/cleaned/city-weather.txt"
            # instead of just "city-weather.txt", which is much more useful.
            source_path = os.path.relpath(filepath, directory_path)
            
            documents.append({
                "source": source_path,
                "text": content
            })
            
        except Exception as e:
            print(f"  [!] Warning: Could not read {filepath}. Error: {e}")

    print(f"✔ Data loaded. Found {len(documents)} documents.")
    return documents

# ---------------- Index Building (Unchanged) ----------------
def build_and_save_index(documents, model_name, index_dir):
    """
    Creates embeddings for all documents and saves them to a 
    FAISS index and a metadata file.
    """
    if not documents:
        print("No documents to index.")
        return

    # 1. Initialize the embedding model
    print(f"Loading sentence transformer model: {model_name}...")
    model = SentenceTransformer(model_name, device="cpu")
    print("✔ Model loaded.")

    # 2. Get the text content from each document
    texts_to_embed = [doc["text"] for doc in documents]
    
    # 3. Create the embeddings
    print(f"Creating embeddings for {len(texts_to_embed)} documents... (This may take a while)")
    embeddings = model.encode(texts_to_embed, show_progress_bar=True, convert_to_numpy=True)
    print("✔ Embeddings created.")

    # 4. Create a FAISS index
    d = embeddings.shape[1]  # Get the dimension of the vectors
    index = faiss.IndexFlatL2(d)  # Using L2 (Euclidean) distance
    
    # 5. Add embeddings to the index
    index.add(embeddings)
    print(f"✔ Embeddings added to FAISS index (Dimension: {d}).")

    # 6. Create the output directory if it doesn't exist
    os.makedirs(index_dir, exist_ok=True)

    # 7. Save the index and metadata
    index_file = os.path.join(index_dir, "faiss_index.bin")
    meta_file = os.path.join(index_dir, "metadata.json")

    faiss.write_index(index, index_file)
    print(f"✔ FAISS index saved to: {index_file}")

    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(documents, f, indent=4)
    print(f"✔ Metadata saved to: {meta_file}")


# ---------------- Main Execution (Unchanged) ----------------
if __name__ == "__main__":
    docs = load_data_from_directory(TXT_FILES_DIR) 
    
    if docs:
        build_and_save_index(docs, MODEL_NAME, INDEX_DIR)
        print("\n🎉 Indexing complete! You can now run the Q&A script.")