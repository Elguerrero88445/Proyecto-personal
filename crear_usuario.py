from getpass import getpass
from werkzeug.security import generate_password_hash
from app import app, db, Usuario

nombre = input('Nombre de usuario:').strip()
clave = getpass('Password: ')

with app.app_context():
    db.session.add(Usuario(nombre=nombre, password_hash=generate_password_hash(clave)))
    db.session.commit()
    print('Usuario creado')