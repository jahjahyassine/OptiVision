import sqlite3
import numpy as np

# 1. Connect to the database
conn = sqlite3.connect("/home/yassine/Projects/OptiVision/database/face_embeddings/faces.db")
cursor = conn.cursor()

# 2. Execute the selection
cursor.execute("SELECT * FROM faces")
rows = cursor.fetchall()

# 3. Process each row
for row in rows:
    face_id = row[0]
    name = row[1]
    # row[2] is the empty string/placeholder
    blob = row[3]  # This is the binary embedding
    timestamp = row[4]

    # Convert the binary blob back into a NumPy array of floats
    # We use float32 because it's the standard for face embeddings
    vector = np.frombuffer(blob, dtype=np.float32)

    print(f"ID: {face_id} | Name: {name} | Timestamp: {timestamp}")
    print(f"Vector (first 5 values): {vector[:5]}...") 
    print("-" * 30)

conn.close()