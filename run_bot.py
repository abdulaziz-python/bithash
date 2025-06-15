#!/usr/bin/env python3
"""
Standalone Telegram Bot Runner
Run this script separately from the Flask app
"""

import sys
import os
import logging
from bot import start_bot_polling

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def main():
    print("🤖 Starting BitHash Telegram Bot...")
    print("🔄 Using polling mode (no webhook needed)")
    
    try:
        start_bot_polling()
        
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Bot error: {e}")
        logging.error(f"Bot error: {e}")
    finally:
        print("👋 Bot shutdown complete")

if __name__ == '__main__':
    main()
