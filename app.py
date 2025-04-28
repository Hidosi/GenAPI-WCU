from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, login_user, login_required,
    logout_user, current_user, UserMixin
)
from werkzeug.security import generate_password_hash, check_password_hash
from config_loader import ConfigLoader
from genapi_client import GenApiClient
from datetime import datetime
import logging
import requests

app = Flask(__name__)
app.config['SECRET_KEY'] = 'твой_секретный_ключ_замени_на_свой'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('web')

class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    api_key = db.Column(db.String(256), nullable=True)
    chats = db.relationship('Chat', backref='owner', lazy=True)

class Chat(db.Model):
    __tablename__ = 'chats'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    model_name = db.Column(db.String(120), nullable=True)  # Новое поле для модели
    messages = db.relationship('Message', backref='chat', lazy=True, cascade="all, delete-orphan")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id'), nullable=False)
    role = db.Column(db.String(20))
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def find_network_and_model(model_name):
    config = ConfigLoader.load_config()
    for provider_name, provider_info in config.items():
        for network in provider_info.get('networks', []):
            llm_id = network.get('llm_id')
            for model in network.get('models', []):
                if model.get('name') == model_name:
                    return llm_id, model
    return None, None

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/mobile')
@login_required
def mobile():
    return render_template('mobile.html')

@app.route('/login', methods=['GET'])
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    return render_template('index.html')

@app.route('/me')
def me():
    if current_user.is_authenticated:
        return jsonify(authenticated=True, username=current_user.username)
    else:
        return jsonify(authenticated=False)

@app.route('/providers')
@login_required
def providers():
    config = ConfigLoader.load_config()
    providers_data = []

    for provider_name, provider_info in config.items():
        networks = provider_info.get('networks', [])
        models_list = []
        for network in networks:
            llm_id = network.get('llm_id')
            for model in network.get('models', []):
                model_data = {
                    'name': model.get('name'),
                    'title': model.get('title'),
                    'max_tokens': model.get('max_tokens'),
                    'context_window': model.get('context_window'),
                    'input_price': model.get('input_price'),
                    'output_price': model.get('output_price'),
                    'provider': provider_name,
                    'llm_id': llm_id,
                }
                models_list.append(model_data)

        providers_data.append({
            'name': provider_name,
            'description': f'Models from {provider_name}',
            'models': models_list
        })

    return jsonify(providers_data)

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('login')
    password = data.get('password')
    api_key = data.get('api_key')

    if not username or not password or not api_key:
        return jsonify(success=False, error='Логин, пароль и API-ключ обязательны')

    if User.query.filter_by(username=username).first():
        return jsonify(success=False, error='Пользователь уже существует')

    new_user = User(
        username=username,
        password_hash=generate_password_hash(password),
        api_key=api_key
    )
    db.session.add(new_user)
    db.session.commit()
    login_user(new_user)
    return jsonify(success=True)

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('login')
    password = data.get('password')

    if not username or not password:
        return jsonify(success=False, error='Логин и пароль обязательны')

    user = User.query.filter_by(username=username).first()
    if user and check_password_hash(user.password_hash, password):
        login_user(user)
        return jsonify(success=True)
    return jsonify(success=False, error='Неверный логин или пароль')

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return jsonify(success=True)

@app.route('/chat/send', methods=['POST'])
@login_required
def chat_send():
    data = request.json
    model_name = data.get('model_id')  # name модели из config.yaml
    message_text = data.get('message')
    chat_id = data.get('chat_id')

    if not message_text or not model_name:
        return jsonify(success=False, error='Отсутствуют обязательные параметры')

    if not current_user.api_key:
        return jsonify(success=False, error='API-ключ не установлен для пользователя')

    network_id, model = find_network_and_model(model_name)
    if not network_id or not model:
        return jsonify(success=False, error='Модель не найдена в конфигурации')

    if chat_id:
        chat = Chat.query.filter_by(id=chat_id, user_id=current_user.id).first()
        if not chat:
            return jsonify(success=False, error='Чат не найден')
        # Обновляем модель, если изменилась
        if chat.model_name != model_name:
            chat.model_name = model_name
            db.session.commit()
    else:
        chat = Chat(title='Новый чат', user_id=current_user.id, model_name=model_name)
        db.session.add(chat)
        db.session.commit()

    user_message = Message(chat_id=chat.id, role='user', content=message_text)
    db.session.add(user_message)
    db.session.commit()

    messages = Message.query.filter_by(chat_id=chat.id).order_by(Message.created_at).all()
    context = [{'role': m.role, 'content': m.content} for m in messages]

    client = GenApiClient(current_user.api_key)

    max_tokens = model.get('max_tokens', 4096)
    if max_tokens > 4096:
        max_tokens = 4096  # ограничение API

    parameters = {
        # не передаём callback_url, чтобы избежать ошибки 422
        "messages": context,
        "model": model_name,
        "stream": False,
        "n": 1,
        "frequency_penalty": 0,
        "max_tokens": max_tokens,
        "presence_penalty": 0,
        "temperature": 1,
        "top_p": 1,
        "response_format": "{\"type\":\"text\"}"
    }

    try:
        # Создаём задачу
        response = client.create_network_task(network_id, parameters)
        request_id = response.get('request_id')
        if not request_id:
            raise RuntimeError('Не удалось получить request_id от API')

        # Ожидаем результат с polling
        result_response = client.wait_for_result(request_id)
        if not result_response:
            raise RuntimeError('Превышено время ожидания результата')

        # Извлекаем текст ответа
        assistant_text = None
        # Попытка получить текст из разных полей
        if 'result' in result_response:
            res = result_response['result']
            if isinstance(res, list) and len(res) > 0:
                assistant_text = res[0]
            elif isinstance(res, str):
                assistant_text = res
        elif 'output' in result_response:
            assistant_text = result_response['output']
        else:
            assistant_text = "Ответ не получен"

    except Exception as e:
        logger.exception("Ошибка при вызове GenAPI")
        assistant_text = f'Ошибка API: {e}'

    assistant_message = Message(chat_id=chat.id, role='assistant', content=assistant_text)
    db.session.add(assistant_message)
    db.session.commit()

    return jsonify(success=True, message=assistant_text, chat_id=chat.id)

@app.route('/chats', methods=['GET'])
@login_required
def get_chats():
    chats = Chat.query.filter_by(user_id=current_user.id).order_by(Chat.created_at.desc()).all()
    chats_data = [{'id': c.id, 'title': c.title or f'Чат #{c.id}', 'model_name': c.model_name} for c in chats]
    return jsonify(chats_data)

@app.route('/chats/<int:chat_id>/messages', methods=['GET'])
@login_required
def get_chat_messages(chat_id):
    chat = Chat.query.filter_by(id=chat_id, user_id=current_user.id).first()
    if not chat:
        return jsonify(success=False, error='Чат не найден'), 404
    messages = Message.query.filter_by(chat_id=chat.id).order_by(Message.created_at).all()
    messages_data = [{'role': m.role, 'content': m.content} for m in messages]
    return jsonify(success=True, messages=messages_data)

@app.route('/chats/<int:chat_id>', methods=['PUT'])
@login_required
def rename_chat(chat_id):
    data = request.json
    new_title = data.get('title', '').strip()
    if not new_title:
        return jsonify(success=False, error='Название не может быть пустым'), 400
    chat = Chat.query.filter_by(id=chat_id, user_id=current_user.id).first()
    if not chat:
        return jsonify(success=False, error='Чат не найден'), 404
    chat.title = new_title
    db.session.commit()
    return jsonify(success=True, title=new_title)

@app.route('/chats/<int:chat_id>', methods=['DELETE'])
@login_required
def delete_chat(chat_id):
    chat = Chat.query.filter_by(id=chat_id, user_id=current_user.id).first()
    if not chat:
        return jsonify(success=False, error='Чат не найден'), 404
    db.session.delete(chat)
    db.session.commit()
    return jsonify(success=True)

@app.route('/balance', methods=['GET'])
@login_required
def get_balance():
    if not current_user.api_key:
        return jsonify(error='API-ключ не установлен'), 400

    headers = {
        'Authorization': f'Bearer {current_user.api_key}',
        'Accept': 'application/json',
    }
    try:
        response = requests.get('https://api.gen-api.ru/api/v1/user', headers=headers, timeout=10)
        response.raise_for_status()
        user_data = response.json()
        balance = user_data.get('balance', 0.0)
        name = user_data.get('name', current_user.username)
        return jsonify(username=name, balance=round(balance, 2))
    except requests.RequestException as e:
        return jsonify(error=f'Ошибка при получении баланса: {e}'), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5055)