import time
import os
import csv
import random
import string
from app.services.cleaner import find_similar_duplicates_sorted_neighborhood, pre_flight_validate
from app.core.state import PRESETS

def generate_large_intelligence_dataset(filepath, num_rows=10000):
    """
    Generates a large simulated intelligence gathering dataset with minor fuzzy variations
    to test the performance and accuracy of our Sorted Neighborhood fuzzy deduplicator.
    """
    headers = ["NAME", "ADDRESS", "PHONE_NUMBER", "NATURE_OF_BUSINESS", "EMAIL"]
    
    # Generate some base values to form fuzzy groups
    base_names = [f"Alhaji {f} {l}" for f in ["Musa", "Bello", "Ibrahim", "Garba", "Usman"] for l in ["Danjuma", "Gwarzo", "Kano", "Abubakar"]]
    base_streets = [f"{i} {s} Road" for i in range(1, 100) for s in ["Oron", "Aka", "Abak", "Nwaniba", "Ikpa"]]
    base_cities = ["Uyo", "Eket", "Ikot Ekpene", "Oron", "Ibeno"]
    base_businesses = ["Retail Trade", "Import Export", "General Merchant", "Logistics & Transport", "Consultancy"]
    
    records = []
    
    for i in range(num_rows):
        name = random.choice(base_names)
        address = f"{random.choice(base_streets)}, {random.choice(base_cities)}"
        phone = f"080{random.randint(10000000, 99999999)}"
        business = random.choice(base_businesses)
        email = f"{name.lower().replace(' ', '')}@example.com"
        records.append([name, address, phone, business, email])
        
    # Inject fuzzy duplicates
    # We will pick 50 random records and insert "weirdly similar" variations of them
    duplicate_indexes = random.sample(range(num_rows), 50)
    for idx in duplicate_indexes:
        orig = records[idx]
        
        # Variation 1: Typo in name or address
        var1 = list(orig)
        var1[0] = var1[0] + " Jr."  # Alhaji Musa Danjuma Jr.
        var1[1] = var1[1].replace("Road", "Rd")
        
        # Variation 2: Swap phone digits slightly or change email casing
        var2 = list(orig)
        var2[4] = var2[4].upper()
        var2[1] = var2[1] + " (Suite 4)"
        
        records.append(var1)
        records.append(var2)
        
    # Shuffle records
    random.shuffle(records)
    
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(records)

    print(f"Generated test dataset with {len(records)} rows and fuzzy duplicates.")
    return len(records)

def run_verification():
    test_csv = "scratch/test_large_intelligence.csv"
    os.makedirs("scratch", exist_ok=True)
    
    try:
        # Step 1: Generate dataset
        num_rows = generate_large_intelligence_dataset(test_csv, num_rows=10000)
        
        # Step 2: Read headers and rows back
        rows = []
        with open(test_csv, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)
            for r in reader:
                rows.append(r)
                
        # Parse into dictionary records matching cleaner.py format
        fields = PRESETS["intelligence"]["fields"]
        records = []
        for idx, row in enumerate(rows):
            record = {
                "id": str(idx + 1),
                "source_row": idx + 2,
                "values": row,
                "clean_values": {fields[i]: row[i] for i in range(len(fields))}
            }
            records.append(record)
            
        print("Starting Sorted Neighborhood Fuzzy Deduplication...")
        start_time = time.time()
        
        # Step 3: Run optimized deduplication
        groups = find_similar_duplicates_sorted_neighborhood(records)
        
        end_time = time.time()
        duration = end_time - start_time
        
        print("\n--- PERFORMANCE & DEDUPLICATION RESULTS ---")
        print(f"Total processed records: {len(records)}")
        print(f"Total duplicate groups discovered: {len(groups)}")
        print(f"Total time taken: {duration:.4f} seconds")
        
        # Assert low-spec PC optimization: 10,000+ rows takes less than 2.0 seconds
        assert duration < 2.0, f"Performance optimization failed! Took {duration:.2f}s which is > 2.0s."
        print("✓ Performance metric MET: Deduplication executed in under 2.0 seconds!")
        
        # Assert some duplicates were actually grouped
        assert len(groups) > 0, "No duplicate clusters detected. Check generation logic."
        print(f"✓ Accuracy metric MET: Successfully clustered duplicate groups.")
        
        # Step 4: Run pre-flight checks on a clean dataset
        print("\nRunning Pre-Flight Audit on generated dataset...")
        health = pre_flight_validate(test_csv)
        print(f"Health Score: {health['score']}/100")
        print(f"Health Status: {health['status']}")
        
        # Assert clean health status
        assert health["score"] >= 95, f"Expected perfect score for clean generated file, got {health['score']}"
        print("✓ Pre-Flight health check PASSED!")
        
    finally:
        if os.path.exists(test_csv):
            os.remove(test_csv)
            print("Cleaned up temporary test files.")

if __name__ == "__main__":
    run_verification()
