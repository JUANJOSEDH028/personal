
from flask import Flask, request
from flask_restx import Api, Resource, fields, reqparse
import pandas as pd
import os
from email.message import EmailMessage
import smtplib
from fpdf import FPDF

# Inicialización
app = Flask(__name__)
api = Api(app, version='1.0', title='API Cotizador Farmacéutico',
          description='Operaciones de búsqueda y envío de cotización', doc="/docs")

ns = api.namespace('productos', description='Endpoints de productos')

# ======================
# Modelos para Swagger UI
# ======================
producto_model = api.model('Producto', {
    'producto_id': fields.String,
    'nombre_producto': fields.String,
    'presentacion': fields.String,
    'precio': fields.Float,
    'disponibilidad': fields.Integer,
    'bodega': fields.String,
    'tiempo_entrega': fields.String,
})

respuesta_model = api.model('RespuestaBusqueda', {
    'disponible': fields.Boolean,
    'mensaje': fields.String,
    'opciones': fields.List(fields.Nested(producto_model))
})

correo_model = api.model('CorreoConPDF', {
    'correo': fields.String(required=True, description='Correo del destinatario'),
    'archivo_pdf': fields.String(required=True, description='Nombre del archivo PDF generado')
})

# ======================
# Variables y carga inicial
# ======================
BODEGA_DATA = []

def estandarizar_dataframe(df: pd.DataFrame, nombre_archivo: str) -> pd.DataFrame:
    columnas = [str(col).lower().strip() for col in df.columns]
    df.columns = columnas

    df["producto_id"] = df.index.astype(str)

    if 'nombre' in columnas:
        df["nombre_producto"] = df["nombre"].astype(str)
    elif 'productos' in columnas:
        df["nombre_producto"] = df["productos"].astype(str)
    elif 'descripción' in columnas:
        df["nombre_producto"] = df["descripción"].astype(str)
    else:
        df["nombre_producto"] = "SIN_NOMBRE"

    posibles_stock = [c for c in columnas if 'stock' in c or 'cant' in c]
    if posibles_stock:
        df["disponibilidad"] = pd.to_numeric(df[posibles_stock[0]], errors='coerce').fillna(0).astype(int)
    else:
        df["disponibilidad"] = 0

    posibles_precio = [c for c in columnas if 'precio' in c]
    if posibles_precio:
        precio_raw = df[posibles_precio[0]].astype(str).str.replace("$", "").str.replace(",", "").str.replace(".", "", regex=False)
        df["precio"] = pd.to_numeric(precio_raw, errors='coerce') / 100
    else:
        df["precio"] = 0.0

    df["presentacion"] = df["nombre_producto"].str.extract(r"(FRASCO.*|TAB.*|CX\d+)", expand=False).fillna("N/A")
    df["bodega"] = os.path.splitext(nombre_archivo)[0].lower()
    df["tiempo_entrega"] = "2 días"

    return df[["producto_id", "nombre_producto", "presentacion", "precio", "disponibilidad", "bodega", "tiempo_entrega"]]

def cargar_datos_bodegas():
    global BODEGA_DATA
    BODEGA_DATA.clear()
    archivos = [f for f in os.listdir(".") if f.endswith(".xlsx") or f.endswith(".xls")]
    for archivo in archivos:
        try:
            extension = os.path.splitext(archivo)[1].lower()
            if extension == ".xlsx":
                df = pd.read_excel(archivo, engine="openpyxl")
            elif extension == ".xls":
                df = pd.read_excel(archivo, engine="xlrd")
            else:
                continue
            df_normalizado = estandarizar_dataframe(df, archivo)
            BODEGA_DATA.append(df_normalizado)
        except Exception as e:
            print(f"Error cargando {archivo}: {e}")

cargar_datos_bodegas()

# ======================
# Endpoint: Buscar producto
# ======================
buscar_parser = reqparse.RequestParser()
buscar_parser.add_argument('nombre', type=str, required=True, help='Nombre del producto a buscar')

@ns.route('/buscar')
class BuscarProducto(Resource):
    @ns.expect(buscar_parser)
    @ns.marshal_with(respuesta_model)
    def get(self):
        args = buscar_parser.parse_args()
        nombre = args['nombre'].strip().lower()
        resultados = []

        for df in BODEGA_DATA:
            df_temp = df.copy()
            df_temp["nombre_producto"] = df_temp["nombre_producto"].astype(str)
            coincidencias = df_temp[df_temp["nombre_producto"].str.lower().str.contains(nombre)]
            disponibles = coincidencias[coincidencias["disponibilidad"] > 0]
            resultados.extend(disponibles.to_dict(orient="records"))

        if not resultados:
            return {
                "disponible": False,
                "mensaje": f"No hay disponibilidad para '{nombre}'.",
                "opciones": []
            }

        return {
            "disponible": True,
            "mensaje": f"Se encontraron {len(resultados)} opciones.",
            "opciones": resultados
        }

# ======================
# Endpoint: Enviar PDF por correo
# ======================
def enviar_correo(destinatario, archivo_pdf):
    from email.header import Header
    from email.utils import formataddr

    msg = EmailMessage()
    msg['Subject'] = 'Cotización Farmacéutica'
    msg['From'] = formataddr((str(Header('Cotizador', 'utf-8')), 'tu_correo@gmail.com'))
    msg['To'] = destinatario

    # Contenido codificado explícitamente como UTF-8
    msg.set_content('Adjunto encontrarás el archivo con la cotización solicitada.', charset='utf-8')

    # Adjuntar el archivo con nombre codificado correctamente
    with open(archivo_pdf, 'rb') as f:
        file_data = f.read()
        file_name = os.path.basename(archivo_pdf)
        # Asegura que el nombre del archivo esté en UTF-8
        msg.add_attachment(file_data, maintype='application', subtype='pdf', filename=(Header(file_name, 'utf-8').encode()))

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login('tu_correo@gmail.com', 'tu_contraseña_de_aplicación')
        smtp.send_message(msg)

@ns.route('/enviar')
class EnviarPDF(Resource):
    @ns.expect(correo_model)
    def post(self):
        data = request.json
        correo = data.get('correo')
        archivo_pdf = data.get('archivo_pdf')

        if not os.path.exists(archivo_pdf):
            return {'error': f'El archivo {archivo_pdf} no existe en el servidor.'}, 400

        try:
            enviar_correo(correo, archivo_pdf)
            return {'mensaje': f'Cotización enviada exitosamente a {correo}.'}
        except Exception as e:
            return {'error': str(e)}, 500

@ns.route('/generar-pdf')
class GenerarPDF(Resource):
    def post(self):
        data = request.json
        carrito = data.get("carrito", [])
        nombre_archivo = data.get("nombre_archivo", "cotizacion.pdf")

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)

        pdf.cell(200, 10, txt="Cotización de productos farmacéuticos", ln=True, align='C')
        pdf.ln(10)

        total = 0
        for idx, item in enumerate(carrito, start=1):
            cantidad = int(item.get("cantidad", 1))
            precio_unitario = float(item.get("precio", 0))
            subtotal = precio_unitario * cantidad

            linea = (
                f"{idx}. {item.get('nombre_producto', 'N/A')} - "
                f"{item.get('presentacion', 'N/A')} - "
                f"${precio_unitario:.2f} x {cantidad} = ${subtotal:.2f} - "
                f"Bodega: {item.get('bodega', 'N/A')}"
            )
            pdf.multi_cell(0, 10, linea)
            total += subtotal

        pdf.ln(5)
        pdf.cell(200, 10, txt=f"Total: ${total:.2f}", ln=True)

        try:
            pdf.output(nombre_archivo)
            return {"mensaje": "PDF generado correctamente", "archivo": nombre_archivo}
        except Exception as e:
            return {"error": f"No se pudo generar el PDF: {str(e)}"}, 500




# ======================
# Endpoint de depuración
# ======================
@app.route('/debug/bodegas')
def debug():
    resumen = []
    for df in BODEGA_DATA:
        if not df.empty:
            resumen.append({
                "bodega": df['bodega'].iloc[0],
                "productos": len(df)
            })
    return {"total_bodegas": len(BODEGA_DATA), "detalle": resumen}

# ======================
# Ejecutar app
# ======================
if __name__ == '__main__':
    app.run(debug=True, port=8080)

