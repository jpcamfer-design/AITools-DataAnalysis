"""Los tres agentes de la Mesa Financiera.

  Iris  · La Recolectora  (Agente 1) → consulta Alpha Vantage por MCP y entrega una FICHA (JSON)
  Euler · El Analista     (Agente 2) → piensa estilo Buffett: Python calcula un filtro de calidad/precio
                                       y Claude lo interpreta a largo plazo → ANÁLISIS (JSON)
  Vera  · La Comunicadora (Agente 3) → recibe el análisis y redacta la NOTA final para Telegram
  (Batuta, el orquestador que los dirige, vive en mesa/pipeline.py)

Regla de oro: los números los calcula el código; la IA solo interpreta.
"""
import json

from . import config

DESCARGO = "Nota educativa, no es recomendación de inversión."
FIRMA_VERA = "✍️ Vera · Comunicadora"

# ----------------------------------------------------------------------
# Conexión con Claude (solo se usa fuera del modo simulación)
# ----------------------------------------------------------------------
_cliente = None


def _cliente_claude():
    global _cliente
    if _cliente is None:
        import anthropic
        _cliente = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _cliente


def llamar_claude(system, mensaje, usar_mcp=False, max_tokens=900):
    """Envía un mensaje a Claude. Devuelve (texto, herramientas_MCP_usadas)."""
    base = dict(model=config.MODELO, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": mensaje}])
    cliente = _cliente_claude()
    if usar_mcp:
        respuesta = cliente.beta.messages.create(
            **base,
            mcp_servers=[{
                "type": "url",
                "url": f"https://mcp.alphavantage.co/mcp?apikey={config.ALPHAVANTAGE_API_KEY}",
                "name": "alphavantage",
            }],
            tools=[{"type": "mcp_toolset", "mcp_server_name": "alphavantage"}],
            betas=["mcp-client-2025-11-20"],
        )
    else:
        respuesta = cliente.messages.create(**base)
    texto = "".join(b.text for b in respuesta.content if b.type == "text").strip()
    herramientas = [b.name for b in respuesta.content if b.type == "mcp_tool_use"]
    return texto, herramientas


def extraer_json(texto):
    """Recupera el objeto JSON de un texto (a veces el modelo agrega palabras alrededor)."""
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fin <= inicio:
        raise ValueError("El agente no devolvió JSON")
    return json.loads(texto[inicio:fin + 1])


def a_numero(valor):
    """Convierte '123.4', '-0.8%' o '1,234' en número; si no se puede, None."""
    try:
        return float(str(valor).replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------
# IRIS · La Recolectora (Agente 1)
# ----------------------------------------------------------------------
PROMPT_RECOLECTOR = """Eres Iris, la Recolectora (Agente 1) de una mesa financiera educativa.
Tu personalidad: curiosa y meticulosa; jamás inventas un dato.
Tarea: obtener datos REALES de la acción indicada con las herramientas de Alpha Vantage.
Reglas:
- Haz como máximo 2 consultas: cotización actual y datos generales de la empresa.
- NUNCA inventes cifras. Si un dato no está disponible, escribe null.
- roe y margen_neto: cópialos tal cual los da Alpha Vantage (ReturnOnEquityTTM, ProfitMargin),
  en decimal (0.25 = 25 %). No los conviertas.
- Responde SOLO con un JSON con estas claves exactas:
  ticker, nombre, sector, precio, cambio_pct, fecha_dato, pe_ratio, beta,
  max_52s, min_52s, cap_mercado_usd, roe, margen_neto"""

DATOS_DEMO = {
    "nombre": "Empresa ficticia (simulación)", "sector": "Tecnología",
    "precio": 150.0, "cambio_pct": 1.2, "fecha_dato": "dato ficticio",
    "pe_ratio": 28.0, "beta": 1.25, "max_52s": 180.0, "min_52s": 120.0,
    "cap_mercado_usd": None, "roe": 0.22, "margen_neto": 0.18,
}


def ficha_demo(ticker, motivo):
    ficha = {"ticker": ticker, **DATOS_DEMO}
    ficha["fuente"] = f"DATOS DEMO, no son reales ({motivo})"
    return ficha


def agente_recolector(ticker):
    """Devuelve (ficha, herramientas_usadas)."""
    if config.MODO_SIMULACION:
        return ficha_demo(ticker, "modo simulación"), []
    try:
        texto, herramientas = llamar_claude(PROMPT_RECOLECTOR, f"Acción: {ticker}", usar_mcp=True)
        ficha = extraer_json(texto)
        ficha["ticker"] = ticker
        ficha["fuente"] = "Alpha Vantage vía MCP"
        return ficha, herramientas
    except Exception as error:                     # MCP caído, cuota agotada o JSON inválido
        return ficha_demo(ticker, f"MCP no disponible: {type(error).__name__}"), []


# ----------------------------------------------------------------------
# EULER · El Analista (Agente 2)
# ----------------------------------------------------------------------
def calcular_indicadores(ficha):
    """Cálculos deterministas (la IA no hace aritmética)."""
    precio, maximo, minimo = (a_numero(ficha.get(k)) for k in ("precio", "max_52s", "min_52s"))
    beta, pe = a_numero(ficha.get("beta")), a_numero(ficha.get("pe_ratio"))

    # Posición en el rango de 52 semanas: (P - min) / (max - min) × 100
    posicion = None
    if None not in (precio, maximo, minimo) and maximo > minimo:
        posicion = round((precio - minimo) / (maximo - minimo) * 100, 1)

    # Semáforo de beta (umbrales didácticos, no normativos)
    if beta is None:
        semaforo = "⚪ sin dato de beta"
    elif beta < 0.8:
        semaforo = "🟢 volatilidad baja"
    elif beta <= 1.2:
        semaforo = "🟡 volatilidad similar al mercado"
    else:
        semaforo = "🔴 volatilidad alta"

    roe, margen = a_porcentaje(ficha.get("roe")), a_porcentaje(ficha.get("margen_neto"))
    # Rendimiento de utilidades = 1 / (P/E) × 100: lo que "rinde" el negocio por cada dólar pagado
    rend_utilidades = round(100 / pe, 2) if pe and pe > 0 else None

    return {"posicion_rango_52s_pct": posicion, "semaforo_beta": semaforo,
            "beta": beta, "pe_ratio": pe, "cambio_pct": a_numero(ficha.get("cambio_pct")),
            "roe_pct": roe, "margen_neto_pct": margen, "rendimiento_utilidades_pct": rend_utilidades,
            **checklist_buffett(roe, margen, rend_utilidades, beta)}


def a_porcentaje(valor):
    """Alpha Vantage da ROE y margen en decimal (0.25). Si ya viene con '%', se respeta.

    Candado: si el modelo ignoró la instrucción y mandó 25 en vez de 0.25, un valor > 5
    sin '%' se toma como porcentaje (un ROE de 500 % o más es casi imposible)."""
    numero = a_numero(valor)
    if numero is None:
        return None
    ya_es_porcentaje = "%" in str(valor) or abs(numero) > 5
    return round(numero if ya_es_porcentaje else numero * 100, 1)


# Criterios estilo Buffett (umbrales didácticos, no son una regla de inversión)
def checklist_buffett(roe, margen, rend_utilidades, beta):
    """Cuenta cuántos criterios cumple; los que no tienen dato no cuentan ni a favor ni en contra."""
    criterios = [
        ("ROE ≥ 15 % (el negocio rinde sobre el capital)", roe, roe is not None and roe >= 15),
        ("Margen neto ≥ 10 % (poder de precio / foso)", margen, margen is not None and margen >= 10),
        ("Rendimiento de utilidades ≥ 5 % (P/E ≤ 20)", rend_utilidades,
         rend_utilidades is not None and rend_utilidades >= 5),
        ("Beta ≤ 1.2 (negocio estable, sin sobresaltos)", beta, beta is not None and beta <= 1.2),
    ]
    con_dato = sum(valor is not None for _, valor, _ in criterios)
    cumplidos = [nombre for nombre, _, cumple in criterios if cumple]
    if con_dato == 0:
        sello = "⚪ sin datos para el filtro de calidad"
    elif len(cumplidos) == con_dato == 4:
        sello = "🏰 negocio de calidad a precio razonable: vale estudiarlo a fondo"
    elif len(cumplidos) >= con_dato / 2:
        sello = "🔍 tiene cosas buenas, pero no pasa todos los filtros"
    else:
        sello = "⏸️ fuera de los criterios de calidad / precio"
    return {"criterios_cumplidos": cumplidos,
            "calificacion_buffett": f"{len(cumplidos)}/{con_dato} criterios con dato",
            "sello_buffett": sello}


PROMPT_ANALISTA = """Eres Euler, el Analista (Agente 2). Recibes la ficha de Iris y unos indicadores ya calculados.
Tu personalidad: piensas como un inversionista de valor al estilo de Warren Buffett. Eres paciente,
de largo plazo y con sentido común; el movimiento del día te parece ruido. Siempre te preguntas
"¿compraría este negocio completo y lo guardaría 10 años?". Hablas sencillo, con alguna analogía
cotidiana (una tiendita, un puente con foso), sin tecnicismos innecesarios.
Reglas:
- NO recalcules ni cambies cifras; interprétalas para un principiante.
- Usa el checklist (criterios_cumplidos, sello_buffett) como base de tu opinión.
- No inventes frases atribuidas a Buffett ni a nadie. No digas "compra" ni "vende".
Responde SOLO con JSON con las claves:
  lectura_precio (1 frase; recuerda que el precio de hoy importa poco a largo plazo),
  lectura_riesgo (1 frase sobre beta),
  lectura_valuacion (1 frase sobre P/E y rendimiento de utilidades, aclarando que depende del sector),
  lectura_calidad (1 frase sobre ROE y margen: ¿parece tener foso?),
  veredicto_largo_plazo (1 frase con el sello del checklist, sin recomendar),
  pregunta_para_investigar (1 pregunta sobre la ventaja competitiva del negocio)"""


def lectura_simulada(ind):
    pos = ind["posicion_rango_52s_pct"]
    lectura_precio = ("No hay datos suficientes para ubicar el precio en su rango anual." if pos is None else
                      f"El precio está al {pos} % de su rango de 52 semanas; a 10 años eso pesa poco.")
    return {
        "lectura_precio": lectura_precio,
        "lectura_riesgo": f"Semáforo de beta: {ind['semaforo_beta']}.",
        "lectura_valuacion": (f"Por cada 100 USD pagados, el negocio genera {ind['rendimiento_utilidades_pct']} USD "
                              "de utilidad al año; compáralo con su sector."),
        "lectura_calidad": f"ROE de {ind['roe_pct']} % y margen neto de {ind['margen_neto_pct']} %.",
        "veredicto_largo_plazo": f"{ind['sello_buffett']} ({ind['calificacion_buffett']}).",
        "pregunta_para_investigar": "¿Qué impide que un competidor le quite clientes a esta empresa?",
    }


def agente_analista(ficha):
    indicadores = calcular_indicadores(ficha)
    if config.MODO_SIMULACION:
        lectura = lectura_simulada(indicadores)
    else:
        entrada = json.dumps({"ficha": ficha, "indicadores": indicadores}, ensure_ascii=False)
        texto, _ = llamar_claude(PROMPT_ANALISTA, entrada)
        try:
            lectura = extraer_json(texto)
        except ValueError:
            lectura = {"lectura_precio": texto[:300]}
    return {"ficha": ficha, "indicadores": indicadores, "lectura": lectura}


# ----------------------------------------------------------------------
# VERA · La Comunicadora (Agente 3)
# ----------------------------------------------------------------------
PROMPT_COMUNICADOR = f"""Eres Vera, la Comunicadora (Agente 3). Con el análisis de Euler, redacta una nota para Telegram.
Tu personalidad: clara, breve y honesta sobre los límites del análisis.
- Máximo 900 caracteres, español claro, 3 a 5 emojis como máximo.
- Estructura: título con ticker · cifras clave · semáforo de riesgo · filtro de calidad de Euler
  (sello y calificación) · interpretación · pregunta para investigar.
- Usa solo las cifras recibidas; si la fuente dice DEMO, adviértelo en la primera línea.
- Cierra SIEMPRE con: "{DESCARGO}"
Texto plano, sin Markdown."""


def nota_simulada(analisis):
    f, ind, lec = analisis["ficha"], analisis["indicadores"], analisis["lectura"]
    return (f"{FIRMA_VERA}\n⚠️ {f['fuente']}\n"
            f"📊 {f['ticker']} · {f['nombre']}\n"
            f"Precio: {f['precio']} USD ({ind['cambio_pct']} % en el día)\n"
            f"Riesgo: {ind['semaforo_beta']} (beta {ind['beta']})\n"
            f"🏰 Filtro de calidad: {ind['sello_buffett']} ({ind['calificacion_buffett']})\n"
            f"{lec['lectura_precio']}\n"
            f"{lec['lectura_valuacion']}\n"
            f"{lec['lectura_calidad']}\n"
            f"🔎 {lec['pregunta_para_investigar']}\n\n{DESCARGO}")


def agente_comunicador(analisis):
    if config.MODO_SIMULACION:
        return nota_simulada(analisis)
    texto, _ = llamar_claude(PROMPT_COMUNICADOR, json.dumps(analisis, ensure_ascii=False), max_tokens=600)
    if DESCARGO not in texto:                      # garantía aunque el modelo lo olvide
        texto += f"\n\n{DESCARGO}"
    return f"{FIRMA_VERA}\n{texto}"
