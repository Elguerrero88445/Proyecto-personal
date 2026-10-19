import os
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, UserMixin, login_user, logout_user, login_required)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix
from functools import wraps
from flask import abort
from flask_login import current_user
from flask_wtf.csrf import CSRFProtect, CSRFError
from urllib.parse import urlparse, urljoin
from datetime import datetime, date

load_dotenv()
FECHA_INICIO = date.fromisoformat(os.environ.get('FECHA_INICIO', '2026-06-28'))
FECHA_CONOCIDOS = date.fromisoformat(os.environ.get('FECHA_CONOCIDOS', '2024-11-11'))

app = Flask(__name__)
#app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'
app.config['SECRET_KEY'] = os.environ['SECRET_KEY']
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

db = SQLAlchemy(app)
csrf = CSRFProtect(app)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Inicia sesión'

class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    es_admin = db.Column(db.Boolean, nullable=False, default=False)

class Carta(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(120), nullable=False)
    contenido = db.Column(db.Text, nullable=False)
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_desbloqueo = db.Column(db.DateTime, nullable=True)

    def esta_bloqueada(self):
        return self.fecha_desbloqueo is not None and self.fecha_desbloqueo > datetime.now()

with app.app_context():
    db.create_all()

def dias_desde(fecha):
    return max(0, (date.today() - fecha).days)

def es_url_segura(destino):
    base = urlparse(request.host_url)
    prueba = urlparse(urljoin(request.host_url, destino))
    return prueba.scheme in ('http', 'https') and base.netloc == prueba.netloc

@app.route('/')
def index():
    return render_template('index.html', dias_juntos=dias_desde(FECHA_INICIO), dias_conocidos=dias_desde(FECHA_CONOCIDOS))

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def login():
    if request.method == 'POST':
        nombre = request.form.get('usuario', '').strip()
        clave = request.form.get('clave', '')
        usuario = Usuario.query.filter_by(nombre=nombre).first()
        if usuario and check_password_hash(usuario.password_hash, clave):
            login_user(usuario)
            siguiente = request.args.get('next')
            if siguiente and es_url_segura(siguiente):
                return redirect(siguiente)
            return redirect(url_for('index'))
        flash('Usuario o Password incorrectos')
    return render_template('login.html')

@app.route('/logout', methods=['POST'])
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/quien')
@login_required
def quien():
    return render_template('quien.html')

@app.route('/cartas')
@login_required
def cartas():
    todas = Carta.query.order_by(Carta.fecha_creacion.desc()).all()
    return render_template('cartas.html', cartas=todas)

@app.route('/cartas/<int:id>')
@login_required
def carta(id):
    una = db.get_or_404(Carta, id)
    if una.esta_bloqueada() and not current_user.es_admin:
        flash('Esta carta se abre el ' + una.fecha_desbloqueo.strftime('%d/%m/%y'))
        return redirect(url_for('cartas'))
    return render_template('carta.html', carta=una)

@login_manager.user_loader
def cargar_usuario(user_id):
    return db.session.get(Usuario, int(user_id))

def admin_required(f):
    @wraps(f)
    def decorada(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.es_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorada

@app.errorhandler(429)
def demasiados_intentos(e):
    return render_template('429.html'), 429

@app.errorhandler(CSRFError)
def csrf_expirado(e):
    flash('La sesión ha expirado. Por favor, inténtalo de nuevo.')
    return redirect(url_for('login'))

@app.route('/admin/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def nueva_carta():
    if request.method == 'POST':
        titulo = request.form.get('titulo', '').strip()
        contenido = request.form.get('contenido', '').strip()
        texto_fecha = request.form.get('fecha_desbloqueo', '').strip()
        fecha_desbloqueo = None
        if texto_fecha:
            try:
                fecha_desbloqueo = datetime.strptime(texto_fecha, '%Y-%m-%dT%H:%M')
            except ValueError:
                flash('Formato de fecha invalida')
                return render_template('nueva_carta.html')
        if not titulo or not contenido or len(titulo) > 120:
            flash('Título y contenido son obligatorios')
        else:
            db.session.add(Carta(titulo=titulo, contenido=contenido, fecha_desbloqueo=fecha_desbloqueo))
            db.session.commit()
            flash('Carta creada')
            return redirect(url_for('nueva_carta'))
    return render_template('nueva_carta.html')

@app.route('/admin/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_carta(id):
    una = db.get_or_404(Carta, id)
    if request.method == 'POST':
        titulo = request.form.get('titulo', '').strip()
        contenido = request.form.get('contenido', '').strip()
        texto_fecha = request.form.get('fecha_desbloqueo', '').strip()

        fecha_desbloqueo = None
        if texto_fecha:
            try:
                fecha_desbloqueo = datetime.strptime(texto_fecha, '%Y-%m-%dT%H:%M')
            except ValueError:
                flash('La fecha de desbloqueo no es correcta')
                return render_template('nueva_carta.html', carta=una)
            
        if not titulo or not contenido or len(titulo) > 120:
            flash('Completa los 2 campos')
            return render_template('nueva_carta.html', carta=una)
        
        una.titulo = titulo
        una.contenido = contenido
        una.fecha_desbloqueo = fecha_desbloqueo
        db.session.coomit()
        flash('Se actualizo la carta')
        return redirect(url_for('carta, id=una.id'))
    return render_template('nueva_carta.html', carta=una)

@app.route('/admin/nueva/<int:id>/borrar', methods=['POST'])
@login_required
@admin_required
def borrar_carta(id):
    una = db.get_or_404(Carta, id)
    db.session.delete(una)
    db.session.commit()
    flash('Carta borrada')
    return redirect(url_for('cartas'))

if __name__ == '__main__':
    app.run(debug=False)
    