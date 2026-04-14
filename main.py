# main.py

from database.db import init_db, SessionLocal, FileEvent
from datetime import datetime

# Initialize database (creates tables if not exist)
init_db()

# Create a new session
session = SessionLocal()

# Test insertion
test_event = FileEvent(
    filename="test_file.txt",
    action="CREATED",
    timestamp=datetime.utcnow()
)

session.add(test_event)
session.commit()

print("Test event inserted successfully!")
session.close()
