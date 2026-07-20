import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
# Convertir a async si es necesario
if not DATABASE_URL.startswith("postgresql+asyncpg"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

async def add_column():
    engine = create_async_engine(DATABASE_URL, echo=True)
    
    async with engine.connect() as conn:
        # Verificar si la columna existe
        result = await conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'deliveries' 
            AND column_name = 'issue_analysis_result'
        """))
        
        exists = result.fetchone()
        
        if not exists:
            print("Columna no existe. Agregando...")
            await conn.execute(text("""
                ALTER TABLE deliveries 
                ADD COLUMN issue_analysis_result VARCHAR
            """))
            await conn.commit()
            print("✅ Columna 'issue_analysis_result' agregada exitosamente")
        else:
            print("✅ La columna 'issue_analysis_result' ya existe")
    
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(add_column())
