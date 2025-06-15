#!/usr/bin/env python3
"""
Production startup script with enhanced error handling
"""

import os
import sys
import threading
import time
import logging
from multiprocessing import Process
import signal

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def signal_handler(signum, frame):
    logging.info(f"Received signal {signum}, shutting down gracefully...")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def start_web_app():
    """Start the Flask web application with error recovery"""
    while True:
        try:
            from app import app, socketio
            port = int(os.environ.get('PORT', 5000))
            logging.info(f"🌐 Starting web app on port {port}")
            socketio.run(app, host='0.0.0.0', port=port, debug=False)
        except Exception as e:
            logging.error(f"❌ Web app error: {e}")
            logging.info("🔄 Restarting web app in 5 seconds...")
            time.sleep(5)

def start_telegram_bot():
    """Start the Telegram bot with error recovery"""
    while True:
        try:
            from bot import start_bot_polling
            logging.info("🤖 Starting Telegram bot")
            start_bot_polling()
        except Exception as e:
            logging.error(f"❌ Bot error: {e}")
            logging.info("🔄 Restarting bot in 5 seconds...")
            time.sleep(5)

def main():
    mode = os.environ.get('DEPLOYMENT_MODE', 'web')
    
    logging.info(f"🚀 Starting in {mode} mode")
    
    if mode == 'web':
        print("🌐 Starting web application only...")
        start_web_app()
    elif mode == 'bot':
        print("🤖 Starting Telegram bot only...")
        start_telegram_bot()
    elif mode == 'both':
        print("🚀 Starting both web app and bot...")
        # Start bot in separate process
        bot_process = Process(target=start_telegram_bot)
        bot_process.start()
        
        try:
            start_web_app()
        except KeyboardInterrupt:
            print("\n🛑 Shutting down...")
            bot_process.terminate()
            bot_process.join()
    else:
        print("❌ Invalid DEPLOYMENT_MODE. Use 'web', 'bot', or 'both'")
        sys.exit(1)

if __name__ == '__main__':
    main()
