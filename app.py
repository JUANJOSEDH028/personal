from flask import Flask
from flask_restx import Api, Resource, fields, reqparse
import pandas as pd
import os

app = Flask(__name__)
api = Api(app, version='1.0', title='API Cotizador Farmacéutico',
          description='Busca productos en múltiples bodegas locales', doc="/docs")

ns = api.namespace('productos', description='Operaciones de cotización')

# ======================
# Modelo para Swagger UI
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

# ======================
# Cargar todos los datos al iniciar
# ======================
DATA_FOLDER = "data"
BODEGA_DATA = []

def cargar_datos_bodegas():
    global BODEGA_DATA
    BODEGA_DATA.clear()

    if not os.path.exists(DATA_FOLDER):
        os.makedirs(DATA_FOLDER)

    for archivo in os.listdir(DATA_FOLDER):
        if archivo.endswith(".csv"):
            path = os.path.join(DATA_FOLDER, archivo)
            try:
                df = pd.read_csv(path)
                if "nombre_producto" in df.columns:
                    df["bodega"] = df["bodega"].fillna(os.path.splitext(archivo)[0].replace("bodega_", ""))
                    BODEGA_DATA.append(df)
            except Exception as e:
                print(f"Error cargando {archivo}: {e}")

cargar_datos_bodegas()

# ======================
# Parser para búsqueda
# ======================
buscar_parser = reqparse.RequestParser()
buscar_parser.add_argument('nombre', type=str, required=True, help='Nombre del producto a buscar')

# ======================
# Endpoint: Buscar producto
# ======================
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
# Run
# ======================
if __name__ == '__main__':
    app.run(debug=True, port=8080)
