package com.apexsoa.mapinclusive.model

enum class AccessibilityProfile(
    val apiValue: String,
    val label: String,
    val shortLabel: String,
    val activeNavigationHint: String,
) {
    SILLA_DE_RUEDAS(
        apiValue = "silla_de_ruedas",
        label = "Silla de ruedas",
        shortLabel = "Silla de ruedas",
        activeNavigationHint = "Rampa disponible",
    ),
    VISUAL(
        apiValue = "visual",
        label = "Visual",
        shortLabel = "Visual",
        activeNavigationHint = "Semáforo sonoro y guía táctil",
    ),
    AUDITIVO(
        apiValue = "auditivo",
        label = "Auditivo",
        shortLabel = "Auditivo",
        activeNavigationHint = "Cruce con señalización visual clara",
    ),
    MOVILIDAD_REDUCIDA(
        apiValue = "movilidad_reducida",
        label = "Movilidad reducida",
        shortLabel = "Mov. reducida",
        activeNavigationHint = "Pendiente suave y banca en 50 m",
    ),
    NEURODIVERGENTE(
        apiValue = "neurodivergente",
        label = "Persona neurodivergente",
        shortLabel = "Neurodivergente",
        activeNavigationHint = "Calle tranquila · menor ruido",
    ),
}

enum class AppScreen {
    ONBOARDING,
    SEARCH_DESTINATION,
    ROUTE_AND_GEMINI,
    ACTIVE_NAVIGATION,
}

data class ClinicItem(
    val id: String,
    val name: String,
    val address: String,
    val distanceText: String,
    val schedule: String,
)

data class EnvironmentReport(
    val statusMode: String,
    val fromCache: Boolean,
    val modelUsed: String,
    val updatedAt: String,
    val nextRefreshMinutes: Int,
    val bannerResumen: String,
    val clima: String,
    val bloqueos: List<String>,
    val transporteAfectado: List<String>,
    val incidenciasAccesibilidad: List<String>,
    val zonasRiesgo: List<String>,
    val recomendacionesPerfil: List<String>,
    val nivelRiesgo: String,
)

data class IncidentSubmissionResult(
    val id: String,
    val title: String,
    val severity: String,
    val aiAdvice: String,
)

data class VolunteerAssignment(
    val requestId: String,
    val volunteerName: String,
    val etaMinutes: Int,
    val message: String,
)
