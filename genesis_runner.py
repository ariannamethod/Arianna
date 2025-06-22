import os
from utils.genesis import AriannaGenesis

from dotenv import load_dotenv
load_dotenv()

GROUP_ID = os.getenv("GROUP_ID", "ARIANNA-CORE")
CREATOR_CHAT_ID = os.getenv("CREATOR_CHAT_ID")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX = os.getenv("PINECONE_INDEX")
CHRONICLE_PATH = os.getenv("CHRONICLE_PATH", "./config/chronicle.log")

if __name__ == "__main__":
    genesis = AriannaGenesis(
        group_id=GROUP_ID,
        oleg_id=CREATOR_CHAT_ID,
        pinecone_api_key=PINECONE_API_KEY,
        pinecone_index=PINECONE_INDEX,
        chronicle_path=CHRONICLE_PATH
    )
    genesis.run()
