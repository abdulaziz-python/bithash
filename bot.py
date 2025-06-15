import telebot
from telebot import types
import requests
import logging
import threading
import time
import sys
import os
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from database import Database
except ImportError as e:
    logging.error(f"Failed to import database: {e}")
    print("Error: Make sure database.py is in the same directory")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

TELEGRAM_BOT_TOKEN = "8196982433:AAELjUffbtWlvf8yirWfuPICQ_6r3pKrq2M"
WEBHOOK_URL = "https://f4e8-198-163-194-127.ngrok-free.app"
ADMIN_USERNAME = "ablaze_coder"
ADMIN_ID = 6236467772

# Configure requests session with retry strategy
def setup_requests_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

try:
    bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
    db = Database()
    requests_session = setup_requests_session()
    logging.info("Bot and database initialized successfully")
except Exception as e:
    logging.error(f"Failed to initialize bot or database: {e}")
    sys.exit(1)

admin_state = {}

def safe_send_message(chat_id, text, **kwargs):
    """Safely send message with retry logic"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            return bot.send_message(chat_id, text, **kwargs)
        except Exception as e:
            logging.error(f"Send message attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                logging.error(f"All send attempts failed for chat {chat_id}")
                return None
            time.sleep(2 ** attempt)  # Exponential backoff

def safe_send_video(chat_id, video, **kwargs):
    """Safely send video with fallback to message"""
    max_retries = 2
    for attempt in range(max_retries):
        try:
            return bot.send_video(chat_id, video, **kwargs)
        except Exception as e:
            logging.error(f"Video send attempt {attempt + 1} failed: {e}")
            if attempt == max_retries - 1:
                # Fallback to text message
                caption = kwargs.get('caption', '')
                reply_markup = kwargs.get('reply_markup', None)
                return safe_send_message(chat_id, caption, reply_markup=reply_markup, parse_mode=kwargs.get('parse_mode'))
            time.sleep(1)

def is_admin(message):
    uid = getattr(message.from_user, 'id', None)
    uname = getattr(message.from_user, 'username', '')
    return uname == ADMIN_USERNAME or uid == ADMIN_ID

def is_admin_callback(call):
    uid = getattr(call.from_user, 'id', None)
    uname = getattr(call.from_user, 'username', '')
    return uname == ADMIN_USERNAME or uid == ADMIN_ID

@bot.message_handler(commands=['start'])
def start_command(message):
    try:
        chat_id = str(message.chat.id)
        referrer_chat_id = None
        
        if len(message.text.split()) > 1:
            ref_code = message.text.split()[1]
            if ref_code.isdigit():
                referrer_chat_id = ref_code
        
        user_wallet = db.get_user_wallet_by_telegram(chat_id)
        
        if not user_wallet:
            user_wallet = db.create_wallet(chat_id, referrer_chat_id)
            if not user_wallet:
                safe_send_message(chat_id, "❌ Error creating wallet. Please try again.")
                return
            
            if referrer_chat_id:
                safe_send_message(chat_id, "🎉 *Welcome!* You've been referred and both you and your referrer got *+25 energy!* ⚡", parse_mode='Markdown')
        
        referral_link = f"https://t.me/BitHash_miningbot?start={chat_id}"
        
        wallet_data = db.get_wallet_data(user_wallet)
        energy = wallet_data["energy"] if wallet_data else 100.0
        referrals_count = db.get_referrals_count(user_wallet)
        
        welcome_text = f"""🚀 *Welcome to BitHash Mining!*

💎 Your digital mining journey starts here!
⚡ Start mining blocks and earn BHC coins!

🏦 *Your Wallet:* `{user_wallet}`
⚡ *Energy:* {energy:.1f}/200
👥 *Referrals:* {referrals_count}

🔗 *Share & Earn:*
`{referral_link}`

💰 Invite friends to earn *+25 energy* each!"""
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        web_app = types.WebAppInfo(f"{WEBHOOK_URL}?telegram_id={chat_id}")
        app_button = types.InlineKeyboardButton(text='⛏️ Open Mining Dashboard', web_app=web_app)
        markup.add(app_button)
        
        wallet_button = types.InlineKeyboardButton(text='💳 Wallet', callback_data='wallet_info')
        buy_button = types.InlineKeyboardButton(text='⚡ Buy Energy', callback_data='buy_energy')
        markup.add(wallet_button, buy_button)
        
        help_button = types.InlineKeyboardButton(text='❓ Help', callback_data='help_info')
        stats_button = types.InlineKeyboardButton(text='📊 Stats', callback_data='mining_stats')
        markup.add(help_button, stats_button)
        
        # Try to send video, fallback to text if fails
        try:
            if os.path.exists('start.mp4'):
                with open('start.mp4', 'rb') as video:
                    safe_send_video(
                        chat_id, 
                        video, 
                        caption=welcome_text,
                        reply_markup=markup,
                        parse_mode='Markdown'
                    )
            else:
                safe_send_message(chat_id, welcome_text, reply_markup=markup, parse_mode='Markdown')
        except Exception as e:
            logging.error(f"Start command video/message error: {e}")
            safe_send_message(chat_id, welcome_text, reply_markup=markup, parse_mode='Markdown')
        
    except Exception as e:
        logging.error(f"Error in start_command: {e}")
        safe_send_message(message.chat.id, "❌ An error occurred. Please try again.")

@bot.message_handler(commands=['admin'])
def admin_command(message):
    if not is_admin(message):
        safe_send_message(message.chat.id, "❌ Access denied.")
        return
    
    try:
        blockchain = db.get_blockchain()
        wallets_data = db.get_all_wallets()
        total_wallets = len(wallets_data)
        total_blocks = len(blockchain)
        total_supply = sum(
            tx.get('amount', 0) for block in blockchain 
            for tx in block.get('transactions', []) 
            if tx.get('from') == 'network'
        )
        active_miners = sum(1 for wallet in wallets_data if wallet.get('is_mining', 0))
        total_energy = sum(wallet.get('energy', 0) for wallet in wallets_data)
        avg_energy = total_energy / total_wallets if total_wallets > 0 else 0
        
        halving_status = "Active" if hasattr(db, '_halved') and db._halved else "Inactive"
        
        stats_text = f"""🔧 *Admin Panel Statistics*

👥 *Total Users:* {total_wallets}
⛏️ *Active Miners:* {active_miners}
🔗 *Total Blocks:* {total_blocks}
💰 *Total Supply:* {total_supply:.6f} BHC
⚡ *Average Energy:* {avg_energy:.1f}
🪙 *Halving Status:* {halving_status}

📊 *Database Status:* Connected
🔄 *Bot Status:* Running"""
        
        markup = types.InlineKeyboardMarkup(row_width=2)
        broadcast_btn = types.InlineKeyboardButton(text='📢 Broadcast', callback_data='admin_broadcast')
        users_btn = types.InlineKeyboardButton(text='👥 Users', callback_data='admin_users')
        halving_btn = types.InlineKeyboardButton(text='🪙 Halving', callback_data='admin_halving')
        mining_btn = types.InlineKeyboardButton(text='⛏️ Mining', callback_data='admin_mining')
        blockchain_btn = types.InlineKeyboardButton(text='🔗 Blockchain', callback_data='admin_blockchain')
        markup.add(broadcast_btn, users_btn)
        markup.add(halving_btn)
        markup.add(mining_btn, blockchain_btn)
        
        safe_send_message(message.chat.id, stats_text, reply_markup=markup, parse_mode='Markdown')
    except Exception as e:
        logging.error(f"Error in admin_command: {e}")
        safe_send_message(message.chat.id, "❌ Admin panel error.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
def admin_callbacks(call):
    if not is_admin_callback(call):
        bot.answer_callback_query(call.id, "❌ Access denied!")
        return
    
    try:
        if call.data == 'admin_broadcast':
            bot.send_message(call.message.chat.id, "📢 *Broadcast Message*\n\nSend me an image (optional) or type 'skip' to continue:", parse_mode='Markdown')
            admin_state[call.message.chat.id] = {'step': 'broadcast_image'}
        
        elif call.data == 'admin_users':
            wallets_data = db.get_all_wallets()
            total_users = len(wallets_data)
            telegram_users = sum(1 for w in wallets_data if w.get('telegram_chat_id'))
            active_users = sum(1 for w in wallets_data if w.get('last_login', 0) > (time.time() - 86400))
            users_text = f"""👥 *User Statistics*

📊 *Total Users:* {total_users}
📱 *Telegram Users:* {telegram_users}
🟢 *Active (24h):* {active_users}
💤 *Inactive:* {total_users - active_users}

📈 *Growth Rate:* +{telegram_users/max(1, total_users)*100:.1f}% on Telegram"""
            markup = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton(text='🔙 Back', callback_data='admin_back')
            markup.add(back_btn)
            bot.edit_message_text(users_text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        
        elif call.data == 'admin_mining':
            wallets_data = db.get_all_wallets()
            active_miners = sum(1 for w in wallets_data if w.get('is_mining', 0))
            total_mined = sum(w.get('total_mined', 0) for w in wallets_data)
            total_sessions = sum(w.get('mining_sessions', 0) for w in wallets_data)
            avg_session_reward = total_mined / max(1, total_sessions)
            mining_text = f"""⛏️ *Mining Statistics*

🔥 *Active Miners:* {active_miners}
💰 *Total Mined:* {total_mined:.6f} BHC
🎯 *Mining Sessions:* {total_sessions}
📊 *Avg Session Reward:* {avg_session_reward:.6f} BHC

⚡ *Mining Efficiency:* {(total_mined/max(1, total_sessions)*100):.1f}%"""
            markup = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton(text='🔙 Back', callback_data='admin_back')
            markup.add(back_btn)
            bot.edit_message_text(mining_text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        
        elif call.data == 'admin_blockchain':
            blockchain = db.get_blockchain()
            total_blocks = len(blockchain)
            recent_blocks = blockchain[-5:] if blockchain else []
            blockchain_text = f"""🔗 *Blockchain Statistics*

📦 *Total Blocks:* {total_blocks}
🔄 *Network Status:* Active
⚡ *Block Time:* ~2 seconds

📋 *Recent Blocks:*"""
            for block in recent_blocks:
                blockchain_text += f"\n#{block.get('index', 0)} - {block.get('miner', 'Unknown')[:10]}..."
            markup = types.InlineKeyboardMarkup()
            back_btn = types.InlineKeyboardButton(text='🔙 Back', callback_data='admin_back')
            markup.add(back_btn)
            bot.edit_message_text(blockchain_text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
        
        elif call.data == 'admin_halving':
            if not hasattr(db, '_halved'):
                db._halved = False
            
            if not db._halved:
                db._halved = True
                try:
                    db.conn.execute("UPDATE wallets SET halving_applied = 1")
                    db.conn.commit()
                except:
                    pass
                bot.answer_callback_query(call.id, "🪙 Halving activated! Mining rewards and time reduced by 50%")
                admin_command(call.message)
            else:
                db._halved = False
                try:
                    db.conn.execute("UPDATE wallets SET halving_applied = 0")
                    db.conn.commit()
                except:
                    pass
                bot.answer_callback_query(call.id, "🪙 Halving deactivated! Mining rewards and time restored")
                admin_command(call.message)
        
        elif call.data == 'admin_back':
            try:
                admin_command(call.message)
            except Exception as e:
                logging.error(f"Error in admin_back: {e}")
            
    except Exception as e:
        logging.error(f"Error in admin_callbacks: {e}")
        bot.answer_callback_query(call.id, "❌ Error occurred!")

@bot.message_handler(content_types=['photo', 'text'])
def handle_admin_broadcast(message):
    uid = getattr(message.from_user, 'id', None)
    uname = getattr(message.from_user, 'username', '')
    
    if not (uname == ADMIN_USERNAME or uid == ADMIN_ID):
        return
    
    chat_id = message.chat.id
    state = admin_state.get(chat_id, {})
    
    try:
        if state.get('step') == 'broadcast_image':
            if message.content_type == 'photo':
                file_id = message.photo[-1].file_id
                admin_state[chat_id] = {'step': 'broadcast_text', 'image': file_id}
                bot.send_message(chat_id, "📝 Now send the message text:")
            elif message.text and message.text.lower() == 'skip':
                admin_state[chat_id] = {'step': 'broadcast_text'}
                bot.send_message(chat_id, "📝 Send the message text:")
            else:
                bot.send_message(chat_id, "❌ Send an image or type 'skip'")
                
        elif state.get('step') == 'broadcast_text':
            admin_state[chat_id]['text'] = message.text
            bot.send_message(chat_id, "⌨️ Send inline keyboard buttons (format: 'Text1|url1,Text2|url2') or type 'skip':")
            admin_state[chat_id]['step'] = 'broadcast_keyboard'
            
        elif state.get('step') == 'broadcast_keyboard':
            if message.text.lower() == 'skip':
                admin_state[chat_id]['keyboard'] = None
            else:
                admin_state[chat_id]['keyboard'] = message.text
            
            bot.send_message(chat_id, "🔗 Send a link (optional) or type 'skip':")
            admin_state[chat_id]['step'] = 'broadcast_link'
            
        elif state.get('step') == 'broadcast_link':
            if message.text.lower() == 'skip':
                admin_state[chat_id]['link'] = None
            else:
                admin_state[chat_id]['link'] = message.text
            
            broadcast_data = admin_state[chat_id]
            confirm_text = f"""📢 *Broadcast Preview*

📝 Text: {broadcast_data.get('text', 'No text')}
🖼️ Image: {'Yes' if broadcast_data.get('image') else 'No'}
⌨️ Keyboard: {'Yes' if broadcast_data.get('keyboard') else 'No'}
🔗 Link: {'Yes' if broadcast_data.get('link') else 'No'}

Send this broadcast?"""
            
            markup = types.InlineKeyboardMarkup()
            send_btn = types.InlineKeyboardButton(text='✅ Send Broadcast', callback_data='confirm_broadcast')
            cancel_btn = types.InlineKeyboardButton(text='❌ Cancel', callback_data='cancel_broadcast')
            markup.add(send_btn, cancel_btn)
            
            bot.send_message(chat_id, confirm_text, reply_markup=markup, parse_mode='Markdown')
            
    except Exception as e:
        logging.error(f"Error in handle_admin_broadcast: {e}")
        bot.send_message(chat_id, "❌ Error processing broadcast.")

@bot.callback_query_handler(func=lambda call: call.data in ['confirm_broadcast', 'cancel_broadcast'])
def handle_broadcast_confirmation(call):
    uid = getattr(call.from_user, 'id', None)
    uname = getattr(call.from_user, 'username', '')
    
    if not (uname == ADMIN_USERNAME or uid == ADMIN_ID):
        return
    
    chat_id = call.message.chat.id
    
    try:
        if call.data == 'confirm_broadcast':
            broadcast_data = admin_state.get(chat_id, {})
            wallets_data = db.get_all_wallets()
            
            telegram_users = [w for w in wallets_data if w.get('telegram_chat_id')]
            
            bot.send_message(chat_id, f"📡 Starting broadcast to {len(telegram_users)} users...")
            
            success_count = 0
            failed_count = 0
            
            for wallet in telegram_users:
                try:
                    user_chat_id = wallet['telegram_chat_id']
                    text = broadcast_data.get('text', '')
                    
                    markup = None
                    if broadcast_data.get('keyboard'):
                        markup = types.InlineKeyboardMarkup()
                        buttons = broadcast_data['keyboard'].split(',')
                        for button in buttons:
                            if '|' in button:
                                text_part, url_part = button.split('|', 1)
                                markup.add(types.InlineKeyboardButton(text=text_part.strip(), url=url_part.strip()))
                    
                    if broadcast_data.get('link') and not markup:
                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton(text="🔗 Link", url=broadcast_data['link']))
                    
                    if broadcast_data.get('image'):
                        bot.send_photo(user_chat_id, broadcast_data['image'], caption=text, reply_markup=markup, parse_mode='Markdown')
                    else:
                        bot.send_message(user_chat_id, text, reply_markup=markup, parse_mode='Markdown')
                    
                    success_count += 1
                    time.sleep(0.1)
                    
                except Exception as e:
                    failed_count += 1
                    logging.error(f"Broadcast failed for user {user_chat_id}: {e}")
            
            result_text = f"""✅ *Broadcast Complete*

📤 Sent: {success_count}
❌ Failed: {failed_count}
📊 Success Rate: {(success_count/(success_count+failed_count)*100):.1f}%"""
            
            bot.send_message(chat_id, result_text, parse_mode='Markdown')
            
        else:
            bot.send_message(chat_id, "❌ Broadcast cancelled.")
        
        if chat_id in admin_state:
            del admin_state[chat_id]
            
    except Exception as e:
        logging.error(f"Error in handle_broadcast_confirmation: {e}")
        bot.send_message(chat_id, "❌ Broadcast error.")

@bot.callback_query_handler(func=lambda call: call.data == 'mining_stats')
def mining_stats_callback(call):
    try:
        chat_id = str(call.message.chat.id)
        user_wallet = db.get_user_wallet_by_telegram(chat_id)
        
        if user_wallet:
            wallet_data = db.get_wallet_data(user_wallet)
            energy = wallet_data["energy"] if wallet_data else 0
            total_mined = wallet_data["total_mined"] if wallet_data else 0
            
            stats_text = f"""📊 *Mining Statistics*

⛏️ *Total Mined:* {total_mined:.6f} BHC
⚡ *Current Energy:* {energy:.1f}/200
🎯 *Mining Efficiency:* {((total_mined * 100) / max(1, (200 - energy))):.1f}%
🔥 *Status:* {'Active Miner' if energy > 20 else 'Low Energy'}

💡 *Tip:* Keep energy above 20 for optimal mining!"""
            
            markup = types.InlineKeyboardMarkup()
            back_button = types.InlineKeyboardButton(text='🔙 Back', callback_data='back_to_main')
            markup.add(back_button)
            
            try:
                bot.edit_message_text(
                    stats_text,
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=markup,
                    parse_mode='Markdown'
                )
            except telebot.apihelper.ApiTelegramException as ex:
                if "no text in the message to edit" in str(ex).lower():
                    bot.send_message(call.message.chat.id, stats_text, reply_markup=markup, parse_mode='Markdown')
                else:
                    raise ex
        else:
            bot.answer_callback_query(call.id, "❌ Wallet not found!")
            
    except Exception as e:
        logging.error(f"Error in mining_stats_callback: {e}")
        bot.answer_callback_query(call.id, "❌ An error occurred!")

@bot.callback_query_handler(func=lambda call: call.data == 'wallet_info')
def wallet_info_callback(call):
    try:
        chat_id = str(call.message.chat.id)
        user_wallet = db.get_user_wallet_by_telegram(chat_id)
        
        if user_wallet:
            wallet_data = db.get_wallet_data(user_wallet)
            energy = wallet_data["energy"] if wallet_data else 0
            total_mined = wallet_data["total_mined"] if wallet_data else 0
            referrals_count = db.get_referrals_count(user_wallet)
            referral_link = f"https://t.me/BitHash_miningbot?start={chat_id}"
            
            info_text = f"""💳 *Wallet Information*

🏦 *Address:* `{user_wallet}`
⚡ *Energy:* {energy:.1f}/200
💰 *Total Mined:* {total_mined:.6f} BHC
👥 *Referrals:* {referrals_count}

🔗 *Your Referral Link:*
`{referral_link}`

🎁 Share your link to earn *+25 energy* per referral!"""
            
            markup = types.InlineKeyboardMarkup()
            back_button = types.InlineKeyboardButton(text='🔙 Back', callback_data='back_to_main')
            markup.add(back_button)
            
            try:
                bot.edit_message_text(
                    info_text,
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=markup,
                    parse_mode='Markdown'
                )
            except telebot.apihelper.ApiTelegramException as ex:
                if "no text in the message to edit" in str(ex).lower():
                    bot.send_message(call.message.chat.id, info_text, reply_markup=markup, parse_mode='Markdown')
                else:
                    raise ex
        else:
            bot.answer_callback_query(call.id, "❌ Wallet not found!")
            
    except Exception as e:
        logging.error(f"Error in wallet_info_callback: {e}")
        bot.answer_callback_query(call.id, "❌ An error occurred!")

@bot.callback_query_handler(func=lambda call: call.data == 'buy_energy')
def buy_energy_callback(call):
    try:
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        packages = [
            (50, 83), (100, 166), (150, 211), (200, 256),
            (300, 384), (500, 640), (750, 960), (1000, 1280)
        ]
        
        for i in range(0, len(packages), 2):
            row_buttons = []
            for j in range(2):
                if i + j < len(packages):
                    stars, energy = packages[i + j]
                    button = types.InlineKeyboardButton(
                        text=f'⭐ {stars} = ⚡ {energy}',
                        callback_data=f'buy_{stars}_{energy}'
                    )
                    row_buttons.append(button)
            markup.add(*row_buttons)
        
        back_button = types.InlineKeyboardButton(text='🔙 Back', callback_data='back_to_main')
        markup.add(back_button)
        
        energy_text = """⚡ *Choose Energy Package*

💡 Get more energy to mine longer!
📈 Higher packages = better value!
⭐ Pay with Telegram Stars

🎯 *Available Packages:*"""
        
        try:
            bot.edit_message_text(
                energy_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup,
                parse_mode='Markdown'
            )
        except telebot.apihelper.ApiTelegramException as ex:
            if "no text in the message to edit" in str(ex).lower():
                bot.send_message(call.message.chat.id, energy_text, reply_markup=markup, parse_mode='Markdown')
            else:
                raise ex
        
    except Exception as e:
        logging.error(f"Error in buy_energy_callback: {e}")
        bot.answer_callback_query(call.id, "❌ An error occurred!")

@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_'))
def process_energy_purchase(call):
    try:
        _, stars, energy = call.data.split('_')
        stars = int(stars)
        energy = int(energy)
        
        prices = [types.LabeledPrice(label=f'⚡ {energy} Energy', amount=stars)]
        
        bot.send_invoice(
            chat_id=call.message.chat.id,
            title=f'⚡ Energy Package - {energy} Energy',
            description=f'🚀 Get {energy} energy for your mining operations!\n⛏️ Mine more blocks and earn more BHC!\n💰 Boost your mining power now!',
            invoice_payload=f'energy_{stars}_{energy}_{call.message.chat.id}',
            provider_token='',
            currency='XTR',
            prices=prices,
            start_parameter=f'energy-{stars}-{energy}'
        )
        
    except Exception as e:
        logging.error(f"Energy purchase error: {e}")
        bot.send_message(call.message.chat.id, "❌ Error processing purchase. Try again.")

@bot.callback_query_handler(func=lambda call: call.data == 'help_info')
def help_info_callback(call):
    try:
        info_text = """❓ *BitHash Mining Bot Help*

🔧 *How it works:*
• ⛏️ Mine blocks to earn BHC coins
• 🎯 Each block has 36% chance for reward
• ⚡ Mining consumes energy over time
• 💳 Buy energy with Telegram Stars
• 👥 Refer friends for bonus energy

✨ *Features:*
• 🔗 Real blockchain simulation
• 🎮 Live mining with rewards
• ⚡ Energy-based mining system
• 🎁 Referral bonus system
• 💰 Telegram Stars payments

🚀 Start mining and earn digital coins!"""
        
        markup = types.InlineKeyboardMarkup()
        back_button = types.InlineKeyboardButton(text='🔙 Back', callback_data='back_to_main')
        markup.add(back_button)
        
        try:
            bot.edit_message_text(
                info_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup,
                parse_mode='Markdown'
            )
        except telebot.apihelper.ApiTelegramException as ex:
            if "no text in the message to edit" in str(ex).lower():
                bot.send_message(call.message.chat.id, info_text, reply_markup=markup, parse_mode='Markdown')
            else:
                raise ex
        
    except Exception as e:
        logging.error(f"Error in help_info_callback: {e}")
        bot.answer_callback_query(call.id, "❌ An error occurred!")

@bot.callback_query_handler(func=lambda call: call.data == 'back_to_main')
def back_to_main_callback(call):
    try:
        start_command(call.message)
    except Exception as e:
        logging.error(f"Error in back_to_main_callback: {e}")

@bot.pre_checkout_query_handler(func=lambda query: True)
def checkout(pre_checkout_query):
    try:
        bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
    except Exception as e:
        logging.error(f"Error in checkout: {e}")

@bot.message_handler(content_types=['successful_payment'])
def got_payment(message):
    try:
        payload = message.successful_payment.invoice_payload
        parts = payload.split('_')
        
        if len(parts) >= 4 and parts[0] == 'energy':
            stars = int(parts[1])
            energy = int(parts[2])
            chat_id = parts[3]
            
            user_wallet = db.get_user_wallet_by_telegram(chat_id)
            
            if user_wallet:
                db.add_energy(user_wallet, energy)
                current_energy = db.get_wallet_energy(user_wallet)
                
                bot.send_message(
                    message.chat.id,
                    f"✅ *Payment Successful!*\n\n⭐ Stars Paid: {stars}\n⚡ Energy Added: {energy}\n🔋 Current Energy: {current_energy:.1f}/200\n\n🎉 Thank you for your purchase!\n⛏️ Start mining now!",
                    parse_mode='Markdown'
                )
            else:
                bot.send_message(message.chat.id, "❌ Wallet not found. Contact support.")
        else:
            bot.send_message(message.chat.id, "❌ Invalid payment data.")
            
    except Exception as e:
        logging.error(f"Payment processing error: {e}")
        bot.send_message(message.chat.id, "❌ Error processing payment.")

@bot.message_handler(commands=['wallet'])
def wallet_command(message):
    try:
        chat_id = str(message.chat.id)
        user_wallet = db.get_user_wallet_by_telegram(chat_id)
        
        if user_wallet:
            wallet_data = db.get_wallet_data(user_wallet)
            energy = wallet_data["energy"] if wallet_data else 0
            total_mined = wallet_data["total_mined"] if wallet_data else 0
            referrals_count = db.get_referrals_count(user_wallet)
            referral_link = f"https://t.me/BitHash_miningbot?start={chat_id}"
            
            markup = types.InlineKeyboardMarkup()
            web_app = types.WebAppInfo(f"{WEBHOOK_URL}?telegram_id={chat_id}")
            app_button = types.InlineKeyboardButton(text='⛏️ Open Mining Dashboard', web_app=web_app)
            markup.add(app_button)
            
            response_text = f"""💳 *Wallet Status*

🏦 *Address:* `{user_wallet}`
⚡ *Energy:* {energy:.1f}/200
💰 *Total Mined:* {total_mined:.6f} BHC
👥 *Referrals:* {referrals_count}

🔗 *Your Referral Link:*
`{referral_link}`"""
            
            bot.send_message(chat_id, response_text, reply_markup=markup, parse_mode='Markdown')
        else:
            bot.send_message(chat_id, "❌ No wallet found. Use /start to create one.")
            
    except Exception as e:
        logging.error(f"Error in wallet_command: {e}")
        bot.send_message(message.chat.id, "❌ An error occurred. Please try again.")

def notify_mining_completed(wallet_address, total_reward, blocks_mined, mining_duration):
    try:
        chat_id = db.get_telegram_id_by_wallet(wallet_address)
        if chat_id:
            hours = mining_duration // 3600
            minutes = (mining_duration % 3600) // 60
            
            if total_reward > 0:
                message = f"⛏️ *Mining Completed!*\n\n💰 Total Reward: {total_reward:.6f} BHC\n🔥 Blocks Mined: {blocks_mined}\n⏱️ Duration: {hours}h {minutes}m\n\n🎉 Great job miner!"
            else:
                message = f"⛏️ *Mining Session Ended*\n\n📊 Blocks Processed: {blocks_mined}\n⏱️ Duration: {hours}h {minutes}m\n💔 No rewards this time, try again!\n🍀 Better luck next time!"
            
            safe_send_message(chat_id, message, parse_mode='Markdown')
            
    except Exception as e:
        logging.error(f"Mining notification error: {e}")

def mining_reward_halved():
    if hasattr(db, '_halved') and db._halved:
        return True
    return False

def start_bot_polling():
    try:
        delete_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteWebhook"
        delete_response = requests_session.post(delete_url, timeout=10)
        logging.info(f"Delete webhook response: {delete_response.json()}")
        
        print("Starting BitHash Telegram Bot with polling...")
        bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
        
    except Exception as e:
        logging.error(f"Bot polling error: {e}")
        print(f"Bot error: {e}")
        time.sleep(5)
        start_bot_polling()  # Restart on error

if __name__ == '__main__':
    start_bot_polling()
