# bot.py
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from config import BOT_TOKEN, OWNER_ID, MINI_APP_URL
from database import *

# Initialize database
init_db()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
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
                    # Send file directly
                    await send_file_by_type(update, file_id, file_type)
                else:
                    # Show ad button with mini app
                    context.user_data['pending_file'] = short_code
                    keyboard = [[InlineKeyboardButton(
                        text="🎬 Watch Ad to Get File",
                        web_app=WebAppInfo(url=MINI_APP_URL)
                    )]]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    await update.message.reply_text(
                        "📁 **Your file is ready!**\n\n"
                        "⚠️ Watch one ad to get your file.\n"
                        "Click the button below:",
                        reply_markup=reply_markup,
                        parse_mode="Markdown"
                    )
            else:
                await update.message.reply_text("❌ Invalid or expired link!")
        else:
            await update.message.reply_text("👋 Welcome to File Store Bot!\n\nUse /help for commands.")
    else:
        await update.message.reply_text("👋 Welcome to File Store Bot!\n\nUse /help for commands.")

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

async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = update.effective_message.web_app_data.data
    import json
    try:
        ad_data = json.loads(data)
        if ad_data.get('status') == 'ad_completed':
            file_code = ad_data.get('file_code')
            user_id = update.effective_user.id
            
            # Record that user viewed ad
            record_ad_view(user_id, file_code)
            
            # Send the file
            file_data = get_file(file_code)
            if file_data:
                file_id, file_type = file_data
                await send_file_by_type(update, file_id, file_type)
            else:
                await update.message.reply_text("❌ File not found!")
    except:
        pass

async def genlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    context.user_data['waiting_for_file'] = True
    await update.message.reply_text("📤 Forward me a file (video, photo, document, or audio) to generate a shareable link.")

async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('waiting_for_file'):
        message = update.effective_message
        
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
        
        await update.message.reply_text(
            f"✅ **File stored successfully!**\n\n"
            f"🔗 **Shareable Link:**\n`{file_link}`\n\n"
            f"📁 **Short Code:** `{short_code}`\n"
            f"📂 **Type:** {file_type}",
            parse_mode="Markdown"
        )
        
        context.user_data['waiting_for_file'] = False

async def batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return
    
    context.user_data['batch_step'] = 'waiting_first'
    await update.message.reply_text("📦 **Batch Mode Activated**\n\nSend me the **FIRST** message (forward or link) of the batch range.", parse_mode="Markdown")

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
        await update.message.reply_text(f"✅ User `{new_admin_id}` is now an admin.", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Invalid user ID.")

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
        await update.message.reply_text(f"✅ User `{admin_id}` removed from admins.", parse_mode="Markdown")
    except:
        await update.message.reply_text("❌ Invalid user ID.")

async def listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
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

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("genlink", genlink))
    app.add_handler(CommandHandler("batch", batch))
    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("removeadmin", removeadmin))
    app.add_handler(CommandHandler("admins", listadmins))
    
    # Handlers
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_file))
    
    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
