from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from src.config.settings import settings


def get_llm():
    
    return ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=settings.GROQ_API_KEY,
            temperature=0,
    )
  
def get_vision_llm():
    return ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        google_api_key=settings.GOOGLE_API_KEY,
        temperature=0,
    )