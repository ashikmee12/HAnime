# bot.py - সম্পূর্ণ ফাইল প্রতিস্থাপন করুন
import asyncio
import threading
import json
import logging
import os
from flask import Flask, request
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

# Flask app for webhook
flask_app = Flask(__name__)
application = None  # Will be set later

@flask_app.route('/')
def health_check():
    return "Bot is running!"

@flask_app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook updates"""
    global application
    try:
        update = Update.de_json(request.get_json(force=True), application.bot)
        application.update_queue.put_nowait(update)
        return 'ok'
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return 'error', 500

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
                    keyboard = [[InlineKeyboardButton(
                        text="🎬 Watch Ad to Get File",
                        web_app=WebAppInfo(url=MINI_APP_URL)
                    )]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await update.message.reply_text(
                        "📁 **Your file is ready!**\n\n⚠️ Watch ad to get your file.",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
            else:
                await update.message.reply_text("❌ Invalid link!")
        else:
            await update.message.reply_text("👋 Welcome to File Store Bot!\n\nUse /help")
    else:
        await update.message.reply_text("👋 Welcome to File Store Bot!\n\nUse /help")

async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.effective_message.web_app_data.data
    user_id = update.effective_user.id
    
    logger.info(f"WebApp data from {user_id}: {data}")
    
    try:
        ad_data = json.loads(data)
        if ad_data.get('status') == 'ad_completed':
            file_code = ad_data.get('file_code')
            record_ad_view(user_id, file_code)
            file_data = get_file(file_code)
            if file_data:
                file_id, file_type = file_data
                await send_file_by_type(update, file_id, file_type)
                logger.info(f"File {file_code} sent to {user_id}")
            else:
                await update.message.reply_text("❌ File not found!")
    except Exception as e:
        logger.error(f"Error: {e}")

async def genlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Not authorized.")
        return
    context.user_data['waiting_for_file'] = True
    await update.message.reply_text("📤 Forward me a file to generate link.")

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
            await update.message.reply_text("❌ Please send a valid file.")
            return
        
        short_code = generate_short_code()
        save_file(short_code, file_id, file_type, message.chat_id, message.message_id)
        bot_username = context.bot.username
        file_link = f"https://t.me/{bot_username}?start=file_{short_code}"
        
        await update.message.reply_text(
            f"✅ **Link created!**\n\n🔗 `{file_link}`\n\n📁 Code: `{short_code}`",
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
    text = "**👥 Admins:**\n\n"
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
    text += "**Users:** Click any link → Watch ad → Get file"
    await update.message.reply_text(text, parse_mode="Markdown")

def main():
    global application
    
    # Build application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("genlink", genlink))
    application.add_handler(CommandHandler("batch", batch))
    application.add_handler(CommandHandler("addadmin", addadmin))
    application.add_handler(CommandHandler("removeadmin", removeadmin))
    application.add_handler(CommandHandler("admins", listadmins))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_file))
    
    # Set webhook
    render_url = "https://hanime-2-f4rp.onrender.com"
    webhook_url = f"{render_url}/webhook"
    
    application.bot.set_webhook(webhook_url)
    logger.info(f"Webhook set to {webhook_url}")
    
    # Start Flask
    flask_thread = threading.Thread(target=lambda: flask_app.run(host='0.0.0.0', port=10000, debug=False, use_reloader=False))
    flask_thread.daemon = True
    flask_thread.start()
    
    logger.info("🤖 Bot is running with Webhook...")
    
    # Start application
    application.run_polling()

if __name__ == "__main__":
    main()
