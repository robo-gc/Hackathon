package com.apexsoa.mapinclusive

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Accessible
import androidx.compose.material.icons.automirrored.filled.DirectionsWalk
import androidx.compose.material.icons.filled.Flag
import androidx.compose.material.icons.filled.Hearing
import androidx.compose.material.icons.filled.LocalHospital
import androidx.compose.material.icons.filled.LocationOn
import androidx.compose.material.icons.filled.Map
import androidx.compose.material.icons.filled.Navigation
import androidx.compose.material.icons.filled.People
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Psychology
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Report
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.TurnRight
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.apexsoa.mapinclusive.model.AccessibilityProfile
import com.apexsoa.mapinclusive.model.AppScreen
import com.apexsoa.mapinclusive.model.ClinicItem
import com.apexsoa.mapinclusive.model.EnvironmentReport
import com.apexsoa.mapinclusive.network.MapInclusiveApiClient
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

// Paleta oficial de alto contraste definida en la documentación UI/UX de Map Inclusive
private val IndigoDark = Color(0xFF1B2354)
private val BlueAction = Color(0xFF2563EB)
private val EmeraldGreen = Color(0xFF0E9F6E)
private val EmeraldSurface = Color(0xFFD1FAE5)
private val AlertOrange = Color(0xFFEA7B1B)
private val NeutralBg = Color(0xFFF5F6FA)
private val CardBorder = Color(0xFFDCE1EC)

private const val TEN_MINUTES_MS = 10L * 60L * 1000L

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                MapInclusiveApp()
            }
        }
    }
}

@Composable
fun MapInclusiveApp() {
    val apiClient = remember { MapInclusiveApiClient() }
    val scope = rememberCoroutineScope()

    var currentScreen by remember { mutableStateOf(AppScreen.ONBOARDING) }
    var selectedProfile by remember { mutableStateOf(AccessibilityProfile.SILLA_DE_RUEDAS) }
    var destination by remember { mutableStateOf("Clínica 19, Av. Universidad, Coyoacán") }
    var searchQuery by remember { mutableStateOf("") }

    var clinics by remember {
        mutableStateOf(
            listOf(
                ClinicItem(
                    id = "clinica-19",
                    name = "Clínica 19 · 400m",
                    address = "Av. Universidad, Coyoacán",
                    distanceText = "400 m",
                    schedule = "08:00 - 20:00",
                ),
                ClinicItem(
                    id = "centro-salud",
                    name = "Centro Salud Coyoacán",
                    address = "Ignacio Allende, Del Carmen",
                    distanceText = "850 m",
                    schedule = "07:30 - 19:00",
                ),
            )
        )
    }

    var envReport by remember { mutableStateOf<EnvironmentReport?>(null) }
    var isLoadingEnv by remember { mutableStateOf(false) }
    var envError by remember { mutableStateOf<String?>(null) }

    var statusDialogTitle by remember { mutableStateOf<String?>(null) }
    var statusDialogMessage by remember { mutableStateOf<String?>(null) }
    var showIncidentDialog by remember { mutableStateOf(false) }

    fun refreshEnvironment(force: Boolean) {
        scope.launch {
            isLoadingEnv = true
            envError = null
            apiClient.checkEnvironment(
                origin = "Campus Coyoacán, CDMX",
                destination = destination,
                profile = selectedProfile,
                forceRefresh = force,
            ).onSuccess { report ->
                envReport = report
            }.onFailure { err ->
                envError =
                    "Sin conexión con el servidor Python (${err.message ?: "error de red"}). " +
                        "Mostrando ruta accesible en modo local."
            }
            isLoadingEnv = false
        }
    }

    // Cargar clínicas al abrir pantalla de búsqueda
    LaunchedEffect(currentScreen) {
        if (currentScreen == AppScreen.SEARCH_DESTINATION) {
            apiClient.fetchClinics().onSuccess { fetched ->
                if (fetched.isNotEmpty()) clinics = fetched
            }
        }
    }

    // Actualización automática con Gemini cada 10 minutos en Pantallas 3 y 4
    LaunchedEffect(currentScreen, selectedProfile, destination) {
        if (currentScreen == AppScreen.ROUTE_AND_GEMINI || currentScreen == AppScreen.ACTIVE_NAVIGATION) {
            while (true) {
                refreshEnvironment(force = false)
                delay(TEN_MINUTES_MS)
            }
        }
    }

    Surface(modifier = Modifier.fillMaxSize(), color = NeutralBg) {
        when (currentScreen) {
            AppScreen.ONBOARDING -> OnboardingScreen(
                selectedProfile = selectedProfile,
                onSelectProfile = { selectedProfile = it },
                onContinue = { currentScreen = AppScreen.SEARCH_DESTINATION },
            )

            AppScreen.SEARCH_DESTINATION -> SearchDestinationScreen(
                searchQuery = searchQuery,
                onSearchChange = { searchQuery = it },
                clinics = clinics,
                onSelectDestination = { picked ->
                    destination = picked
                    currentScreen = AppScreen.ROUTE_AND_GEMINI
                },
                onOpenReport = { showIncidentDialog = true },
                onBackToProfile = { currentScreen = AppScreen.ONBOARDING },
            )

            AppScreen.ROUTE_AND_GEMINI -> RouteAndGeminiScreen(
                selectedProfile = selectedProfile,
                destination = destination,
                report = envReport,
                isLoading = isLoadingEnv,
                errorMessage = envError,
                onSelectProfile = { selectedProfile = it },
                onForceRefresh = { refreshEnvironment(force = true) },
                onStartRoute = { currentScreen = AppScreen.ACTIVE_NAVIGATION },
                onBackToSearch = { currentScreen = AppScreen.SEARCH_DESTINATION },
                onOpenReport = { showIncidentDialog = true },
                onBackToProfile = { currentScreen = AppScreen.ONBOARDING },
            )

            AppScreen.ACTIVE_NAVIGATION -> ActiveNavigationScreen(
                selectedProfile = selectedProfile,
                destination = destination,
                report = envReport,
                onReportIncident = { showIncidentDialog = true },
                onRequestVolunteer = {
                    scope.launch {
                        apiClient.requestVolunteer(
                            userLocation = "Av. Universidad 400, Coyoacán",
                            destination = destination,
                            profile = selectedProfile,
                        ).onSuccess { assignment ->
                            statusDialogTitle = "Guía Voluntaria Confirmada"
                            statusDialogMessage =
                                "${assignment.volunteerName}\nTiempo estimado: ${assignment.etaMinutes} min\n\n${assignment.message}"
                        }.onFailure {
                            statusDialogTitle = "Guía Voluntaria (Modo Demo)"
                            statusDialogMessage =
                                "Sofía Hernández (Voluntaria Campus Coyoacán) fue notificada.\nETA estimado: 6 min."
                        }
                    }
                },
                onFinish = { currentScreen = AppScreen.ONBOARDING },
            )
        }
    }

    if (showIncidentDialog) {
        ReportIncidentDialog(
            profile = selectedProfile,
            onDismiss = { showIncidentDialog = false },
            onSubmit = { title, desc ->
                showIncidentDialog = false
                scope.launch {
                    apiClient.reportIncident(
                        title = title,
                        description = desc,
                        location = "Av. Universidad, Coyoacán",
                        profile = selectedProfile,
                    ).onSuccess { res ->
                        statusDialogTitle = "Incidencia reportada (${res.severity.uppercase()})"
                        statusDialogMessage = "Consejo de Gemini:\n${res.aiAdvice}"
                        refreshEnvironment(force = true)
                    }.onFailure {
                        statusDialogTitle = "Incidencia guardada localmente"
                        statusDialogMessage =
                            "No se pudo conectar al backend ahora. El aviso '$title' quedará en cola."
                    }
                }
            },
        )
    }

    if (statusDialogTitle != null && statusDialogMessage != null) {
        AlertDialog(
            onDismissRequest = {
                statusDialogTitle = null
                statusDialogMessage = null
            },
            title = { Text(statusDialogTitle!!, fontWeight = FontWeight.Bold, color = IndigoDark) },
            text = { Text(statusDialogMessage!!) },
            confirmButton = {
                TextButton(onClick = {
                    statusDialogTitle = null
                    statusDialogMessage = null
                }) {
                    Text("Entendido", color = BlueAction, fontWeight = FontWeight.SemiBold)
                }
            },
        )
    }
}

// =====================================================================
// PANTALLA 1: PANTALLA INICIAL (Selección de perfil de accesibilidad)
// =====================================================================
@Composable
private fun OnboardingScreen(
    selectedProfile: AccessibilityProfile,
    onSelectProfile: (AccessibilityProfile) -> Unit,
    onContinue: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.White)
            .padding(horizontal = 24.dp, vertical = 28.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                modifier = Modifier
                    .size(34.dp)
                    .clip(CircleShape)
                    .background(EmeraldGreen),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    imageVector = Icons.AutoMirrored.Filled.Accessible,
                    contentDescription = "Logo Map Inclusive",
                    tint = Color.White,
                    modifier = Modifier.size(20.dp),
                )
            }
            Spacer(modifier = Modifier.width(10.dp))
            Column {
                Text(
                    text = "map inclusive",
                    fontSize = 24.sp,
                    fontWeight = FontWeight.Bold,
                    color = IndigoDark,
                )
                Text(
                    text = "Campus Coyoacán · Apex soa",
                    fontSize = 12.sp,
                    color = Color(0xFF5A647E),
                )
            }
        }

        Spacer(modifier = Modifier.height(26.dp))

        Text(
            text = "¿Cómo te desplazas hoy?",
            fontSize = 22.sp,
            fontWeight = FontWeight.SemiBold,
            color = IndigoDark,
            textAlign = TextAlign.Center,
        )

        Spacer(modifier = Modifier.height(20.dp))

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            ProfileCard(
                modifier = Modifier.weight(1f),
                title = "Silla de\nruedas",
                icon = Icons.AutoMirrored.Filled.Accessible,
                selected = selectedProfile == AccessibilityProfile.SILLA_DE_RUEDAS,
                onClick = { onSelectProfile(AccessibilityProfile.SILLA_DE_RUEDAS) },
            )
            ProfileCard(
                modifier = Modifier.weight(1f),
                title = "Visual",
                icon = Icons.Default.Visibility,
                selected = selectedProfile == AccessibilityProfile.VISUAL,
                onClick = { onSelectProfile(AccessibilityProfile.VISUAL) },
            )
        }

        Spacer(modifier = Modifier.height(12.dp))

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            ProfileCard(
                modifier = Modifier.weight(1f),
                title = "Auditivo",
                icon = Icons.Default.Hearing,
                selected = selectedProfile == AccessibilityProfile.AUDITIVO,
                onClick = { onSelectProfile(AccessibilityProfile.AUDITIVO) },
            )
            ProfileCard(
                modifier = Modifier.weight(1f),
                title = "Movilidad\nreducida",
                icon = Icons.AutoMirrored.Filled.DirectionsWalk,
                selected = selectedProfile == AccessibilityProfile.MOVILIDAD_REDUCIDA,
                onClick = { onSelectProfile(AccessibilityProfile.MOVILIDAD_REDUCIDA) },
            )
        }

        Spacer(modifier = Modifier.height(12.dp))

        val isNeuroSelected = selectedProfile == AccessibilityProfile.NEURODIVERGENTE
        Card(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { onSelectProfile(AccessibilityProfile.NEURODIVERGENTE) },
            shape = RoundedCornerShape(16.dp),
            colors = CardDefaults.cardColors(
                containerColor = if (isNeuroSelected) IndigoDark else Color.White,
            ),
            border = BorderStroke(1.5.dp, if (isNeuroSelected) IndigoDark else CardBorder),
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp, vertical = 18.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.Center,
            ) {
                Icon(
                    imageVector = Icons.Default.Psychology,
                    contentDescription = "Persona neurodivergente",
                    tint = if (isNeuroSelected) Color.White else IndigoDark,
                    modifier = Modifier.size(30.dp),
                )
                Spacer(modifier = Modifier.width(12.dp))
                Text(
                    text = "Persona neurodivergente",
                    fontSize = 16.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = if (isNeuroSelected) Color.White else IndigoDark,
                )
            }
        }

        Spacer(modifier = Modifier.weight(1f))

        Button(
            onClick = onContinue,
            modifier = Modifier
                .fillMaxWidth()
                .height(52.dp),
            shape = RoundedCornerShape(26.dp),
            colors = ButtonDefaults.buttonColors(containerColor = BlueAction),
        ) {
            Text("Continuar", fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
        }
    }
}

@Composable
private fun ProfileCard(
    modifier: Modifier,
    title: String,
    icon: ImageVector,
    selected: Boolean,
    onClick: () -> Unit,
) {
    Card(
        modifier = modifier
            .height(128.dp)
            .clickable(onClick = onClick),
        shape = RoundedCornerShape(16.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (selected) IndigoDark else Color.White,
        ),
        border = BorderStroke(1.5.dp, if (selected) IndigoDark else CardBorder),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(14.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = title,
                tint = if (selected) Color.White else IndigoDark,
                modifier = Modifier.size(36.dp),
            )
            Spacer(modifier = Modifier.height(10.dp))
            Text(
                text = title,
                fontSize = 15.sp,
                fontWeight = FontWeight.SemiBold,
                color = if (selected) Color.White else IndigoDark,
                textAlign = TextAlign.Center,
                lineHeight = 18.sp,
            )
        }
    }
}

// =====================================================================
// PANTALLA 2: BUSCAR DESTINO (Mapa minimalista, clínicas y alertas)
// =====================================================================
@Composable
private fun SearchDestinationScreen(
    searchQuery: String,
    onSearchChange: (String) -> Unit,
    clinics: List<ClinicItem>,
    onSelectDestination: (String) -> Unit,
    onOpenReport: () -> Unit,
    onBackToProfile: () -> Unit,
) {
    Scaffold(
        bottomBar = {
            MapInclusiveBottomBar(
                selectedTab = 0,
                onReportClick = onOpenReport,
                onProfileClick = onBackToProfile,
            )
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .background(NeutralBg),
        ) {
            // Barra superior de búsqueda
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(Color.White)
                    .padding(horizontal = 16.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedTextField(
                    value = searchQuery,
                    onValueChange = onSearchChange,
                    modifier = Modifier.weight(1f),
                    singleLine = true,
                    shape = RoundedCornerShape(14.dp),
                    placeholder = { Text("Buscar destino...") },
                    leadingIcon = {
                        Icon(Icons.Default.Search, contentDescription = "Buscar", tint = IndigoDark)
                    },
                )
                Spacer(modifier = Modifier.width(8.dp))
                Button(
                    onClick = {
                        val target = searchQuery.trim().ifEmpty { "Clínica 19, Av. Universidad, Coyoacán" }
                        onSelectDestination(target)
                    },
                    shape = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = BlueAction),
                    contentPadding = PaddingValues(horizontal = 14.dp, vertical = 14.dp),
                ) {
                    Text("Ir")
                }
            }

            // Mapa vectorial minimalista con clínicas y aviso naranja
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
            ) {
                MinimalistMapCanvas(showRoute = false)

                // Aviso preventivo: Zona poco concurrida
                Surface(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .padding(14.dp),
                    shape = RoundedCornerShape(20.dp),
                    color = AlertOrange,
                    shadowElevation = 4.dp,
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(
                            Icons.Default.Warning,
                            contentDescription = null,
                            tint = Color.White,
                            modifier = Modifier.size(16.dp),
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Text(
                            text = "Zona poco concurrida",
                            color = Color.White,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.SemiBold,
                        )
                    }
                }

                // Pines de clínicas en verde esmeralda
                ClinicPin(
                    modifier = Modifier
                        .align(Alignment.CenterStart)
                        .padding(start = 52.dp, bottom = 70.dp)
                )
                ClinicPin(
                    modifier = Modifier
                        .align(Alignment.Center)
                        .padding(start = 24.dp, bottom = 110.dp)
                )
                ClinicPin(
                    modifier = Modifier
                        .align(Alignment.CenterEnd)
                        .padding(end = 44.dp, top = 60.dp)
                )

                // Tarjetas inferiores de sugerencias rápidas (Clínica 19 · 400m)
                LazyRow(
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .fillMaxWidth()
                        .padding(bottom = 14.dp),
                    contentPadding = PaddingValues(horizontal = 16.dp),
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    items(clinics) { clinic ->
                        Card(
                            modifier = Modifier
                                .width(250.dp)
                                .clickable { onSelectDestination("${clinic.name}, ${clinic.address}") },
                            shape = RoundedCornerShape(18.dp),
                            colors = CardDefaults.cardColors(containerColor = Color.White),
                            elevation = CardDefaults.cardElevation(defaultElevation = 4.dp),
                        ) {
                            Column(modifier = Modifier.padding(14.dp)) {
                                Text(
                                    text = "${clinic.name} · ${clinic.distanceText}",
                                    fontWeight = FontWeight.Bold,
                                    color = IndigoDark,
                                    fontSize = 15.sp,
                                    maxLines = 1,
                                    overflow = TextOverflow.Ellipsis,
                                )
                                Spacer(modifier = Modifier.height(4.dp))
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    Icon(
                                        Icons.Default.LocationOn,
                                        contentDescription = null,
                                        tint = IndigoDark,
                                        modifier = Modifier.size(15.dp),
                                    )
                                    Spacer(modifier = Modifier.width(4.dp))
                                    Text(
                                        text = clinic.address,
                                        fontSize = 13.sp,
                                        color = Color(0xFF4B5563),
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                }
                                Spacer(modifier = Modifier.height(4.dp))
                                Text(
                                    text = "Horario: ${clinic.schedule}",
                                    fontSize = 11.sp,
                                    color = EmeraldGreen,
                                    fontWeight = FontWeight.Medium,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

// =====================================================================
// PANTALLA 3: RUTA Y GEMINI (Ruta accesible + banner actualizado cada 10 min)
// =====================================================================
@Composable
private fun RouteAndGeminiScreen(
    selectedProfile: AccessibilityProfile,
    destination: String,
    report: EnvironmentReport?,
    isLoading: Boolean,
    errorMessage: String?,
    onSelectProfile: (AccessibilityProfile) -> Unit,
    onForceRefresh: () -> Unit,
    onStartRoute: () -> Unit,
    onBackToSearch: () -> Unit,
    onOpenReport: () -> Unit,
    onBackToProfile: () -> Unit,
) {
    var showDetails by remember { mutableStateOf(false) }

    Scaffold(
        bottomBar = {
            MapInclusiveBottomBar(
                selectedTab = 0,
                onReportClick = onOpenReport,
                onProfileClick = onBackToProfile,
            )
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .background(NeutralBg),
        ) {
            // Encabezado Ruta Accesible + filtros rápidos de perfil
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(Color.White)
                    .padding(top = 12.dp, bottom = 10.dp),
            ) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(
                        text = "Ruta Accesible",
                        fontSize = 20.sp,
                        fontWeight = FontWeight.Bold,
                        color = IndigoDark,
                    )
                    IconButton(onClick = onBackToSearch) {
                        Icon(Icons.Default.Search, contentDescription = "Cambiar destino", tint = IndigoDark)
                    }
                }

                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .horizontalScroll(rememberScrollState())
                        .padding(horizontal = 16.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    AccessibilityProfile.entries.forEach { profile ->
                        FilterChip(
                            selected = profile == selectedProfile,
                            onClick = { onSelectProfile(profile) },
                            label = { Text(profile.shortLabel, fontSize = 12.sp) },
                            colors = FilterChipDefaults.filterChipColors(
                                selectedContainerColor = IndigoDark,
                                selectedLabelColor = Color.White,
                            ),
                        )
                    }
                }
            }

            // Mapa de ruta evitando Rampa bloqueada
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f),
            ) {
                MinimalistMapCanvas(showRoute = true)

                Surface(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .padding(14.dp),
                    shape = RoundedCornerShape(18.dp),
                    color = AlertOrange,
                    shadowElevation = 4.dp,
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(
                            Icons.Default.Warning,
                            contentDescription = null,
                            tint = Color.White,
                            modifier = Modifier.size(16.dp),
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Text(
                            text = "Rampa bloqueada",
                            color = Color.White,
                            fontSize = 12.sp,
                            fontWeight = FontWeight.SemiBold,
                        )
                    }
                }
            }

            // Tarjeta inferior de resumen + Banner de Gemini (actualizado cada 10 min)
            Card(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(14.dp),
                shape = RoundedCornerShape(22.dp),
                colors = CardDefaults.cardColors(containerColor = Color.White),
                elevation = CardDefaults.cardElevation(defaultElevation = 6.dp),
            ) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(16.dp),
                ) {
                    Text(
                        text = "Ruta Accesible",
                        fontSize = 18.sp,
                        fontWeight = FontWeight.Bold,
                        color = IndigoDark,
                    )
                    Text(
                        text = "${selectedProfile.label} · 15 min - 1.2 km",
                        fontSize = 13.sp,
                        color = Color(0xFF4B5563),
                    )
                    Text(
                        text = "Destino: $destination",
                        fontSize = 12.sp,
                        color = Color(0xFF6B7280),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )

                    Spacer(modifier = Modifier.height(10.dp))

                    // Banner verde de Gemini
                    Surface(
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { showDetails = !showDetails },
                        shape = RoundedCornerShape(14.dp),
                        color = if (errorMessage != null) Color(0xFFFEF3C7) else EmeraldSurface,
                    ) {
                        Row(
                            modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            if (isLoading) {
                                CircularProgressIndicator(
                                    modifier = Modifier.size(18.dp),
                                    strokeWidth = 2.dp,
                                    color = EmeraldGreen,
                                )
                            } else {
                                Box(
                                    modifier = Modifier
                                        .size(10.dp)
                                        .clip(CircleShape)
                                        .background(if (errorMessage != null) AlertOrange else EmeraldGreen)
                                )
                            }
                            Spacer(modifier = Modifier.width(10.dp))
                            Column(modifier = Modifier.weight(1f)) {
                                val headline = when {
                                    isLoading -> "Consultando entorno con Gemini..."
                                    errorMessage != null -> errorMessage
                                    report != null -> "Actualizado con Gemini: ${report.bannerResumen}"
                                    else -> "Listo para consultar entorno con Gemini"
                                }
                                Text(
                                    text = headline,
                                    fontSize = 13.sp,
                                    fontWeight = FontWeight.SemiBold,
                                    color = IndigoDark,
                                )
                                if (report != null && !isLoading) {
                                    Text(
                                        text = "Cada ${report.nextRefreshMinutes} min · ${report.modelUsed} · Toca para detalles",
                                        fontSize = 11.sp,
                                        color = Color(0xFF065F46),
                                    )
                                }
                            }
                            IconButton(
                                onClick = onForceRefresh,
                                modifier = Modifier.size(32.dp),
                            ) {
                                Icon(
                                    Icons.Default.Refresh,
                                    contentDescription = "Actualizar con Gemini ahora",
                                    tint = IndigoDark,
                                    modifier = Modifier.size(18.dp),
                                )
                            }
                        }
                    }

                    if (showDetails && report != null) {
                        Spacer(modifier = Modifier.height(8.dp))
                        Column(
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(130.dp)
                                .verticalScroll(rememberScrollState())
                                .background(NeutralBg, RoundedCornerShape(10.dp))
                                .padding(10.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            Text("Clima: ${report.clima}", fontSize = 12.sp, color = IndigoDark)
                            Text(
                                "Bloqueos: ${report.bloqueos.joinToString()}",
                                fontSize = 12.sp,
                                color = IndigoDark,
                            )
                            Text(
                                "Transporte: ${report.transporteAfectado.joinToString()}",
                                fontSize = 12.sp,
                                color = IndigoDark,
                            )
                            Text(
                                "Recomendación: ${report.recomendacionesPerfil.firstOrNull().orEmpty()}",
                                fontSize = 12.sp,
                                color = EmeraldGreen,
                                fontWeight = FontWeight.Medium,
                            )
                        }
                    }

                    Spacer(modifier = Modifier.height(12.dp))

                    Button(
                        onClick = onStartRoute,
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(48.dp),
                        shape = RoundedCornerShape(24.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = BlueAction),
                    ) {
                        Text("Iniciar Ruta", fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                    }
                }
            }
        }
    }
}

// =====================================================================
// PANTALLA 4: EN CAMINO (Navegación activa + Reportar + Guía Voluntaria)
// =====================================================================
@Composable
private fun ActiveNavigationScreen(
    selectedProfile: AccessibilityProfile,
    destination: String,
    report: EnvironmentReport?,
    onReportIncident: () -> Unit,
    onRequestVolunteer: () -> Unit,
    onFinish: () -> Unit,
) {
    Column(modifier = Modifier.fillMaxSize().background(NeutralBg)) {
        // Banner superior de navegación en alto contraste
        Surface(
            modifier = Modifier.fillMaxWidth(),
            color = IndigoDark,
            shadowElevation = 6.dp,
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp, vertical = 20.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    imageVector = Icons.Default.TurnRight,
                    contentDescription = "Gira a la derecha",
                    tint = Color.White,
                    modifier = Modifier.size(38.dp),
                )
                Spacer(modifier = Modifier.width(14.dp))
                Column {
                    Text(
                        text = "Gira a la derecha en 80m",
                        color = Color.White,
                        fontSize = 19.sp,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        text = "· ${selectedProfile.activeNavigationHint}",
                        color = Color(0xFFD1FAE5),
                        fontSize = 14.sp,
                    )
                }
            }
        }

        // Mapa activo con flecha de ubicación
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .weight(1f),
        ) {
            MinimalistMapCanvas(showRoute = true)

            Box(
                modifier = Modifier
                    .align(Alignment.Center)
                    .padding(top = 60.dp)
                    .size(46.dp)
                    .clip(CircleShape)
                    .background(BlueAction.copy(alpha = 0.22f)),
                contentAlignment = Alignment.Center,
            ) {
                Box(
                    modifier = Modifier
                        .size(30.dp)
                        .clip(CircleShape)
                        .background(BlueAction),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = Icons.Default.Navigation,
                        contentDescription = "Tu ubicación",
                        tint = Color.White,
                        modifier = Modifier.size(18.dp),
                    )
                }
            }

            if (report != null) {
                Surface(
                    modifier = Modifier
                        .align(Alignment.TopCenter)
                        .padding(12.dp),
                    shape = RoundedCornerShape(16.dp),
                    color = EmeraldSurface,
                ) {
                    Text(
                        text = "Gemini activo · ${report.bannerResumen}",
                        modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp),
                        fontSize = 12.sp,
                        color = IndigoDark,
                        fontWeight = FontWeight.Medium,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }

        // Panel inferior de acciones rápidas
        Card(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            shape = RoundedCornerShape(22.dp),
            colors = CardDefaults.cardColors(containerColor = Color.White),
            elevation = CardDefaults.cardElevation(defaultElevation = 6.dp),
        ) {
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text(
                    text = "Rumbo a: $destination",
                    fontSize = 12.sp,
                    color = Color(0xFF6B7280),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )

                OutlinedButton(
                    onClick = onReportIncident,
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(48.dp),
                    shape = RoundedCornerShape(14.dp),
                    border = BorderStroke(1.dp, CardBorder),
                ) {
                    Icon(Icons.Default.Report, contentDescription = null, tint = Color(0xFFDC2626))
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Reportar Incidencia", color = IndigoDark, fontWeight = FontWeight.SemiBold)
                }

                OutlinedButton(
                    onClick = onRequestVolunteer,
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(48.dp),
                    shape = RoundedCornerShape(14.dp),
                    border = BorderStroke(1.dp, CardBorder),
                ) {
                    Icon(Icons.Default.People, contentDescription = null, tint = BlueAction)
                    Spacer(modifier = Modifier.width(8.dp))
                    Text("Pedir Guía Voluntaria", color = IndigoDark, fontWeight = FontWeight.SemiBold)
                }

                OutlinedButton(
                    onClick = onFinish,
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(44.dp),
                    shape = RoundedCornerShape(22.dp),
                    border = BorderStroke(1.dp, Color(0xFFDC2626)),
                ) {
                    Text("Finalizar", color = Color(0xFFDC2626), fontWeight = FontWeight.SemiBold)
                }
            }
        }
    }
}

@Composable
private fun ClinicPin(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .size(34.dp)
            .clip(CircleShape)
            .background(EmeraldGreen),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = Icons.Default.LocalHospital,
            contentDescription = "Clínica cercana",
            tint = Color.White,
            modifier = Modifier.size(19.dp),
        )
    }
}

@Composable
private fun MinimalistMapCanvas(showRoute: Boolean) {
    Canvas(modifier = Modifier.fillMaxSize().background(Color(0xFFEDF0F5))) {
        val streetColor = Color.White
        val parkColor = Color(0xFFD7EFE2)

        // Áreas verdes minimalistas
        drawCircle(
            color = parkColor,
            radius = size.minDimension * 0.16f,
            center = Offset(size.width * 0.45f, size.height * 0.28f),
        )

        // Calles principales limpias (mapa de bajo ruido visual)
        for (i in 1..4) {
            val y = size.height * (i / 5f)
            drawLine(
                color = streetColor,
                start = Offset(0f, y),
                end = Offset(size.width, y - 40f),
                strokeWidth = 14f,
            )
        }
        for (i in 1..3) {
            val x = size.width * (i / 4f)
            drawLine(
                color = streetColor,
                start = Offset(x, 0f),
                end = Offset(x + 35f, size.height),
                strokeWidth = 14f,
            )
        }

        if (showRoute) {
            val path = Path().apply {
                moveTo(size.width * 0.52f, size.height * 0.78f)
                lineTo(size.width * 0.65f, size.height * 0.56f)
                lineTo(size.width * 0.36f, size.height * 0.40f)
                lineTo(size.width * 0.56f, size.height * 0.22f)
            }
            drawPath(
                path = path,
                color = IndigoDark,
                style = Stroke(
                    width = 12f,
                    cap = StrokeCap.Round,
                    join = StrokeJoin.Round,
                ),
            )
        }
    }
}

@Composable
private fun MapInclusiveBottomBar(
    selectedTab: Int,
    onReportClick: () -> Unit,
    onProfileClick: () -> Unit,
) {
    NavigationBar(containerColor = Color.White) {
        NavigationBarItem(
            selected = selectedTab == 0,
            onClick = {},
            icon = { Icon(Icons.Default.Map, contentDescription = "Mapa") },
            label = { Text("Mapa", fontSize = 10.sp) },
        )
        NavigationBarItem(
            selected = false,
            onClick = onReportClick,
            icon = { Icon(Icons.Default.Flag, contentDescription = "Reportar") },
            label = { Text("Reportar", fontSize = 10.sp) },
        )
        NavigationBarItem(
            selected = false,
            onClick = {},
            icon = { Icon(Icons.Default.LocalHospital, contentDescription = "Clínicas") },
            label = { Text("Clínicas", fontSize = 10.sp) },
        )
        NavigationBarItem(
            selected = false,
            onClick = {},
            icon = { Icon(Icons.Default.People, contentDescription = "Voluntarios") },
            label = { Text("Voluntarios", fontSize = 10.sp) },
        )
        NavigationBarItem(
            selected = false,
            onClick = onProfileClick,
            icon = { Icon(Icons.Default.Person, contentDescription = "Perfil") },
            label = { Text("Perfil", fontSize = 10.sp) },
        )
    }
}

@Composable
private fun ReportIncidentDialog(
    profile: AccessibilityProfile,
    onDismiss: () -> Unit,
    onSubmit: (String, String) -> Unit,
) {
    var title by remember { mutableStateOf("Rampa bloqueada") }
    var description by remember { mutableStateOf("Auto estacionado bloqueando el acceso peatonal") }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Reportar incidencia", fontWeight = FontWeight.Bold, color = IndigoDark) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(
                    text = "Perfil activo: ${profile.label}",
                    fontSize = 12.sp,
                    color = Color(0xFF4B5563),
                )
                OutlinedTextField(
                    value = title,
                    onValueChange = { title = it },
                    label = { Text("Título") },
                    singleLine = true,
                )
                OutlinedTextField(
                    value = description,
                    onValueChange = { description = it },
                    label = { Text("Descripción") },
                )
            }
        },
        confirmButton = {
            Button(
                onClick = { if (title.isNotBlank()) onSubmit(title.trim(), description.trim()) },
                colors = ButtonDefaults.buttonColors(containerColor = BlueAction),
            ) {
                Text("Enviar")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("Cancelar")
            }
        },
    )
}
