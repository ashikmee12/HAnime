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

@flask_app.route('/')
def health_check():
    return "Bot is running!"

@flask_app.route('/ad-callback', methods=['POST', 'OPTIONS'])
def ad_callback():
    # Handle CORS preflight request
    if request.method == 'OPTIONS':
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
        return response
    
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
                logger.info(f"Sending file {file_code} to user {user_id}")
                
                # Send file via bot API directly
                bot_token = BOT_TOKEN
                
                # First send a confirmation message
                send_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                requests.post(send_url, json={
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
                
                logger.info(f"File {file_code} sent successfully to {user_id}")
            else:
                logger.error(f"File not found: {file_code}")
        
        response = jsonify({'status': 'ok'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response
        
    except Exception as e:
        logger.error(f"Callback error: {e}")
        response = jsonify({'status': 'error', 'message': str(e)})
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 500

async def send_file_by_type(update, file_id, file_type):
    """Send file based on its type"""
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
    
    # Check if this is a deep link (with file code)
    if context.args:
        file_code = context.args[0]
        
        if file_code.startswith("file_"):
            short_code = file_code.replace("file_", "")
            file_data = get_file(short_code)
            
            if file_data:
                file_id, file_type = file_data
                
                # Check if user already viewed ad
                if has_viewed_ad(user_id, short_code):
                    logger.info(f"User {user_id} already viewed ad, sending file directly")
                    await send_file_by_type(update, file_id, file_type)
                else:
                    # Store pending file in context
                    context.user_data['pending_file'] = short_code
                    
                    # Create mini app button with parameters
                    render_url = "https://hanime-2-f4rp.onrender.com"
                    mini_app_url = f"{MINI_APP_URL}?user_id={user_id}&file_code={short_code}"
                    
                    keyboard = [[InlineKeyboardButton(
                        text="🎬 Watch Ad to Get File",
                        web_app=WebAppInfo(url=mini_app_url)
                    )]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    await update.message.reply_text(
                        "📁 **Your file is ready!**\n\n"
                        "⚠️ Watch the ad below to get your file instantly.\n\n"
                        "**Click the button:**",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
            else:
                await update.message.reply_text("❌ Invalid or expired link!")
        else:
            await update.message.reply_text("👋 Welcome to File Store Bot!\n\nUse /help for commands.")
    else:
        await update.message.reply_text("👋 Welcome to File Store Bot!\n\nUse /help for commands.")

async def genlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate a shareable link for a file (admin only)"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    context.user_data['waiting_for_file'] = True
    await update.message.reply_text("📤 Forward me a file (video, photo, document, or audio) to generate a shareable link.")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle forwarded file from admin"""
    if context.user_data.get('waiting_for_file'):
        message = update.effective_message
        user_id = update.effective_user.id
        
        # Get file from message
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
            await update.message.reply_text("❌ Please forward a valid file (video, photo, document, or audio).")
            return
        
        # Generate short code
        short_code = generate_short_code()
        
        # Save to database
        save_file(short_code, file_id, file_type, message.chat_id, message.message_id)
        
        # Create link
        bot_username = context.bot.username
        file_link = f"https://t.me/{bot_username}?start=file_{short_code}"
        
        logger.info(f"Admin {user_id} created link for file {short_code}")
        
        await update.message.reply_text(
            f"✅ **File stored successfully!**\n\n"
            f"🔗 **Shareable Link:**\n`{file_link}`\n\n"
            f"📁 **Short Code:** `{short_code}`\n"
            f"📂 **Type:** {file_type}",
            parse_mode="Markdown"
        )
        
        context.user_data['waiting_for_file'] = False

async def batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create batch link for multiple files (admin only)"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    context.user_data['batch_step'] = 'waiting_first'
    await update.message.reply_text("📦 **Batch Mode Activated**\n\nSend me the **FIRST** message (forward or link) of the batch range.", parse_mode="Markdown")

async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a new admin (owner only)"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only owner can add admins.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /addadmin <user_id>")
        return
    
    try:
        new_admin_id = int(context.args[0])
        add_admin(new_admin_id, user_id)
        await update.message.reply_text(f"✅ User `{new_admin_id}` is now an admin.", parse_mode="Markdown")
        logger.info(f"Owner {user_id} added admin {new_admin_id}")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")

async def removeadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove an admin (owner only)"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only owner can remove admins.")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /removeadmin <user_id>")
        return
    
    try:
        admin_id = int(context.args[0])
        remove_admin(admin_id)
        await update.message.reply_text(f"✅ User `{admin_id}` removed from admins.", parse_mode="Markdown")
        logger.info(f"Owner {user_id} removed admin {admin_id}")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")

async def listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all admins (admin only)"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized.")
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
    """Show help message"""
    user_id = update.effective_user.id
    is_admin_user = is_admin(user_id)
    
    text = "**📖 Bot Commands:**\n\n"
    
    if is_admin_user:
        text += "**Admin Commands:**\n"
        text += "🔹 `/genlink` - Generate a shareable link for a file\n"
        text += "🔹 `/batch` - Create batch link for multiple files\n"
        text += "🔹 `/admins` - List all admins\n\n"
    
    if user_id == OWNER_ID:
        text += "**Owner Commands:**\n"
        text += "🔹 `/addadmin <id>` - Add new admin\n"
        text += "🔹 `/removeadmin <id>` - Remove admin\n\n"
    
    text += "**User Commands:**\n"
    text += "🔹 Click any file link → Watch ad → Get file automatically"
    
    await update.message.reply_text(text, parse_mode="Markdown")

def run_flask():
    """Run Flask app in a separate thread"""
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
    
    # Add message handlers
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_file))
    
    logger.info("🤖 Bot is running with Flask callback endpoint on port 10000...")
    print("🤖 Bot is running with Flask callback endpoint on port 10000...")
    
    # Start polling
    app.run_polling()

if __name__ == "__main__":
    main()
