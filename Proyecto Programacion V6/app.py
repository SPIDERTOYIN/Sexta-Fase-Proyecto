#app.py
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
from models import db, Usuario, Empleado, Asistencia, Sucursal
from datetime import datetime
import pandas as pd
from io import BytesIO


app = Flask(__name__)
app.secret_key = "clave_super_secreta"

# 🔹 Render usa PostgreSQL, por eso no conviene SQLite en producción
# Pero dejamos SQLite como fallback para pruebas locales
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///asistencia.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

with app.app_context():
    db.create_all()

# ----------- LOGIN -------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        user = Usuario.query.filter_by(email=email).first()
        if user and user.check_password(password):
            session["user_id"] = user.id
            session["rol"] = user.rol
            return redirect(url_for("dashboard"))
        return "Credenciales incorrectas"
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ----------- DASHBOARD -------------
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = Usuario.query.get(session["user_id"])
    if user.rol == "dueno":
        sucursales = Sucursal.query.all()
    else:
        sucursales = [user.sucursal]

    return render_template("dashboard.html", usuario=user, sucursales=sucursales)

# ----------- API PARA ESP32 -------------
@app.route("/api/asistencia", methods=["POST"])
def api_asistencia():
    data = request.json
    empleado = Empleado.query.filter_by(
        huella_id=data["huella_id"],
        sucursal_id=data["sucursal_id"]
    ).first()

    if not empleado:
        return jsonify({"status": "error", "msg": "Empleado no encontrado"}), 404

    hoy = datetime.now().date()
    asistencia = Asistencia.query.filter_by(
        empleado_id=empleado.id,
        fecha=hoy
    ).first()

    if not asistencia:
        # Primera vez del día → registrar entrada
        asistencia = Asistencia(
            empleado=empleado,
            fecha=hoy,
            hora_entrada=datetime.now().time()
        )
        db.session.add(asistencia)
        db.session.commit()
        accion = "entrada"
    else:
        # Ya existe → registrar salida (si no existe aún)
        if not asistencia.hora_salida:
            asistencia.hora_salida = datetime.now().time()
            db.session.commit()
            accion = "salida"
        else:
            accion = "ya_registrado"

    return jsonify({
        "status": "ok",
        "empleado": empleado.nombre,
        "accion": accion,
        "entrada": asistencia.hora_entrada.strftime("%H:%M:%S") if asistencia.hora_entrada else None,
        "salida": asistencia.hora_salida.strftime("%H:%M:%S") if asistencia.hora_salida else None
    })

# ----------- VISTA SUCURSAL -------------
# ----------- VISTA SUCURSAL -------------
@app.route("/sucursal/<int:id>")
def ver_sucursal(id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = Usuario.query.get(session["user_id"])
    sucursal = Sucursal.query.get(id)
    if not sucursal:
        return "Sucursal no encontrada", 404

    # Restringir acceso para admins
    if user.rol == "admin" and user.sucursal_id != sucursal.id:
        return "Acceso denegado"

    return render_template("sucursal.html", sucursal=sucursal)


@app.route("/sucursal/<int:id>/exportar/<formato>")
def exportar_asistencias(id, formato):
    if "user_id" not in session:
        return redirect(url_for("login"))

    sucursal = Sucursal.query.get(id)
    if not sucursal:
        return "Sucursal no encontrada", 404

    # Recolectar datos
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

    # Crear DataFrame
    df = pd.DataFrame(registros)

    # Exportar según formato
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

def registrar_accion(usuario_id, opcion, descripcion=""):
    from models import Accion
    nueva = Accion(usuario_id=usuario_id, opcion=opcion, descripcion=descripcion)
    db.session.add(nueva)
    db.session.commit()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
