import asyncio
import json
import os
from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument, MessageMediaWebPage, MessageMediaContact, MessageMediaGeo, MessageMediaVenue, MessageMediaGame, MessageMediaInvoice, MessageMediaPoll, MessageMediaDice, MessageMediaStory

# Load configuration from config.py
try:
    from config import API_ID, API_HASH, BOT_TOKEN
except ImportError:
    print("Error: config.py not found or missing API_ID, API_HASH, BOT_TOKEN.")
    exit(1)

# File paths for storing channel and message mappings
CHANNELS_FILE = 'channels.json'
MESSAGE_MAP_FILE = 'message_map.json'

# Initialize TelegramClient for user session (for full API access)
client = TelegramClient('user_session', API_ID, API_HASH)

# Initialize TelegramClient for bot session (for bot commands) 
bot = TelegramClient('bot_session', API_ID, API_HASH)

# Global variables for message processing
message_processing_lock = asyncio.Lock()
pending_messages = {}  # Store messages waiting for reply resolution

# --- Helper Functions ---

def load_channels():
    if os.path.exists(CHANNELS_FILE):
        with open(CHANNELS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'source_channel': None, 'target_channels': []}

def save_channels(channels_data):
    with open(CHANNELS_FILE, 'w', encoding='utf-8') as f:
        json.dump(channels_data, f, ensure_ascii=False, indent=4)

def load_message_map():
    if os.path.exists(MESSAGE_MAP_FILE):
        with open(MESSAGE_MAP_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_message_map(message_map_data):
    with open(MESSAGE_MAP_FILE, 'w', encoding='utf-8') as f:
        json.dump(message_map_data, f, ensure_ascii=False, indent=4)

async def get_channel_name(channel_id):
    """Kanal nomini olish funksiyasi"""
    try:
        entity = await client.get_entity(channel_id)
        if hasattr(entity, 'title') and entity.title:
            return entity.title
        elif hasattr(entity, 'username') and entity.username:
            return f"@{entity.username}"
        else:
            return f"ID: {channel_id}"
    except Exception as e:
        print(f"Error getting channel name for {channel_id}: {e}")
        return f"ID: {channel_id}"

async def get_entity_id(entity_str):
    """Entity ID ni olish funksiyasi"""
    try:
        # Try to convert to int directly if it's a numeric string
        entity_id = int(entity_str)
        # For channels/groups, Telethon expects negative IDs
        if entity_id > 0:
            return -100000000000000 - entity_id  # Proper supergroup/channel ID conversion
        return entity_id
    except ValueError:
        # If not a numeric string, try to resolve by username/link
        try:
            entity = await client.get_entity(entity_str)
            return entity.id
        except Exception as e:
            print(f"Entity resolution error: {e}")
            return None

async def get_media_for_forward(message):
    """Media faylni to'g'ri formatda qaytarish"""
    if not message.media:
        return None
    
    try:
        # Photo uchun
        if isinstance(message.media, MessageMediaPhoto):
            return message.photo
        
        # Document uchun (video, audio, file)
        elif isinstance(message.media, MessageMediaDocument):
            return message.document
        
        # WebPage da photo bo'lsa
        elif isinstance(message.media, MessageMediaWebPage):
            if hasattr(message.media.webpage, 'photo') and message.media.webpage.photo:
                return message.media.webpage.photo
            elif hasattr(message.media.webpage, 'document') and message.media.webpage.document:
                return message.media.webpage.document
        
        # Boshqa media turlar
        elif hasattr(message, 'photo') and message.photo:
            return message.photo
        elif hasattr(message, 'document') and message.document:
            return message.document
        
        return None
    except Exception as e:
        print(f"Error getting media: {e}")
        return None

async def wait_for_reply_mapping(reply_to_msg_id, max_wait_time=10):
    """Reply xabar uchun mapping kutish funksiyasi"""
    wait_time = 0
    while wait_time < max_wait_time:
        message_map_data = load_message_map()
        if str(reply_to_msg_id) in message_map_data:
            return message_map_data[str(reply_to_msg_id)]
        await asyncio.sleep(0.5)
        wait_time += 0.5
    return None

async def process_pending_messages():
    """Kutilayotgan xabarlarni qayta ishlash"""
    global pending_messages
    
    if not pending_messages:
        return
    
    print(f"Processing {len(pending_messages)} pending messages...")
    
    # Pending messages ni copy qilib, originalini tozalash
    messages_to_process = pending_messages.copy()
    pending_messages.clear()
    
    for msg_id, msg_data in messages_to_process.items():
        try:
            await forward_message_with_reply(
                msg_data['event'],
                msg_data['target_channel_ids'],
                msg_data['reply_to_msg_id']
            )
        except Exception as e:
            print(f"Error processing pending message {msg_id}: {e}")

async def forward_message_with_reply(event, target_channel_ids, reply_to_msg_id=None):
    """Xabarni reply bilan forward qilish"""
    message_map_data = load_message_map()
    original_message_id = event.id
    forwarded_message_ids = {}
    
    for target_id in target_channel_ids:
        try:
            target_reply_to_id = None
            
            # Reply xabar ID ni topish
            if reply_to_msg_id:
                original_reply_map = message_map_data.get(str(reply_to_msg_id))
                if original_reply_map:
                    target_reply_to_id = original_reply_map.get(str(target_id))
                else:
                    # Agar mapping topilmasa, kutib ko'rish
                    print(f"Waiting for reply mapping for message {reply_to_msg_id}")
                    reply_mapping = await wait_for_reply_mapping(reply_to_msg_id)
                    if reply_mapping:
                        target_reply_to_id = reply_mapping.get(str(target_id))
            
            # Xabarni yuborish
            forwarded_message = await client.send_message(
                entity=target_id,
                message=event.message.text,
                file=await get_media_for_forward(event.message),
                reply_to=target_reply_to_id,
                link_preview=event.message.web_preview if hasattr(event.message, 'web_preview') else None,
                buttons=event.message.buttons if hasattr(event.message, 'buttons') else None,
                parse_mode='html'
            )
            
            forwarded_message_ids[str(target_id)] = forwarded_message.id
            print(f"Forwarded message {original_message_id} to {target_id} as {forwarded_message.id}")
            
        except Exception as e:
            print(f"Error forwarding message {original_message_id} to {target_id}: {e}")
    
    # Mapping ni saqlash
    if forwarded_message_ids:
        async with message_processing_lock:
            message_map_data = load_message_map()
            message_map_data[str(original_message_id)] = forwarded_message_ids
            save_message_map(message_map_data)

# --- Bot Commands ---

@bot.on(events.NewMessage(pattern='/start'))
async def start_command(event):
    if not event.is_private:
        return
    
    start_text = """
🤖 **Kanal Sinxronlash Boti**

Salom! Men kanallar orasidagi postlarni sinxronlash, tahrirlash va o'chirishni boshqaruvchi botman.

📋 **Asosiy funksiyalar:**
• Postlarni bir kanaldan boshqa kanallarga nusxalash
• Postlarni tahrirlash (48 soat+ ham ishlaydi)
• Postlarni o'chirish
• Reply (javob) postlarni qo'llab-quvvatlash

⚙️ **Buyruqlar:**
`/set_source` - Manba kanalni belgilash
`/add_target` - Maqsad kanal qo'shish  
`/remove_target` - Maqsad kanalni o'chirish
`/list_channels` - Sozlangan kanallarni ko'rish

📝 **Misol:**
`/set_source @manba_kanal`
`/add_target @maqsad_kanal1`

🔄 Bot tayyor! Kanallarni sozlashdan boshlang.
    """
    await event.reply(start_text)

@bot.on(events.NewMessage(pattern='/set_source'))
async def set_source_channel(event):
    if not event.is_private:
        return
    try:
        channel_str = event.raw_text.split(' ', 1)[1].strip()
        channel_id = await get_entity_id(channel_str)
        if channel_id is None:
            await event.reply("❌ **Xatolik!**\n\nManba kanal topilmadi. ID, username yoki linkni to'g'ri kiriting.\n\n**Misol:**\n`/set_source @kanal_nomi`\n`/set_source https://t.me/kanal_nomi`")
            return

        # Kanal nomini olish
        channel_name = await get_channel_name(channel_id)
        
        channels_data = load_channels()
        channels_data['source_channel'] = channel_id
        save_channels(channels_data)
        
        success_msg = f"✅ **Manba kanal muvaffaqiyatli o'rnatildi!**\n\n"
        success_msg += f"📥 **Kanal:** {channel_name}\n"
        success_msg += f"🆔 **ID:** `{channel_id}`\n\n"
        success_msg += "💡 Endi maqsad kanallarni qo'shing:\n`/add_target @maqsad_kanal`"
        
        await event.reply(success_msg)
    except IndexError:
        await event.reply("❌ **Noto'g'ri format!**\n\n**Foydalanish:**\n`/set_source @kanal_nomi`\n`/set_source https://t.me/kanal_nomi`\n`/set_source -1001234567890`")
    except Exception as e:
        await event.reply(f"❌ **Xatolik yuz berdi:**\n`{e}`")

@bot.on(events.NewMessage(pattern='/add_target'))
async def add_target_channel(event):
    if not event.is_private:
        return
    try:
        channel_str = event.raw_text.split(' ', 1)[1].strip()
        channel_id = await get_entity_id(channel_str)
        if channel_id is None:
            await event.reply("❌ **Xatolik!**\n\nMaqsad kanal topilmadi. ID, username yoki linkni to'g'ri kiriting.\n\n**Misol:**\n`/add_target @kanal_nomi`")
            return

        # Kanal nomini olish
        channel_name = await get_channel_name(channel_id)
        
        channels_data = load_channels()
        if channel_id not in channels_data['target_channels']:
            channels_data['target_channels'].append(channel_id)
            save_channels(channels_data)
            
            success_msg = f"✅ **Maqsad kanal muvaffaqiyatli qo'shildi!**\n\n"
            success_msg += f"📤 **Kanal:** {channel_name}\n"
            success_msg += f"🆔 **ID:** `{channel_id}`\n\n"
            success_msg += f"📊 **Jami maqsad kanallar:** {len(channels_data['target_channels'])} ta"
            
            await event.reply(success_msg)
        else:
            await event.reply(f"⚠️ **Diqqat!**\n\nBu kanal allaqachon maqsad kanallar ro'yxatida mavjud:\n\n📤 **Kanal:** {channel_name}\n🆔 **ID:** `{channel_id}`")
    except IndexError:
        await event.reply("❌ **Noto'g'ri format!**\n\n**Foydalanish:**\n`/add_target @kanal_nomi`\n`/add_target https://t.me/kanal_nomi`")
    except Exception as e:
        await event.reply(f"❌ **Xatolik yuz berdi:**\n`{e}`")

@bot.on(events.NewMessage(pattern='/remove_target'))
async def remove_target_channel(event):
    if not event.is_private:
        return
    try:
        channel_str = event.raw_text.split(' ', 1)[1].strip()
        channel_id = await get_entity_id(channel_str)
        if channel_id is None:
            await event.reply("❌ **Xatolik!**\n\nMaqsad kanal topilmadi. ID, username yoki linkni to'g'ri kiriting.")
            return

        # Kanal nomini olish
        channel_name = await get_channel_name(channel_id)
        
        channels_data = load_channels()
        if channel_id in channels_data['target_channels']:
            channels_data['target_channels'].remove(channel_id)
            save_channels(channels_data)
            
            success_msg = f"✅ **Maqsad kanal muvaffaqiyatli o'chirildi!**\n\n"
            success_msg += f"📤 **Kanal:** {channel_name}\n"
            success_msg += f"🆔 **ID:** `{channel_id}`\n\n"
            success_msg += f"📊 **Qolgan maqsad kanallar:** {len(channels_data['target_channels'])} ta"
            
            await event.reply(success_msg)
        else:
            await event.reply(f"⚠️ **Diqqat!**\n\nBu kanal maqsad kanallar ro'yxatida mavjud emas:\n\n📤 **Kanal:** {channel_name}\n🆔 **ID:** `{channel_id}`")
    except IndexError:
        await event.reply("❌ **Noto'g'ri format!**\n\n**Foydalanish:**\n`/remove_target @kanal_nomi`")
    except Exception as e:
        await event.reply(f"❌ **Xatolik yuz berdi:**\n`{e}`")

@bot.on(events.NewMessage(pattern='/list_channels'))
async def list_channels(event):
    if not event.is_private:
        return
    
    channels_data = load_channels()
    source = channels_data['source_channel']
    targets = channels_data['target_channels']

    msg = "📋 **Kanallar Konfiguratsiyasi**\n"
    msg += "═" * 30 + "\n\n"
    
    # Manba kanal
    if source is None:
        msg += "📥 **Manba Kanal:**\n"
        msg += "   ❌ Hech qanday kanal belgilanmagan\n\n"
    else:
        source_name = await get_channel_name(source)
        msg += "📥 **Manba Kanal:**\n"
        msg += f"   ✅ {source_name}\n"
        msg += f"   🆔 `{source}`\n\n"
    
    # Maqsad kanallar
    msg += "📤 **Maqsad Kanallar:**\n"
    if not targets:
        msg += "   ❌ Hech qanday kanal qo'shilmagan\n\n"
    else:
        for i, target in enumerate(targets, 1):
            target_name = await get_channel_name(target)
            msg += f"   {i}. ✅ {target_name}\n"
            msg += f"      🆔 `{target}`\n\n"
    
    # Status
    if source and targets:
        msg += "🟢 **Status:** Aktiv - Bot ishlamoqda\n"
        msg += f"📊 **Statistika:** {len(targets)} ta maqsad kanal"
    else:
        msg += "🔴 **Status:** Nofaol - Kanallarni sozlang"
    
    await event.reply(msg)

# --- Event Handlers for Message Sync ---

@client.on(events.NewMessage)
async def handle_new_message(event):
    channels_data = load_channels()
    source_channel_id = channels_data['source_channel']
    target_channel_ids = channels_data['target_channels']

    if source_channel_id is None or not target_channel_ids:
        return

    # Convert positive ID from JSON to the negative format Telethon uses
    if isinstance(source_channel_id, int) and source_channel_id > 0:
        source_channel_id = int(f"-100{source_channel_id}")

    if event.chat_id == source_channel_id:
        reply_to_msg_id = event.message.reply_to_msg_id
        
        # Agar reply xabar bo'lsa va uning mapping i hali yo'q bo'lsa
        if reply_to_msg_id:
            message_map_data = load_message_map()
            if str(reply_to_msg_id) not in message_map_data:
                # Xabarni pending holatiga qo'yish
                global pending_messages
                pending_messages[event.id] = {
                    'event': event,
                    'target_channel_ids': target_channel_ids,
                    'reply_to_msg_id': reply_to_msg_id
                }
                print(f"Message {event.id} added to pending queue (waiting for reply mapping)")
                
                # 2 soniya kutib, pending xabarlarni qayta ishlash
                await asyncio.sleep(2)
                await process_pending_messages()
                return
        
        # Oddiy xabar yoki reply mapping mavjud bo'lsa
        await forward_message_with_reply(event, target_channel_ids, reply_to_msg_id)

@client.on(events.MessageEdited)
async def handle_edited_message(event):
    channels_data = load_channels()
    source_channel_id = channels_data['source_channel']
    target_channel_ids = channels_data['target_channels']

    if source_channel_id is None or not target_channel_ids:
        return

    # Convert positive ID from JSON to the negative format Telethon uses
    if isinstance(source_channel_id, int) and source_channel_id > 0:
        source_channel_id = int(f"-100{source_channel_id}")

    if event.chat_id == source_channel_id:
        async with message_processing_lock:
            message_map_data = load_message_map()
            original_message_id = event.id

            if str(original_message_id) in message_map_data:
                forwarded_ids_map = message_map_data[str(original_message_id)]
                
                # Har bir target kanal uchun tahrirlash
                for target_id_str, forwarded_msg_id in forwarded_ids_map.items():
                    target_id = int(target_id_str)
                    try:
                        # Avval media + caption tahrirlashga harakat qilish
                        await client.edit_message(
                            entity=target_id,
                            message=forwarded_msg_id,
                            text=event.message.text,
                            file=await get_media_for_forward(event.message),
                            link_preview=event.message.web_preview if hasattr(event.message, 'web_preview') else None,
                            buttons=event.message.buttons if hasattr(event.message, 'buttons') else None,
                            parse_mode='html'
                        )
                        print(f"Edited forwarded message {forwarded_msg_id} in {target_id} for original {original_message_id}")
                    except Exception as e:
                        print(f"Error editing message {forwarded_msg_id} in {target_id}: {e}")
                        # Fallback: Faqat caption tahrirlash
                        try:
                            await client.edit_message(
                                entity=target_id,
                                message=forwarded_msg_id,
                                text=event.message.text,
                                parse_mode='html'
                            )
                            print(f"Fallback: Edited caption only for message {forwarded_msg_id}")
                        except Exception as fallback_error:
                            print(f"Fallback also failed: {fallback_error}")

@client.on(events.MessageDeleted)
async def handle_deleted_message(event):
    channels_data = load_channels()
    source_channel_id = channels_data['source_channel']
    target_channel_ids = channels_data['target_channels']

    if source_channel_id is None or not target_channel_ids:
        return

    # Convert positive ID from JSON to the negative format Telethon uses
    if isinstance(source_channel_id, int) and source_channel_id > 0:
        source_channel_id = int(f"-100{source_channel_id}")

    # Check if deletion is from source channel
    if hasattr(event, 'chat_id') and event.chat_id != source_channel_id:
        return

    # Handle different types of deleted_id (can be int or list)
    deleted_ids = []
    if isinstance(event.deleted_id, int):
        deleted_ids = [event.deleted_id]
    elif isinstance(event.deleted_id, list):
        deleted_ids = event.deleted_id
    else:
        print(f"Unknown deleted_id type: {type(event.deleted_id)}")
        return

    # Process each deleted message
    for original_message_id in deleted_ids:
        async with message_processing_lock:
            message_map_data = load_message_map()
            if str(original_message_id) in message_map_data:
                forwarded_ids_map = message_map_data[str(original_message_id)]
                
                # Har bir target kanaldan o'chirish
                for target_id_str, forwarded_msg_id in forwarded_ids_map.items():
                    target_id = int(target_id_str)
                    try:
                        await client.delete_messages(entity=target_id, message_ids=[forwarded_msg_id])
                        print(f"Deleted forwarded message {forwarded_msg_id} in {target_id} for original {original_message_id}")
                    except Exception as e:
                        print(f"Error deleting message {forwarded_msg_id} in {target_id}: {e}")
                
                # Mapping dan o'chirish
                del message_map_data[str(original_message_id)]
                save_message_map(message_map_data)
                print(f"Removed message mapping for {original_message_id}")
            else:
                print(f"No mapping found for deleted message {original_message_id}")

async def main():
    print("Bot ishga tushmoqda...")
    
    try:
        # Start the user client (for listening to channel events)
        print("User client ishga tushmoqda...")
        await client.start()
        print("User client ishga tushdi.")

        # Start the bot client
        print("Bot client ishga tushmoqda...")
        await bot.start(bot_token=BOT_TOKEN)
        me = await bot.get_me()
        print(f"Bot client ishga tushdi: @{me.username}")
        print("Bot tayyor! Kanal xabarlarini kuzatish boshlandi...")
        
        # Run both clients concurrently using asyncio.gather
        await asyncio.gather(
            client.run_until_disconnected(),
            bot.run_until_disconnected()
        )
        
    except Exception as e:
        print(f"Client start error: {e}")
        raise

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot to'xtatildi.")
    except Exception as e:
        print(f"Botda kutilmagan xatolik: {e}")
        import traceback
        traceback.print_exc()
