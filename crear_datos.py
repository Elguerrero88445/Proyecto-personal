from app import app, db, Carta

with app.app_context():
    db.session.add(Carta(titulo='Carta de prueba', contenido='Este es el contenido de la carta de prueba.'))
    db.session.commit()
    print("Listo")