# database/db.py

from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from config import DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME
from datetime import datetime

Base = declarative_base()

# Database connection string
DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

engine = create_engine(DATABASE_URL, echo=True)
Session = sessionmaker(bind=engine)
session = Session()  # This is what monitor.py needs

# Define the FileEvent table
class FileEvent(Base):
    __tablename__ = "file_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False)
    action = Column(String(50), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

# Initialize DB
def init_db():
    Base.metadata.create_all(engine)
