from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DB_USER: str
    DB_PASSWORD: str
    DB_HOST: str
    DB_PORT: int
    DB_NAME: str

    GROQ_API_KEY:str
    GOOGLE_API_KEY: str
    
    REDIS_HOST: str 
    REDIS_PORT: int 

    JWT_SECRET_KEY:str
    JWT_REFRESH_SECRET_KEY:str
    JWT_ALGORITHM:str
    JWT_EXPIRATION_MINUTES:int
    JWT_REFRESH_SECRET_KEY_EXPIRATION_DAYS:int
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings=Settings()