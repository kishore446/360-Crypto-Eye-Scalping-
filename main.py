# main.py — entry point for the 360 Crypto Eye Scalping bot
from bot.config_validator import validate_config
from bot.bot import main

if __name__ == "__main__":
    validate_config()
    main()
