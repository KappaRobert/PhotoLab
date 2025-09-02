from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///photolab.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Создаем необходимые папки
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('templates', exist_ok=True)
os.makedirs('static/css', exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Пожалуйста, войдите в систему для доступа к этой странице.'

# Модели базы данных
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    role = db.Column(db.String(20), default='client')  # client, admin, employee
    phone = db.Column(db.String(20))
    full_name = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    orders = db.relationship('Order', backref='customer', lazy=True)

class Service(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    processing_time = db.Column(db.Integer)  # в часах
    is_active = db.Column(db.Boolean, default=True)
    category = db.Column(db.String(50), default='printing')

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(20), unique=True, nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    service_id = db.Column(db.Integer, db.ForeignKey('service.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, processing, ready, completed, cancelled
    quantity = db.Column(db.Integer, default=1)
    total_price = db.Column(db.Float, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    
    service = db.relationship('Service', backref='orders')
    files = db.relationship('OrderFile', backref='order', lazy=True, cascade='all, delete-orphan')

class OrderFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Утилиты
def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Маршруты
@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role in ['admin', 'employee']:
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('client_dashboard'))
    
    services = Service.query.filter_by(is_active=True).limit(6).all()
    return render_template_string(INDEX_TEMPLATE, services=services)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        phone = request.form.get('phone', '')
        full_name = request.form.get('full_name', '')
        
        # Проверяем существование пользователя
        if User.query.filter_by(username=username).first():
            flash('Пользователь с таким именем уже существует', 'danger')
            return render_template_string(REGISTER_TEMPLATE)
        
        if User.query.filter_by(email=email).first():
            flash('Пользователь с таким email уже существует', 'danger')
            return render_template_string(REGISTER_TEMPLATE)
        
        # Создаем нового пользователя
        user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            phone=phone,
            full_name=full_name
        )
        db.session.add(user)
        db.session.commit()
        
        flash('Регистрация успешна! Войдите в систему.', 'success')
        return redirect(url_for('login'))
    
    return render_template_string(REGISTER_TEMPLATE)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash(f'Добро пожаловать, {user.username}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Неверные учетные данные', 'danger')
    
    return render_template_string(LOGIN_TEMPLATE)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))

@app.route('/client_dashboard')
@login_required
def client_dashboard():
    if current_user.role not in ['client']:
        return redirect(url_for('admin_dashboard'))
    
    orders = Order.query.filter_by(customer_id=current_user.id).order_by(Order.created_at.desc()).all()
    services = Service.query.filter_by(is_active=True).all()
    
    # Статистика для клиента
    total_orders = len(orders)
    pending_orders = len([o for o in orders if o.status == 'pending'])
    ready_orders = len([o for o in orders if o.status == 'ready'])
    
    stats = {
        'total_orders': total_orders,
        'pending_orders': pending_orders,
        'ready_orders': ready_orders
    }
    
    return render_template_string(CLIENT_DASHBOARD_TEMPLATE, orders=orders, services=services, stats=stats)

@app.route('/admin_dashboard')
@login_required
def admin_dashboard():
    if current_user.role not in ['admin', 'employee']:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('client_dashboard'))
    
    orders = Order.query.order_by(Order.created_at.desc()).limit(50).all()
    services = Service.query.all()
    users = User.query.all()
    
    # Статистика
    total_orders = Order.query.count()
    pending_orders = Order.query.filter_by(status='pending').count()
    processing_orders = Order.query.filter_by(status='processing').count()
    ready_orders = Order.query.filter_by(status='ready').count()
    total_revenue = db.session.query(db.func.sum(Order.total_price)).filter_by(status='completed').scalar() or 0
    
    stats = {
        'total_orders': total_orders,
        'pending_orders': pending_orders,
        'processing_orders': processing_orders,
        'ready_orders': ready_orders,
        'total_revenue': total_revenue
    }
    
    return render_template_string(ADMIN_DASHBOARD_TEMPLATE, orders=orders, services=services, users=users, stats=stats)

@app.route('/create_order', methods=['GET', 'POST'])
@login_required
def create_order():
    if request.method == 'POST':
        service_id = request.form['service_id']
        quantity = int(request.form['quantity'])
        notes = request.form.get('notes', '')
        
        service = Service.query.get(service_id)
        if not service:
            flash('Услуга не найдена', 'danger')
            return redirect(url_for('client_dashboard'))
        
        # Генерируем номер заказа
        order_count = Order.query.count()
        order_number = f"PL{datetime.now().strftime('%Y%m%d')}{order_count + 1:04d}"
        
        # Рассчитываем срок выполнения
        due_date = datetime.utcnow() + timedelta(hours=service.processing_time or 24)
        
        order = Order(
            order_number=order_number,
            customer_id=current_user.id,
            service_id=service_id,
            quantity=quantity,
            total_price=service.price * quantity,
            notes=notes,
            due_date=due_date
        )
        
        db.session.add(order)
        db.session.commit()
        
        # Обработка загруженных файлов
        if 'files' in request.files:
            files = request.files.getlist('files')
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    unique_filename = f"{order.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                    file.save(file_path)
                    
                    # Создаем запись в базе
                    order_file = OrderFile(
                        order_id=order.id,
                        filename=unique_filename,
                        original_filename=filename,
                        file_size=os.path.getsize(file_path)
                    )
                    db.session.add(order_file)
            
            db.session.commit()
        
        flash(f'Заказ {order_number} успешно создан!', 'success')
        return redirect(url_for('client_dashboard'))
    
    services = Service.query.filter_by(is_active=True).all()
    return render_template_string(CREATE_ORDER_TEMPLATE, services=services)

@app.route('/order/<int:order_id>')
@login_required
def order_details(order_id):
    order = Order.query.get_or_404(order_id)
    
    # Проверяем права доступа
    if current_user.role == 'client' and order.customer_id != current_user.id:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('client_dashboard'))
    
    return render_template_string(ORDER_DETAILS_TEMPLATE, order=order)

@app.route('/update_order_status/<int:order_id>', methods=['POST'])
@login_required
def update_order_status(order_id):
    if current_user.role not in ['admin', 'employee']:
        return jsonify({'error': 'Доступ запрещен'}), 403
    
    order = Order.query.get_or_404(order_id)
    new_status = request.json.get('status')
    
    if new_status in ['pending', 'processing', 'ready', 'completed', 'cancelled']:
        order.status = new_status
        if new_status == 'completed':
            order.completed_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True, 'message': 'Статус обновлен'})
    
    return jsonify({'error': 'Неверный статус'}), 400

@app.route('/services')
@login_required
def services():
    if current_user.role not in ['admin', 'employee']:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('client_dashboard'))
    
    services = Service.query.all()
    return render_template_string(SERVICES_TEMPLATE, services=services)

@app.route('/create_service', methods=['GET', 'POST'])
@login_required
def create_service():
    if current_user.role != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('client_dashboard'))
    
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        price = float(request.form['price'])
        processing_time = int(request.form['processing_time'])
        category = request.form.get('category', 'printing')
        
        service = Service(
            name=name,
            description=description,
            price=price,
            processing_time=processing_time,
            category=category
        )
        
        db.session.add(service)
        db.session.commit()
        
        flash('Услуга успешно создана!', 'success')
        return redirect(url_for('services'))
    
    return render_template_string(CREATE_SERVICE_TEMPLATE)

@app.route('/edit_service/<int:service_id>', methods=['GET', 'POST'])
@login_required
def edit_service(service_id):
    if current_user.role != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('client_dashboard'))
    
    service = Service.query.get_or_404(service_id)
    
    if request.method == 'POST':
        service.name = request.form['name']
        service.description = request.form['description']
        service.price = float(request.form['price'])
        service.processing_time = int(request.form['processing_time'])
        service.category = request.form.get('category', 'printing')
        service.is_active = 'is_active' in request.form
        
        db.session.commit()
        flash('Услуга обновлена!', 'success')
        return redirect(url_for('services'))
    
    return render_template_string(EDIT_SERVICE_TEMPLATE, service=service)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/api/orders')
@login_required
def api_orders():
    if current_user.role == 'client':
        orders = Order.query.filter_by(customer_id=current_user.id).all()
    else:
        orders = Order.query.all()
    
    orders_data = []
    for order in orders:
        orders_data.append({
            'id': order.id,
            'order_number': order.order_number,
            'customer': order.customer.username,
            'service': order.service.name,
            'status': order.status,
            'quantity': order.quantity,
            'total_price': order.total_price,
            'created_at': order.created_at.strftime('%Y-%m-%d %H:%M'),
            'due_date': order.due_date.strftime('%Y-%m-%d %H:%M') if order.due_date else None
        })
    
    return jsonify(orders_data)

@app.route('/search_orders')
@login_required
def search_orders():
    query = request.args.get('q', '')
    status_filter = request.args.get('status', '')
    
    orders_query = Order.query
    
    if current_user.role == 'client':
        orders_query = orders_query.filter_by(customer_id=current_user.id)
    
    if query:
        orders_query = orders_query.filter(
            db.or_(
                Order.order_number.contains(query),
                Order.notes.contains(query)
            )
        )
    
    if status_filter:
        orders_query = orders_query.filter_by(status=status_filter)
    
    orders = orders_query.order_by(Order.created_at.desc()).all()
    
    return render_template_string(SEARCH_RESULTS_TEMPLATE, orders=orders, query=query, status_filter=status_filter)

def init_db():
    """Инициализация базы данных с тестовыми данными"""
    db.create_all()
    
    # Создаем администратора если его нет
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        admin = User(
            username='admin',
            email='admin@photolab.com',
            password_hash=generate_password_hash('admin123'),
            role='admin',
            full_name='Администратор системы'
        )
        db.session.add(admin)
    
    # Создаем тестового сотрудника
    employee = User.query.filter_by(username='employee').first()
    if not employee:
        employee = User(
            username='employee',
            email='employee@photolab.com',
            password_hash=generate_password_hash('emp123'),
            role='employee',
            full_name='Сотрудник лаборатории'
        )
        db.session.add(employee)
    
    # Создаем базовые услуги если их нет
    if Service.query.count() == 0:
        services = [
            Service(name='Печать фото 10x15', description='Стандартная печать фотографий на глянцевой бумаге', price=15.0, processing_time=2, category='printing'),
            Service(name='Печать фото 15x20', description='Печать фотографий увеличенного размера', price=25.0, processing_time=3, category='printing'),
            Service(name='Печать фото 20x30', description='Большие фотографии высокого качества', price=45.0, processing_time=4, category='printing'),
            Service(name='Ретушь фото', description='Профессиональная ретушь изображений', price=200.0, processing_time=24, category='editing'),
            Service(name='Реставрация старых фото', description='Восстановление поврежденных фотографий', price=500.0, processing_time=48, category='restoration'),
            Service(name='Фотокнига', description='Создание персональной фотокниги', price=800.0, processing_time=72, category='products'),
            Service(name='Печать на холсте', description='Печать фотографий на художественном холсте', price=150.0, processing_time=6, category='printing'),
            Service(name='Цветокоррекция', description='Профессиональная цветокоррекция изображений', price=100.0, processing_time=12, category='editing'),
        ]
        
        for service in services:
            db.session.add(service)
    
    db.session.commit()

# HTML шаблоны
BASE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Фотолаборатория{% endblock %}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.0/font/bootstrap-icons.css" rel="stylesheet">
    <style>
        .navbar-brand {
            font-weight: bold;
            font-size: 1.5rem;
        }
        .status-badge {
            font-size: 0.8em;
        }
        .card-hover:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            transition: all 0.3s ease;
        }
        .stats-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
        }
        .order-card {
            border-left: 4px solid #007bff;
        }
        .service-card {
            border-top: 3px solid #28a745;
        }
        .hero-section {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 4rem 0;
        }
        .feature-icon {
            font-size: 3rem;
            color: #007bff;
        }
        .bg-gradient {
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
        }
    </style>
</head>
<body class="bg-light">
    <nav class="navbar navbar-expand-lg navbar-dark bg-primary shadow">
        <div class="container">
            <a class="navbar-brand" href="{{ url_for('index') }}">
                <i class="bi bi-camera-fill"></i> ФотоЛаб
            </a>
            
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                <span class="navbar-toggler-icon"></span>
            </button>
            
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav me-auto">
                    {% if current_user.is_authenticated %}
                        {% if current_user.role in ['admin', 'employee'] %}
                            <li class="nav-item">
                                <a class="nav-link" href="{{ url_for('admin_dashboard') }}">
                                    <i class="bi bi-speedometer2"></i> Панель управления
                                </a>
                            </li>
                            <li class="nav-item">
                                <a class="nav-link" href="{{ url_for('services') }}">
                                    <i class="bi bi-gear-fill"></i> Услуги
                                </a>
                            </li>
                        {% else %}
                            <li class="nav-item">
                                <a class="nav-link" href="{{ url_for('client_dashboard') }}">
                                    <i class="bi bi-house-fill"></i> Мои заказы
                                </a>
                            </li>
                            <li class="nav-item">
                                <a class="nav-link" href="{{ url_for('create_order') }}">
                                    <i class="bi bi-plus-circle-fill"></i> Новый заказ
                                </a>
                            </li>
                        {% endif %}
                    {% endif %}
                </ul>
                
                <ul class="navbar-nav">
                    {% if current_user.is_authenticated %}
                        <li class="nav-item dropdown">
                            <a class="nav-link dropdown-toggle" href="#" role="button" data-bs-toggle="dropdown">
                                <i class="bi bi-person-circle"></i> {{ current_user.username }}
                            </a>
                            <ul class="dropdown-menu">
                                <li><span class="dropdown-item-text">
                                    <strong>{{ current_user.full_name or current_user.username }}</strong><br>
                                    <small class="text-muted">{{ current_user.role }}</small>
                                </span></li>
                                <li><hr class="dropdown-divider"></li>
                                <li><a class="dropdown-item" href="{{ url_for('logout') }}">
                                    <i class="bi bi-box-arrow-right"></i> Выйти
                                </a></li>
                            </ul>
                        </li>
                    {% else %}
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('login') }}">
                                <i class="bi bi-box-arrow-in-right"></i> Войти
                            </a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="{{ url_for('register') }}">
                                <i class="bi bi-person-plus"></i> Регистрация
                            </a>
                        </li>
                    {% endif %}
                </ul>
            </div>
        </div>
    </nav>

    <main>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                <div class="container mt-3">
                    {% for category, message in messages %}
                        <div class="alert alert-{{ 'danger' if category == 'error' else category }} alert-dismissible fade show" role="alert">
                            {{ message }}
                            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                        </div>
                    {% endfor %}
                </div>
            {% endif %}
        {% endwith %}

        {% block content %}{% endblock %}
    </main>

    <footer class="bg-dark text-light mt-5 py-4">
        <div class="container">
            <div class="row">
                <div class="col-md-6">
                    <h5><i class="bi bi-camera-fill"></i> ФотоЛаб</h5>
                    <p class="mb-0">Профессиональная фотолаборатория с высоким качеством обслуживания</p>
                </div>
                <div class="col-md-6">
                    <h6>Контакты</h6>
                    <p class="mb-0">
                        <i class="bi bi-telephone-fill"></i> +7 (123) 456-78-90<br>
                        <i class="bi bi-envelope-fill"></i> info@photolab.com
                    </p>
                </div>
            </div>
        </div>
    </footer>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        // Функция для обновления статуса заказа
        function updateOrderStatus(orderId, newStatus) {
            fetch(`/update_order_status/${orderId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({status: newStatus})
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    alert('Ошибка при обновлении статуса: ' + (data.error || 'Неизвестная ошибка'));
                }
            })
            .catch(error => {
                alert('Ошибка сети: ' + error);
            });
        }

        // Функция для получения класса бейджа по статусу
        function getStatusBadgeClass(status) {
            const statusClasses = {
                'pending': 'bg-warning text-dark',
                'processing': 'bg-info',
                'ready': 'bg-success',
                'completed': 'bg-secondary',
                'cancelled': 'bg-danger'
            };
            return statusClasses[status] || 'bg-secondary';
        }

        // Функция для получения русского названия статуса
        function getStatusText(status) {
            const statusTexts = {
                'pending': 'Ожидает обработки',
                'processing': 'В работе',
                'ready': 'Готов к выдаче',
                'completed': 'Завершен',
                'cancelled': 'Отменен'
            };
            return statusTexts[status] || status;
        }

        // Обновление времени
        function updateTime() {
            const now = new Date();
            const timeString = now.toLocaleString('ru-RU');
            const timeElements = document.querySelectorAll('.current-time');
            timeElements.forEach(el => el.textContent = timeString);
        }
        
        setInterval(updateTime, 1000);
        updateTime();
    </script>
    {% block scripts %}{% endblock %}
</body>
</html>
'''

INDEX_TEMPLATE = '''
{% extends "base.html" %}
{% block content %}
<div class="hero-section">
    <div class="container">
        <div class="row align-items-center">
            <div class="col-lg-6">
                <h1 class="display-4 fw-bold mb-3">Добро пожаловать в ФотоЛаб</h1>
                <p class="lead mb-4">Профессиональная фотолаборатория с современными технологиями и высоким качеством обслуживания</p>
                <div class="d-flex gap-3">
                    <a href="{{ url_for('register') }}" class="btn btn-light btn-lg">
                        <i class="bi bi-person-plus"></i> Регистрация
                    </a>
                    <a href="{{ url_for('login') }}" class="btn btn-outline-light btn-lg">
                        <i class="bi bi-box-arrow-in-right"></i> Вход
                    </a>
                </div>
            </div>
            <div class="col-lg-6 text-center">
                <i class="bi bi-camera-fill" style="font-size: 8rem; opacity: 0.3;"></i>
            </div>
        </div>
    </div>
</div>

<div class="container my-5">
    <div class="row text-center mb-5">
        <div class="col-12">
            <h2 class="mb-3">Наши услуги</h2>
            <p class="text-muted">Широкий спектр услуг для всех ваших потребностей в фотографии</p>
        </div>
    </div>
    
    <div class="row">
        {% for service in services %}
        <div class="col-md-4 mb-4">
            <div class="card h-100 card-hover service-card">
                <div class="card-body">
                    <h5 class="card-title">{{ service.name }}</h5>
                    <p class="card-text">{{ service.description }}</p>
                    <div class="d-flex justify-content-between align-items-center">
                        <span class="h5 text-primary mb-0">{{ service.price }} ₽</span>
                        <small class="text-muted">{{ service.processing_time }}ч</small>
                    </div>
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
    
    <div class="text-center mt-4">
        <a href="{{ url_for('register') }}" class="btn btn-primary btn-lg">
            Начать работу с нами
        </a>
    </div>
</div>

<div class="bg-gradient py-5">
    <div class="container">
        <div class="row">
            <div class="col-md-4 text-center mb-4">
                <i class="bi bi-lightning-charge-fill feature-icon"></i>
                <h4 class="mt-3">Быстро</h4>
                <p>Обработка заказов от 2 часов</p>
            </div>
            <div class="col-md-4 text-center mb-4">
                <i class="bi bi-award-fill feature-icon"></i>
                <h4 class="mt-3">Качественно</h4>
                <p>Профессиональное оборудование и материалы</p>
            </div>
            <div class="col-md-4 text-center mb-4">
                <i class="bi bi-shield-check-fill feature-icon"></i>
                <h4 class="mt-3">Надежно</h4>
                <p>Гарантия качества на все услуги</p>
            </div>
        </div>
    </div>
</div>
{% endblock %}
'''

LOGIN_TEMPLATE = '''
{% extends "base.html" %}
{% block title %}Вход - Фотолаборатория{% endblock %}
{% block content %}
<div class="container mt-5">
    <div class="row justify-content-center">
        <div class="col-md-6 col-lg-4">
            <div class="card shadow">
                <div class="card-body p-4">
                    <div class="text-center mb-4">
                        <i class="bi bi-camera-fill text-primary" style="font-size: 3rem;"></i>
                        <h3 class="mt-2">Вход в систему</h3>
                    </div>
                    
                    <form method="POST">
                        <div class="mb-3">
                            <label for="username" class="form-label">Имя пользователя</label>
                            <input type="text" class="form-control" id="username" name="username" required>
                        </div>
                        <div class="mb-3">
                            <label for="password" class="form-label">Пароль</label>
                            <input type="password" class="form-control" id="password" name="password" required>
                        </div>
                        <button type="submit" class="btn btn-primary w-100">
                            <i class="bi bi-box-arrow-in-right"></i> Войти
                        </button>
                    </form>
                    
                    <div class="text-center mt-3">
                        <p>Нет аккаунта? <a href="{{ url_for('register') }}">Зарегистрироваться</a></p>
                        <small class="text-muted">
                            Тестовые данные:<br>
                            admin / admin123 (администратор)<br>
                            employee / emp123 (сотрудник)
                        </small>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
'''

REGISTER_TEMPLATE = '''
{% extends "base.html" %}
{% block title %}Регистрация - Фотолаборатория{% endblock %}
{% block content %}
<div class="container mt-5">
    <div class="row justify-content-center">
        <div class="col-md-6 col-lg-5">
            <div class="card shadow">
                <div class="card-body p-4">
                    <div class="text-center mb-4">
                        <i class="bi bi-person-plus-fill text-primary" style="font-size: 3rem;"></i>
                        <h3 class="mt-2">Регистрация</h3>
                    </div>
                    
                    <form method="POST">
                        <div class="mb-3">
                            <label for="full_name" class="form-label">Полное имя</label>
                            <input type="text" class="form-control" id="full_name" name="full_name">
                        </div>
                        <div class="mb-3">
                            <label for="username" class="form-label">Имя пользователя *</label>
                            <input type="text" class="form-control" id="username" name="username" required>
                        </div>
                        <div class="mb-3">
                            <label for="email" class="form-label">Email *</label>
                            <input type="email" class="form-control" id="email" name="email" required>
                        </div>
                        <div class="mb-3">
                            <label for="phone" class="form-label">Телефон</label>
                            <input type="tel" class="form-control" id="phone" name="phone">
                        </div>
                        <div class="mb-3">
                            <label for="password" class="form-label">Пароль *</label>
                            <input type="password" class="form-control" id="password" name="password" required>
                        </div>
                        <button type="submit" class="btn btn-primary w-100">
                            <i class="bi bi-person-plus"></i> Зарегистрироваться
                        </button>
                    </form>
                    
                    <div class="text-center mt-3">
                        <p>Уже есть аккаунт? <a href="{{ url_for('login') }}">Войти</a></p>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
'''

CLIENT_DASHBOARD_TEMPLATE = '''
{% extends "base.html" %}
{% block title %}Мои заказы - Фотолаборатория{% endblock %}
{% block content %}
<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2><i class="bi bi-person-circle"></i> Личный кабинет</h2>
        <a href="{{ url_for('create_order') }}" class="btn btn-primary">
            <i class="bi bi-plus-circle"></i> Новый заказ
        </a>
    </div>
    
    <!-- Статистика -->
    <div class="row mb-4">
        <div class="col-md-4">
            <div class="card stats-card text-center">
                <div class="card-body">
                    <i class="bi bi-box-seam" style="font-size: 2rem;"></i>
                    <h3 class="mt-2">{{ stats.total_orders }}</h3>
                    <p class="mb-0">Всего заказов</p>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card bg-warning text-center">
                <div class="card-body">
                    <i class="bi bi-clock-history" style="font-size: 2rem;"></i>
                    <h3 class="mt-2">{{ stats.pending_orders }}</h3>
                    <p class="mb-0">В обработке</p>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card bg-success text-white text-center">
                <div class="card-body">
                    <i class="bi bi-check-circle" style="font-size: 2rem;"></i>
                    <h3 class="mt-2">{{ stats.ready_orders }}</h3>
                    <p class="mb-0">Готовы к выдаче</p>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Поиск заказов -->
    <div class="card mb-4">
        <div class="card-body">
            <form method="GET" action="{{ url_for('search_orders') }}" class="row g-3">
                <div class="col-md-6">
                    <input type="text" class="form-control" name="q" placeholder="Поиск по номеру заказа или примечаниям" value="{{ request.args.get('q', '') }}">
                </div>
                <div class="col-md-4">
                    <select class="form-select" name="status">
                        <option value="">Все статусы</option>
                        <option value="pending" {% if request.args.get('status') == 'pending' %}selected{% endif %}>Ожидает обработки</option>
                        <option value="processing" {% if request.args.get('status') == 'processing' %}selected{% endif %}>В работе</option>
                        <option value="ready" {% if request.args.get('status') == 'ready' %}selected{% endif %}>Готов к выдаче</option>
                        <option value="completed" {% if request.args.get('status') == 'completed' %}selected{% endif %}>Завершен</option>
                    </select>
                </div>
                <div class="col-md-2">
                    <button type="submit" class="btn btn-outline-primary w-100">
                        <i class="bi bi-search"></i> Поиск
                    </button>
                </div>
            </form>
        </div>
    </div>
    
    <!-- Список заказов -->
    <div class="row">
        {% for order in orders %}
        <div class="col-md-6 col-lg-4 mb-4">
            <div class="card order-card card-hover h-100">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-start mb-2">
                        <h6 class="card-title mb-0">{{ order.order_number }}</h6>
                        <span class="badge status-badge
                            {% if order.status == 'pending' %}bg-warning text-dark
                            {% elif order.status == 'processing' %}bg-info
                            {% elif order.status == 'ready' %}bg-success
                            {% elif order.status == 'completed' %}bg-secondary
                            {% elif order.status == 'cancelled' %}bg-danger
                            {% endif %}">
                            {% if order.status == 'pending' %}Ожидает
                            {% elif order.status == 'processing' %}В работе
                            {% elif order.status == 'ready' %}Готов
                            {% elif order.status == 'completed' %}Завершен
                            {% elif order.status == 'cancelled' %}Отменен
                            {% endif %}
                        </span>
                    </div>
                    
                    <p class="card-text">
                        <strong>Услуга:</strong> {{ order.service.name }}<br>
                        <strong>Количество:</strong> {{ order.quantity }}<br>
                        <strong>Сумма:</strong> {{ order.total_price }} ₽
                    </p>
                    
                    <div class="small text-muted">
                        <div><i class="bi bi-calendar"></i> Создан: {{ order.created_at.strftime('%d.%m.%Y %H:%M') }}</div>
                        {% if order.due_date %}
                        <div><i class="bi bi-clock"></i> Готовность: {{ order.due_date.strftime('%d.%m.%Y %H:%M') }}</div>
                        {% endif %}
                    </div>
                    
                    <div class="mt-3">
                        <a href="{{ url_for('order_details', order_id=order.id) }}" class="btn btn-outline-primary btn-sm">
                            <i class="bi bi-eye"></i> Подробнее
                        </a>
                    </div>
                </div>
            </div>
        </div>
        {% endfor %}
        
        {% if not orders %}
        <div class="col-12">
            <div class="text-center py-5">
                <i class="bi bi-inbox" style="font-size: 4rem; color: #ccc;"></i>
                <h4 class="mt-3 text-muted">У вас пока нет заказов</h4>
                <p class="text-muted">Создайте свой первый заказ прямо сейчас!</p>
                <a href="{{ url_for('create_order') }}" class="btn btn-primary">
                    <i class="bi bi-plus-circle"></i> Создать заказ
                </a>
            </div>
        </div>
        {% endif %}
    </div>
</div>
{% endblock %}
'''

ADMIN_DASHBOARD_TEMPLATE = '''
{% extends "base.html" %}
{% block title %}Панель управления - Фотолаборатория{% endblock %}
{% block content %}
<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2><i class="bi bi-speedometer2"></i> Панель управления</h2>
        <div class="current-time badge bg-secondary fs-6"></div>
    </div>
    
    <!-- Статистика -->
    <div class="row mb-4">
        <div class="col-md-3">
            <div class="card stats-card text-center">
                <div class="card-body">
                    <i class="bi bi-box-seam" style="font-size: 2rem;"></i>
                    <h3 class="mt-2">{{ stats.total_orders }}</h3>
                    <p class="mb-0">Всего заказов</p>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card bg-warning text-center">
                <div class="card-body">
                    <i class="bi bi-hourglass-split" style="font-size: 2rem;"></i>
                    <h3 class="mt-2">{{ stats.pending_orders }}</h3>
                    <p class="mb-0">Ожидают</p>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card bg-info text-white text-center">
                <div class="card-body">
                    <i class="bi bi-gear-fill" style="font-size: 2rem;"></i>
                    <h3 class="mt-2">{{ stats.processing_orders }}</h3>
                    <p class="mb-0">В работе</p>
                </div>
            </div>
        </div>
        <div class="col-md-3">
            <div class="card bg-success text-white text-center">
                <div class="card-body">
                    <i class="bi bi-check-circle" style="font-size: 2rem;"></i>
                    <h3 class="mt-2">{{ stats.ready_orders }}</h3>
                    <p class="mb-0">Готовы</p>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Доходы -->
    <div class="row mb-4">
        <div class="col-md-12">
            <div class="card bg-success text-white">
                <div class="card-body text-center">
                    <i class="bi bi-currency-ruble" style="font-size: 2rem;"></i>
                    <h3 class="mt-2">{{ "%.2f"|format(stats.total_revenue) }} ₽</h3>
                    <p class="mb-0">Общий доход от завершенных заказов</p>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Последние заказы -->
    <div class="card">
        <div class="card-header d-flex justify-content-between align-items-center">
            <h5 class="mb-0"><i class="bi bi-list-ul"></i> Последние заказы</h5>
            <a href="{{ url_for('search_orders') }}" class="btn btn-outline-primary btn-sm">
                <i class="bi bi-search"></i> Поиск
            </a>
        </div>
        <div class="card-body p-0">
            <div class="table-responsive">
                <table class="table table-hover mb-0">
                    <thead class="table-light">
                        <tr>
                            <th>Номер</th>
                            <th>Клиент</th>
                            <th>Услуга</th>
                            <th>Статус</th>
                            <th>Сумма</th>
                            <th>Создан</th>
                            <th>Действия</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for order in orders %}
                        <tr>
                            <td><strong>{{ order.order_number }}</strong></td>
                            <td>{{ order.customer.username }}</td>
                            <td>{{ order.service.name }}</td>
                            <td>
                                <select class="form-select form-select-sm" onchange="updateOrderStatus({{ order.id }}, this.value)">
                                    <option value="pending" {% if order.status == 'pending' %}selected{% endif %}>Ожидает</option>
                                    <option value="processing" {% if order.status == 'processing' %}selected{% endif %}>В работе</option>
                                    <option value="ready" {% if order.status == 'ready' %}selected{% endif %}>Готов</option>
                                    <option value="completed" {% if order.status == 'completed' %}selected{% endif %}>Завершен</option>
                                    <option value="cancelled" {% if order.status == 'cancelled' %}selected{% endif %}>Отменен</option>
                                </select>
                            </td>
                            <td>{{ order.total_price }} ₽</td>
                            <td>{{ order.created_at.strftime('%d.%m %H:%M') }}</td>
                            <td>
                                <a href="{{ url_for('order_details', order_id=order.id) }}" class="btn btn-outline-primary btn-sm">
                                    <i class="bi bi-eye"></i>
                                </a>
                            </td>
                        </tr>
                        {% endfor %}
                        
                        {% if not orders %}
                        <tr>
                            <td colspan="7" class="text-center py-4 text-muted">
                                <i class="bi bi-inbox"></i> Заказов пока нет
                            </td>
                        </tr>
                        {% endif %}
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</div>
{% endblock %}
'''

CREATE_ORDER_TEMPLATE = '''
{% extends "base.html" %}
{% block title %}Новый заказ - Фотолаборатория{% endblock %}
{% block content %}
<div class="container mt-4">
    <div class="row justify-content-center">
        <div class="col-md-8">
            <div class="card shadow">
                <div class="card-header">
                    <h4 class="mb-0"><i class="bi bi-plus-circle"></i> Создание нового заказа</h4>
                </div>
                <div class="card-body">
                    <form method="POST" enctype="multipart/form-data">
                        <div class="mb-3">
                            <label for="service_id" class="form-label">Услуга *</label>
                            <select class="form-select" id="service_id" name="service_id" required onchange="updatePrice()">
                                <option value="">Выберите услугу</option>
                                {% for service in services %}
                                <option value="{{ service.id }}" data-price="{{ service.price }}" data-time="{{ service.processing_time }}">
                                    {{ service.name }} - {{ service.price }} ₽
                                </option>
                                {% endfor %}
                            </select>
                        </div>
                        
                        <div class="mb-3">
                            <label for="quantity" class="form-label">Количество *</label>
                            <input type="number" class="form-control" id="quantity" name="quantity" value="1" min="1" required onchange="updatePrice()">
                        </div>
                        
                        <div class="mb-3">
                            <label class="form-label">Общая стоимость</label>
                            <div class="form-control-plaintext h5 text-primary" id="total_price">0 ₽</div>
                        </div>
                        
                        <div class="mb-3">
                            <label class="form-label">Время выполнения</label>
                            <div class="form-control-plaintext" id="processing_time">Выберите услугу</div>
                        </div>
                        
                        <div class="mb-3">
                            <label for="files" class="form-label">Загрузить файлы</label>
                            <input type="file" class="form-control" id="files" name="files" multiple accept="image/*">
                            <div class="form-text">Поддерживаются форматы: JPG, PNG, GIF, BMP, TIFF. Максимальный размер файла: 16 МБ</div>
                        </div>
                        
                        <div class="mb-3">
                            <label for="notes" class="form-label">Примечания</label>
                            <textarea class="form-control" id="notes" name="notes" rows="3" placeholder="Дополнительные пожелания или инструкции"></textarea>
                        </div>
                        
                        <div class="d-flex gap-2">
                            <button type="submit" class="btn btn-primary">
                                <i class="bi bi-plus-circle"></i> Создать заказ
                            </button>
                            <a href="{{ url_for('client_dashboard') }}" class="btn btn-outline-secondary">
                                <i class="bi bi-arrow-left"></i> Отмена
                            </a>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
function updatePrice() {
    const serviceSelect = document.getElementById('service_id');
    const quantityInput = document.getElementById('quantity');
    const totalPriceDiv = document.getElementById('total_price');
    const processingTimeDiv = document.getElementById('processing_time');
    
    const selectedOption = serviceSelect.options[serviceSelect.selectedIndex];
    const price = parseFloat(selectedOption.dataset.price) || 0;
    const time = parseInt(selectedOption.dataset.time) || 0;
    const quantity = parseInt(quantityInput.value) || 1;
    
    const total = price * quantity;
    totalPriceDiv.textContent = total.toFixed(2) + ' ₽';
    
    if (time > 0) {
        const hours = time;
        const days = Math.floor(hours / 24);
        const remainingHours = hours % 24;
        
        let timeText = '';
        if (days > 0) {
            timeText += days + ' д. ';
        }
        if (remainingHours > 0) {
            timeText += remainingHours + ' ч.';
        }
        processingTimeDiv.textContent = timeText || 'Не указано';
    } else {
        processingTimeDiv.textContent = 'Не указано';
    }
}
</script>
{% endblock %}
'''

ORDER_DETAILS_TEMPLATE = '''
{% extends "base.html" %}
{% block title %}Заказ {{ order.order_number }} - Фотолаборатория{% endblock %}
{% block content %}
<div class="container mt-4">
    <div class="row justify-content-center">
        <div class="col-md-8">
            <div class="card shadow">
                <div class="card-header d-flex justify-content-between align-items-center">
                    <h4 class="mb-0"><i class="bi bi-file-earmark-text"></i> Заказ {{ order.order_number }}</h4>
                    <span class="badge fs-6
                        {% if order.status == 'pending' %}bg-warning text-dark
                        {% elif order.status == 'processing' %}bg-info
                        {% elif order.status == 'ready' %}bg-success
                        {% elif order.status == 'completed' %}bg-secondary
                        {% elif order.status == 'cancelled' %}bg-danger
                        {% endif %}">
                        {% if order.status == 'pending' %}Ожидает обработки
                        {% elif order.status == 'processing' %}В работе
                        {% elif order.status == 'ready' %}Готов к выдаче
                        {% elif order.status == 'completed' %}Завершен
                        {% elif order.status == 'cancelled' %}Отменен
                        {% endif %}
                    </span>
                </div>
                <div class="card-body">
                    <div class="row">
                        <div class="col-md-6">
                            <h6>Информация о заказе</h6>
                            <table class="table table-sm">
                                <tr>
                                    <td><strong>Номер заказа:</strong></td>
                                    <td>{{ order.order_number }}</td>
                                </tr>
                                <tr>
                                    <td><strong>Клиент:</strong></td>
                                    <td>{{ order.customer.full_name or order.customer.username }}</td>
                                </tr>
                                <tr>
                                    <td><strong>Email:</strong></td>
                                    <td>{{ order.customer.email }}</td>
                                </tr>
                                {% if order.customer.phone %}
                                <tr>
                                    <td><strong>Телефон:</strong></td>
                                    <td>{{ order.customer.phone }}</td>
                                </tr>
                                {% endif %}
                                <tr>
                                    <td><strong>Услуга:</strong></td>
                                    <td>{{ order.service.name }}</td>
                                </tr>
                                <tr>
                                    <td><strong>Количество:</strong></td>
                                    <td>{{ order.quantity }}</td>
                                </tr>
                                <tr>
                                    <td><strong>Сумма:</strong></td>
                                    <td><strong>{{ order.total_price }} ₽</strong></td>
                                </tr>
                            </table>
                        </div>
                        <div class="col-md-6">
                            <h6>Временные метки</h6>
                            <table class="table table-sm">
                                <tr>
                                    <td><strong>Создан:</strong></td>
                                    <td>{{ order.created_at.strftime('%d.%m.%Y %H:%M') }}</td>
                                </tr>
                                {% if order.due_date %}
                                <tr>
                                    <td><strong>Срок готовности:</strong></td>
                                    <td>{{ order.due_date.strftime('%d.%m.%Y %H:%M') }}</td>
                                </tr>
                                {% endif %}
                                {% if order.completed_at %}
                                <tr>
                                    <td><strong>Завершен:</strong></td>
                                    <td>{{ order.completed_at.strftime('%d.%m.%Y %H:%M') }}</td>
                                </tr>
                                {% endif %}
                            </table>
                        </div>
                    </div>
                    
                    {% if order.notes %}
                    <div class="mt-3">
                        <h6>Примечания</h6>
                        <div class="bg-light p-3 rounded">{{ order.notes }}</div>
                    </div>
                    {% endif %}
                    
                    {% if order.files %}
                    <div class="mt-3">
                        <h6>Загруженные файлы</h6>
                        <div class="row">
                            {% for file in order.files %}
                            <div class="col-md-3 mb-2">
                                <div class="card">
                                    <div class="card-body p-2 text-center">
                                        <i class="bi bi-file-earmark-image text-primary" style="font-size: 2rem;"></i>
                                        <div class="small">{{ file.original_filename }}</div>
                                        <div class="small text-muted">{{ "%.1f"|format(file.file_size / 1024) }} КБ</div>
                                        <a href="{{ url_for('uploaded_file', filename=file.filename) }}" class="btn btn-outline-primary btn-sm mt-1" target="_blank">
                                            <i class="bi bi-download"></i>
                                        </a>
                                    </div>
                                </div>
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                    {% endif %}
                    
                    <div class="mt-4 d-flex gap-2">
                        {% if current_user.role in ['admin', 'employee'] %}
                            <div class="btn-group" role="group">
                                <button type="button" class="btn btn-outline-warning btn-sm" onclick="updateOrderStatus({{ order.id }}, 'pending')">
                                    <i class="bi bi-hourglass"></i> В ожидании
                                </button>
                                <button type="button" class="btn btn-outline-info btn-sm" onclick="updateOrderStatus({{ order.id }}, 'processing')">
                                    <i class="bi bi-gear"></i> В работе
                                </button>
                                <button type="button" class="btn btn-outline-success btn-sm" onclick="updateOrderStatus({{ order.id }}, 'ready')">
                                    <i class="bi bi-check"></i> Готов
                                </button>
                                <button type="button" class="btn btn-outline-secondary btn-sm" onclick="updateOrderStatus({{ order.id }}, 'completed')">
                                    <i class="bi bi-check-all"></i> Завершен
                                </button>
                            </div>
                        {% endif %}
                        
                        <a href="{% if current_user.role in ['admin', 'employee'] %}{{ url_for('admin_dashboard') }}{% else %}{{ url_for('client_dashboard') }}{% endif %}" class="btn btn-outline-secondary">
                            <i class="bi bi-arrow-left"></i> Назад
                        </a>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
'''

SERVICES_TEMPLATE = '''
{% extends "base.html" %}
{% block title %}Управление услугами - Фотолаборатория{% endblock %}
{% block content %}
<div class="container mt-4">
    <div class="d-flex justify-content-between align-items-center mb-4">
        <h2><i class="bi bi-gear-fill"></i> Управление услугами</h2>
        {% if current_user.role == 'admin' %}
        <a href="{{ url_for('create_service') }}" class="btn btn-primary">
            <i class="bi bi-plus-circle"></i> Добавить услугу
        </a>
        {% endif %}
    </div>
    
    <div class="row">
        {% for service in services %}
        <div class="col-md-6 col-lg-4 mb-4">
            <div class="card service-card card-hover h-100">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-start mb-2">
                        <h5 class="card-title">{{ service.name }}</h5>
                        <span class="badge {% if service.is_active %}bg-success{% else %}bg-secondary{% endif %}">
                            {% if service.is_active %}Активна{% else %}Неактивна{% endif %}
                        </span>
                    </div>
                    
                    <p class="card-text">{{ service.description }}</p>
                    
                    <div class="row text-center">
                        <div class="col-6">
                            <div class="h5 text-primary mb-0">{{ service.price }} ₽</div>
                            <small class="text-muted">Цена</small>
                        </div>
                        <div class="col-6">
                            <div class="h6 mb-0">{{ service.processing_time }}ч</div>
                            <small class="text-muted">Время</small>
                        </div>
                    </div>
                    
                    {% if current_user.role == 'admin' %}
                    <div class="mt-3">
                        <a href="{{ url_for('edit_service', service_id=service.id) }}" class="btn btn-outline-primary btn-sm">
                            <i class="bi bi-pencil"></i> Редактировать
                        </a>
                    </div>
                    {% endif %}
                </div>
            </div>
        </div>
        {% endfor %}
    </div>
</div>
{% endblock %}
'''

CREATE_SERVICE_TEMPLATE = '''
{% extends "base.html" %}
{% block title %}Новая услуга - Фотолаборатория{% endblock %}
{% block content %}
<div class="container mt-4">
    <div class="row justify-content-center">
        <div class="col-md-6">
            <div class="card shadow">
                <div class="card-header">
                    <h4 class="mb-0"><i class="bi bi-plus-circle"></i> Добавление новой услуги</h4>
                </div>
                <div class="card-body">
                    <form method="POST">
                        <div class="mb-3">
                            <label for="name" class="form-label">Название услуги *</label>
                            <input type="text" class="form-control" id="name" name="name" required>
                        </div>
                        
                        <div class="mb-3">
                            <label for="description" class="form-label">Описание</label>
                            <textarea class="form-control" id="description" name="description" rows="3"></textarea>
                        </div>
                        
                        <div class="mb-3">
                            <label for="category" class="form-label">Категория</label>
                            <select class="form-select" id="category" name="category">
                                <option value="printing">Печать</option>
                                <option value="editing">Редактирование</option>
                                <option value="restoration">Реставрация</option>
                                <option value="products">Продукция</option>
                            </select>
                        </div>
                        
                        <div class="row">
                            <div class="col-md-6">
                                <div class="mb-3">
                                    <label for="price" class="form-label">Цена (₽) *</label>
                                    <input type="number" class="form-control" id="price" name="price" step="0.01" min="0" required>
                                </div>
                            </div>
                            <div class="col-md-6">
                                <div class="mb-3">
                                    <label for="processing_time" class="form-label">Время выполнения (часы) *</label>
                                    <input type="number" class="form-control" id="processing_time" name="processing_time" min="1" required>
                                </div>
                            </div>
                        </div>
                        
                        <div class="d-flex gap-2">
                            <button type="submit" class="btn btn-primary">
                                <i class="bi bi-plus-circle"></i> Создать услугу
                            </button>
                            <a href="{{ url_for('services') }}" class="btn btn-outline-secondary">
                                <i class="bi bi-arrow-left"></i> Отмена
                            </a>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
'''

EDIT_SERVICE_TEMPLATE = '''
{% extends "base.html" %}
{% block title %}Редактирование услуги - Фотолаборатория{% endblock %}
{% block content %}
<div class="container mt-4">
    <div class="row justify-content-center">
        <div class="col-md-6">
            <div class="card shadow">
                <div class="card-header">
                    <h4 class="mb-0"><i class="bi bi-pencil"></i> Редактирование услуги</h4>
                </div>
                <div class="card-body">
                    <form method="POST">
                        <div class="mb-3">
                            <label for="name" class="form-label">Название услуги *</label>
                            <input type="text" class="form-control" id="name" name="name" value="{{ service.name }}" required>
                        </div>
                        
                        <div class="mb-3">
                            <label for="description" class="form-label">Описание</label>
                            <textarea class="form-control" id="description" name="description" rows="3">{{ service.description }}</textarea>
                        </div>
                        
                        <div class="mb-3">
                            <label for="category" class="form-label">Категория</label>
                            <select class="form-select" id="category" name="category">
                                <option value="printing" {% if service.category == 'printing' %}selected{% endif %}>Печать</option>
                                <option value="editing" {% if service.category == 'editing' %}selected{% endif %}>Редактирование</option>
                                <option value="restoration" {% if service.category == 'restoration' %}selected{% endif %}>Реставрация</option>
                                <option value="products" {% if service.category == 'products' %}selected{% endif %}>Продукция</option>
                            </select>
                        </div>
                        
                        <div class="row">
                            <div class="col-md-6">
                                <div class="mb-3">
                                    <label for="price" class="form-label">Цена (₽) *</label>
                                    <input type="number" class="form-control" id="price" name="price" step="0.01" min="0" value="{{ service.price }}" required>
                                </div>
                            </div>
                            <div class="col-md-6">
                                <div class="mb-3">
                                    <label for="processing_time" class="form-label">Время выполнения (часы) *</label>
                                    <input type="number" class="form-control" id="processing_time" name="processing_time" min="1" value="{{ service.processing_time }}" required>
                                </div>
                            </div>
                        </div>
                        
                        <div class="mb-3">
                            <div class="form-check">
                                <input class="form-check-input" type="checkbox" id="is_active" name="is_active" {% if service.is_active %}checked{% endif %}>
                                <label class="form-check-label" for="is_active">
                                    Услуга активна
                                </label>
                            </div>
                        </div>
                        
                        <div class="d-flex gap-2">
                            <button type="submit" class="btn btn-primary">
                                <i class="bi bi-check-circle"></i> Сохранить
                            </button>
                            <a href="{{ url_for('services') }}" class="btn btn-outline-secondary">
                                <i class="bi bi-arrow-left"></i> Отмена
                            </a>
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
'''

SEARCH_RESULTS_TEMPLATE = '''
{% extends "base.html" %}
{% block title %}Результаты поиска - Фотолаборатория{% endblock %}
{% block content %}
<div class="container mt-4">
    <h2><i class="bi bi-search"></i> Результаты поиска</h2>
    
    {% if query or status_filter %}
    <div class="alert alert-info">
        Поиск по: 
        {% if query %}"{{ query }}"{% endif %}
        {% if status_filter %}статус "{{ status_filter }}"{% endif %}
        - найдено {{ orders|length }} заказов
    </div>
    {% endif %}
    
    <div class="row">
        {% for order in orders %}
        <div class="col-md-6 col-lg-4 mb-4">
            <div class="card order-card card-hover h-100">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-start mb-2">
                        <h6 class="card-title mb-0">{{ order.order_number }}</h6>
                        <span class="badge status-badge
                            {% if order.status == 'pending' %}bg-warning text-dark
                            {% elif order.status == 'processing' %}bg-info
                            {% elif order.status == 'ready' %}bg-success
                            {% elif order.status == 'completed' %}bg-secondary
                            {% elif order.status == 'cancelled' %}bg-danger
                            {% endif %}">
                            {% if order.status == 'pending' %}Ожидает
                            {% elif order.status == 'processing' %}В работе
                            {% elif order.status == 'ready' %}Готов
                            {% elif order.status == 'completed' %}Завершен
                            {% elif order.status == 'cancelled' %}Отменен
                            {% endif %}
                        </span>
                    </div>
                    
                    <p class="card-text">
                        {% if current_user.role in ['admin', 'employee'] %}
                        <strong>Клиент:</strong> {{ order.customer.username }}<br>
                        {% endif %}
                        <strong>Услуга:</strong> {{ order.service.name }}<br>
                        <strong>Количество:</strong> {{ order.quantity }}<br>
                        <strong>Сумма:</strong> {{ order.total_price }} ₽
                    </p>
                    
                    <div class="small text-muted">
                        <div><i class="bi bi-calendar"></i> {{ order.created_at.strftime('%d.%m.%Y %H:%M') }}</div>
                        {% if order.due_date %}
                        <div><i class="bi bi-clock"></i> {{ order.due_date.strftime('%d.%m.%Y %H:%M') }}</div>
                        {% endif %}
                    </div>
                    
                    <div class="mt-3">
                        <a href="{{ url_for('order_details', order_id=order.id) }}" class="btn btn-outline-primary btn-sm">
                            <i class="bi bi-eye"></i> Подробнее
                        </a>
                    </div>
                </div>
            </div>
        </div>
        {% endfor %}
        
        {% if not orders %}
        <div class="col-12">
            <div class="text-center py-5">
                <i class="bi bi-search" style="font-size: 4rem; color: #ccc;"></i>
                <h4 class="mt-3 text-muted">Заказы не найдены</h4>
                <p class="text-muted">Попробуйте изменить параметры поиска</p>
            </div>
        </div>
        {% endif %}
    </div>
    
    <div class="mt-4">
        <a href="{% if current_user.role in ['admin', 'employee'] %}{{ url_for('admin_dashboard') }}{% else %}{{ url_for('client_dashboard') }}{% endif %}" class="btn btn-outline-secondary">
            <i class="bi bi-arrow-left"></i> Назад к панели
        </a>
    </div>
</div>
{% endblock %}
'''

# Функция для рендеринга шаблонов
def render_template_string(template_string, **context):
    from flask import render_template_string as flask_render_template_string
    # Добавляем базовый шаблон в контекст
    full_template = template_string.replace('{% extends "base.html" %}', '').strip()
    if '{% block content %}' in full_template:
        content = full_template.split('{% block content %}')[1].split('{% endblock %}')[0]
        full_template = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', content)
    else:
        full_template = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', full_template)
    
    return flask_render_template_string(full_template, **context)

if __name__ == '__main__':
    with app.app_context():
        init_db()
        print("База данных инициализирована!")
        print("Тестовые учетные данные:")
        print("Администратор: admin / admin123")
        print("Сотрудник: employee / emp123")
        print("Приложение запущено на http://localhost:1245")
    
    app.run(debug=True, host='0.0.0.0', port=1245)
