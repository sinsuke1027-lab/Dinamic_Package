"""
データベース接続設定モジュール。
SQLAlchemy を使用して SQLite（開発）/ PostgreSQL（本番）に接続する。
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# .env ファイルから環境変数を読み込む
load_dotenv()

# 環境変数 DATABASE_URL が設定されていれば本番DBを使用、なければSQLiteを使用
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./dynamic_pricing.db")

# SQLite の場合は check_same_thread を無効化（FastAPIのマルチスレッド対応）
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)

# セッションファクトリ（各リクエストごとにセッションを生成する）
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 全モデルの基底クラス
Base = declarative_base()


def get_db():
    """
    FastAPI の依存性注入 (Depends) で使用するDBセッションのジェネレーター。
    リクエスト終了後に必ずセッションをクローズする。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
