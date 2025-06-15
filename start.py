#!/usr/bin/env python3
"""
BitHash Mining System Startup Script
This script helps you start both the Flask app and Telegram bot
"""

import subprocess
import sys
import time
import os
from threading import Thread

def run_flask_app():
    """Run the Flask application"""
    print("🌐 Starting Flask App...")
    try:
        subprocess.run([sys.executable, "app.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Flask app error: {e}")
    except KeyboardInterrupt:
        print("🛑 Flask app stopped")

def run_telegram_bot():
    """Run the Telegram bot"""
    print("🤖 Starting Telegram Bot...")
    try:
        subprocess.run([sys.executable, "run_bot.py"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Bot error: {e}")
    except KeyboardInterrupt:
        print("🛑 Bot stopped")

def main():
    print("🚀 BitHash Mining System Startup")
    print("=" * 50)
    print()
    print("Choose how to start the system:")
    print("1. Start Flask App only")
    print("2. Start Telegram Bot only")
    print("3. Start both (recommended)")
    print("4. Exit")
    print()
    
    try:
        choice = input("Enter your choice (1-4): ").strip()
        
        if choice == "1":
            print("\n🌐 Starting Flask App only...")
            run_flask_app()
            
        elif choice == "2":
            print("\n🤖 Starting Telegram Bot only...")
            run_telegram_bot()
            
        elif choice == "3":
            print("\n🚀 Starting both services...")
            print("📝 Note: You can also run them separately in different terminals:")
            print("   Terminal 1: python app.py")
            print("   Terminal 2: python run_bot.py")
            print()
            
            # Start Flask app in a separate thread
            flask_thread = Thread(target=run_flask_app, daemon=True)
            flask_thread.start()
            
            # Give Flask a moment to start
            time.sleep(2)
            
            # Start bot in main thread
            run_telegram_bot()
            
        elif choice == "4":
            print("👋 Goodbye!")
            sys.exit(0)
            
        else:
            print("❌ Invalid choice. Please enter 1-4.")
            main()
            
    except KeyboardInterrupt:
        print("\n🛑 Startup cancelled")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == '__main__':
    main()
