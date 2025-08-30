import sqlite3

DB_NAME = "facts.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS facts (
                    question TEXT PRIMARY KEY,
                    answer TEXT
                )''')
    conn.commit()
    conn.close()

def save_fact(question, answer):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO facts (question, answer) VALUES (?, ?)", (question.lower(), answer))
    conn.commit()
    conn.close()

def get_fact(question):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT answer FROM facts WHERE question=?", (question.lower(),))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None
