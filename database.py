import sqlite3
from config import DB_NAME, OWNER_ID
import random
import string

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        short_code TEXT UNIQUE,
        file_id TEXT,
        file_type TEXT,
        chat_id INTEGER,
        message_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        user_id INTEGER PRIMARY KEY,
        added_by INTEGER,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_owner BOOLEAN DEFAULT 0
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_code TEXT UNIQUE,
        first_msg_id INTEGER,
        last_msg_id INTEGER,
        chat_id INTEGER,
        total_files INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS batch_files (
        batch_id INTEGER,
        file_id INTEGER,
        file_index INTEGER,
        FOREIGN KEY(batch_id) REFERENCES batches(id),
        FOREIGN KEY(file_id) REFERENCES files(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS ad_views (
        user_id INTEGER,
        short_code TEXT,
        viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed BOOLEAN DEFAULT 0
    )''')
    
    c.execute("INSERT OR IGNORE INTO admins (user_id, is_owner) VALUES (?, 1)", (OWNER_ID,))
    
    conn.commit()
    conn.close()

def generate_short_code():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))

def save_file(short_code, file_id, file_type, chat_id, message_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO files (short_code, file_id, file_type, chat_id, message_id) VALUES (?, ?, ?, ?, ?)",
              (short_code, file_id, file_type, chat_id, message_id))
    conn.commit()
    conn.close()

def get_file(short_code):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT file_id, file_type FROM files WHERE short_code = ?", (short_code,))
    result = c.fetchone()
    conn.close()
    return result

def is_admin(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

def add_admin(user_id, added_by):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO admins (user_id, added_by, is_owner) VALUES (?, ?, 0)", (user_id, added_by))
    conn.commit()
    conn.close()

def remove_admin(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM admins WHERE user_id = ? AND is_owner = 0", (user_id,))
    conn.commit()
    conn.close()

def get_all_admins():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id, is_owner FROM admins")
    result = c.fetchall()
    conn.close()
    return result

def save_batch(batch_code, chat_id, first_msg_id, last_msg_id, total_files):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO batches (batch_code, chat_id, first_msg_id, last_msg_id, total_files) VALUES (?, ?, ?, ?, ?)",
              (batch_code, chat_id, first_msg_id, last_msg_id, total_files))
    batch_id = c.lastrowid
    conn.commit()
    conn.close()
    return batch_id

def save_batch_file(batch_id, file_id, file_index):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO batch_files (batch_id, file_id, file_index) VALUES (?, ?, ?)",
              (batch_id, file_id, file_index))
    conn.commit()
    conn.close()

def get_batch_files(batch_code):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''SELECT f.file_id, f.file_type FROM batch_files bf
                 JOIN batches b ON bf.batch_id = b.id
                 JOIN files f ON bf.file_id = f.id
                 WHERE b.batch_code = ?
                 ORDER BY bf.file_index''', (batch_code,))
    result = c.fetchall()
    conn.close()
    return result

def record_ad_view(user_id, short_code):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO ad_views (user_id, short_code, completed) VALUES (?, ?, 1)", (user_id, short_code))
    conn.commit()
    conn.close()

def has_viewed_ad(user_id, short_code):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT 1 FROM ad_views WHERE user_id = ? AND short_code = ?", (user_id, short_code))
    result = c.fetchone()
    conn.close()
    return result is not None
