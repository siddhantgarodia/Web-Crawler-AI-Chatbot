#!/usr/bin/env python3
import os
import re
import json
import time
import glob
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
import google.generativeai as genai
from urllib.parse import urlparse

# --- Configuration ---

# 1. PASTE YOUR API KEY HERE
API_KEY = "AIzaSyD5rRbN3O7AGKoJIl8fIIp_jhKmiUqjrw8"

# 2. This must match the folder where you saved your index
INDEX_DIR = "faiss_index"

# 3. This must match the model used in build_index.py
MODEL_NAME = "all-MiniLM-L6-v2" 

# 4. MODEL UPDATED per your request
GEMINI_MODEL = "gemini-2.5-flash"

# 5. Directory to search for link_db.json and .txt files
RESULTS_DIR = "results" 

# 6. THRESHOLD UPDATED per your request
POOR_MATCH_THRESHOLD = 1.25

# 7. NEW: How many chunks to retrieve before filtering
RETRIEVAL_TOP_K = 5

# --- Helper Function (from integrated.py) ---
def filename_for_url(url):
    """Generates a safe filename base from a URL."""
    parsed = urlparse(url)
    path = parsed.path.strip("/") or "root"
    safe = re.sub(r"[^A-Za-z0-9_\-\.]", "_", path)
    if parsed.query:
        safe += f"_q{abs(hash(parsed.query)) % 100000}"
    return safe

# ---------------- Resource Loading ----------------
def load_resources(index_dir, results_dir, model_name, device="cpu"):
    """
    Loads FAISS, metadata, link_db, model, and creates a
    text file lookup map.
    """
    index_file = os.path.join(index_dir, "faiss_index.bin")
    meta_file = os.path.join(index_dir, "metadata.json")

    if not os.path.exists(index_file) or not os.path.exists(meta_file):
        raise FileNotFoundError(
            f"❌ FAISS index or metadata not found in '{index_dir}'. "
            "Please run 'build_index.py' first."
        )

    # 1. Load FAISS index and metadata
    print("Loading FAISS index and metadata...")
    index = faiss.read_index(index_file)
    with open(meta_file, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    # 2. Load Sentence Transformer Model
    print("Loading sentence transformer model...")
    model = SentenceTransformer(model_name, device=device)
    
    # 3. Load all link_db.json files
    print(f"Loading link databases from '{results_dir}'...")
    link_db_pattern = os.path.join(results_dir, "**", "link_db.json")
    link_db_files = glob.glob(link_db_pattern, recursive=True)
    link_database = []
    if link_db_files:
        for db_file in link_db_files:
            try:
                with open(db_file, "r", encoding="utf-8") as f:
                    link_database.extend(json.load(f))
            except Exception as e:
                print(f"  [!] Warning: Could not load {db_file}. Error: {e}")
        print(f"  -> Loaded {len(link_database)} links.")

    # 4. Create a quick-lookup map for text content
    print("Creating text file lookup map...")
    text_lookup_map = {}
    for doc in metadata:
        base_name = os.path.basename(doc["source"]).replace('.txt', '')
        text_lookup_map[base_name] = doc["text"]
    print(f"  -> Map created with {len(text_lookup_map)} text files.")

    print("✔ All components loaded.")
    return index, metadata, model, link_database, text_lookup_map

# ---------------- Retrieval ----------------
def retrieve(query, index, metadata, model, top_k=RETRIEVAL_TOP_K):
    """
    Encodes the query and searches the FAISS index.
    """
    print(f"  -> Retrieving top {top_k} contexts for: '{query}'")
    query_vec = model.encode([query], convert_to_numpy=True)
    distances, indices = index.search(query_vec, top_k)
    
    results = []
    for i in range(len(indices[0])):
        idx = indices[0][i]
        results.append({
            "source_file": metadata[idx]["source"],
            "text": metadata[idx]["text"],
            "distance": float(distances[0][i])
        })
    
    if results:
        print(f"  -> Found top match from '{results[0]['source_file']}' (distance: {results[0]['distance']:.4f})")
    
    return results

def find_links_and_load_text(query, link_database, text_lookup, max_links=3):
    """
    Searches link_db, then uses the lookup map to find the
    corresponding text for those links.
    """
    print(f"  -> Searching link database for: '{query}'")
    keywords = query.lower().split()
    context_chunks = []
    found_urls = set()

    for link in link_database:
        anchor = str(link.get("anchor", "")).lower()
        child_url = str(link.get("child", ""))
        
        if not child_url or child_url in found_urls:
            continue
        
        if any(kw in anchor for kw in keywords) or any(kw in child_url.lower() for kw in keywords):
            filename_base = filename_for_url(child_url)
            
            if filename_base in text_lookup:
                print(f"  -> Found relevant link and text for: {filename_base}")
                context_chunks.append({
                    "source_file": f"Linked from {link.get('parent', 'sitemap')}",
                    "text": text_lookup[filename_base],
                    "distance": 999.0 # Use a high number to show it's a fallback
                })
                found_urls.add(child_url)
            
            if len(context_chunks) >= max_links:
                break
    
    return context_chunks

def extract_source_url(text_content):
    """Extracts the source URL from the first line of the cleaned text."""
    first_line = text_content.split('\n', 1)[0]
    url_match = re.search(r"Source URL: (https?://[^\s]+)", first_line)
    if url_match:
        return url_match.group(1)
    id_match = re.search(r"Source Identifier: ([^\n]+)", first_line)
    if id_match:
        return id_match.group(1)
    return "Unknown Source"


# ---------------- Gemini Chatbot ----------------
def ask_gemini(query, context_chunks, gemini_model):
    """Builds a prompt with the retrieved context and asks Gemini."""
    
    context_parts = []
    for chunk in context_chunks:
        source_url = extract_source_url(chunk['text'])
        
        if chunk['distance'] == 999.0:
            citation_label = f"Source (from link search): {source_url}"
        else:
            citation_label = f"Source: {source_url} (Match Distance: {chunk['distance']:.4f})"
        
        context_parts.append(
            f"Context from: {citation_label}\n"
            f"Content:\n{chunk['text']}\n"
        )
    context = "\n---\n".join(context_parts)

    prompt = f"""
    You are MOSDAC Assistant, a specialized AI. Your task is to answer the user's question based *only* on the provided MOSDAC context.
    You will be given one or more context blocks. Synthesize an answer from all of them.

    **Strict Rules:**
    1.  Use *only* the information in the "MOSDAC Context" blocks. Do not use any outside knowledge.
    2.  If the answer is not in the context, state clearly: "I could not find information on that topic in the MOSDAC data."
    3.  You *must* cite your sources. After providing the answer, add citations for all sources used in this exact format:
        **(Source: https://en.wikipedia.org/wiki/Identifier, Match Distance: [distance_value])**
    4.  If the source is from a link search (distance 999.0), cite it as:
        **(Source: https://en.wikipedia.org/wiki/Identifier, found via link search)**
    5.  Refer to the data as "MOSDAC data."

    ---
    **MOSDAC Context:**
    {context}
    ---

    **Question (for MOSDAC):**
    {query}

    **Answer (from MOSDAC context only, with citations):**
    """

    try:
        response = gemini_model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"⚠️ Error calling Gemini API: {e}"

# ---------------- Main Loop (MODIFIED) ----------------
if __name__ == "__main__":
    if not API_KEY or API_KEY == "YOUR_API_KEY_HERE":
        print("❌ ERROR: Please paste your valid GEMINI_API_KEY into the API_KEY variable.")
    else:
        genai.configure(api_key=API_KEY)
        
        try:
            # 1. Load all resources
            index, metadata, sentence_model, link_database, text_lookup = load_resources(
                INDEX_DIR, RESULTS_DIR, MODEL_NAME
            )
            
            gemini_model = genai.GenerativeModel(GEMINI_MODEL)
            
            print("\n🤖 Hi! I'm ready to answer questions about your documents (Hybrid Search & Multi-Context Enabled).")
            print("   Type 'exit' to quit.")

            while True:
                query = input("\nAsk me something: ")
                if query.lower() == "exit":
                    break
                if not query.strip():
                    continue
                
                total_start_time = time.perf_counter()
                
                # 3. Retrieve context
                retrieve_start_time = time.perf_counter()
                all_context_chunks = retrieve(query, index, metadata, sentence_model, top_k=RETRIEVAL_TOP_K)
                retrieve_end_time = time.perf_counter()
                
                answer = ""
                generate_start_time = generate_end_time = 0.0
                
                # --- MODIFIED: Filter chunks *before* checking the threshold ---
                good_context_chunks = [
                    chunk for chunk in all_context_chunks 
                    if chunk['distance'] < POOR_MATCH_THRESHOLD
                ]
                
                top_hit_distance = all_context_chunks[0]['distance'] if all_context_chunks else float('inf')

                # 4. Check if any good matches were found
                if not good_context_chunks:
                    # 4a. Fallback: Search link_db AND load the text
                    print(f"  -> Top match distance ({top_hit_distance:.4f}) is over threshold ({POOR_MATCH_THRESHOLD}). Trying link fallback.")
                    # We pass the 'text_lookup' map to find the text for the links
                    fallback_chunks = find_links_and_load_text(query, link_database, text_lookup)
                    
                    if not fallback_chunks:
                        answer = "🤖 I could not find a direct match in the text data or any relevant links for that topic."
                    else:
                        # We found text via links! Send it to Gemini.
                        print("  -> Sending link-based context to Gemini.")
                        generate_start_time = time.perf_counter()
                        answer = ask_gemini(query, fallback_chunks, gemini_model) 
                        generate_end_time = time.perf_counter()
                else:
                    # 4b. Standard Answer: Send *only the good chunks* to Gemini
                    print(f"  -> Found {len(good_context_chunks)} relevant context chunk(s). Sending to Gemini.")
                    generate_start_time = time.perf_counter()
                    answer = ask_gemini(query, good_context_chunks, gemini_model) # Pass the filtered list
                    generate_end_time = time.perf_counter()
                
                total_end_time = time.perf_counter()
                
                print(f"\n{answer}")
                
                print("\n--- 📊 Query Performance ---")
                print(f"  - Top Match Distance: {top_hit_distance:.4f} (Lower is better, 999.0 = link fallback)")
                print(f"  - Retrieval Time:   {(retrieve_end_time - retrieve_start_time):.4f}s")
                print(f"  - Generation Time:  {(generate_end_time - generate_start_time):.4f}s")
                print(f"  - Total Time:       {(total_end_time - total_start_time):.4f}s")
                print("-----------------------------")

        except FileNotFoundError as e:
            print(e)
        except Exception as e:
            print(f"An unexpected error occurred: {e}")