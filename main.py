from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import sqlite3
import time
from typing import List, Optional

app = FastAPI()

# Configuration
RESERVATION_WINDOW_MINS = 10

# Database Setup
def get_db():
    conn = sqlite3.connect('laundry.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # State table
    c.execute('''CREATE TABLE IF NOT EXISTS state (
        id INTEGER PRIMARY KEY,
        status TEXT,
        end_time REAL,
        reservation_end_time REAL,
        current_user TEXT,
        last_user TEXT
    )''')
    # Add last_user column if it doesn't exist (for existing DBs)
    try:
        c.execute('ALTER TABLE state ADD COLUMN last_user TEXT')
    except sqlite3.OperationalError:
        pass # Already exists

    # Queue table
    c.execute('''CREATE TABLE IF NOT EXISTS queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_name TEXT,
        joined_at REAL
    )''')
    # Default state if empty
    c.execute('SELECT count(*) FROM state')
    if c.fetchone()[0] == 0:
        c.execute('INSERT INTO state (id, status, end_time, reservation_end_time, current_user, last_user) VALUES (1, "FREE", 0, 0, NULL, NULL)')
    conn.commit()
    conn.close()

init_db()

# Models
class UserAction(BaseModel):
    user_name: str
    duration_minutes: Optional[int] = 90

# Core Logic: Lazy State Evaluation
def evaluate_state(conn):
    c = conn.cursor()
    c.execute('SELECT * FROM state WHERE id=1')
    state = dict(c.fetchone())
    now = time.time()
    
    # Status: IN_USE -> Check if cycle finished
    if state['status'] == 'IN_USE' and now > state['end_time']:
        # Cycle finished. Save this user as last_user.
        last_user = state['current_user']
        
        # Check queue.
        c.execute('SELECT * FROM queue ORDER BY joined_at ASC LIMIT 1')
        next_user = c.fetchone()
        
        if next_user:
            # Reserve for next user
            res_end = now + (RESERVATION_WINDOW_MINS * 60)
            c.execute('UPDATE state SET status="RESERVED", reservation_end_time=?, current_user=?, last_user=? WHERE id=1', (res_end, next_user['user_name'], last_user))
        else:
            # No one waiting
            c.execute('UPDATE state SET status="FREE", end_time=0, reservation_end_time=0, current_user=NULL, last_user=? WHERE id=1', (last_user,))
        conn.commit()
        # Re-fetch state
        c.execute('SELECT * FROM state WHERE id=1')
        state = dict(c.fetchone())

    # Status: RESERVED -> Check if reservation expired
    if state['status'] == 'RESERVED' and now > state['reservation_end_time']:
        # Reservation expired. Remove user and move to next.
        c.execute('DELETE FROM queue WHERE user_name=?', (state['current_user'],))
        
        c.execute('SELECT * FROM queue ORDER BY joined_at ASC LIMIT 1')
        next_user = c.fetchone()
        
        if next_user:
            res_end = now + (RESERVATION_WINDOW_MINS * 60)
            c.execute('UPDATE state SET status="RESERVED", reservation_end_time=?, current_user=? WHERE id=1', (res_end, next_user['user_name']))
        else:
            c.execute('UPDATE state SET status="FREE", end_time=0, reservation_end_time=0, current_user=NULL WHERE id=1')
        conn.commit()
        # Re-fetch state
        c.execute('SELECT * FROM state WHERE id=1')
        state = dict(c.fetchone())
        
    return state

# API Endpoints
@app.get("/api/status")
def get_status():
    conn = get_db()
    state = evaluate_state(conn)
    
    c = conn.cursor()
    c.execute('SELECT user_name FROM queue ORDER BY joined_at ASC')
    queue = [row['user_name'] for row in c.fetchall()]
    conn.close()
    
    return {
        "status": state['status'],
        "end_time": state['end_time'],
        "reservation_end_time": state['reservation_end_time'],
        "current_user": state['current_user'],
        "last_user": state['last_user'],
        "queue": queue,
        "server_time": time.time()
    }

@app.post("/api/start")
def start_laundry(action: UserAction):
    conn = get_db()
    state = evaluate_state(conn)
    c = conn.cursor()
    
    can_start = False
    if state['status'] == 'FREE':
        can_start = True
    elif state['status'] == 'RESERVED' and state['current_user'] == action.user_name:
        can_start = True
        # Remove from queue
        c.execute('DELETE FROM queue WHERE user_name=?', (action.user_name,))
        
    if not can_start:
        conn.close()
        raise HTTPException(status_code=400, detail="Not authorized or machine busy.")
        
    end_time = time.time() + (action.duration_minutes * 60)
    c.execute('UPDATE state SET status="IN_USE", end_time=?, reservation_end_time=0, current_user=? WHERE id=1', (end_time, action.user_name))
    conn.commit()
    conn.close()
    return {"status": "started", "end_time": end_time}

@app.post("/api/free")
def set_free():
    conn = get_db()
    c = conn.cursor()
    # Get current user to save as last_user
    c.execute('SELECT current_user FROM state WHERE id=1')
    row = c.fetchone()
    last_user = row['current_user'] if row else None

    # Reset current state and trigger evaluation
    c.execute('UPDATE state SET status="FREE", end_time=0, reservation_end_time=0, current_user=NULL, last_user=? WHERE id=1', (last_user,))
    conn.commit()
    evaluate_state(conn)
    conn.close()
    return {"status": "freed"}

@app.post("/api/queue/join")
def join_queue(action: UserAction):
    conn = get_db()
    state = evaluate_state(conn)
    c = conn.cursor()
    
    # Check if already in queue or using
    c.execute('SELECT * FROM queue WHERE user_name=?', (action.user_name,))
    if c.fetchone() or state['current_user'] == action.user_name:
        conn.close()
        return {"status": "already_in"}
        
    c.execute('INSERT INTO queue (user_name, joined_at) VALUES (?, ?)', (action.user_name, time.time()))
    conn.commit()
    
    # If machine was FREE, trigger reservation immediately
    if state['status'] == 'FREE':
        evaluate_state(conn)
        
    conn.close()
    return {"status": "joined"}

@app.post("/api/queue/leave")
def leave_queue(action: UserAction):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM queue WHERE user_name=?', (action.user_name,))
    conn.commit()
    
    # If they were the RESERVED user, evaluate who's next
    c.execute('SELECT * FROM state WHERE id=1')
    state = c.fetchone()
    if state['status'] == 'RESERVED' and state['current_user'] == action.user_name:
        c.execute('UPDATE state SET status="FREE", reservation_end_time=0, current_user=NULL WHERE id=1')
        conn.commit()
        evaluate_state(conn)
        
    conn.close()
    return {"status": "left"}

@app.get("/")
def read_root():
    try:
        with open("index.html", "r") as f:
            return HTMLResponse(content=f.read(), status_code=200)
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Frontend index.html not found</h1>", status_code=404)
