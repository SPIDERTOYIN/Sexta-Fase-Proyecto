# Importamos las librerías necesarias
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
from models import db, Usuario, Empleado, Asistencia, Sucursal
from datetime import datetime
import pandas as pd
from io import BytesIO

# Inicializamos la aplicación Flask
app = Flask(__name__)
app.secret_key = "clave_super_secreta"  # 🔑 Se usa para manejar sesiones de usuarios (login)

# Configuración de la base de datos (SQLite local en este caso)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///asistencia.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Vinculamos SQLAlchemy a nuestra app
db.init_app(app)

# Creamos las tablas en caso de que no existan
with app.app_context():
    db.create_all()

# ---------------- LOGIN ----------------
@app.route("/", methods=["GET", "POST"])
def login():
    # Si el usuario envía el formulario de login
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        # Buscamos el usuario en la BD
        user = Usuario.query.filter_by(email=email).first()
        # Verificamos que exista y que la contraseña sea correcta
        if user and user.check_password(password):
            # Guardamos datos en la sesión (para saber quién está logueado)
            session["user_id"] = user.id
            session["rol"] = user.rol
            return redirect(url_for("dashboard"))
        return "Credenciales incorrectas"
    # Si solo abre la página, mostramos el formulario
    return render_template("login.html")

# Cerrar sesión
@app.route("/logout")
def logout():
    session.clear()  # Borramos datos de la sesión
    return redirect(url_for("login"))

# ---------------- DASHBOARD ----------------
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = Usuario.query.get(session["user_id"])

    # El dueño ve todas las sucursales, el admin solo la suya
    if user.rol == "dueno":
        sucursales = Sucursal.query.all()
    else:
        sucursales = [user.sucursal]

    return render_template("dashboard.html", usuario=user, sucursales=sucursales)

# ---------------- API PARA ESP32 ----------------
@app.route("/api/asistencia", methods=["POST"])
def api_asistencia():
    # Recibimos los datos JSON enviados por el ESP32
    data = request.json
    empleado = Empleado.query.filter_by(
        huella_id=data["huella_id"],   # ID de huella que detecta el sensor
        sucursal_id=data["sucursal_id"]  # ID de la sucursal que envía la ESP32
    ).first()

    # Si no existe el empleado en la BD, devolvemos error
    if not empleado:
        return jsonify({"status": "error", "msg": "Empleado no encontrado"}), 404

    # Revisamos si ya tiene asistencia en el día
    hoy = datetime.now().date()
    asistencia = Asistencia.query.filter_by(
        empleado_id=empleado.id,
        fecha=hoy
    ).first()

    # Si no hay registro previo → es ENTRADA
    if not asistencia:
        asistencia = Asistencia(
            empleado=empleado,
            fecha=hoy,
            hora_entrada=datetime.now().time()
        )
        db.session.add(asistencia)
        db.session.commit()
        accion = "entrada"
    else:
        # Si ya tiene entrada, registramos la salida
        if not asistencia.hora_salida:
            asistencia.hora_salida = datetime.now().time()
            db.session.commit()
            accion = "salida"
        else:
            # Ya tiene entrada y salida → no registramos nada más
            accion = "ya_registrado"

    # Devolvemos una respuesta JSON para confirmar
    return jsonify({
        "status": "ok",
        "empleado": empleado.nombre,
        "accion": accion,
        "entrada": asistencia.hora_entrada.strftime("%H:%M:%S") if asistencia.hora_entrada else None,
        "salida": asistencia.hora_salida.strftime("%H:%M:%S") if asistencia.hora_salida else None
    })

# ---------------- VISTA DE SUCURSAL ----------------
@app.route("/sucursal/<int:id>")
def ver_sucursal(id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = Usuario.query.get(session["user_id"])
    sucursal = Sucursal.query.get(id)
    if not sucursal:
        return "Sucursal no encontrada", 404

    # Restricción: un admin no puede ver sucursales que no sean la suya
    if user.rol == "admin" and user.sucursal_id != sucursal.id:
        return "Acceso denegado"

    return render_template("sucursal.html", sucursal=sucursal)

# ---------------- EXPORTAR DATOS ----------------
@app.route("/sucursal/<int:id>/exportar/<formato>")
def exportar_asistencias(id, formato):
    if "user_id" not in session:
        return redirect(url_for("login"))

    sucursal = Sucursal.query.get(id)
    if not sucursal:
        return "Sucursal no encontrada", 404

    # Recolectamos todas las asistencias de esa sucursal
    registros = []
    for emp in sucursal.empleados:
        for asis in emp.asistencias:
            registros.append({
                "Empleado": emp.nombre,
                "Fecha": asis.fecha.strftime("%Y-%m-%d") if asis.fecha else "",
                "Hora Entrada": asis.hora_entrada.strftime("%H:%M:%S") if asis.hora_entrada else "",
                "Hora Salida": asis.hora_salida.strftime("%H:%M:%S") if asis.hora_salida else ""
            })

    if not registros:
        return "No hay asistencias registradas para exportar."

    # Pasamos los registros a un DataFrame (pandas)
    df = pd.DataFrame(registros)

    # Dependiendo del formato, exportamos a Excel o CSV
    output = BytesIO()
    if formato == "excel":
        df.to_excel(output, index=False, engine="openpyxl")
        output.seek(0)
        return send_file(output, download_name="asistencias.xlsx", as_attachment=True)
    elif formato == "csv":
        df.to_csv(output, index=False)
        output.seek(0)
        return send_file(output, download_name="asistencias.csv", as_attachment=True)
    else:
        return "Formato no soportado", 400

# ---------------- REGISTRO DE ACCIONES ----------------
def registrar_accion(usuario_id, opcion, descripcion=""):
    from models import Accion
    nueva = Accion(usuario_id=usuario_id, opcion=opcion, descripcion=descripcion)
    db.session.add(nueva)
    db.session.commit()

# ---------------- EJECUTAR APP ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
