import os
import csv
import openpyxl
import asyncio
import httpx
import logging
from typing import List, Dict, Any, Optional, Tuple

from app.core.config import settings

logger = logging.getLogger("app.intelligence")

URL = "https://akirs-tms.net/intelligence_db/api/v1/intelligence/intelligenceGathering"

def compute_jaccard_similarity(s1: str, s2: str) -> float:
    """Compute token-based Jaccard similarity score between two strings."""
    if not s1 or not s2:
        return 0.0
    w1 = set(s1.lower().strip().split())
    w2 = set(s2.lower().strip().split())
    if not w1 or not w2:
        return 0.0
    return len(w1.intersection(w2)) / len(w1.union(w2))

async def check_db_record(query: str, db_target_column: str = "ANY", fuzzy_match: bool = False) -> Optional[Dict[str, Any]]:
    """
    Query the live search endpoint to find an existing record in the database.
    Supports strict search or token-based fuzzy similarity checking.
    """
    token = settings.intelligence_token
    if not token:
        logger.error("No intelligence token configured in Settings!")
        return None

    if not query or len(str(query).strip()) < 3:
        return None

    query_str = str(query).strip()

    headers = {
        "accept": "application/json",
        "authorization": f"Bearer {token}",
        "Origin": "https://ibomtax.net",
        "Referer": "https://ibomtax.net/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    }
    
    params = {
        "page": 1,
        "limit": 10 if fuzzy_match else 5,
        "search": query_str
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(URL, headers=headers, params=params)
            if response.status_code == 200:
                res_data = response.json()
                data_items = res_data.get("data", [])
                if data_items:
                    q_lower = query_str.lower()
                    
                    best_match = None
                    best_score = 0.0

                    for item in data_items:
                        name = str(item.get("taxPayerName", "")).strip().lower()
                        email = str(item.get("email", "")).strip().lower()
                        phone = str(item.get("phone", "")).strip().lower()
                        
                        match_found = False
                        # Check exact/substring matches first
                        if db_target_column in ("ANY", "NAME") and q_lower in name:
                            match_found = True
                        elif db_target_column in ("ANY", "EMAIL") and q_lower in email:
                            match_found = True
                        elif db_target_column in ("ANY", "PHONE") and q_lower in phone:
                            match_found = True

                        if match_found:
                            return item

                        # If fuzzy matching is enabled, compute Jaccard token similarity
                        if fuzzy_match:
                            score = 0.0
                            if db_target_column in ("ANY", "NAME"):
                                score = max(score, compute_jaccard_similarity(query_str, name))
                            if db_target_column in ("ANY", "EMAIL"):
                                score = max(score, compute_jaccard_similarity(query_str, email))
                            if db_target_column in ("ANY", "PHONE"):
                                score = max(score, compute_jaccard_similarity(query_str, phone))
                                
                            if score > best_score:
                                best_score = score
                                best_match = item
                                
                    if fuzzy_match and best_score >= 0.35: # Suggest if >= 35% word token match similarity
                        logger.info(f"Fuzzy duplicate match found: '{query_str}' -> '{best_match.get('taxPayerName')}' (Jaccard: {best_score:.2f})")
                        return best_match
            elif response.status_code == 401:
                logger.warning("Token expired or unauthorized (401) on search check.")
    except Exception as e:
        logger.error(f"Error calling live search endpoint: {e!r}")
        logger.error(f"response: {response!r}")
    
    return None

async def check_records_batch(queries: List[str], db_target_column: str = "ANY", fuzzy_match: bool = False) -> List[Optional[Dict[str, Any]]]:
    """
    Runs parallel lookups against the search API using asyncio.Semaphore to throttle concurrency.
    """
    sem = asyncio.Semaphore(15)
    
    async def worker(q: str):
        if not q or len(str(q).strip()) < 3:
            return None
        async with sem:
            return await check_db_record(q, db_target_column, fuzzy_match)
            
    tasks = [worker(q) for q in queries]
    return await asyncio.gather(*tasks)

async def check_file_records_against_db(
    records: List[Dict[str, Any]],
    fields: List[str],
    query_field: Optional[str] = None,
    db_target_column: str = "ANY",
    fuzzy_match: bool = False
) -> List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]]:
    """
    Given a list of extracted records, runs throttled parallel queries against the live database.
    Allows specifying the exact field to query by, falling back to typical identifier searches.
    """
    queries: List[str] = []
    
    # 1. Resolve search indices
    query_idx = fields.index(query_field) if query_field and query_field in fields else -1
    
    name_idx = fields.index("NAME") if "NAME" in fields else (fields.index("ACCOUNT_NAME") if "ACCOUNT_NAME" in fields else -1)
    email_idx = fields.index("EMAIL") if "EMAIL" in fields else -1
    phone_idx = fields.index("PHONE_NUMBER") if "PHONE_NUMBER" in fields else (fields.index("PHONE") if "PHONE" in fields else -1)
    
    for rec in records:
        vals = rec.get("values", [])
        q_val = ""
        
        # Read the chosen custom query column if selected
        if query_idx != -1 and query_idx < len(vals) and vals[query_idx] != "N/A" and vals[query_idx]:
            q_val = vals[query_idx]
        else:
            # Fall back to typical default ordering
            if name_idx != -1 and name_idx < len(vals) and vals[name_idx] != "N/A" and vals[name_idx]:
                q_val = vals[name_idx]
            elif email_idx != -1 and email_idx < len(vals) and vals[email_idx] != "N/A" and vals[email_idx]:
                q_val = vals[email_idx]
            elif phone_idx != -1 and phone_idx < len(vals) and vals[phone_idx] != "N/A" and vals[phone_idx]:
                q_val = vals[phone_idx]
                
        queries.append(q_val)
        
    results = await check_records_batch(queries, db_target_column, fuzzy_match)
    return list(zip(records, results))
