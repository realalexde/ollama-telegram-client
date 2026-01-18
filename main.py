import asyncio
import json
import sqlite3
import re
from datetime import datetime
from typing import Optional, Dict, List
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, InlineQueryResultArticle, InputTextMessageContent
import aiohttp
from localization import LOCALES, LANGUAGES

API_TOKEN = 'YOUR_BOT_TOKEN_HERE'

class States(StatesGroup):
    waiting_host = State()
    waiting_host_name = State()
    waiting_model_name = State()
    waiting_chat_rename = State()
    waiting_message = State()
    waiting_response_edit = State()

class Database:
    def __init__(self, db_path='userdata.db'):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            host TEXT,
            selected_model TEXT,
            translator_model TEXT,
            locale TEXT DEFAULT 'ru'
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS hosts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            host_url TEXT,
            host_name TEXT,
            is_active INTEGER DEFAULT 0,
            created_at TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_name TEXT,
            model TEXT,
            created_at TIMESTAMP
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            role TEXT,
            content TEXT,
            timestamp TIMESTAMP
        )''')
        conn.commit()
        conn.close()
    
    def get_user(self, user_id: int) -> Optional[Dict]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return {'user_id': row[0], 'host': row[1], 'selected_model': row[2], 
                    'translator_model': row[3], 'locale': row[4]}
        return None
    
    def create_user(self, user_id: int, host: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO users (user_id, host, locale) VALUES (?, ?, ?)', 
                  (user_id, host, 'ru'))
        conn.commit()
        conn.close()
    
    def add_host(self, user_id: int, host_url: str, host_name: str) -> int:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # Деактивировать все хосты пользователя
        c.execute('UPDATE hosts SET is_active = 0 WHERE user_id = ?', (user_id,))
        # Добавить новый активный хост
        c.execute('INSERT INTO hosts (user_id, host_url, host_name, is_active, created_at) VALUES (?, ?, ?, 1, ?)',
                  (user_id, host_url, host_name, datetime.now()))
        host_id = c.lastrowid
        # Обновить текущий хост у пользователя
        c.execute('UPDATE users SET host = ? WHERE user_id = ?', (host_url, user_id))
        conn.commit()
        conn.close()
        return host_id
    
    def get_user_hosts(self, user_id: int) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT * FROM hosts WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
        rows = c.fetchall()
        conn.close()
        return [{'id': r[0], 'user_id': r[1], 'host_url': r[2], 'host_name': r[3], 'is_active': r[4], 'created_at': r[5]} for r in rows]
    
    def set_active_host(self, user_id: int, host_id: int):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        # Деактивировать все хосты
        c.execute('UPDATE hosts SET is_active = 0 WHERE user_id = ?', (user_id,))
        # Активировать выбранный
        c.execute('UPDATE hosts SET is_active = 1 WHERE id = ?', (host_id,))
        # Получить URL хоста
        c.execute('SELECT host_url FROM hosts WHERE id = ?', (host_id,))
        row = c.fetchone()
        if row:
            c.execute('UPDATE users SET host = ? WHERE user_id = ?', (row[0], user_id))
        conn.commit()
        conn.close()
    
    def delete_host(self, host_id: int):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('DELETE FROM hosts WHERE id = ?', (host_id,))
        conn.commit()
        conn.close()
    
    def update_user(self, user_id: int, **kwargs):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        for key, value in kwargs.items():
            c.execute(f'UPDATE users SET {key} = ? WHERE user_id = ?', (value, user_id))
        conn.commit()
        conn.close()
    
    def create_chat(self, user_id: int, chat_name: str, model: str) -> int:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('INSERT INTO chats (user_id, chat_name, model, created_at) VALUES (?, ?, ?, ?)',
                  (user_id, chat_name, model, datetime.now()))
        chat_id = c.lastrowid
        conn.commit()
        conn.close()
        return chat_id
    
    def get_user_chats(self, user_id: int) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT * FROM chats WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
        rows = c.fetchall()
        conn.close()
        return [{'id': r[0], 'user_id': r[1], 'chat_name': r[2], 'model': r[3], 'created_at': r[4]} for r in rows]
    
    def get_chat(self, chat_id: int) -> Optional[Dict]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT * FROM chats WHERE id = ?', (chat_id,))
        row = c.fetchone()
        conn.close()
        if row:
            return {'id': row[0], 'user_id': row[1], 'chat_name': row[2], 'model': row[3], 'created_at': row[4]}
        return None
    
    def update_chat_name(self, chat_id: int, new_name: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('UPDATE chats SET chat_name = ? WHERE id = ?', (new_name, chat_id))
        conn.commit()
        conn.close()
    
    def delete_chat(self, chat_id: int):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('DELETE FROM messages WHERE chat_id = ?', (chat_id,))
        c.execute('DELETE FROM chats WHERE id = ?', (chat_id,))
        conn.commit()
        conn.close()
    
    def add_message(self, chat_id: int, role: str, content: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('INSERT INTO messages (chat_id, role, content, timestamp) VALUES (?, ?, ?, ?)',
                  (chat_id, role, content, datetime.now()))
        conn.commit()
        conn.close()
    
    def get_chat_messages(self, chat_id: int) -> List[Dict]:
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('SELECT role, content FROM messages WHERE chat_id = ? ORDER BY timestamp', (chat_id,))
        rows = c.fetchall()
        conn.close()
        return [{'role': r[0], 'content': r[1]} for r in rows]
    
    def update_last_message(self, chat_id: int, new_content: str):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''UPDATE messages SET content = ? 
                     WHERE chat_id = ? AND id = (
                         SELECT id FROM messages WHERE chat_id = ? ORDER BY timestamp DESC LIMIT 1
                     )''', (new_content, chat_id, chat_id))
        conn.commit()
        conn.close()

db = Database()
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

user_states: Dict[int, Dict] = {}

def get_locale(user_id: int) -> str:
    user = db.get_user(user_id)
    if user and user['locale']:
        return user['locale']
    return 'ru'  # По умолчанию русский

def t(user_id: int, key: str) -> str:
    locale = get_locale(user_id)
    result = LOCALES.get(locale, LOCALES['ru']).get(key, LOCALES['ru'].get(key, key))
    return result

def get_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t(user_id, 'btn_model_select'))],
            [KeyboardButton(text=t(user_id, 'btn_chats'))],
            [KeyboardButton(text=t(user_id, 'btn_settings'))]
        ],
        resize_keyboard=True
    )
    return keyboard

async def get_ollama_models(host: str) -> List[str]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{host}/api/tags", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [model['name'] for model in data.get('models', [])]
    except Exception as e:
        print(f"Ошибка получения моделей: {e}")
    return []

async def check_ollama_connection(host: str) -> bool:
    """Проверка доступности Ollama сервера"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{host}/api/tags", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                return resp.status == 200
    except Exception as e:
        print(f"Ошибка подключения к {host}: {e}")
        return False

async def pull_model(host: str, model_name: str, progress_callback):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{host}/api/pull", 
                                   json={'name': model_name}, 
                                   timeout=aiohttp.ClientTimeout(total=None)) as resp:
                if resp.status == 200:
                    async for line in resp.content:
                        if line:
                            try:
                                data = json.loads(line.decode('utf-8'))
                                if 'status' in data:
                                    completed = data.get('completed', 0)
                    total = data.get('total', 1)
                                    if total > 0:
                                        progress = int((completed / total) * 100)
                                        await progress_callback(progress, data['status'])
                                    if data.get('status') == 'success':
                                        return True
                            except Exception as e:
                                print(f"Ошибка парсинга: {e}")
                    return True
                else:
                    print(f"Ошибка pull: status {resp.status}")
                    return False
    except Exception as e:
        print(f"Ошибка pull_model: {e}")
        return False

async def load_model(host: str, model_name: str) -> bool:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{host}/api/generate", 
                                   json={'model': model_name, 'prompt': '', 'stream': False},
                                   timeout=aiohttp.ClientTimeout(total=60)) as resp:
                return resp.status == 200
    except Exception as e:
        print(f"Ошибка load_model: {e}")
        return False

async def unload_model(host: str, model_name: str) -> bool:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{host}/api/generate",
                                   json={'model': model_name, 'keep_alive': 0},
                                   timeout=10) as resp:
                return resp.status == 200
    except:
        return False

async def chat_with_ollama(host: str, model: str, messages: List[Dict], tools: Optional[List[Dict]] = None) -> Optional[Dict]:
    try:
        payload = {'model': model, 'messages': messages, 'stream': False}
        if tools:
            payload['tools'] = tools
        
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{host}/api/chat", 
                                   json=payload, 
                                   timeout=aiohttp.ClientTimeout(total=180)) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    print(f"Ошибка chat: status {resp.status}")
    except Exception as e:
        print(f"Ошибка chat_with_ollama: {e}")
    return None

async def translate_text(host: str, translator_model: str, text: str, target_lang: str) -> str:
    if not translator_model:
        return text
    
    system_prompt = '''You are a professional translator. Input is a JSON object where the key is the target language code and the value is the source text. Translate the text accurately, preserving meaning and nuances, following the target language's grammar and cultural norms. Output ONLY the translated text, with no explanations, comments, or formatting.'''
    
    json_input = json.dumps({target_lang: text})
    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': json_input}
    ]
    
    response = await chat_with_ollama(host, translator_model, messages)
    if response and 'message' in response:
        return response['message']['content'].strip()
    return text

TOOLS = [
    {
        'type': 'function',
        'function': {
            'name': 'rename_chat',
            'description': 'Rename the current chat to better reflect its content',
            'parameters': {
                'type': 'object',
                'properties': {
                    'new_name': {
                        'type': 'string',
                        'description': 'The new name for the chat'
                    }
                },
                'required': ['new_name']
            }
        }
    },
    {
        'type': 'function',
        'function': {
            'name': 'calculator',
            'description': 'Perform mathematical calculations',
            'parameters': {
                'type': 'object',
                'properties': {
                    'expression': {
                        'type': 'string',
                        'description': 'Mathematical expression to evaluate'
                    }
                },
                'required': ['expression']
            }
        }
    }
]

def execute_tool(tool_name: str, arguments: Dict) -> str:
    if tool_name == 'calculator':
        try:
            result = eval(arguments['expression'], {"__builtins__": {}}, {})
            return str(result)
        except:
            return "Ошибка вычисления"
    return ""

@dp.message(CommandStart())
async def start_handler(message: types.Message, state: FSMContext):
    user = db.get_user(message.from_user.id)
    
    if not user or not user['host']:
        await message.answer(t(message.from_user.id, 'welcome'))
        await state.set_state(States.waiting_host)
    else:
        await show_main_menu(message)

@dp.message(States.waiting_host)
async def host_input_handler(message: types.Message, state: FSMContext):
    host = message.text.strip()
    
    if not re.match(r'^https?://[\w\.\-]+:\d+

async def show_main_menu(message: types.Message):
    user = db.get_user(message.from_user.id)
    selected_model = user['selected_model'] if user and user['selected_model'] else t(message.from_user.id, 'no_model')
    
    text = f"{t(message.from_user.id, 'main_menu')}\n{t(message.from_user.id, 'selected_model')}: {selected_model}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(message.from_user.id, 'btn_model_select'), callback_data='select_model')],
        [InlineKeyboardButton(text=t(message.from_user.id, 'btn_new_chat'), callback_data='new_chat')],
        [InlineKeyboardButton(text=t(message.from_user.id, 'btn_chats'), callback_data='chat_list')],
        [InlineKeyboardButton(text=t(message.from_user.id, 'btn_settings'), callback_data='settings')]
    ])
    
    await message.answer(text, reply_markup=keyboard)

@dp.callback_query(F.data == 'select_model')
async def select_model_handler(callback: types.CallbackQuery):
    user = db.get_user(callback.from_user.id)
    models = await get_ollama_models(user['host'])
    
    keyboard = []
    for model in models:
        check = '✓ ' if model == user['selected_model'] else ''
        keyboard.append([InlineKeyboardButton(text=f"{check}{model}", callback_data=f"model_{model}")])
    
    keyboard.append([InlineKeyboardButton(text=t(callback.from_user.id, 'btn_add_model'), callback_data='add_model')])
    keyboard.append([InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='back_main')])
    
    await callback.message.edit_text(
        t(callback.from_user.id, 'model_selection'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith('model_'))
async def model_select_handler(callback: types.CallbackQuery):
    model_name = callback.data.replace('model_', '')
    user = db.get_user(callback.from_user.id)
    
    loading_msg = await callback.message.answer(t(callback.from_user.id, 'loading_model'))
    
    success = await load_model(user['host'], model_name)
    await loading_msg.delete()
    
    if success:
        db.update_user(callback.from_user.id, selected_model=model_name)
        await callback.answer(t(callback.from_user.id, 'model_loaded'))
        
        if callback.from_user.id in user_states and user_states[callback.from_user.id].get('return_to_new_chat'):
            user_states[callback.from_user.id]['return_to_new_chat'] = False
            await create_new_chat(callback.message, callback.from_user.id)
        else:
            await select_model_handler(callback)
    else:
        await callback.answer(t(callback.from_user.id, 'model_load_error'), show_alert=True)

@dp.callback_query(F.data == 'add_model')
async def add_model_handler(callback: types.CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='select_model')]
    ])
    await callback.message.edit_text(t(callback.from_user.id, 'enter_model_name'), reply_markup=keyboard)
    await state.set_state(States.waiting_model_name)
    await callback.answer()

@dp.message(States.waiting_model_name)
async def model_name_input_handler(message: types.Message, state: FSMContext):
    model_name = message.text.strip()
    user = db.get_user(message.from_user.id)
    
    progress_msg = await message.answer(t(message.from_user.id, 'downloading_model') + "\n▱▱▱▱▱▱▱▱▱▱ 0%")
    
    async def update_progress(percent: int, status: str):
        filled = int(percent / 10)
        bar = '▰' * filled + '▱' * (10 - filled)
        await progress_msg.edit_text(f"{status}\n{bar} {percent}%")
    
    success = await pull_model(user['host'], model_name, update_progress)
    
    if success:
        await progress_msg.delete()
        await message.answer(t(message.from_user.id, 'model_downloaded'))
        await state.clear()
        fake_callback = types.CallbackQuery(
            id='fake', from_user=message.from_user, message=message,
            chat_instance='', data='select_model'
        )
        await select_model_handler(fake_callback)
    else:
        await progress_msg.edit_text(t(message.from_user.id, 'model_not_found'))
        await state.clear()

@dp.callback_query(F.data == 'new_chat')
async def new_chat_handler(callback: types.CallbackQuery):
    user = db.get_user(callback.from_user.id)
    
    if not user['selected_model']:
        user_states[callback.from_user.id] = {'return_to_new_chat': True}
        await select_model_handler(callback)
        return
    
    await create_new_chat(callback.message, callback.from_user.id)
    await callback.answer()

async def create_new_chat(message: types.Message, user_id: int):
    user = db.get_user(user_id)
    chat_id = db.create_chat(user_id, t(user_id, 'new_chat_name'), user['selected_model'])
    
    user_states[user_id] = {'current_chat': chat_id}
    
    await message.answer(
        f"{t(user_id, 'chat_with_model')} {user['selected_model']}",
        reply_markup=get_main_keyboard(user_id)
    )

@dp.callback_query(F.data == 'chat_list')
async def chat_list_handler(callback: types.CallbackQuery):
    chats = db.get_user_chats(callback.from_user.id)
    
    if not chats:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_create_chat'), callback_data='new_chat')],
            [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='back_main')]
        ])
        await callback.message.edit_text(t(callback.from_user.id, 'no_chats'), reply_markup=keyboard)
    else:
        keyboard = []
        for chat in chats:
            keyboard.append([InlineKeyboardButton(text=chat['chat_name'], callback_data=f"open_chat_{chat['id']}")])
        keyboard.append([InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='back_main')])
        
        await callback.message.edit_text(t(callback.from_user.id, 'your_chats'), 
                                        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

@dp.callback_query(F.data.startswith('open_chat_'))
async def open_chat_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('open_chat_', ''))
    chat = db.get_chat(chat_id)
    
    text = f"{t(callback.from_user.id, 'chat')}: {chat['chat_name']}\n{t(callback.from_user.id, 'model_in_chat')}: {chat['model']}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_delete_chat'), callback_data=f"delete_chat_{chat_id}")],
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_rename_chat'), callback_data=f"rename_chat_{chat_id}")],
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_continue_chat'), callback_data=f"continue_chat_{chat_id}")],
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='chat_list')]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith('delete_chat_'))
async def delete_chat_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('delete_chat_', ''))
    db.delete_chat(chat_id)
    
    if callback.from_user.id in user_states and user_states[callback.from_user.id].get('current_chat') == chat_id:
        user_states[callback.from_user.id]['current_chat'] = None
    
    await callback.answer(t(callback.from_user.id, 'chat_deleted'))
    await chat_list_handler(callback)

@dp.callback_query(F.data.startswith('rename_chat_'))
async def rename_chat_handler(callback: types.CallbackQuery, state: FSMContext):
    chat_id = int(callback.data.replace('rename_chat_', ''))
    await state.update_data(rename_chat_id=chat_id)
    await state.set_state(States.waiting_chat_rename)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data=f'open_chat_{chat_id}')]
    ])
    await callback.message.edit_text(t(callback.from_user.id, 'enter_new_name'), reply_markup=keyboard)
    await callback.answer()

@dp.message(States.waiting_chat_rename)
async def chat_rename_input_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data.get('rename_chat_id')
    new_name = message.text.strip()
    
    db.update_chat_name(chat_id, new_name)
    await state.clear()
    await message.answer(t(message.from_user.id, 'chat_renamed'))

@dp.callback_query(F.data.startswith('continue_chat_'))
async def continue_chat_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('continue_chat_', ''))
    user_states[callback.from_user.id] = {'current_chat': chat_id}
    
    chat = db.get_chat(chat_id)
    await callback.message.answer(
        f"{t(callback.from_user.id, 'continuing_chat')} {chat['chat_name']}",
        reply_markup=get_main_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.callback_query(F.data == 'settings')
async def settings_handler(callback: types.CallbackQuery):
    user = db.get_user(callback.from_user.id)
    models = await get_ollama_models(user['host'])
    hosts = db.get_user_hosts(callback.from_user.id)
    
    active_host = next((h for h in hosts if h['is_active']), None)
    host_name = active_host['host_name'] if active_host else user['host']
    
    text = f"""{t(callback.from_user.id, 'settings')}
{t(callback.from_user.id, 'selected_host')}: {host_name}
{t(callback.from_user.id, 'translator_model')}: {user['translator_model'] or t(callback.from_user.id, 'none')}
{t(callback.from_user.id, 'loaded_models')}: {', '.join(models) if models else t(callback.from_user.id, 'none')}
{t(callback.from_user.id, 'selected_model')}: {user['selected_model'] or t(callback.from_user.id, 'none')}"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_manage_hosts'), callback_data='manage_hosts')],
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_select_translator'), callback_data='select_translator')],
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_manage_models'), callback_data='manage_models')],
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_localization'), callback_data='localization')],
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='back_main')]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == 'manage_hosts')
async def manage_hosts_handler(callback: types.CallbackQuery):
    hosts = db.get_user_hosts(callback.from_user.id)
    
    if not hosts:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_add_host'), callback_data='add_host')],
            [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='settings')]
        ])
        await callback.message.edit_text("У вас нет сохраненных хостов", reply_markup=keyboard)
    else:
        text = "📡 Ваши хосты:\n\n"
        keyboard = []
        for host in hosts:
            status = "✓ " if host['is_active'] else ""
            text += f"{status}{host['host_name']}: {host['host_url']}\n"
            keyboard.append([
                InlineKeyboardButton(text=f"{status}{host['host_name']}", callback_data=f"selhost_{host['id']}"),
                InlineKeyboardButton(text="🗑", callback_data=f"delhost_{host['id']}")
            ])
        
        keyboard.append([InlineKeyboardButton(text=t(callback.from_user.id, 'btn_add_host'), callback_data='add_host')])
        keyboard.append([InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='settings')])
        
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

@dp.callback_query(F.data == 'add_host')
async def add_host_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(t(callback.from_user.id, 'enter_new_host'))
    await state.set_state(States.waiting_host)
    await callback.answer()

@dp.callback_query(F.data.startswith('selhost_'))
async def select_host_handler(callback: types.CallbackQuery):
    host_id = int(callback.data.replace('selhost_', ''))
    db.set_active_host(callback.from_user.id, host_id)
    await callback.answer("✅ Хост активирован!")
    await manage_hosts_handler(callback)

@dp.callback_query(F.data.startswith('delhost_'))
async def delete_host_handler(callback: types.CallbackQuery):
    host_id = int(callback.data.replace('delhost_', ''))
    db.delete_host(host_id)
    await callback.answer("🗑 Хост удален")
    await manage_hosts_handler(callback)

@dp.callback_query(F.data == 'change_host')
async def change_host_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(t(callback.from_user.id, 'enter_new_host'))
    await state.set_state(States.waiting_host)
    await callback.answer()

@dp.callback_query(F.data == 'select_translator')
async def select_translator_handler(callback: types.CallbackQuery):
    user = db.get_user(callback.from_user.id)
    models = await get_ollama_models(user['host'])
    
    keyboard = []
    for model in models:
        check = '✓ ' if model == user['translator_model'] else ''
        keyboard.append([InlineKeyboardButton(text=f"{check}{model}", callback_data=f"trans_{model}")])
    
    keyboard.append([InlineKeyboardButton(text=t(callback.from_user.id, 'btn_none'), callback_data='trans_none')])
    keyboard.append([InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='settings')])
    
    await callback.message.edit_text(
        t(callback.from_user.id, 'select_translator_model'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith('trans_'))
async def translator_select_handler(callback: types.CallbackQuery):
    model = callback.data.replace('trans_', '')
    if model == 'none':
        model = None
    
    db.update_user(callback.from_user.id, translator_model=model)
    await callback.answer(t(callback.from_user.id, 'translator_set'))
    await settings_handler(callback)

@dp.callback_query(F.data == 'manage_models')
async def manage_models_handler(callback: types.CallbackQuery):
    user = db.get_user(callback.from_user.id)
    models = await get_ollama_models(user['host'])
    
    keyboard = []
    for model in models:
        keyboard.append([
            InlineKeyboardButton(text=f"📥 {model}", callback_data=f"load_{model}"),
            InlineKeyboardButton(text="📤", callback_data=f"unload_{model}")
        ])
    
    keyboard.append([InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='settings')])
    
    await callback.message.edit_text(
        t(callback.from_user.id, 'manage_models_text'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith('load_'))
async def load_model_handler(callback: types.CallbackQuery):
    model = callback.data.replace('load_', '')
    user = db.get_user(callback.from_user.id)
    
    await callback.answer(t(callback.from_user.id, 'loading_model'))
    success = await load_model(user['host'], model)
    
    if success:
        await callback.message.answer(t(callback.from_user.id, 'model_loaded'))
    else:
        await callback.message.answer(t(callback.from_user.id, 'model_load_error'))

@dp.callback_query(F.data.startswith('unload_'))
async def unload_model_handler(callback: types.CallbackQuery):
    model = callback.data.replace('unload_', '')
    user = db.get_user(callback.from_user.id)
    
    await callback.answer(t(callback.from_user.id, 'unloading_model'))
    success = await unload_model(user['host'], model)
    
    if success:
        await callback.message.answer(t(callback.from_user.id, 'model_unloaded'))
    else:
        await callback.message.answer(t(callback.from_user.id, 'model_unload_error'))

@dp.callback_query(F.data == 'localization')
async def localization_handler(callback: types.CallbackQuery):
    keyboard = []
    for code, lang_info in LANGUAGES.items():
        keyboard.append([InlineKeyboardButton(
            text=f"{lang_info['flag']} {lang_info['name']}", 
            callback_data=f"lang_{code}"
        )])
    
    keyboard.append([InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='settings')])
    
    await callback.message.edit_text(
        t(callback.from_user.id, 'select_language'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith('lang_'))
async def language_select_handler(callback: types.CallbackQuery):
    lang_code = callback.data.replace('lang_', '')
    db.update_user(callback.from_user.id, locale=lang_code)
    await callback.answer(t(callback.from_user.id, 'language_changed'))
    await settings_handler(callback)

@dp.callback_query(F.data == 'back_main')
async def back_main_handler(callback: types.CallbackQuery):
    await callback.message.delete()
    await show_main_menu(callback.message)
    await callback.answer()

async def send_typing_action(chat_id: int):
    while True:
        try:
            await bot.send_chat_action(chat_id, 'typing')
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            break

@dp.callback_query(F.data.startswith('regen_'))
async def regenerate_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('regen_', ''))
    user = db.get_user(callback.from_user.id)
    chat = db.get_chat(chat_id)
    
    messages = db.get_chat_messages(chat_id)[:-1]
    
    typing_task = asyncio.create_task(send_typing_action(callback.message.chat.id))
    response = await chat_with_ollama(user['host'], chat['model'], messages, TOOLS)
    typing_task.cancel()
    
    if response:
        content = response['message']['content']
        if user['translator_model']:
            content = await translate_text(user['host'], user['translator_model'], content, user['locale'])
        
        db.update_last_message(chat_id, response['message']['content'])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=t(callback.from_user.id, 'btn_regenerate'), callback_data=f'regen_{chat_id}'),
                InlineKeyboardButton(text=t(callback.from_user.id, 'btn_modify'), callback_data=f'modify_{chat_id}')
            ]
        ])
        
        await callback.message.edit_text(content, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith('modify_'))
async def modify_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('modify_', ''))
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(callback.from_user.id, 'btn_shorter'), callback_data=f'mod_shorter_{chat_id}'),
            InlineKeyboardButton(text=t(callback.from_user.id, 'btn_longer'), callback_data=f'mod_longer_{chat_id}')
        ],
        [
            InlineKeyboardButton(text=t(callback.from_user.id, 'btn_simpler'), callback_data=f'mod_simpler_{chat_id}'),
            InlineKeyboardButton(text=t(callback.from_user.id, 'btn_complex'), callback_data=f'mod_complex_{chat_id}')
        ],
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_edit_response'), callback_data=f'edit_resp_{chat_id}')],
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data=f'cancel_modify_{chat_id}')]
    ])
    
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer()

async def modify_response(callback: types.CallbackQuery, chat_id: int, modification: str):
    user = db.get_user(callback.from_user.id)
    chat = db.get_chat(chat_id)
    messages = db.get_chat_messages(chat_id)
    
    mod_prompt = {
        'shorter': 'Make your previous response shorter and more concise.',
        'longer': 'Expand your previous response with more details.',
        'simpler': 'Simplify your previous response for easier understanding.',
        'complex': 'Make your previous response more detailed and sophisticated.'
    }
    
    messages.append({'role': 'user', 'content': mod_prompt[modification]})
    
    typing_task = asyncio.create_task(send_typing_action(callback.message.chat.id))
    response = await chat_with_ollama(user['host'], chat['model'], messages, TOOLS)
    typing_task.cancel()
    
    if response:
        content = response['message']['content']
        if user['translator_model']:
            content = await translate_text(user['host'], user['translator_model'], content, user['locale'])
        
        db.update_last_message(chat_id, response['message']['content'])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=t(callback.from_user.id, 'btn_regenerate'), callback_data=f'regen_{chat_id}'),
                InlineKeyboardButton(text=t(callback.from_user.id, 'btn_modify'), callback_data=f'modify_{chat_id}')
            ]
        ])
        
        await callback.message.edit_text(content, reply_markup=keyboard)

@dp.callback_query(F.data.startswith('mod_shorter_'))
async def mod_shorter_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('mod_shorter_', ''))
    await modify_response(callback, chat_id, 'shorter')
    await callback.answer()

@dp.callback_query(F.data.startswith('mod_longer_'))
async def mod_longer_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('mod_longer_', ''))
    await modify_response(callback, chat_id, 'longer')
    await callback.answer()

@dp.callback_query(F.data.startswith('mod_simpler_'))
async def mod_simpler_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('mod_simpler_', ''))
    await modify_response(callback, chat_id, 'simpler')
    await callback.answer()

@dp.callback_query(F.data.startswith('mod_complex_'))
async def mod_complex_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('mod_complex_', ''))
    await modify_response(callback, chat_id, 'complex')
    await callback.answer()

@dp.callback_query(F.data.startswith('edit_resp_'))
async def edit_response_handler(callback: types.CallbackQuery, state: FSMContext):
    chat_id = int(callback.data.replace('edit_resp_', ''))
    await state.update_data(edit_chat_id=chat_id)
    await state.set_state(States.waiting_response_edit)
    
    await callback.message.answer(t(callback.from_user.id, 'enter_new_response'))
    await callback.answer()

@dp.message(States.waiting_response_edit)
async def response_edit_input_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data.get('edit_chat_id')
    
    db.update_last_message(chat_id, message.text)
    await state.clear()
    await message.answer(t(message.from_user.id, 'response_updated'))

@dp.callback_query(F.data.startswith('cancel_modify_'))
async def cancel_modify_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('cancel_modify_', ''))
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(callback.from_user.id, 'btn_regenerate'), callback_data=f'regen_{chat_id}'),
            InlineKeyboardButton(text=t(callback.from_user.id, 'btn_modify'), callback_data=f'modify_{chat_id}')
        ]
    ])
    
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer()

@dp.inline_query()
async def inline_query_handler(inline_query: types.InlineQuery):
    user = db.get_user(inline_query.from_user.id)
    
    if not user or not user['selected_model']:
        results = [
            InlineQueryResultArticle(
                id='no_model',
                title=t(inline_query.from_user.id, 'no_model_selected'),
                input_message_content=InputTextMessageContent(
                    message_text=t(inline_query.from_user.id, 'please_select_model_inline')
                )
            )
        ]
        await inline_query.answer(results, cache_time=1)
        return
    
    query = inline_query.query.strip()
    if not query:
        await inline_query.answer([], cache_time=1)
        return
    
    results = [
        InlineQueryResultArticle(
            id='answer',
            title=t(inline_query.from_user.id, 'inline_answer'),
            description=t(inline_query.from_user.id, 'inline_answer_desc'),
            input_message_content=InputTextMessageContent(message_text='⏳'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text='⏳', callback_data=f'inline_answer_{query}')
            ]])
        ),
        InlineQueryResultArticle(
            id='translate',
            title=t(inline_query.from_user.id, 'inline_translate'),
            description=t(inline_query.from_user.id, 'inline_translate_desc'),
            input_message_content=InputTextMessageContent(message_text='⏳'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text='⏳', callback_data=f'inline_translate_{query}')
            ]])
        )
    ]
    
    await inline_query.answer(results, cache_time=1)

@dp.callback_query(F.data.startswith('inline_answer_'))
async def inline_answer_handler(callback: types.CallbackQuery):
    query = callback.data.replace('inline_answer_', '')
    user = db.get_user(callback.from_user.id)
    
    messages = [{'role': 'user', 'content': query}]
    response = await chat_with_ollama(user['host'], user['selected_model'], messages)
    
    if response:
        content = response['message']['content']
        if user['translator_model']:
            content = await translate_text(user['host'], user['translator_model'], content, user['locale'])
        await callback.message.edit_text(content)
    else:
        await callback.message.edit_text(t(callback.from_user.id, 'error_generating'))
    
    await callback.answer()

@dp.callback_query(F.data.startswith('inline_translate_'))
async def inline_translate_handler(callback: types.CallbackQuery):
    query = callback.data.replace('inline_translate_', '')
    user = db.get_user(callback.from_user.id)
    
    if not user['translator_model']:
        await callback.message.edit_text(t(callback.from_user.id, 'no_translator'))
        await callback.answer()
        return
    
    system_prompt = '''You are a professional translator. Input is a JSON object where the key is the target language code and the value is the source text. Translate the text accurately, preserving meaning and nuances, following the target language's grammar and cultural norms. Output ONLY the translated text, with no explanations, comments, or formatting.'''
    
    json_input = json.dumps({user['locale']: query})
    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': json_input}
    ]
    
    response = await chat_with_ollama(user['host'], user['translator_model'], messages)
    
    if response:
        content = response['message']['content'].strip()
        await callback.message.edit_text(content)
    else:
        await callback.message.edit_text(t(callback.from_user.id, 'error_translating'))
    
    await callback.answer()

@dp.message(F.text)
async def text_message_handler(message: types.Message):
    text = message.text
    user_id = message.from_user.id
    
    # Check if it's a keyboard button
    if text == t(user_id, 'btn_model_select'):
        fake_callback = types.CallbackQuery(
            id='fake', from_user=message.from_user, message=message,
            chat_instance='', data='select_model'
        )
        await select_model_handler(fake_callback)
        return
    
    if text == t(user_id, 'btn_chats'):
        fake_callback = types.CallbackQuery(
            id='fake', from_user=message.from_user, message=message,
            chat_instance='', data='chat_list'
        )
        await chat_list_handler(fake_callback)
        return
    
    if text == t(user_id, 'btn_settings'):
        fake_callback = types.CallbackQuery(
            id='fake', from_user=message.from_user, message=message,
            chat_instance='', data='settings'
        )
        await settings_handler(fake_callback)
        return
    
    # Process as regular user message
    user = db.get_user(message.from_user.id)
    
    if not user or not user['selected_model']:
        await message.answer(t(message.from_user.id, 'please_select_model'))
        return
    
    if message.from_user.id not in user_states or not user_states[message.from_user.id].get('current_chat'):
        chat_id = db.create_chat(message.from_user.id, t(message.from_user.id, 'new_chat_name'), user['selected_model'])
        user_states[message.from_user.id] = {'current_chat': chat_id}
    
    chat_id = user_states[message.from_user.id]['current_chat']
    chat = db.get_chat(chat_id)
    
    user_text = message.text
    if user['translator_model']:
        user_text = await translate_text(user['host'], user['translator_model'], message.text, 'en')
    
    db.add_message(chat_id, 'user', user_text)
    
    typing_task = asyncio.create_task(send_typing_action(message.chat.id))
    
    messages = db.get_chat_messages(chat_id)
    response = await chat_with_ollama(user['host'], chat['model'], messages, TOOLS)
    
    typing_task.cancel()
    
    if not response:
        await message.answer(t(message.from_user.id, 'error_generating'))
        return
    
    assistant_message = response['message']
    tool_notes = []
    
    if 'tool_calls' in assistant_message:
        for tool_call in assistant_message['tool_calls']:
            func_name = tool_call['function']['name']
            func_args = tool_call['function']['arguments']
            
            if func_name == 'rename_chat':
                old_name = chat['chat_name']
                new_name = func_args['new_name']
                db.update_chat_name(chat_id, new_name)
                tool_notes.append(f"(ИИ изменил имя чата: \"{old_name}\" → \"{new_name}\")")
            elif func_name == 'calculator':
                result = execute_tool(func_name, func_args)
                messages.append({'role': 'assistant', 'content': '', 'tool_calls': assistant_message['tool_calls']})
                messages.append({'role': 'tool', 'content': result})
                response = await chat_with_ollama(user['host'], chat['model'], messages)
                if response:
                    assistant_message = response['message']
    
    content = assistant_message['content']
    
    if user['translator_model'] and content:
        content = await translate_text(user['host'], user['translator_model'], content, user['locale'])
    
    db.add_message(chat_id, 'assistant', assistant_message['content'])
    
    full_text = content
    if tool_notes:
        full_text += '\n\n' + '\n'.join(tool_notes)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(message.from_user.id, 'btn_regenerate'), callback_data=f'regen_{chat_id}'),
            InlineKeyboardButton(text=t(message.from_user.id, 'btn_modify'), callback_data=f'modify_{chat_id}')
        ]
    ])
    
    await message.answer(full_text, reply_markup=keyboard)

async def main():
    print("🤖 Ollama Telegram Bot запущен!")
    print("📊 Ожидание сообщений...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main()), host):
        await message.answer(t(message.from_user.id, 'invalid_host'))
        return
    
    # Проверка подключения
    checking_msg = await message.answer("🔍 Проверка подключения к серверу...")
    is_connected = await check_ollama_connection(host)
    await checking_msg.delete()
    
    if not is_connected:
        await message.answer("❌ Не удалось подключиться к серверу. Проверьте:\n• Правильность адреса\n• Доступность сервера\n• Запущен ли Ollama")
        return
    
    # Запрос имени хоста
    await state.update_data(host_url=host)
    await state.set_state(States.waiting_host_name)
    await message.answer("✅ Сервер доступен!\n\nВведите название для этого хоста (например: 'Домашний сервер', 'VPS', 'Локальный'):")

@dp.message(States.waiting_host_name)
async def host_name_input_handler(message: types.Message, state: FSMContext):
    host_name = message.text.strip()
    data = await state.get_data()
    host_url = data.get('host_url')
    
    user = db.get_user(message.from_user.id)
    if not user:
        db.create_user(message.from_user.id, host_url)
    
    db.add_host(message.from_user.id, host_url, host_name)
    await state.clear()
    await message.answer(f"✅ Хост '{host_name}' успешно добавлен и активирован!", reply_markup=get_main_keyboard(message.from_user.id))
    await show_main_menu(message)

async def show_main_menu(message: types.Message):
    user = db.get_user(message.from_user.id)
    selected_model = user['selected_model'] if user and user['selected_model'] else t(message.from_user.id, 'no_model')
    
    text = f"{t(message.from_user.id, 'main_menu')}\n{t(message.from_user.id, 'selected_model')}: {selected_model}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(message.from_user.id, 'btn_model_select'), callback_data='select_model')],
        [InlineKeyboardButton(text=t(message.from_user.id, 'btn_new_chat'), callback_data='new_chat')],
        [InlineKeyboardButton(text=t(message.from_user.id, 'btn_chats'), callback_data='chat_list')],
        [InlineKeyboardButton(text=t(message.from_user.id, 'btn_settings'), callback_data='settings')]
    ])
    
    await message.answer(text, reply_markup=keyboard)

@dp.callback_query(F.data == 'select_model')
async def select_model_handler(callback: types.CallbackQuery):
    user = db.get_user(callback.from_user.id)
    models = await get_ollama_models(user['host'])
    
    keyboard = []
    for model in models:
        check = '✓ ' if model == user['selected_model'] else ''
        keyboard.append([InlineKeyboardButton(text=f"{check}{model}", callback_data=f"model_{model}")])
    
    keyboard.append([InlineKeyboardButton(text=t(callback.from_user.id, 'btn_add_model'), callback_data='add_model')])
    keyboard.append([InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='back_main')])
    
    await callback.message.edit_text(
        t(callback.from_user.id, 'model_selection'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith('model_'))
async def model_select_handler(callback: types.CallbackQuery):
    model_name = callback.data.replace('model_', '')
    user = db.get_user(callback.from_user.id)
    
    loading_msg = await callback.message.answer(t(callback.from_user.id, 'loading_model'))
    
    success = await load_model(user['host'], model_name)
    await loading_msg.delete()
    
    if success:
        db.update_user(callback.from_user.id, selected_model=model_name)
        await callback.answer(t(callback.from_user.id, 'model_loaded'))
        
        if callback.from_user.id in user_states and user_states[callback.from_user.id].get('return_to_new_chat'):
            user_states[callback.from_user.id]['return_to_new_chat'] = False
            await create_new_chat(callback.message, callback.from_user.id)
        else:
            await select_model_handler(callback)
    else:
        await callback.answer(t(callback.from_user.id, 'model_load_error'), show_alert=True)

@dp.callback_query(F.data == 'add_model')
async def add_model_handler(callback: types.CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='select_model')]
    ])
    await callback.message.edit_text(t(callback.from_user.id, 'enter_model_name'), reply_markup=keyboard)
    await state.set_state(States.waiting_model_name)
    await callback.answer()

@dp.message(States.waiting_model_name)
async def model_name_input_handler(message: types.Message, state: FSMContext):
    model_name = message.text.strip()
    user = db.get_user(message.from_user.id)
    
    progress_msg = await message.answer(t(message.from_user.id, 'downloading_model') + "\n▱▱▱▱▱▱▱▱▱▱ 0%")
    
    async def update_progress(percent: int, status: str):
        filled = int(percent / 10)
        bar = '▰' * filled + '▱' * (10 - filled)
        await progress_msg.edit_text(f"{status}\n{bar} {percent}%")
    
    success = await pull_model(user['host'], model_name, update_progress)
    
    if success:
        await progress_msg.delete()
        await message.answer(t(message.from_user.id, 'model_downloaded'))
        await state.clear()
        fake_callback = types.CallbackQuery(
            id='fake', from_user=message.from_user, message=message,
            chat_instance='', data='select_model'
        )
        await select_model_handler(fake_callback)
    else:
        await progress_msg.edit_text(t(message.from_user.id, 'model_not_found'))
        await state.clear()

@dp.callback_query(F.data == 'new_chat')
async def new_chat_handler(callback: types.CallbackQuery):
    user = db.get_user(callback.from_user.id)
    
    if not user['selected_model']:
        user_states[callback.from_user.id] = {'return_to_new_chat': True}
        await select_model_handler(callback)
        return
    
    await create_new_chat(callback.message, callback.from_user.id)
    await callback.answer()

async def create_new_chat(message: types.Message, user_id: int):
    user = db.get_user(user_id)
    chat_id = db.create_chat(user_id, t(user_id, 'new_chat_name'), user['selected_model'])
    
    user_states[user_id] = {'current_chat': chat_id}
    
    await message.answer(
        f"{t(user_id, 'chat_with_model')} {user['selected_model']}",
        reply_markup=get_main_keyboard(user_id)
    )

@dp.callback_query(F.data == 'chat_list')
async def chat_list_handler(callback: types.CallbackQuery):
    chats = db.get_user_chats(callback.from_user.id)
    
    if not chats:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_create_chat'), callback_data='new_chat')],
            [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='back_main')]
        ])
        await callback.message.edit_text(t(callback.from_user.id, 'no_chats'), reply_markup=keyboard)
    else:
        keyboard = []
        for chat in chats:
            keyboard.append([InlineKeyboardButton(text=chat['chat_name'], callback_data=f"open_chat_{chat['id']}")])
        keyboard.append([InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='back_main')])
        
        await callback.message.edit_text(t(callback.from_user.id, 'your_chats'), 
                                        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
    await callback.answer()

@dp.callback_query(F.data.startswith('open_chat_'))
async def open_chat_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('open_chat_', ''))
    chat = db.get_chat(chat_id)
    
    text = f"{t(callback.from_user.id, 'chat')}: {chat['chat_name']}\n{t(callback.from_user.id, 'model_in_chat')}: {chat['model']}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_delete_chat'), callback_data=f"delete_chat_{chat_id}")],
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_rename_chat'), callback_data=f"rename_chat_{chat_id}")],
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_continue_chat'), callback_data=f"continue_chat_{chat_id}")],
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='chat_list')]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith('delete_chat_'))
async def delete_chat_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('delete_chat_', ''))
    db.delete_chat(chat_id)
    
    if callback.from_user.id in user_states and user_states[callback.from_user.id].get('current_chat') == chat_id:
        user_states[callback.from_user.id]['current_chat'] = None
    
    await callback.answer(t(callback.from_user.id, 'chat_deleted'))
    await chat_list_handler(callback)

@dp.callback_query(F.data.startswith('rename_chat_'))
async def rename_chat_handler(callback: types.CallbackQuery, state: FSMContext):
    chat_id = int(callback.data.replace('rename_chat_', ''))
    await state.update_data(rename_chat_id=chat_id)
    await state.set_state(States.waiting_chat_rename)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data=f'open_chat_{chat_id}')]
    ])
    await callback.message.edit_text(t(callback.from_user.id, 'enter_new_name'), reply_markup=keyboard)
    await callback.answer()

@dp.message(States.waiting_chat_rename)
async def chat_rename_input_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data.get('rename_chat_id')
    new_name = message.text.strip()
    
    db.update_chat_name(chat_id, new_name)
    await state.clear()
    await message.answer(t(message.from_user.id, 'chat_renamed'))

@dp.callback_query(F.data.startswith('continue_chat_'))
async def continue_chat_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('continue_chat_', ''))
    user_states[callback.from_user.id] = {'current_chat': chat_id}
    
    chat = db.get_chat(chat_id)
    await callback.message.answer(
        f"{t(callback.from_user.id, 'continuing_chat')} {chat['chat_name']}",
        reply_markup=get_main_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.callback_query(F.data == 'settings')
async def settings_handler(callback: types.CallbackQuery):
    user = db.get_user(callback.from_user.id)
    models = await get_ollama_models(user['host'])
    
    text = f"""{t(callback.from_user.id, 'settings')}
{t(callback.from_user.id, 'selected_host')}: {user['host']}
{t(callback.from_user.id, 'translator_model')}: {user['translator_model'] or t(callback.from_user.id, 'none')}
{t(callback.from_user.id, 'loaded_models')}: {', '.join(models) if models else t(callback.from_user.id, 'none')}
{t(callback.from_user.id, 'selected_model')}: {user['selected_model'] or t(callback.from_user.id, 'none')}"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_change_host'), callback_data='change_host')],
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_select_translator'), callback_data='select_translator')],
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_manage_models'), callback_data='manage_models')],
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_localization'), callback_data='localization')],
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='back_main')]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data == 'change_host')
async def change_host_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(t(callback.from_user.id, 'enter_new_host'))
    await state.set_state(States.waiting_host)
    await callback.answer()

@dp.callback_query(F.data == 'select_translator')
async def select_translator_handler(callback: types.CallbackQuery):
    user = db.get_user(callback.from_user.id)
    models = await get_ollama_models(user['host'])
    
    keyboard = []
    for model in models:
        check = '✓ ' if model == user['translator_model'] else ''
        keyboard.append([InlineKeyboardButton(text=f"{check}{model}", callback_data=f"trans_{model}")])
    
    keyboard.append([InlineKeyboardButton(text=t(callback.from_user.id, 'btn_none'), callback_data='trans_none')])
    keyboard.append([InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='settings')])
    
    await callback.message.edit_text(
        t(callback.from_user.id, 'select_translator_model'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith('trans_'))
async def translator_select_handler(callback: types.CallbackQuery):
    model = callback.data.replace('trans_', '')
    if model == 'none':
        model = None
    
    db.update_user(callback.from_user.id, translator_model=model)
    await callback.answer(t(callback.from_user.id, 'translator_set'))
    await settings_handler(callback)

@dp.callback_query(F.data == 'manage_models')
async def manage_models_handler(callback: types.CallbackQuery):
    user = db.get_user(callback.from_user.id)
    models = await get_ollama_models(user['host'])
    
    keyboard = []
    for model in models:
        keyboard.append([
            InlineKeyboardButton(text=f"📥 {model}", callback_data=f"load_{model}"),
            InlineKeyboardButton(text="📤", callback_data=f"unload_{model}")
        ])
    
    keyboard.append([InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='settings')])
    
    await callback.message.edit_text(
        t(callback.from_user.id, 'manage_models_text'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith('load_'))
async def load_model_handler(callback: types.CallbackQuery):
    model = callback.data.replace('load_', '')
    user = db.get_user(callback.from_user.id)
    
    await callback.answer(t(callback.from_user.id, 'loading_model'))
    success = await load_model(user['host'], model)
    
    if success:
        await callback.message.answer(t(callback.from_user.id, 'model_loaded'))
    else:
        await callback.message.answer(t(callback.from_user.id, 'model_load_error'))

@dp.callback_query(F.data.startswith('unload_'))
async def unload_model_handler(callback: types.CallbackQuery):
    model = callback.data.replace('unload_', '')
    user = db.get_user(callback.from_user.id)
    
    await callback.answer(t(callback.from_user.id, 'unloading_model'))
    success = await unload_model(user['host'], model)
    
    if success:
        await callback.message.answer(t(callback.from_user.id, 'model_unloaded'))
    else:
        await callback.message.answer(t(callback.from_user.id, 'model_unload_error'))

@dp.callback_query(F.data == 'localization')
async def localization_handler(callback: types.CallbackQuery):
    keyboard = []
    for code, lang_info in LANGUAGES.items():
        keyboard.append([InlineKeyboardButton(
            text=f"{lang_info['flag']} {lang_info['name']}", 
            callback_data=f"lang_{code}"
        )])
    
    keyboard.append([InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data='settings')])
    
    await callback.message.edit_text(
        t(callback.from_user.id, 'select_language'),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith('lang_'))
async def language_select_handler(callback: types.CallbackQuery):
    lang_code = callback.data.replace('lang_', '')
    db.update_user(callback.from_user.id, locale=lang_code)
    await callback.answer(t(callback.from_user.id, 'language_changed'))
    await settings_handler(callback)

@dp.callback_query(F.data == 'back_main')
async def back_main_handler(callback: types.CallbackQuery):
    await callback.message.delete()
    await show_main_menu(callback.message)
    await callback.answer()

async def send_typing_action(chat_id: int):
    while True:
        try:
            await bot.send_chat_action(chat_id, 'typing')
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            break

@dp.callback_query(F.data.startswith('regen_'))
async def regenerate_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('regen_', ''))
    user = db.get_user(callback.from_user.id)
    chat = db.get_chat(chat_id)
    
    messages = db.get_chat_messages(chat_id)[:-1]
    
    typing_task = asyncio.create_task(send_typing_action(callback.message.chat.id))
    response = await chat_with_ollama(user['host'], chat['model'], messages, TOOLS)
    typing_task.cancel()
    
    if response:
        content = response['message']['content']
        if user['translator_model']:
            content = await translate_text(user['host'], user['translator_model'], content, user['locale'])
        
        db.update_last_message(chat_id, response['message']['content'])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=t(callback.from_user.id, 'btn_regenerate'), callback_data=f'regen_{chat_id}'),
                InlineKeyboardButton(text=t(callback.from_user.id, 'btn_modify'), callback_data=f'modify_{chat_id}')
            ]
        ])
        
        await callback.message.edit_text(content, reply_markup=keyboard)
    await callback.answer()

@dp.callback_query(F.data.startswith('modify_'))
async def modify_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('modify_', ''))
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(callback.from_user.id, 'btn_shorter'), callback_data=f'mod_shorter_{chat_id}'),
            InlineKeyboardButton(text=t(callback.from_user.id, 'btn_longer'), callback_data=f'mod_longer_{chat_id}')
        ],
        [
            InlineKeyboardButton(text=t(callback.from_user.id, 'btn_simpler'), callback_data=f'mod_simpler_{chat_id}'),
            InlineKeyboardButton(text=t(callback.from_user.id, 'btn_complex'), callback_data=f'mod_complex_{chat_id}')
        ],
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_edit_response'), callback_data=f'edit_resp_{chat_id}')],
        [InlineKeyboardButton(text=t(callback.from_user.id, 'btn_back'), callback_data=f'cancel_modify_{chat_id}')]
    ])
    
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer()

async def modify_response(callback: types.CallbackQuery, chat_id: int, modification: str):
    user = db.get_user(callback.from_user.id)
    chat = db.get_chat(chat_id)
    messages = db.get_chat_messages(chat_id)
    
    mod_prompt = {
        'shorter': 'Make your previous response shorter and more concise.',
        'longer': 'Expand your previous response with more details.',
        'simpler': 'Simplify your previous response for easier understanding.',
        'complex': 'Make your previous response more detailed and sophisticated.'
    }
    
    messages.append({'role': 'user', 'content': mod_prompt[modification]})
    
    typing_task = asyncio.create_task(send_typing_action(callback.message.chat.id))
    response = await chat_with_ollama(user['host'], chat['model'], messages, TOOLS)
    typing_task.cancel()
    
    if response:
        content = response['message']['content']
        if user['translator_model']:
            content = await translate_text(user['host'], user['translator_model'], content, user['locale'])
        
        db.update_last_message(chat_id, response['message']['content'])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=t(callback.from_user.id, 'btn_regenerate'), callback_data=f'regen_{chat_id}'),
                InlineKeyboardButton(text=t(callback.from_user.id, 'btn_modify'), callback_data=f'modify_{chat_id}')
            ]
        ])
        
        await callback.message.edit_text(content, reply_markup=keyboard)

@dp.callback_query(F.data.startswith('mod_shorter_'))
async def mod_shorter_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('mod_shorter_', ''))
    await modify_response(callback, chat_id, 'shorter')
    await callback.answer()

@dp.callback_query(F.data.startswith('mod_longer_'))
async def mod_longer_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('mod_longer_', ''))
    await modify_response(callback, chat_id, 'longer')
    await callback.answer()

@dp.callback_query(F.data.startswith('mod_simpler_'))
async def mod_simpler_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('mod_simpler_', ''))
    await modify_response(callback, chat_id, 'simpler')
    await callback.answer()

@dp.callback_query(F.data.startswith('mod_complex_'))
async def mod_complex_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('mod_complex_', ''))
    await modify_response(callback, chat_id, 'complex')
    await callback.answer()

@dp.callback_query(F.data.startswith('edit_resp_'))
async def edit_response_handler(callback: types.CallbackQuery, state: FSMContext):
    chat_id = int(callback.data.replace('edit_resp_', ''))
    await state.update_data(edit_chat_id=chat_id)
    await state.set_state(States.waiting_response_edit)
    
    await callback.message.answer(t(callback.from_user.id, 'enter_new_response'))
    await callback.answer()

@dp.message(States.waiting_response_edit)
async def response_edit_input_handler(message: types.Message, state: FSMContext):
    data = await state.get_data()
    chat_id = data.get('edit_chat_id')
    
    db.update_last_message(chat_id, message.text)
    await state.clear()
    await message.answer(t(message.from_user.id, 'response_updated'))

@dp.callback_query(F.data.startswith('cancel_modify_'))
async def cancel_modify_handler(callback: types.CallbackQuery):
    chat_id = int(callback.data.replace('cancel_modify_', ''))
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(callback.from_user.id, 'btn_regenerate'), callback_data=f'regen_{chat_id}'),
            InlineKeyboardButton(text=t(callback.from_user.id, 'btn_modify'), callback_data=f'modify_{chat_id}')
        ]
    ])
    
    await callback.message.edit_reply_markup(reply_markup=keyboard)
    await callback.answer()

@dp.inline_query()
async def inline_query_handler(inline_query: types.InlineQuery):
    user = db.get_user(inline_query.from_user.id)
    
    if not user or not user['selected_model']:
        results = [
            InlineQueryResultArticle(
                id='no_model',
                title=t(inline_query.from_user.id, 'no_model_selected'),
                input_message_content=InputTextMessageContent(
                    message_text=t(inline_query.from_user.id, 'please_select_model_inline')
                )
            )
        ]
        await inline_query.answer(results, cache_time=1)
        return
    
    query = inline_query.query.strip()
    if not query:
        await inline_query.answer([], cache_time=1)
        return
    
    results = [
        InlineQueryResultArticle(
            id='answer',
            title=t(inline_query.from_user.id, 'inline_answer'),
            description=t(inline_query.from_user.id, 'inline_answer_desc'),
            input_message_content=InputTextMessageContent(message_text='⏳'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text='⏳', callback_data=f'inline_answer_{query}')
            ]])
        ),
        InlineQueryResultArticle(
            id='translate',
            title=t(inline_query.from_user.id, 'inline_translate'),
            description=t(inline_query.from_user.id, 'inline_translate_desc'),
            input_message_content=InputTextMessageContent(message_text='⏳'),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text='⏳', callback_data=f'inline_translate_{query}')
            ]])
        )
    ]
    
    await inline_query.answer(results, cache_time=1)

@dp.callback_query(F.data.startswith('inline_answer_'))
async def inline_answer_handler(callback: types.CallbackQuery):
    query = callback.data.replace('inline_answer_', '')
    user = db.get_user(callback.from_user.id)
    
    messages = [{'role': 'user', 'content': query}]
    response = await chat_with_ollama(user['host'], user['selected_model'], messages)
    
    if response:
        content = response['message']['content']
        if user['translator_model']:
            content = await translate_text(user['host'], user['translator_model'], content, user['locale'])
        await callback.message.edit_text(content)
    else:
        await callback.message.edit_text(t(callback.from_user.id, 'error_generating'))
    
    await callback.answer()

@dp.callback_query(F.data.startswith('inline_translate_'))
async def inline_translate_handler(callback: types.CallbackQuery):
    query = callback.data.replace('inline_translate_', '')
    user = db.get_user(callback.from_user.id)
    
    if not user['translator_model']:
        await callback.message.edit_text(t(callback.from_user.id, 'no_translator'))
        await callback.answer()
        return
    
    system_prompt = '''You are a professional translator. Input is a JSON object where the key is the target language code and the value is the source text. Translate the text accurately, preserving meaning and nuances, following the target language's grammar and cultural norms. Output ONLY the translated text, with no explanations, comments, or formatting.'''
    
    json_input = json.dumps({user['locale']: query})
    messages = [
        {'role': 'system', 'content': system_prompt},
        {'role': 'user', 'content': json_input}
    ]
    
    response = await chat_with_ollama(user['host'], user['translator_model'], messages)
    
    if response:
        content = response['message']['content'].strip()
        await callback.message.edit_text(content)
    else:
        await callback.message.edit_text(t(callback.from_user.id, 'error_translating'))
    
    await callback.answer()

@dp.message(F.text)
async def text_message_handler(message: types.Message):
    text = message.text
    user_id = message.from_user.id
    
    # Check if it's a keyboard button
    if text == t(user_id, 'btn_model_select'):
        fake_callback = types.CallbackQuery(
            id='fake', from_user=message.from_user, message=message,
            chat_instance='', data='select_model'
        )
        await select_model_handler(fake_callback)
        return
    
    if text == t(user_id, 'btn_chats'):
        fake_callback = types.CallbackQuery(
            id='fake', from_user=message.from_user, message=message,
            chat_instance='', data='chat_list'
        )
        await chat_list_handler(fake_callback)
        return
    
    if text == t(user_id, 'btn_settings'):
        fake_callback = types.CallbackQuery(
            id='fake', from_user=message.from_user, message=message,
            chat_instance='', data='settings'
        )
        await settings_handler(fake_callback)
        return
    
    # Process as regular user message
    user = db.get_user(message.from_user.id)
    
    if not user or not user['selected_model']:
        await message.answer(t(message.from_user.id, 'please_select_model'))
        return
    
    if message.from_user.id not in user_states or not user_states[message.from_user.id].get('current_chat'):
        chat_id = db.create_chat(message.from_user.id, t(message.from_user.id, 'new_chat_name'), user['selected_model'])
        user_states[message.from_user.id] = {'current_chat': chat_id}
    
    chat_id = user_states[message.from_user.id]['current_chat']
    chat = db.get_chat(chat_id)
    
    user_text = message.text
    if user['translator_model']:
        user_text = await translate_text(user['host'], user['translator_model'], message.text, 'en')
    
    db.add_message(chat_id, 'user', user_text)
    
    typing_task = asyncio.create_task(send_typing_action(message.chat.id))
    
    messages = db.get_chat_messages(chat_id)
    response = await chat_with_ollama(user['host'], chat['model'], messages, TOOLS)
    
    typing_task.cancel()
    
    if not response:
        await message.answer(t(message.from_user.id, 'error_generating'))
        return
    
    assistant_message = response['message']
    tool_notes = []
    
    if 'tool_calls' in assistant_message:
        for tool_call in assistant_message['tool_calls']:
            func_name = tool_call['function']['name']
            func_args = tool_call['function']['arguments']
            
            if func_name == 'rename_chat':
                old_name = chat['chat_name']
                new_name = func_args['new_name']
                db.update_chat_name(chat_id, new_name)
                tool_notes.append(f"(ИИ изменил имя чата: \"{old_name}\" → \"{new_name}\")")
            elif func_name == 'calculator':
                result = execute_tool(func_name, func_args)
                messages.append({'role': 'assistant', 'content': '', 'tool_calls': assistant_message['tool_calls']})
                messages.append({'role': 'tool', 'content': result})
                response = await chat_with_ollama(user['host'], chat['model'], messages)
                if response:
                    assistant_message = response['message']
    
    content = assistant_message['content']
    
    if user['translator_model'] and content:
        content = await translate_text(user['host'], user['translator_model'], content, user['locale'])
    
    db.add_message(chat_id, 'assistant', assistant_message['content'])
    
    full_text = content
    if tool_notes:
        full_text += '\n\n' + '\n'.join(tool_notes)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=t(message.from_user.id, 'btn_regenerate'), callback_data=f'regen_{chat_id}'),
            InlineKeyboardButton(text=t(message.from_user.id, 'btn_modify'), callback_data=f'modify_{chat_id}')
        ]
    ])
    
    await message.answer(full_text, reply_markup=keyboard)

async def main():
    print("🤖 Ollama Telegram Bot запущен!")
    print("📊 Ожидание сообщений...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
