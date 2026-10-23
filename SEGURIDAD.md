# Seguridad de la Mesa Financiera

Le pedí a Claude una revisión de seguridad del proyecto. Abajo están las recomendaciones y lo que hice con cada una.

| # | Riesgo encontrado | Qué cambié | Dónde |
|---|---|---|---|
| 1 | Si `TELEGRAM_CHAT_ID` quedaba vacío, **cualquiera** que encontrara el bot podía usarlo y gastar mis créditos de Claude y Alpha Vantage. | Ahora falla cerrado: sin chat configurado no responde a nadie. | `mesa/telegram_io.py` |
| 2 | Las Actions se usaban por etiqueta (`@v7`). Si alguien mueve esa etiqueta a otro código, mi workflow lo correría con mis Secrets. | Las fijé por commit (SHA). | `.github/workflows/*.yml` |
| 3 | Al fijar versiones ya no llegan parches solas. | Activé Dependabot para Actions y pip (revisa cada semana y abre un PR). | `.github/dependabot.yml` |
| 4 | Un error de conexión imprime la URL de Telegram, y esa URL **trae el token**. GitHub lo tapa en sus logs, pero en mi compu o en Codespaces no. | Todos los errores se imprimen pasando por `ocultar_secretos()`. | `mesa/config.py`, `revisar_telegram.py`, `bot_continuo.py` |
| 5 | `checkout` dejaba guardado el token de GitHub en el runner. | `persist-credentials: false`. | workflows |
| 6 | Si faltaba una llave, el bot pasaba a simulación sin avisar (me pasó: la nota decía "modo SIMULACIÓN"). | Agregué un paso que avisa qué Secret falta, sin mostrar valores. | `mesa-financiera.yml` |
| 7 | El repo es público y las evidencias se guardaban 14 días. | Bajé la retención a 7 días. | `mesa-financiera.yml` |
| 8 | Las librerías no tenían tope de versión: una versión mayor nueva podía romper el bot sin aviso. | Les puse tope (`<2`, `<3`). | `requirements.txt` |

## Lo que ya venía bien y mantuve
- Llaves solo en **GitHub Secrets** / `.env` (y `.env` está en `.gitignore`).
- `permissions: contents: read`: el workflow no puede modificar el repo.
- El ticker se valida con una regex y se pasa como variable de entorno, no pegado dentro del comando (evita inyección).
- El texto de Telegram nunca llega directo a la IA: solo pasa el ticker ya validado.
- Límite de 3 análisis por ejecución para cuidar la cuota.

## Pendiente / límites
- La llave de Alpha Vantage va en la URL del MCP (así lo pide el servidor), entonces Anthropic la ve. No hay forma de evitarlo con este MCP.
- Si alguna vez una llave se ve en un log o en un commit, hay que **rotarla** (generar una nueva), no solo borrarla.
