package com.apexsoa.mapinclusive.network

import com.apexsoa.mapinclusive.BuildConfig
import com.apexsoa.mapinclusive.model.AccessibilityProfile
import com.apexsoa.mapinclusive.model.ClinicItem
import com.apexsoa.mapinclusive.model.EnvironmentReport
import com.apexsoa.mapinclusive.model.IncidentSubmissionResult
import com.apexsoa.mapinclusive.model.VolunteerAssignment
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.BufferedReader
import java.io.OutputStreamWriter
import java.net.HttpURLConnection
import java.net.URL

class MapInclusiveApiClient(
    private val baseUrl: String = BuildConfig.BACKEND_BASE_URL,
) {
    suspend fun checkEnvironment(
        origin: String,
        destination: String,
        profile: AccessibilityProfile,
        forceRefresh: Boolean = false,
    ): Result<EnvironmentReport> = withContext(Dispatchers.IO) {
        runCatching {
            val payload = JSONObject().apply {
                put("origin", origin)
                put("destination", destination)
                put("profile", profile.apiValue)
                put("latitude", 19.3498)
                put("longitude", -99.1617)
                put("force_refresh", forceRefresh)
            }
            val raw = postJson("$baseUrl/api/v1/environment-check", payload)
            val json = JSONObject(raw)
            EnvironmentReport(
                statusMode = json.optString("status_mode", "offline_demo"),
                fromCache = json.optBoolean("from_cache", false),
                modelUsed = json.optString("model_used", "gemini-4-hydrogen"),
                updatedAt = json.optString("updated_at", ""),
                nextRefreshMinutes = json.optInt("next_refresh_minutes", 10),
                bannerResumen = json.optString("banner_resumen", "Clima despejado, sin bloqueos"),
                clima = json.optString("clima", "Sin dato de clima"),
                bloqueos = json.optJSONArray("bloqueos").toStringList(),
                transporteAfectado = json.optJSONArray("transporte_afectado").toStringList(),
                incidenciasAccesibilidad = json.optJSONArray("incidencias_accesibilidad").toStringList(),
                zonasRiesgo = json.optJSONArray("zonas_riesgo").toStringList(),
                recomendacionesPerfil = json.optJSONArray("recomendaciones_perfil").toStringList(),
                nivelRiesgo = json.optString("nivel_riesgo", "bajo"),
            )
        }
    }

    suspend fun fetchClinics(): Result<List<ClinicItem>> = withContext(Dispatchers.IO) {
        runCatching {
            val raw = getJson("$baseUrl/api/v1/clinics")
            val array = JSONArray(raw)
            buildList {
                for (i in 0 until array.length()) {
                    val obj = array.getJSONObject(i)
                    add(
                        ClinicItem(
                            id = obj.optString("id"),
                            name = obj.optString("name"),
                            address = obj.optString("address"),
                            distanceText = obj.optString("distance_text"),
                            schedule = obj.optString("schedule"),
                        )
                    )
                }
            }
        }
    }

    suspend fun reportIncident(
        title: String,
        description: String,
        location: String,
        profile: AccessibilityProfile,
    ): Result<IncidentSubmissionResult> = withContext(Dispatchers.IO) {
        runCatching {
            val payload = JSONObject().apply {
                put("title", title)
                put("description", description)
                put("location", location)
                put("profile", profile.apiValue)
            }
            val raw = postJson("$baseUrl/api/v1/incidents", payload)
            val json = JSONObject(raw)
            IncidentSubmissionResult(
                id = json.optString("id"),
                title = json.optString("title"),
                severity = json.optString("severity", "medio"),
                aiAdvice = json.optString("ai_advice", "Reporte registrado."),
            )
        }
    }

    suspend fun requestVolunteer(
        userLocation: String,
        destination: String,
        profile: AccessibilityProfile,
    ): Result<VolunteerAssignment> = withContext(Dispatchers.IO) {
        runCatching {
            val payload = JSONObject().apply {
                put("user_location", userLocation)
                put("destination", destination)
                put("profile", profile.apiValue)
            }
            val raw = postJson("$baseUrl/api/v1/volunteer-request", payload)
            val json = JSONObject(raw)
            VolunteerAssignment(
                requestId = json.optString("request_id"),
                volunteerName = json.optString("volunteer_name"),
                etaMinutes = json.optInt("eta_minutes", 6),
                message = json.optString("message"),
            )
        }
    }

    private fun getJson(urlStr: String): String {
        val conn = (URL(urlStr).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 8000
            readTimeout = 20000
        }
        return readResponse(conn)
    }

    private fun postJson(urlStr: String, body: JSONObject): String {
        val conn = (URL(urlStr).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 8000
            readTimeout = 25000
            doOutput = true
            setRequestProperty("Content-Type", "application/json; charset=UTF-8")
        }
        OutputStreamWriter(conn.outputStream, Charsets.UTF_8).use { writer ->
            writer.write(body.toString())
        }
        return readResponse(conn)
    }

    private fun readResponse(conn: HttpURLConnection): String {
        return try {
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use(BufferedReader::readText).orEmpty()
            if (code !in 200..299) {
                throw IllegalStateException("HTTP $code: $text")
            }
            text
        } finally {
            conn.disconnect()
        }
    }

    private fun JSONArray?.toStringList(): List<String> {
        if (this == null) return emptyList()
        return buildList {
            for (i in 0 until length()) {
                add(optString(i))
            }
        }
    }
}
