#!/usr/bin/env python3
import os
import asyncio
import tempfile
import time
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode, ChatAction

# ── Configuration ───────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
OWNER_ID = int(os.environ.get("OWNER_ID", "123456789")) # Your Telegram User ID

def split_text(text: str, limit: int = 4000) -> list[str]:
    """Split long output into chunks that fit Telegram's 4096 char limit."""
    return [text[i:i+limit] for i in range(0, len(text), limit)]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    context.user_data['cwd'] = os.getcwd()
    context.user_data['active'] = True
    await update.message.reply_text(
        f"✅ *Terminal Ready*\n\nSend any command now.\nCurrent Directory: `{context.user_data['cwd']}`",
        parse_mode=ParseMode.MARKDOWN
    )

async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    process = context.user_data.get('process')
    if process and process.returncode is None:
        try:
            process.terminate()
            await update.message.reply_text("🛑 Running process has been terminated.")
        except Exception as e:
            await update.message.reply_text(f"Error terminating process: {e}")
    else:
        await update.message.reply_text("No process is currently running.")

async def handle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.user_data.get('active'):
        await update.message.reply_text("Please send /start first.")
        return
    
    command = update.message.text.strip()
    if not command:
        return
        
    cwd = context.user_data.get('cwd', os.getcwd())
    
    # Handle Directory Changes (cd)
    if command == "cd":
        command = "cd ~"
    if command.startswith("cd "):
        target = command[3:].strip()
        target = os.path.expanduser(target)
        new_dir = os.path.abspath(os.path.join(cwd, target))
        if os.path.isdir(new_dir):
            context.user_data['cwd'] = new_dir
            await update.message.reply_text(f"📂 `{new_dir}`", parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(f"cd: no such directory: {target}")
        return

    # Send initial loading message
    msg = await update.message.reply_text("⏳ Running command...")
    
    # Use a temp file to avoid pipe buffer deadlocks on massive outputs
    with tempfile.NamedTemporaryFile(delete=False, mode='w+') as tf:
        temp_path = tf.name
        
    start_time = time.time()
    
    try:
        # Spawn the subprocess
        process = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=open(temp_path, 'w'),
            stderr=asyncio.subprocess.STDOUT, # Combine stderr with stdout
            cwd=cwd
        )
    except Exception as e:
        await msg.edit_text(f"❌ Execution failed: {e}")
        return
        
    context.user_data['process'] = process
    
    # Polling loop for loading animation
    try:
        while process.returncode is None:
            await asyncio.sleep(3)
            elapsed = int(time.time() - start_time)
            # Trigger typing indicator every 6 seconds
            if elapsed % 6 == 0:
                try: await update.message.chat.send_action(action=ChatAction.TYPING)
                except: pass
            try:
                await msg.edit_text(f"⏳ Running command... ({elapsed}s)")
            except: pass
    finally:
        await process.wait()
        context.user_data.pop('process', None)
        
    elapsed = int(time.time() - start_time)
    exit_code = process.returncode
    
    # Read the output
    try:
        with open(temp_path, 'r', errors='replace') as f:
            output = f.read()
    except Exception as e:
        output = f"[Error reading output file: {e}]"
    finally:
        try: os.remove(temp_path)
        except: pass
        
    # Edit the loading message to show completion
    await msg.edit_text(f"✅ Finished in {elapsed}s (exit code {exit_code})")
    
    if not output.strip():
        await update.message.reply_text("_(no output)_", parse_mode=ParseMode.MARKDOWN)
        return
        
    # Chunk and send output
    chunks = split_text(output, 4000)
    for chunk in chunks:
        try:
            # Send in monospace format
            await update.message.reply_text(f"<pre>{chunk}</pre>", parse_mode=ParseMode.HTML)
        except Exception:
            # Fallback to plain text if HTML parser fails (e.g. weird characters)
            await update.message.reply_text(chunk)
        await asyncio.sleep(0.5) # Prevent Telegram rate limits

def main():
    if not BOT_TOKEN or not OWNER_ID:
        print("ERROR: Please set BOT_TOKEN and OWNER_ID environment variables.")
        return
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_command))
    print("🚀 Bot is running...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
