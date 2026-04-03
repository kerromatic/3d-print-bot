import aiosqlite
import os
from datetime import datetime
from pathlib import Path


class Database:
    """Async SQLite database for bot persistence."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.db: aiosqlite.Connection | None = None

    async def connect(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.db = await aiosqlite.connect(self.db_path)
        self.db.row_factory = aiosqlite.Row
        await self._create_tables()

    async def close(self):
        if self.db:
            await self.db.close()

    async def _create_tables(self):
        await self.db.executescript("""
            CREATE TABLE IF NOT EXISTS prints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                image_path TEXT,
                tags TEXT DEFAULT '',
                printer TEXT DEFAULT '',
                material TEXT DEFAULT '',
                stl_link TEXT DEFAULT '',
                posted_by INTEGER,
                message_id INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                print_id INTEGER,
                user_id INTEGER,
                username TEXT,
                rating INTEGER CHECK(rating BETWEEN 1 AND 5),
                text TEXT,
                message_id INTEGER,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (print_id) REFERENCES prints(id)
            );
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                display_name TEXT,
                prints_shared INTEGER DEFAULT 0,
                reviews_given INTEGER DEFAULT 0,
                requests_fulfilled INTEGER DEFAULT 0,
                joined_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS print_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                description TEXT,
                claimed_by INTEGER DEFAULT NULL,
                status TEXT DEFAULT 'open',
                message_id INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS potd_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                print_id INTEGER,
                featured_date TEXT DEFAULT (date('now')),
                FOREIGN KEY (print_id) REFERENCES prints(id)
            );
        """)
        await self.db.commit()

    async def add_print(self, name, description, image_path, tags="", printer="", material="", stl_link="", posted_by=0, message_id=0) -> int:
        cursor = await self.db.execute(
            """INSERT INTO prints (name, description, image_path, tags, printer, material, stl_link, posted_by, message_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, description, image_path, tags, printer, material, stl_link, posted_by, message_id),
        )
        await self.db.commit()
        return cursor.lastrowid

    async def get_print(self, print_id: int):
        cursor = await self.db.execute("SELECT * FROM prints WHERE id = ?", (print_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def search_prints(self, keyword: str, limit: int = 10):
        cursor = await self.db.execute(
            """SELECT * FROM prints
               WHERE name LIKE ? OR tags LIKE ? OR material LIKE ? OR description LIKE ?
               ORDER BY created_at DESC LIMIT ?""",
            (f"%{keyword}%",) * 4 + (limit,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def get_random_print_for_potd(self):
        cursor = await self.db.execute(
            """SELECT p.* FROM prints p
               WHERE p.id NOT IN (
                   SELECT print_id FROM potd_history
                   WHERE featured_date > date('now', '-30 days')
               )
               ORDER BY RANDOM() LIMIT 1"""
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def record_potd(self, print_id: int):
        await self.db.execute("INSERT INTO potd_history (print_id) VALUES (?)", (print_id,))
        await self.db.commit()

    async def get_print_count(self) -> int:
        cursor = await self.db.execute("SELECT COUNT(*) FROM prints")
        return (await cursor.fetchone())[0]

    async def add_review(self, print_id, user_id, username, rating, text, message_id=0) -> int:
        cursor = await self.db.execute(
            """INSERT INTO reviews (print_id, user_id, username, rating, text, message_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (print_id, user_id, username, rating, text, message_id),
        )
        await self.db.commit()
        await self._increment_user_stat(user_id, username, "reviews_given")
        return cursor.lastrowid

    async def get_reviews_for_print(self, print_id: int):
        cursor = await self.db.execute(
            "SELECT * FROM reviews WHERE print_id = ? ORDER BY created_at DESC", (print_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def get_average_rating(self, print_id: int):
        cursor = await self.db.execute("SELECT AVG(rating) FROM reviews WHERE print_id = ?", (print_id,))
        row = await cursor.fetchone()
        return round(row[0], 1) if row[0] else None

    async def upsert_user(self, user_id, username, display_name):
        await self.db.execute(
            """INSERT INTO users (user_id, username, display_name) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, display_name=excluded.display_name""",
            (user_id, username, display_name),
        )
        await self.db.commit()

    async def _increment_user_stat(self, user_id, username, field):
        await self.upsert_user(user_id, username, username)
        await self.db.execute(f"UPDATE users SET {field} = {field} + 1 WHERE user_id = ?", (user_id,))
        await self.db.commit()

    async def get_leaderboard(self, limit=10):
        cursor = await self.db.execute(
            """SELECT *, (prints_shared * 3 + reviews_given * 2 + requests_fulfilled * 5) AS score
               FROM users ORDER BY score DESC LIMIT ?""", (limit,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def get_user_count(self) -> int:
        cursor = await self.db.execute("SELECT COUNT(*) FROM users")
        return (await cursor.fetchone())[0]

    async def add_request(self, user_id, username, description, message_id=0) -> int:
        cursor = await self.db.execute(
            "INSERT INTO print_requests (user_id, username, description, message_id) VALUES (?, ?, ?, ?)",
            (user_id, username, description, message_id),
        )
        await self.db.commit()
        return cursor.lastrowid

    async def claim_request(self, request_id, claimer_id) -> bool:
        cursor = await self.db.execute(
            "UPDATE print_requests SET claimed_by=?, status='claimed' WHERE id=? AND status='open'",
            (claimer_id, request_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def get_open_requests(self, limit=10):
        cursor = await self.db.execute(
            "SELECT * FROM print_requests WHERE status='open' ORDER BY created_at DESC LIMIT ?", (limit,),
        )
        return [dict(r) for r in await cursor.fetchall()]

    async def get_review_count(self) -> int:
        cursor = await self.db.execute("SELECT COUNT(*) FROM reviews")
        return (await cursor.fetchone())[0]
