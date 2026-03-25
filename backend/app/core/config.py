import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    PROJECT_NAME: str = "Interview Copilot API"
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/interview_copilot")
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")

settings = Settings()
