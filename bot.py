# bot.py
import asyncio
import threading
import json
import logging
import requests
from flask import Flask, request, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from config import BOT_TOKEN, OWNER_ID, MINI_APP_URL
from database import *

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize database
init_db()

# Flask app for receiving data
flask_app = Flask(__name__)
bot_app = None

@flask_app.route('/')
def health_check():
    return "Bot is running!"

@flask_app.route('/ad-callback', methods=['POST'])
def ad_callback():
    """Receive data from Mini App"""
    try:
        data = request.get_json()
        logger.info(f"Received callback: {data}")
        
        status = data.get('status')
        file_code = data.get('file_code')
        user_id = data.get('user_id')
        
        if status == 'ad_completed' and file_code and user_id:
            # Record that user viewed ad
            record_ad_view(user_id, file_code)
            
            # Get file from database
            file_data = get_file(file_code)
            if file_data:
                file_id, file_type = file_data
                
                # Send file via bot API directly
                bot_token = BOT_TOKEN
                send_file_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                
                # First, tell user file is coming
                requests.post(send_file_url, json={
                    'chat_id': user_id,
                    'text': '✅ Ad completed! Sending your file...'
                })
                
                # Send the actual file
                if file_type == 'video':
                    send_url = f"https://api.telegram.org/bot{bot_token}/sendVideo"
                    requests.post(send_url, json={'chat_id': user_id, 'video': file_id})
                elif file_type == 'photo':
                    send_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
                    requests.post(send_url, json={'chat_id': user_id, 'photo': file_id})
                elif file_type == 'document':
                    send_url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
                    requests.post(send_url, json={'chat_id': user_id, 'document': file_id})
                elif file_type == 'audio':
                    send_url = f"https://api.telegram.org/bot{bot_token}/sendAudio"
                    requests.post(send_url, json={'chat_id': user_id, 'audio': file_id})
                
                logger.info(f"File {file_code} sent to {user_id}")
                return jsonify({'status': 'ok'})
            else:
                logger.error(f"File not found: {file_code}")
                return jsonify({'status': 'error', 'message': 'File not found'}), 404
        
        return jsonify({'status': 'ignored'})
    except Exception as e:
        logger.error(f"Callback error: {e}")
        return jsonify({'status': 'error'}), 500

async def send_file_by_type(update, file_id, file_type):
    if file_type == 'video':
        await update.message.reply_video(file_id)
    elif file_type == 'photo':
        await update.message.reply_photo(file_id)
    elif file_type == 'document':
        await update.message.reply_document(file_id)
    elif file_type == 'audio':
        await update.message.reply_audio(file_id)
    else:
        await update.message.reply_text("File type not supported")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info(f"User {user_id} started with args: {context.args}")
    
    if context.args:
        file_code = context.args[0]
        if file_code.startswith("file_"):
            short_code = file_code.replace("file_", "")
            file_data = get_file(short_code)
            
            if file_data:
                file_id, file_type = file_data
                
                if has_viewed_ad(user_id, short_code):
                    await send_file_by_type(update, file_id, file_type)
                else:
                    context.user_data['pending_file'] = short_code
                    
                    # Store user_id in context for the mini app
                    context.user_data['user_id'] = user_id
                    
                    # Create mini app button with custom URL including user_id
                    render_url = "https://hanime-2-f4rp.onrender.com"
                    mini_app_url = f"{MINI_APP_URL}?user_id={user_id}&file_code={short_code}"
                    
                    keyboard = [[InlineKeyboardButton(
                        text="🎬 Watch Ad & Get File",
                        web_app=WebAppInfo(url=mini_app_url)
                    )]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        "📁 **Your file is ready!**\n\n"
                        "⚠️ Watch the ad below to get your file instantly.\n"
                        "Click the button:",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
            else:
                await update.message.reply_text("❌ Invalid or expired link!")
        else:
            await update.message.reply_text("👋 Welcome! Use /help for commands.")
    else:
        await update.message.reply_text("👋 Welcome! Use /help for commands.")

async def genlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    context.user_data['waiting_for_file'] = True
    await update.message.reply_text("📤 Forward me a file to generate a shareable link.")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_for_file'):
        message = update.effective_message
        if message.video:
            file_id = message.video.file_id
            file_type = 'video'
        elif message.photo:
            file_id = message.photo[-1].file_id
            file_type = 'photo'
        elif message.document:
            file_id = message.document.file_id
            file_type = 'document'
        elif message.audio:
            file_id = message.audio.file_id
            file_type = 'audio'
        else:
            await update.message.reply_text("❌ Please forward a valid file.")
            return
        
        short_code = generate_short_code()
        save_file(short_code, file_id, file_type, message.chat_id, message.message_id)
        bot_username = context.bot.username
        file_link = f"https://t.me/{bot_username}?start=file_{short_code}"
        
        await update.message.reply_text(
            f"✅ **File stored!**\n\n🔗 **Link:**\n`{file_link}`\n\n📁 **Code:** `{short_code}`",
            parse_mode="Markdown"
        )
        context.user_data['waiting_for_file'] = False

async def batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    context.user_data['batch_step'] = 'waiting_first'
    await update.message.reply_text("📦 Send FIRST message of the batch range.")

async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Only owner can add admins.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /addadmin <user_id>")
        return
    try:
        new_admin_id = int(context.args[0])
        add_admin(new_admin_id, update.effective_user.id)
        await update.message.reply_text(f"✅ User `{new_admin_id}` is now admin.", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Invalid ID.")

async def removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Only owner can remove admins.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /removeadmin <user_id>")
        return
    try:
        admin_id = int(context.args[0])
        remove_admin(admin_id)
        await update.message.reply_text(f"✅ User `{admin_id}` removed.", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Invalid ID.")

async def listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    admins = get_all_admins()
    if not admins:
        await update.message.reply_text("No admins found.")
        return
    text = "**👥 Admin List:**\n\n"
    for admin_id, is_owner in admins:
        role = "👑 Owner" if is_owner else "👤 Admin"
        text += f"• `{admin_id}` - {role}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = "**📖 Bot Commands:**\n\n"
    if is_admin(user_id):
        text += "🔹 `/genlink` - Create file link\n"
        text += "🔹 `/batch` - Create batch link\n"
        text += "🔹 `/admins` - List admins\n\n"
    if user_id == OWNER_ID:
        text += "🔹 `/addadmin <id>` - Add admin\n"
        text += "🔹 `/removeadmin <id>` - Remove admin\n\n"
    text += "**Users:** Click any link → Watch ad → Get file instantly"
    await update.message.reply_text(text, parse_mode="Markdown")

def run_flask():
    flask_app.run(host='0.0.0.0', port=10000, debug=False, use_reloader=False)

def main():
    # Start Flask in a separate thread
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Build the bot application
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Add command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("genlink", genlink))
    app.add_handler(CommandHandler("batch", batch))
    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("removeadmin", removeadmin))
    app.add_handler(CommandHandler("admins", listadmins))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_file))
    
    logger.info("🤖 Bot is running with Flask callback endpoint...")
    print("🤖 Bot is running with Flask callback endpoint...")
    app.run_polling()

if __name__ == "__main__":
    main()
