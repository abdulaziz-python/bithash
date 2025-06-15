import sqlite3
import json
import time
import uuid
import logging
import os
import threading
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

logging.basicConfig(level=logging.INFO)

POSTGRES_URL = os.getenv("POSTGRES_URL", "postgres://avnadmin:AVNS_bCFJfrxAeuXiegPEupE@pg-8197d21-bithash353da232.b.aivencloud.com:16902/defaultdb?sslmode=require")

def is_postgres():
    return POSTGRES_URL and POSTGRES_URL.startswith("postgres://")

# Connection pool for production
_pg_pool = None
_pool_lock = threading.Lock()

def get_pg_pool():
    global _pg_pool
    if _pg_pool is None:
        with _pool_lock:
            if _pg_pool is None:
                try:
                    _pg_pool = ThreadedConnectionPool(
                        minconn=1,
                        maxconn=20,
                        dsn=POSTGRES_URL
                    )
                    logging.info("✅ PostgreSQL connection pool created")
                except Exception as e:
                    logging.error(f"❌ Failed to create connection pool: {e}")
                    raise
    return _pg_pool

@contextmanager
def get_pg_conn():
    pool = get_pg_pool()
    conn = None
    try:
        conn = pool.getconn()
        yield conn
    except Exception as e:
        if conn:
            conn.rollback()
        logging.error(f"❌ Database error: {e}")
        raise
    finally:
        if conn:
            pool.putconn(conn)

class Database:
    def __init__(self, db_path='mining.db'):
        self.db_path = db_path
        self.pg_mode = is_postgres()
        self._local_lock = threading.Lock()
        self.init_database()
    
    def init_database(self):
        if self.pg_mode:
            try:
                with get_pg_conn() as conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                        # Check and create wallets table
                        cursor.execute("""
                            SELECT EXISTS (
                                SELECT FROM information_schema.tables 
                                WHERE table_schema = 'public' 
                                AND table_name = 'wallets'
                            );
                        """)
                        
                        if not cursor.fetchone()[0]:
                            cursor.execute('''
                                CREATE TABLE wallets (
                                    address TEXT PRIMARY KEY,
                                    energy REAL DEFAULT 100.0,
                                    last_mined BIGINT DEFAULT 0,
                                    created_at BIGINT DEFAULT 0,
                                    total_mined REAL DEFAULT 0.0,
                                    total_sent REAL DEFAULT 0.0,
                                    total_received REAL DEFAULT 0.0,
                                    telegram_chat_id TEXT,
                                    last_login BIGINT DEFAULT 0,
                                    mining_sessions INTEGER DEFAULT 0,
                                    total_blocks_mined INTEGER DEFAULT 0,
                                    mining_start_time BIGINT DEFAULT 0,
                                    is_mining INTEGER DEFAULT 0,
                                    session_blocks INTEGER DEFAULT 0,
                                    session_rewards REAL DEFAULT 0.0,
                                    referrer TEXT,
                                    referrals TEXT DEFAULT '[]'
                                );
                            ''')
                            logging.info("✅ Wallets table created")
                        
                        # Check and create blockchain table
                        cursor.execute("""
                            SELECT EXISTS (
                                SELECT FROM information_schema.tables 
                                WHERE table_schema = 'public' 
                                AND table_name = 'blockchain'
                            );
                        """)
                        
                        if not cursor.fetchone()[0]:
                            cursor.execute('''
                                CREATE TABLE blockchain (
                                    id SERIAL PRIMARY KEY,
                                    block_index INTEGER,
                                    timestamp TEXT,
                                    miner TEXT,
                                    previous_hash TEXT,
                                    hash TEXT,
                                    transactions TEXT,
                                    nonce INTEGER,
                                    difficulty INTEGER,
                                    reward REAL,
                                    status TEXT
                                );
                            ''')
                            logging.info("✅ Blockchain table created")
                        
                        # Check and create pending_transactions table
                        cursor.execute("""
                            SELECT EXISTS (
                                SELECT FROM information_schema.tables 
                                WHERE table_schema = 'public' 
                                AND table_name = 'pending_transactions'
                            );
                        """)
                        
                        if not cursor.fetchone()[0]:
                            cursor.execute('''
                                CREATE TABLE pending_transactions (
                                    id SERIAL PRIMARY KEY,
                                    from_wallet TEXT,
                                    to_wallet TEXT,
                                    amount REAL,
                                    timestamp TEXT,
                                    type TEXT
                                );
                            ''')
                            logging.info("✅ Pending transactions table created")
                        
                        conn.commit()
                        logging.info("✅ PostgreSQL database initialized successfully")
                        
            except Exception as e:
                logging.error(f"❌ PostgreSQL init error: {e}")
                # Don't raise to allow app to continue
        else:
            with self._local_lock:
                conn = sqlite3.connect(self.db_path, check_same_thread=False)
                cursor = conn.cursor()
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS wallets (
                        address TEXT PRIMARY KEY,
                        energy REAL DEFAULT 100.0,
                        last_mined INTEGER DEFAULT 0,
                        created_at INTEGER DEFAULT 0,
                        total_mined REAL DEFAULT 0.0,
                        total_sent REAL DEFAULT 0.0,
                        total_received REAL DEFAULT 0.0,
                        telegram_chat_id TEXT,
                        last_login INTEGER DEFAULT 0,
                        mining_sessions INTEGER DEFAULT 0,
                        total_blocks_mined INTEGER DEFAULT 0,
                        mining_start_time INTEGER DEFAULT 0,
                        is_mining INTEGER DEFAULT 0,
                        session_blocks INTEGER DEFAULT 0,
                        session_rewards REAL DEFAULT 0.0,
                        referrer TEXT,
                        referrals TEXT DEFAULT '[]'
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS blockchain (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        block_index INTEGER,
                        timestamp TEXT,
                        miner TEXT,
                        previous_hash TEXT,
                        hash TEXT,
                        transactions TEXT,
                        nonce INTEGER,
                        difficulty INTEGER,
                        reward REAL,
                        status TEXT
                    )
                ''')
                
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS pending_transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        from_wallet TEXT,
                        to_wallet TEXT,
                        amount REAL,
                        timestamp TEXT,
                        type TEXT
                    )
                ''')
                
                conn.commit()
                conn.close()
                logging.info("✅ SQLite database initialized successfully")

    def get_user_wallet_by_telegram(self, telegram_chat_id):
        try:
            if self.pg_mode:
                with get_pg_conn() as conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                        cursor.execute('SELECT address FROM wallets WHERE telegram_chat_id = %s', (str(telegram_chat_id),))
                        result = cursor.fetchone()
                        return result['address'] if result else None
            else:
                with self._local_lock:
                    conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    cursor = conn.cursor()
                    cursor.execute('SELECT address FROM wallets WHERE telegram_chat_id = ?', (str(telegram_chat_id),))
                    result = cursor.fetchone()
                    conn.close()
                    return result[0] if result else None
        except Exception as e:
            logging.error(f"❌ Get user wallet error: {e}")
            return None

    def create_wallet(self, telegram_chat_id=None, referrer_chat_id=None):
        try:
            address = "bh" + str(uuid.uuid4()).replace('-', '')[:20]
            current_time = int(time.time())
            
            if self.pg_mode:
                with get_pg_conn() as conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                        referrer_address = None
                        if referrer_chat_id:
                            cursor.execute('SELECT address FROM wallets WHERE telegram_chat_id = %s', (str(referrer_chat_id),))
                            r = cursor.fetchone()
                            if r:
                                referrer_address = r['address']
                        
                        cursor.execute('''
                            INSERT INTO wallets (
                                address, energy, created_at, last_login, 
                                telegram_chat_id, referrer
                            ) VALUES (%s, %s, %s, %s, %s, %s)
                        ''', (address, 125.0 if referrer_address else 100.0, current_time, current_time, 
                            str(telegram_chat_id) if telegram_chat_id else None,
                            referrer_address))
                        
                        if referrer_address:
                            cursor.execute('SELECT referrals, energy FROM wallets WHERE address = %s', (referrer_address,))
                            ref_data = cursor.fetchone()
                            if ref_data:
                                referrals_list = json.loads(ref_data['referrals'] or '[]')
                                referrals_list.append(str(telegram_chat_id))
                                new_energy = min(200.0, ref_data['energy'] + 25)
                                cursor.execute('''
                                    UPDATE wallets SET referrals = %s, energy = %s WHERE address = %s
                                ''', (json.dumps(referrals_list), new_energy, referrer_address))
                                logging.info(f"🎁 Referral bonus applied: +25 energy to {referrer_address}")
                        
                        conn.commit()
                        logging.info(f"✅ Wallet created: {address}")
                        return address
            else:
                with self._local_lock:
                    conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    cursor = conn.cursor()
                    
                    referrer_address = None
                    if referrer_chat_id:
                        cursor.execute('SELECT address FROM wallets WHERE telegram_chat_id = ?', (str(referrer_chat_id),))
                        result = cursor.fetchone()
                        if result:
                            referrer_address = result[0]
                    
                    cursor.execute('''
                        INSERT INTO wallets (
                            address, energy, created_at, last_login, 
                            telegram_chat_id, referrer
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    ''', (address, 125.0 if referrer_address else 100.0, current_time, current_time, 
                          str(telegram_chat_id) if telegram_chat_id else None,
                          referrer_address))
                    
                    if referrer_address:
                        cursor.execute('SELECT referrals, energy FROM wallets WHERE address = ?', (referrer_address,))
                        ref_data = cursor.fetchone()
                        if ref_data:
                            ref_referrals, ref_energy = ref_data
                            referrals_list = json.loads(ref_referrals or '[]')
                            referrals_list.append(str(telegram_chat_id))
                            new_energy = min(200.0, ref_energy + 25)
                            
                            cursor.execute('''
                                UPDATE wallets SET referrals = ?, energy = ? WHERE address = ?
                            ''', (json.dumps(referrals_list), new_energy, referrer_address))
                            
                            logging.info(f"🎁 Referral bonus applied: +25 energy to {referrer_address}")
                    
                    conn.commit()
                    conn.close()
                    logging.info(f"✅ Wallet created: {address}")
                    return address
                    
        except Exception as e:
            logging.error(f"❌ Create wallet error: {e}")
            return None

    def get_wallet_data(self, address):
        try:
            if self.pg_mode:
                with get_pg_conn() as conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                        cursor.execute('SELECT * FROM wallets WHERE address = %s', (address,))
                        result = cursor.fetchone()
                        if result:
                            return dict(result)
                        return None
            else:
                with self._local_lock:
                    conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    cursor = conn.cursor()
                    cursor.execute('SELECT * FROM wallets WHERE address = ?', (address,))
                    result = cursor.fetchone()
                    conn.close()
                    
                    if result:
                        columns = ['address', 'energy', 'last_mined', 'created_at', 'total_mined',
                                  'total_sent', 'total_received', 'telegram_chat_id', 'last_login',
                                  'mining_sessions', 'total_blocks_mined', 'mining_start_time',
                                  'is_mining', 'session_blocks', 'session_rewards', 'referrer', 'referrals']
                        return dict(zip(columns, result))
                    return None
        except Exception as e:
            logging.error(f"❌ Get wallet data error: {e}")
            return None

    def update_wallet(self, address, **kwargs):
        try:
            if self.pg_mode:
                with get_pg_conn() as conn:
                    with conn.cursor() as cursor:
                        set_clause = ', '.join([f"{key} = %s" for key in kwargs.keys()])
                        values = list(kwargs.values()) + [address]
                        cursor.execute(f'UPDATE wallets SET {set_clause} WHERE address = %s', values)
                        conn.commit()
                        return True
            else:
                with self._local_lock:
                    conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    cursor = conn.cursor()
                    set_clause = ', '.join([f"{key} = ?" for key in kwargs.keys()])
                    values = list(kwargs.values()) + [address]
                    cursor.execute(f'UPDATE wallets SET {set_clause} WHERE address = ?', values)
                    conn.commit()
                    conn.close()
                    return True
        except Exception as e:
            logging.error(f"❌ Update wallet error: {e}")
            return False

    def get_wallet_energy(self, address):
        try:
            if self.pg_mode:
                with get_pg_conn() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute('SELECT energy FROM wallets WHERE address = %s', (address,))
                        result = cursor.fetchone()
                        return result[0] if result else 0
            else:
                with self._local_lock:
                    conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    cursor = conn.cursor()
                    cursor.execute('SELECT energy FROM wallets WHERE address = ?', (address,))
                    result = cursor.fetchone()
                    conn.close()
                    return result[0] if result else 0
        except Exception as e:
            logging.error(f"❌ Get wallet energy error: {e}")
            return 0

    def add_energy(self, address, energy_amount):
        try:
            if self.pg_mode:
                with get_pg_conn() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute('SELECT energy FROM wallets WHERE address = %s', (address,))
                        result = cursor.fetchone()
                        if result:
                            current_energy = result[0]
                            new_energy = min(200.0, current_energy + energy_amount)
                            cursor.execute('UPDATE wallets SET energy = %s WHERE address = %s', (new_energy, address))
                            conn.commit()
                            logging.info(f"⚡ Energy added: +{energy_amount} to {address}")
                            return True
                        return False
            else:
                with self._local_lock:
                    conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    cursor = conn.cursor()
                    cursor.execute('SELECT energy FROM wallets WHERE address = ?', (address,))
                    result = cursor.fetchone()
                    if result:
                        current_energy = result[0]
                        new_energy = min(200.0, current_energy + energy_amount)
                        cursor.execute('UPDATE wallets SET energy = ? WHERE address = ?', (new_energy, address))
                        conn.commit()
                        conn.close()
                        logging.info(f"⚡ Energy added: +{energy_amount} to {address}")
                        return True
                    conn.close()
                    return False
        except Exception as e:
            logging.error(f"❌ Add energy error: {e}")
            return False

    def get_referrals_count(self, address):
        try:
            if self.pg_mode:
                with get_pg_conn() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute('SELECT referrals FROM wallets WHERE address = %s', (address,))
                        result = cursor.fetchone()
                        if result and result[0]:
                            referrals = json.loads(result[0])
                            return len(referrals)
                        return 0
            else:
                with self._local_lock:
                    conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    cursor = conn.cursor()
                    cursor.execute('SELECT referrals FROM wallets WHERE address = ?', (address,))
                    result = cursor.fetchone()
                    conn.close()
                    if result and result[0]:
                        referrals = json.loads(result[0])
                        return len(referrals)
                    return 0
        except Exception as e:
            logging.error(f"❌ Get referrals count error: {e}")
            return 0

    def get_all_wallets(self):
        try:
            if self.pg_mode:
                with get_pg_conn() as conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                        cursor.execute('SELECT * FROM wallets ORDER BY created_at DESC')
                        results = cursor.fetchall()
                        return [dict(row) for row in results]
            else:
                with self._local_lock:
                    conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    cursor = conn.cursor()
                    cursor.execute('SELECT * FROM wallets ORDER BY created_at DESC')
                    results = cursor.fetchall()
                    conn.close()
                    
                    columns = ['address', 'energy', 'last_mined', 'created_at', 'total_mined',
                              'total_sent', 'total_received', 'telegram_chat_id', 'last_login',
                              'mining_sessions', 'total_blocks_mined', 'mining_start_time',
                              'is_mining', 'session_blocks', 'session_rewards', 'referrer', 'referrals']
                    
                    return [dict(zip(columns, row)) for row in results]
        except Exception as e:
            logging.error(f"❌ Get all wallets error: {e}")
            return []

    def add_block(self, block_data):
        try:
            if self.pg_mode:
                with get_pg_conn() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute('''
                            INSERT INTO blockchain (
                                block_index, timestamp, miner, previous_hash, hash,
                                transactions, nonce, difficulty, reward, status
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ''', (
                            block_data['index'], block_data['timestamp'], block_data['miner'],
                            block_data['previous_hash'], block_data['hash'],
                            json.dumps(block_data['transactions']), block_data['nonce'],
                            block_data['difficulty'], block_data['reward'], block_data['status']
                        ))
                        conn.commit()
                        return True
            else:
                with self._local_lock:
                    conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO blockchain (
                            block_index, timestamp, miner, previous_hash, hash,
                            transactions, nonce, difficulty, reward, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        block_data['index'], block_data['timestamp'], block_data['miner'],
                        block_data['previous_hash'], block_data['hash'],
                        json.dumps(block_data['transactions']), block_data['nonce'],
                        block_data['difficulty'], block_data['reward'], block_data['status']
                    ))
                    conn.commit()
                    conn.close()
                    return True
        except Exception as e:
            logging.error(f"❌ Add block error: {e}")
            return False

    def get_blockchain(self):
        try:
            if self.pg_mode:
                with get_pg_conn() as conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                        cursor.execute('SELECT * FROM blockchain ORDER BY block_index')
                        results = cursor.fetchall()
                        blocks = []
                        for row in results:
                            block = {
                                'index': row['block_index'],
                                'timestamp': row['timestamp'],
                                'miner': row['miner'],
                                'previous_hash': row['previous_hash'],
                                'hash': row['hash'],
                                'transactions': json.loads(row['transactions']),
                                'nonce': row['nonce'],
                                'difficulty': row['difficulty'],
                                'reward': row['reward'],
                                'status': row['status']
                            }
                            blocks.append(block)
                        return blocks
            else:
                with self._local_lock:
                    conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    cursor = conn.cursor()
                    cursor.execute('SELECT * FROM blockchain ORDER BY block_index')
                    results = cursor.fetchall()
                    conn.close()
                    
                    blocks = []
                    for row in results:
                        block = {
                            'index': row[1],
                            'timestamp': row[2],
                            'miner': row[3],
                            'previous_hash': row[4],
                            'hash': row[5],
                            'transactions': json.loads(row[6]),
                            'nonce': row[7],
                            'difficulty': row[8],
                            'reward': row[9],
                            'status': row[10]
                        }
                        blocks.append(block)
                    
                    return blocks
        except Exception as e:
            logging.error(f"❌ Get blockchain error: {e}")
            return []

    def add_pending_transaction(self, tx_data):
        try:
            if self.pg_mode:
                with get_pg_conn() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute('''
                            INSERT INTO pending_transactions (
                                from_wallet, to_wallet, amount, timestamp, type
                            ) VALUES (%s, %s, %s, %s, %s)
                        ''', (tx_data['from'], tx_data['to'], tx_data['amount'], 
                              tx_data['timestamp'], tx_data['type']))
                        conn.commit()
                        return True
            else:
                with self._local_lock:
                    conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO pending_transactions (
                            from_wallet, to_wallet, amount, timestamp, type
                        ) VALUES (?, ?, ?, ?, ?)
                    ''', (tx_data['from'], tx_data['to'], tx_data['amount'], 
                          tx_data['timestamp'], tx_data['type']))
                    conn.commit()
                    conn.close()
                    return True
        except Exception as e:
            logging.error(f"❌ Add pending transaction error: {e}")
            return False

    def get_pending_transactions(self):
        try:
            if self.pg_mode:
                with get_pg_conn() as conn:
                    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
                        cursor.execute('SELECT * FROM pending_transactions ORDER BY timestamp')
                        results = cursor.fetchall()
                        transactions = []
                        for row in results:
                            tx = {
                                'from': row['from_wallet'],
                                'to': row['to_wallet'],
                                'amount': row['amount'],
                                'timestamp': row['timestamp'],
                                'type': row['type']
                            }
                            transactions.append(tx)
                        return transactions
            else:
                with self._local_lock:
                    conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    cursor = conn.cursor()
                    cursor.execute('SELECT * FROM pending_transactions ORDER BY timestamp')
                    results = cursor.fetchall()
                    conn.close()
                    
                    transactions = []
                    for row in results:
                        tx = {
                            'from': row[1],
                            'to': row[2],
                            'amount': row[3],
                            'timestamp': row[4],
                            'type': row[5]
                        }
                        transactions.append(tx)
                    
                    return transactions
        except Exception as e:
            logging.error(f"❌ Get pending transactions error: {e}")
            return []

    def remove_pending_transaction(self, tx_data):
        try:
            if self.pg_mode:
                with get_pg_conn() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute('''
                            DELETE FROM pending_transactions 
                            WHERE from_wallet = %s AND to_wallet = %s AND amount = %s AND timestamp = %s
                        ''', (tx_data['from'], tx_data['to'], tx_data['amount'], tx_data['timestamp']))
                        conn.commit()
                        return True
            else:
                with self._local_lock:
                    conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    cursor = conn.cursor()
                    cursor.execute('''
                        DELETE FROM pending_transactions 
                        WHERE from_wallet = ? AND to_wallet = ? AND amount = ? AND timestamp = ?
                    ''', (tx_data['from'], tx_data['to'], tx_data['amount'], tx_data['timestamp']))
                    conn.commit()
                    conn.close()
                    return True
        except Exception as e:
            logging.error(f"❌ Remove pending transaction error: {e}")
            return False

    def get_telegram_id_by_wallet(self, wallet_address):
        """Get telegram chat ID by wallet address"""
        try:
            if self.pg_mode:
                with get_pg_conn() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute('SELECT telegram_chat_id FROM wallets WHERE address = %s', (wallet_address,))
                        result = cursor.fetchone()
                        return result[0] if result and result[0] else None
            else:
                with self._local_lock:
                    conn = sqlite3.connect(self.db_path, check_same_thread=False)
                    cursor = conn.cursor()
                    cursor.execute('SELECT telegram_chat_id FROM wallets WHERE address = ?', (wallet_address,))
                    result = cursor.fetchone()
                    conn.close()
                    return result[0] if result and result[0] else None
        except Exception as e:
            logging.error(f"❌ Get telegram ID error: {e}")
            return None
