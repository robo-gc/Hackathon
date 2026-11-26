# Map Inclusive — Prueba Corta (Python + Android + Gemini API)

**Equipo:** Apex soa (Márquez Fuentes Sebastian, Calderón Pérez Emiliano Javier, Nelson Alejandro Gonzalez Al Daoud)  
**Campus:** Coyoacán

![Boceto Secuencial UI/UX](docs/boceto_secuencial.jpg)

---

## Arquitectura de la prueba corta

```text
[App Android (Kotlin + Jetpack Compose)]
     │  HTTP JSON (actualización automática cada 10 min)
     ▼
[Backend Python (FastAPI)]
     │  SDK oficial google-genai >= 3.5.0 (Interactions API)
     ▼
[Google Gemini (gemini-4-hydrogen + Google Search Grounding + Structured Output)]
```

### ¿Qué función de Gemini se integró?

1. **Monitor de Entorno Urbano cada 10 minutos (`POST /api/v1/environment-check`):**
   - Usa **`gemini-4-hydrogen`** mediante `client.interactions.create(...)` con **Google Search Grounding** (`{"type": "google_search"}`) y **Structured Output** (`response_format` JSON Schema).
   - Recopila clima, bloqueos viales/peatonales, transporte fuera de servicio, incidencias de accesibilidad y zonas de riesgo, y genera un resumen corto listo para el banner verde de la Pantalla 3 (*"Actualizado con Gemini: ..."*) más recomendaciones específicas según el perfil elegido (`silla_de_ruedas`, `visual`, `auditivo`, `movilidad_reducida` y `neurodivergente`).
   - Incluye **caché de 10 minutos (600 s)** y **manejo sin conexión (`offline_demo`)** cuando no hay API key o internet.
2. **Clasificación rápida de incidencias ciudadanas (`POST /api/v1/incidents`):**
   - Al reportar un obstáculo desde la Pantalla 4 (*"Rampa bloqueada"*), Gemini evalúa la severidad (`bajo` | `medio` | `alto`), genera un consejo inmediato y actualiza el contexto de la siguiente consulta de ruta.

---

## 1. Probar en Python (en 1 minuto)

### Instalación
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Configurar tu API Key de Gemini (opcional para pruebas locales)
```bash
cp .env.example .env
# Edita backend/.env y coloca tu GEMINI_API_KEY de https://aistudio.google.com/apikey
```
> Si todavía no colocas `GEMINI_API_KEY`, el backend responde en modo `offline_demo` para que puedas probar todo el flujo Python + Android de inmediato.

### Prueba rápida por terminal (sin levantar servidor)
```bash
# Consulta única
python3 backend/quick_test.py --profile silla_de_ruedas --destination "Clínica 19, Av. Universidad, Coyoacán"

# Probar perfil neurodivergente
python3 backend/quick_test.py --profile neurodivergente

# Probar actualización periódica (ej. cada 15 s para demo; por defecto 600 s = 10 min)
python3 backend/quick_test.py --loop --interval 15
```

### Levantar el servidor FastAPI para Android
```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
- Documentación interactiva Swagger: `http://localhost:8000/docs`
- Verificación de salud: `http://localhost:8000/health`

### Ejecutar pruebas automatizadas
```bash
pytest -v backend/tests/test_api.py
```

---

## 2. Probar en Android (Android Studio)

1. Abre la carpeta [`android/`](android/) en **Android Studio**.
2. Asegúrate de tener corriendo el servidor Python en el puerto `8000` (`uvicorn main:app --host 0.0.0.0 --port 8000`).
3. Ejecuta la app en un **Emulador Android**:
   - Por defecto apunta a `http://10.0.2.2:8000` (el `localhost` de tu PC desde el emulador).
   - Si pruebas en un **teléfono físico** en la misma red Wi-Fi, cambia `BACKEND_BASE_URL` en `android/app/build.gradle.kts` a `http://<IP_LOCAL_DE_TU_PC>:8000`.
4. Recorre las 4 pantallas del boceto:
   1. **Pantalla Inicial:** elige uno de los 5 perfiles de accesibilidad y toca **Continuar**.
   2. **Buscar Destino:** selecciona **Clínica 19 · 400m** o escribe un destino.
   3. **Ruta y Gemini:** observa el banner verde actualizado con Gemini (se refresca automáticamente cada 10 minutos o al tocar el botón de recarga; toca el banner para desplegar clima, bloqueos, transporte y recomendaciones).
   4. **En Camino:** prueba **Reportar Incidencia**, **Pedir Guía Voluntaria** y **Finalizar**.