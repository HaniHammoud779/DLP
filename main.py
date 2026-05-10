from database.db import init_db, SessionLocal, FileEvent
from datetime import datetime, timezone

init_db()

session = SessionLocal()

event = FileEvent(
    filename="test_file.txt",
    action="TEST",
    label="SAFE",
    score=10.0,
    ml_prediction="SAFE",
    ml_confidence=0.90,
    rule_score=0.0,
    reason="Database test event",
    timestamp=datetime.now(timezone.utc)
)

session.add(event)
session.commit()
session.close()

print("Database test inserted successfully.")
