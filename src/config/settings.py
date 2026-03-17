from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DB_USER: str
    DB_PASSWORD: str
    DB_HOST: str
    DB_PORT: int
    DB_NAME: str

    GROQ_API_KEY: str
    GOOGLE_API_KEY: str

    REDIS_HOST: str
    REDIS_PORT: int

    JWT_SECRET_KEY: str
    JWT_REFRESH_SECRET_KEY: str
    JWT_ALGORITHM: str
    JWT_EXPIRATION_MINUTES: int
    JWT_REFRESH_SECRET_KEY_EXPIRATION_DAYS: int

    MAIL_USERNAME: str
    MAIL_PASSWORD: str
    MAIL_FROM: str
    MAIL_SERVER: str
    MAIL_PORT: int
    MAIL_STARTTLS: bool = True
    MAIL_SSL_TLS: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()