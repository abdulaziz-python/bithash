from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_socketio import SocketIO, emit
import hashlib
import time
import threading
import secrets
import logging
import random
import json
from datetime import datetime, timedelta
import requests
from database import Database

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)

# Production optimizations
app.config['WTF_CSRF_ENABLED'] = False  # Disable CSRF for API endpoints
app.config['JSON_SORT_KEYS'] = False

socketio = SocketIO(app, cors_allowed_origins="*", 
                   async_mode='threading',
                   ping_timeout=60,
                   ping_interval=25)

ADMIN_PASSWORD = "Ablaze_1326"

# Thread-safe database instance
db = Database()

# Thread-safe mining state
mining_active = {}
mining_lock = threading.Lock()

MINING_DIFFICULTY = 4
BASE_MINING_REWARD = 0.001
REWARD_VARIANCE = 0.0005
ENERGY_DRAIN_RATE = 0.3
MINING_COOLDOWN = 15
MAX_TRANSACTIONS_PER_BLOCK = 5
MAX_COIN_SUPPLY = 21000000
REWARD_CHANCE = 0.36

def compute_hash(block):
    block_data = {k: block[k] for k in sorted(block.keys()) if k != "hash"}
    block_string = json.dumps(block_data, sort_keys=True)
    return hashlib.sha256(block_string.encode()).hexdigest()

def get_balance(wallet, blockchain_data):
    balance = 0.0
    for block in blockchain_data:
        for tx in block.get('transactions', []):
            if tx.get('to') == wallet:
                balance += tx.get('amount', 0)
            if tx.get('from') == wallet:
                balance -= tx.get('amount', 0)
    return balance

def generate_mining_reward():
    if random.random() < REWARD_CHANCE:
        return round(BASE_MINING_REWARD + random.uniform(-REWARD_VARIANCE, REWARD_VARIANCE), 6)
    return 0.0

def mine_block(index, miner, previous_hash, transactions, difficulty=MINING_DIFFICULTY):
    reward = generate_mining_reward()
    
    block = {
        "index": index,
        "timestamp": str(time.time()),
        "miner": miner,
        "previous_hash": previous_hash,
        "transactions": transactions,
        "nonce": 0,
        "difficulty": difficulty,
        "reward": reward,
        "status": "success" if reward > 0 else "no_reward"
    }
    
    target = "0" * difficulty
    
    while True:
        block["hash"] = compute_hash(block)
        
        if block["hash"].startswith(target):
            return block
        
        block["nonce"] += 1

def can_mine(wallet):
    if not wallet:
        return False, "Invalid wallet"
    
    wallet_data = db.get_wallet_data(wallet)
    if not wallet_data:
        return False, "Wallet not found"
    
    with mining_lock:
        if mining_active.get(wallet, False):
            return False, "Already mining"
    
    if wallet_data["energy"] <= 0:
        return False, "No energy"
    
    cooldown_remaining = MINING_COOLDOWN - (time.time() - wallet_data["last_mined"])
    if cooldown_remaining > 0:
        return False, f"Cooldown: {int(cooldown_remaining)}s"
    
    return True, "Ready"

def decrease_energy(wallet):
    while True:
        with mining_lock:
            if not mining_active.get(wallet, False):
                break
                
        wallet_data = db.get_wallet_data(wallet)
        if not wallet_data or wallet_data["energy"] <= 0:
            break
            
        new_energy = max(0, wallet_data["energy"] - ENERGY_DRAIN_RATE)
        db.update_wallet(wallet, energy=new_energy)
        
        try:
            socketio.emit('energy_update', {
                'wallet': wallet, 
                'energy': new_energy
            })
        except Exception as e:
            logging.error(f"❌ Socket emission error: {e}")
        
        time.sleep(1)
        
        if new_energy <= 0:
            break
    
    stop_mining_session(wallet)

def stop_mining_session(wallet):
    with mining_lock:
        if wallet in mining_active and mining_active[wallet]:
            mining_active[wallet] = False
            
            wallet_data = db.get_wallet_data(wallet)
            if wallet_data:
                mining_duration = int(time.time()) - wallet_data["mining_start_time"]
                session_blocks = wallet_data["session_blocks"]
                session_rewards = wallet_data["session_rewards"]
                
                db.update_wallet(wallet, 
                                is_mining=0,
                                session_blocks=0,
                                session_rewards=0.0,
                                last_mined=int(time.time()))
                
                try:
                    from bot import notify_mining_completed
                    threading.Thread(target=notify_mining_completed, 
                                   args=(wallet, session_rewards, session_blocks, mining_duration), 
                                   daemon=True).start()
                except ImportError:
                    pass
                
                try:
                    socketio.emit('mining_stopped', {
                        'wallet': wallet,
                        'total_reward': session_rewards,
                        'blocks_mined': session_blocks,
                        'duration': mining_duration
                    })
                except Exception as e:
                    logging.error(f"❌ Socket emission error: {e}")

def mining_process(wallet):
    try:
        current_time = int(time.time())
        db.update_wallet(wallet, 
                        mining_start_time=current_time,
                        is_mining=1,
                        session_blocks=0,
                        session_rewards=0.0)
        
        while True:
            with mining_lock:
                if not mining_active.get(wallet, False):
                    break
                    
            wallet_data = db.get_wallet_data(wallet)
            if not wallet_data or wallet_data["energy"] <= 0:
                break
                
            blockchain = db.get_blockchain()
            if not blockchain:
                genesis = {
                    "index": 0,
                    "timestamp": str(time.time()),
                    "miner": "genesis",
                    "previous_hash": "0",
                    "hash": "0",
                    "transactions": [],
                    "nonce": 0,
                    "difficulty": MINING_DIFFICULTY,
                    "reward": 0.0,
                    "status": "genesis"
                }
                genesis["hash"] = compute_hash(genesis)
                db.add_block(genesis)
                blockchain = [genesis]
            
            last_block = blockchain[-1]
            
            pending_transactions = db.get_pending_transactions()
            valid_transactions = []
            for tx in pending_transactions:
                if get_balance(tx['from'], blockchain) >= tx['amount']:
                    valid_transactions.append(tx)
                if len(valid_transactions) >= MAX_TRANSACTIONS_PER_BLOCK:
                    break
            
            reward = generate_mining_reward()
            
            if reward > 0:
                reward_tx = {
                    "from": "network",
                    "to": wallet,
                    "amount": reward,
                    "timestamp": str(time.time()),
                    "type": "mining_reward"
                }
                transactions = [reward_tx] + valid_transactions
            else:
                transactions = valid_transactions
            
            new_block = mine_block(
                last_block['index'] + 1,
                wallet,
                last_block['hash'],
                transactions
            )
            
            db.add_block(new_block)
            
            for tx in valid_transactions:
                db.remove_pending_transaction(tx)
            
            wallet_data = db.get_wallet_data(wallet)
            new_total_mined = wallet_data["total_mined"] + reward
            new_mining_sessions = wallet_data["mining_sessions"] + 1
            new_total_blocks = wallet_data["total_blocks_mined"] + 1
            new_session_blocks = wallet_data["session_blocks"] + 1
            new_session_rewards = wallet_data["session_rewards"] + reward
            
            db.update_wallet(wallet,
                           total_mined=new_total_mined,
                           mining_sessions=new_mining_sessions,
                           total_blocks_mined=new_total_blocks,
                           session_blocks=new_session_blocks,
                           session_rewards=new_session_rewards)
            
            blockchain = db.get_blockchain()
            current_balance = get_balance(wallet, blockchain)
            
            try:
                socketio.emit('mining_log', {
                    'wallet': wallet,
                    'block_number': new_block['index'],
                    'block_hash': new_block['hash'][:16] + '...',
                    'reward': reward,
                    'energy': wallet_data["energy"],
                    'timestamp': time.time(),
                    'status': new_block['status']
                })
                
                socketio.emit('balance_update', {
                    'wallet': wallet,
                    'balance': current_balance,
                    'session_rewards': new_session_rewards
                })
                
                socketio.emit('new_block', {
                    'block': new_block,
                    'miner': wallet,
                    'reward': reward
                })
            except Exception as e:
                logging.error(f"❌ Socket emission error: {e}")
            
            time.sleep(2)
            
    except Exception as e:
        logging.error(f"❌ Mining error: {e}")
        stop_mining_session(wallet)

def get_total_supply():
    try:
        blockchain = db.get_blockchain()
        total = 0.0
        for block in blockchain:
            for tx in block.get('transactions', []):
                if tx.get('from') == 'network':
                    total += tx.get('amount', 0)
        return min(total, MAX_COIN_SUPPLY)
    except Exception as e:
        logging.error(f"❌ Get total supply error: {e}")
        return 0.0

# ... keep existing code (all route handlers remain the same)

@app.route('/')
def index():
    wallet = request.args.get('wallet')
    telegram_id = request.args.get('telegram_id')
    
    if wallet:
        wallet_data = db.get_wallet_data(wallet)
        if wallet_data:
            session['wallet'] = wallet
            session.permanent = True
            db.update_wallet(wallet, last_login=int(time.time()))
            return redirect(url_for('user_page'))
    
    if telegram_id:
        wallet = db.get_user_wallet_by_telegram(telegram_id)
        if wallet:
            session['wallet'] = wallet
            session.permanent = True
            db.update_wallet(wallet, last_login=int(time.time()))
            return redirect(url_for('user_page'))
    
    if 'wallet' in session:
        wallet_data = db.get_wallet_data(session['wallet'])
        if wallet_data:
            return redirect(url_for('user_page'))
    
    blockchain = db.get_blockchain()
    wallets = db.get_all_wallets()
    
    return render_template('index.html', 
                         blockchain_height=len(blockchain),
                         wallets=wallets)

@app.route('/create_wallet', methods=['POST'])
def handle_create_wallet():
    try:
        wallet_address = db.create_wallet()
        if wallet_address:
            session['wallet'] = wallet_address
            session.permanent = True
            flash('Wallet created successfully!', 'success')
            return redirect(url_for('user_page'))
        else:
            flash('Error creating wallet', 'error')
            return redirect(url_for('index'))
    except Exception as e:
        logging.error(f"❌ Create wallet error: {e}")
        flash('Error creating wallet', 'error')
        return redirect(url_for('index'))

@app.route('/login_wallet', methods=['POST'])
def login_wallet():
    try:
        wallet_address = request.form.get('wallet_address', '').strip()
        telegram_id = request.form.get('telegram_id', '').strip()
        
        if wallet_address:
            wallet_data = db.get_wallet_data(wallet_address)
            if wallet_data:
                session['wallet'] = wallet_address
                session.permanent = True
                db.update_wallet(wallet_address, last_login=int(time.time()))
                flash('Login successful!', 'success')
                return redirect(url_for('user_page'))
        
        if telegram_id:
            wallet = db.get_user_wallet_by_telegram(telegram_id)
            if wallet:
                session['wallet'] = wallet
                session.permanent = True
                db.update_wallet(wallet, last_login=int(time.time()))
                flash('Login successful!', 'success')
                return redirect(url_for('user_page'))
        
        flash('Wallet or Telegram ID not found', 'error')
        return redirect(url_for('index'))
    except Exception as e:
        logging.error(f"❌ Login error: {e}")
        flash('Login failed', 'error')
        return redirect(url_for('index'))

@app.route('/user')
def user_page():
    wallet = session.get('wallet')
    if not wallet:
        return redirect(url_for('index'))
    
    try:
        wallet_data = db.get_wallet_data(wallet)
        if not wallet_data:
            return redirect(url_for('index'))
        
        blockchain = db.get_blockchain()
        if not blockchain:
            genesis = {
                "index": 0,
                "timestamp": str(time.time()),
                "miner": "genesis",
                "previous_hash": "0",
                "hash": "0",
                "transactions": [],
                "nonce": 0,
                "difficulty": MINING_DIFFICULTY,
                "reward": 0.0,
                "status": "genesis"
            }
            genesis["hash"] = compute_hash(genesis)
            db.add_block(genesis)
            blockchain = [genesis]
        
        balance = get_balance(wallet, blockchain)
        can_mine_status, mine_status = can_mine(wallet)
        
        recent_blocks = []
        for block in reversed(blockchain[-50:]):
            if block.get('miner') == wallet:
                recent_blocks.append(block)
        
        pending_transactions = db.get_pending_transactions()
        
        return render_template('user.html',
            wallet=wallet,
            balance=balance,
            energy=wallet_data["energy"],
            is_mining=mining_active.get(wallet, False),
            can_mine=can_mine_status,
            mine_status=mine_status,
            wallet_stats=wallet_data,
            blockchain_height=len(blockchain),
            pending_tx_count=len(pending_transactions),
            total_supply=get_total_supply(),
            max_supply=MAX_COIN_SUPPLY,
            recent_blocks=recent_blocks,
            reward_chance=int(REWARD_CHANCE * 100)
        )
    except Exception as e:
        logging.error(f"❌ User page error: {e}")
        flash('Error loading user page', 'error')
        return redirect(url_for('index'))

@app.route('/api/start_mining', methods=['POST'])
def api_start_mining():
    wallet = session.get('wallet')
    can_mine_status, message = can_mine(wallet)
    
    if not can_mine_status:
        return jsonify({'success': False, 'message': message}), 400
    
    with mining_lock:
        mining_active[wallet] = True
    
    threading.Thread(target=mining_process, args=(wallet,), daemon=True).start()
    threading.Thread(target=decrease_energy, args=(wallet,), daemon=True).start()
    
    return jsonify({'success': True, 'message': 'Mining started!'})

@app.route('/api/stop_mining', methods=['POST'])
def api_stop_mining():
    wallet = session.get('wallet')
    with mining_lock:
        if wallet in mining_active:
            stop_mining_session(wallet)
            return jsonify({'success': True, 'message': 'Mining stopped'})
    return jsonify({'success': False, 'message': 'Not mining'})

@app.route('/api/wallet_status')
def api_wallet_status():
    wallet = session.get('wallet')
    if not wallet:
        return jsonify({'error': 'No wallet'}), 401
    
    try:
        wallet_data = db.get_wallet_data(wallet)
        if not wallet_data:
            return jsonify({'error': 'Wallet not found'}), 404
        
        blockchain = db.get_blockchain()
        balance = get_balance(wallet, blockchain)
        can_mine_status, mine_status = can_mine(wallet)
        
        return jsonify({
            'balance': balance,
            'energy': wallet_data["energy"],
            'is_mining': mining_active.get(wallet, False),
            'can_mine': can_mine_status,
            'mine_status': mine_status,
            'session_rewards': wallet_data["session_rewards"]
        })
    except Exception as e:
        logging.error(f"❌ Wallet status error: {e}")
        return jsonify({'error': 'Internal error'}), 500

@app.route('/mine', methods=['POST'])
def start_mining():
    wallet = session.get('wallet')
    can_mine_status, message = can_mine(wallet)
    
    if not can_mine_status:
        flash(f'Cannot mine: {message}', 'error')
        return redirect(url_for('user_page'))
    
    with mining_lock:
        mining_active[wallet] = True
    
    threading.Thread(target=mining_process, args=(wallet,), daemon=True).start()
    threading.Thread(target=decrease_energy, args=(wallet,), daemon=True).start()
    
    flash('Mining started!', 'success')
    return redirect(url_for('user_page'))

@app.route('/stop_mine', methods=['POST'])
def stop_mining():
    wallet = session.get('wallet')
    with mining_lock:
        if wallet in mining_active:
            stop_mining_session(wallet)
            flash('Mining stopped', 'info')
    return redirect(url_for('user_page'))

@app.route('/tasks')
def tasks_page():
    wallet = session.get('wallet')
    if not wallet:
        return redirect(url_for('index'))
    
    try:
        wallet_data = db.get_wallet_data(wallet)
        if not wallet_data:
            return redirect(url_for('index'))
        
        blockchain = db.get_blockchain()
        balance = get_balance(wallet, blockchain)
        
        tasks = [
            {'name': 'Join Community', 'url': 'https://t.me/bithash_airdrop', 'icon': '👥'},
            {'name': 'Join Channel', 'url': 'https://t.me/pythonNews_Uzbekistan', 'icon': '📢'}
        ]
        
        return render_template('tasks.html', wallet=wallet, tasks=tasks, balance=balance)
    except Exception as e:
        logging.error(f"❌ Tasks page error: {e}")
        flash('Error loading tasks', 'error')
        return redirect(url_for('user_page'))

@app.route('/admin')
def admin_login():
    return render_template('admin_login.html')

@app.route('/admin_auth', methods=['POST'])
def admin_auth():
    password = request.form.get('password')
    if password == ADMIN_PASSWORD:
        session['admin'] = True
        return redirect(url_for('admin_panel'))
    else:
        flash('Invalid password', 'error')
        return redirect(url_for('admin_login'))

@app.route('/admin_panel')
def admin_panel():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    
    try:
        blockchain = db.get_blockchain()
        wallets_data = db.get_all_wallets()
        
        all_holders = []
        for wallet_data in wallets_data:
            balance = get_balance(wallet_data['address'], blockchain)
            if balance > 0:
                all_holders.append({
                    'wallet': wallet_data['address'],
                    'balance': balance,
                    'mined': wallet_data.get('total_mined', 0)
                })
        
        all_holders.sort(key=lambda x: x['balance'], reverse=True)
        
        with mining_lock:
            active_miners_count = sum(1 for active in mining_active.values() if active)
        
        stats = {
            'total_wallets': len(wallets_data),
            'active_miners': active_miners_count,
            'total_blocks': len(blockchain),
            'total_supply': get_total_supply(),
            'max_supply': MAX_COIN_SUPPLY,
            'pending_transactions': len(db.get_pending_transactions()),
            'total_holders': len(all_holders)
        }
        
        top_miners = sorted(wallets_data, key=lambda x: x['total_mined'], reverse=True)[:10]
        
        return render_template('admin.html', 
                             wallets=wallets_data, 
                             blockchain=blockchain, 
                             stats=stats, 
                             top_miners=top_miners,
                             all_holders=all_holders)
    except Exception as e:
        logging.error(f"❌ Admin panel error: {e}")
        flash('Error loading admin panel', 'error')
        return redirect(url_for('admin_login'))

@app.route('/transaction', methods=['POST'])
def create_transaction():
    wallet = session.get('wallet')
    if not wallet:
        return redirect(url_for('index'))
    
    try:
        to_wallet = request.form.get('to_wallet', '').strip()
        amount = float(request.form.get('amount', 0))
        
        if amount <= 0:
            flash('Invalid amount', 'error')
            return redirect(url_for('tasks_page'))
        
        to_wallet_data = db.get_wallet_data(to_wallet)
        if not to_wallet_data:
            flash('Wallet not found', 'error')
            return redirect(url_for('tasks_page'))
        
        blockchain = db.get_blockchain()
        if get_balance(wallet, blockchain) < amount:
            flash('Insufficient balance', 'error')
            return redirect(url_for('tasks_page'))
        
        transaction = {
            "from": wallet,
            "to": to_wallet,
            "amount": amount,
            "timestamp": str(time.time()),
            "type": "transfer"
        }
        
        db.add_pending_transaction(transaction)
        flash(f'Sent {amount} BHC', 'success')
        
    except ValueError:
        flash('Invalid amount', 'error')
    except Exception as e:
        logging.error(f"❌ Transaction error: {e}")
        flash('Transaction failed', 'error')
    
    return redirect(url_for('tasks_page'))

@app.route('/blockchain')
def view_blockchain():
    try:
        blockchain = db.get_blockchain()
        pending_transactions = db.get_pending_transactions()
        
        return render_template('blockchain.html', 
                             blockchain=blockchain,
                             total_blocks=len(blockchain),
                             pending_transactions=pending_transactions)
    except Exception as e:
        logging.error(f"❌ Blockchain view error: {e}")
        flash('Error loading blockchain', 'error')
        return redirect(url_for('index'))

@socketio.on('connect')
def handle_connect():
    try:
        blockchain = db.get_blockchain()
        emit('blockchain_update', {'blockchain': blockchain})
    except Exception as e:
        logging.error(f"❌ Socket connect error: {e}")

@app.errorhandler(500)
def internal_error(error):
    logging.error(f"❌ Internal server error: {error}")
    return "Internal Server Error", 500

@app.errorhandler(404)
def not_found_error(error):
    return "Page Not Found", 404

if __name__ == '__main__':
    try:
        blockchain = db.get_blockchain()
        
        if not blockchain:
            genesis = {
                "index": 0,
                "timestamp": str(time.time()),
                "miner": "genesis",
                "previous_hash": "0",
                "hash": "0",
                "transactions": [],
                "nonce": 0,
                "difficulty": MINING_DIFFICULTY,
                "reward": 0.0,
                "status": "genesis"
            }
            genesis["hash"] = compute_hash(genesis)
            db.add_block(genesis)
        
        logging.info(f"✅ Starting with {len(blockchain)} blocks")
        
        socketio.run(app, host='0.0.0.0', port=5000, debug=False)
        
    except Exception as e:
        logging.error(f"❌ Startup failed: {e}")
        socketio.run(app, host='0.0.0.0', port=5000, debug=False)
