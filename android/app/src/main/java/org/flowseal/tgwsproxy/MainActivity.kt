package org.flowseal.tgwsproxy

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.widget.ArrayAdapter
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatDelegate
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.isVisible
import androidx.core.widget.doAfterTextChanged
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import com.google.android.material.snackbar.Snackbar
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.flowseal.tgwsproxy.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
    private lateinit var settingsStore: ProxySettingsStore
    private var currentUpdateStatus: ProxyUpdateStatus? = null
    private val upstreamModeOptions by lazy {
        UpstreamMode.options.map { option ->
            option.value to getString(option.labelResId)
        }
    }
    private val appearanceOptions by lazy {
        appearanceModes().map { mode ->
            mode to appearanceLabelForValue(mode)
        }
    }

    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (!granted) {
            Toast.makeText(
                this,
                "Без уведомлений Android может скрыть foreground service.",
                Toast.LENGTH_LONG,
            ).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        val initialSettingsStore = ProxySettingsStore(this)
        applyAppearance(initialSettingsStore.load().appearance)
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        settingsStore = initialSettingsStore
        setContentView(binding.root)

        binding.startButton.setOnClickListener { onStartClicked() }
        binding.stopButton.setOnClickListener { ProxyForegroundService.stop(this) }
        binding.restartButton.setOnClickListener { onRestartClicked() }
        binding.saveButton.setOnClickListener { onSaveClicked(showMessage = true) }
        binding.openLogsButton.setOnClickListener { onOpenLogsClicked() }
        binding.openTelegramButton.setOnClickListener { onOpenTelegramClicked() }
        binding.openReleasePageButton.setOnClickListener { onOpenReleasePageClicked() }
        binding.donateButton.setOnClickListener { onOpenDonateClicked() }
        binding.secretRegenerateButton.setOnClickListener { onRegenerateSecretClicked() }
        binding.checkUpdatesSwitch.setOnCheckedChangeListener { _, _ ->
            renderUpdateStatus(currentUpdateStatus, binding.checkUpdatesSwitch.isChecked)
        }
        binding.cfProxySwitch.setOnCheckedChangeListener { _, isChecked ->
            renderCfProxyState(isChecked)
        }
        binding.cfProxyCustomDomainSwitch.setOnCheckedChangeListener { _, isChecked ->
            renderCustomCfProxyDomainState(isChecked)
        }
        binding.cfProxyTestButton.setOnClickListener { onCfProxyTestClicked() }
        binding.disableBatteryOptimizationButton.setOnClickListener {
            AndroidSystemStatus.openBatteryOptimizationSettings(this)
        }
        binding.openAppSettingsButton.setOnClickListener {
            AndroidSystemStatus.openAppSettings(this)
        }
        setupAppearanceDropdown()
        setupUpstreamModeDropdown()
        binding.relayUrlInput.doAfterTextChanged {
            renderUpstreamConfigState(
                selectedUpstreamModeValue(),
                it?.toString().orEmpty(),
            )
        }

        val config = settingsStore.load()
        renderConfig(config)
        if (config.checkUpdates) {
            refreshUpdateStatus(checkNow = true)
        } else {
            currentUpdateStatus = null
            renderUpdateStatus(null, false)
        }
        requestNotificationPermissionIfNeeded()
        observeServiceState()
        renderSystemStatus()
    }

    override fun onResume() {
        super.onResume()
        renderSystemStatus()
    }

    private fun onSaveClicked(showMessage: Boolean): NormalizedProxyConfig? {
        val validation = collectConfigFromForm().validate()
        val config = validation.normalized
        if (config == null) {
            binding.errorText.text = validation.errorMessage
            binding.errorText.isVisible = true
            return null
        }

        binding.errorText.isVisible = false
        settingsStore.save(config)
        applyAppearance(config.appearance)
        if (showMessage) {
            Snackbar.make(binding.root, R.string.settings_saved, Snackbar.LENGTH_SHORT).show()
        }
        if (config.checkUpdates) {
            refreshUpdateStatus(checkNow = true)
        } else {
            currentUpdateStatus = null
            renderUpdateStatus(null, false)
        }
        return config
    }

    private fun onStartClicked() {
        onSaveClicked(showMessage = false) ?: return
        ProxyForegroundService.start(this)
        Snackbar.make(binding.root, R.string.service_start_requested, Snackbar.LENGTH_SHORT).show()
    }

    private fun onRestartClicked() {
        onSaveClicked(showMessage = false) ?: return
        ProxyForegroundService.restart(this)
        Snackbar.make(binding.root, R.string.service_restart_requested, Snackbar.LENGTH_SHORT).show()
    }

    private fun onOpenLogsClicked() {
        startActivity(Intent(this, LogViewerActivity::class.java))
    }

    private fun onOpenTelegramClicked() {
        val config = onSaveClicked(showMessage = false) ?: return
        if (!TelegramProxyIntent.open(this, config)) {
            Snackbar.make(binding.root, R.string.telegram_not_found, Snackbar.LENGTH_LONG).show()
        }
    }

    private fun onRegenerateSecretClicked() {
        binding.secretInput.setText(ProxyConfig.generateSecretForUi())
    }

    private fun onOpenDonateClicked() {
        runCatching {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(FUNDING_URL)))
        }
    }

    private fun renderConfig(config: ProxyConfig) {
        binding.hostInput.setText(config.host)
        binding.portInput.setText(config.portText)
        binding.secretInput.setText(config.secretText)
        binding.appearanceInput.setText(appearanceLabelForValue(config.appearance), false)
        binding.dcIpInput.setText(config.dcIpText)
        binding.upstreamModeInput.setText(
            upstreamLabelForValue(config.upstreamMode),
            false,
        )
        binding.relayUrlInput.setText(config.relayUrlText)
        binding.relayTokenInput.setText(config.relayTokenText)
        binding.directWsTimeoutInput.setText(config.directWsTimeoutText)
        binding.cfProxySwitch.isChecked = config.cfproxy
        binding.cfProxyPrioritySwitch.isChecked = config.cfproxyPriority
        binding.cfProxyCustomDomainSwitch.isChecked = config.cfproxyUserDomainText.isNotBlank()
        binding.cfProxyUserDomainInput.setText(config.cfproxyUserDomainText)
        binding.logMaxMbInput.setText(config.logMaxMbText)
        binding.bufferKbInput.setText(config.bufferKbText)
        binding.poolSizeInput.setText(config.poolSizeText)
        binding.checkUpdatesSwitch.isChecked = config.checkUpdates
        binding.verboseSwitch.isChecked = config.verbose
        renderUpdateStatus(currentUpdateStatus, config.checkUpdates)
        renderUpstreamConfigState(
            config.upstreamMode,
            config.relayUrlText,
        )
        renderCfProxyState(config.cfproxy)
        renderCustomCfProxyDomainState(binding.cfProxyCustomDomainSwitch.isChecked)
    }

    private fun collectConfigFromForm(): ProxyConfig {
        return ProxyConfig(
            host = binding.hostInput.text?.toString().orEmpty(),
            portText = binding.portInput.text?.toString().orEmpty(),
            secretText = binding.secretInput.text?.toString().orEmpty(),
            appearance = selectedAppearanceValue(),
            dcIpText = binding.dcIpInput.text?.toString().orEmpty(),
            upstreamMode = selectedUpstreamModeValue(),
            relayUrlText = binding.relayUrlInput.text?.toString().orEmpty(),
            relayTokenText = binding.relayTokenInput.text?.toString().orEmpty(),
            directWsTimeoutText = binding.directWsTimeoutInput.text?.toString().orEmpty(),
            cfproxy = binding.cfProxySwitch.isChecked,
            cfproxyPriority = binding.cfProxyPrioritySwitch.isChecked,
            cfproxyUserDomainText = if (binding.cfProxyCustomDomainSwitch.isChecked) {
                binding.cfProxyUserDomainInput.text?.toString().orEmpty()
            } else {
                ""
            },
            logMaxMbText = binding.logMaxMbInput.text?.toString().orEmpty(),
            bufferKbText = binding.bufferKbInput.text?.toString().orEmpty(),
            poolSizeText = binding.poolSizeInput.text?.toString().orEmpty(),
            checkUpdates = binding.checkUpdatesSwitch.isChecked,
            verbose = binding.verboseSwitch.isChecked,
        )
    }

    private fun onOpenReleasePageClicked() {
        val url = currentUpdateStatus?.htmlUrl ?: "https://github.com/Dark-Avery/tg-ws-proxy/releases/latest"
        val opened = runCatching {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        }.isSuccess
        if (!opened) {
            Snackbar.make(binding.root, R.string.release_page_open_failed, Snackbar.LENGTH_LONG).show()
        }
    }

    private fun onCfProxyTestClicked() {
        val customDomain = if (binding.cfProxyCustomDomainSwitch.isChecked) {
            binding.cfProxyUserDomainInput.text?.toString().orEmpty().trim()
        } else {
            ""
        }
        if (binding.cfProxyCustomDomainSwitch.isChecked && customDomain.isBlank()) {
            Snackbar.make(
                binding.root,
                getString(R.string.cfproxy_test_failed, "empty custom domain"),
                Snackbar.LENGTH_LONG,
            ).show()
            return
        }

        lifecycleScope.launch {
            binding.cfProxyTestButton.isEnabled = false
            binding.cfProxyTestButton.text = getString(R.string.cfproxy_test_running)
            val result = runCatching {
                withContext(Dispatchers.IO) {
                    PythonProxyBridge.runCfProxyTest(this@MainActivity, customDomain)
                }
            }
            binding.cfProxyTestButton.isEnabled = true
            binding.cfProxyTestButton.text = getString(R.string.cfproxy_test_button)
            val message = result.fold(
                onSuccess = { cfResult ->
                    if (cfResult.ok) {
                        getString(
                            R.string.cfproxy_test_passed,
                            cfResult.selectedDomain ?: cfResult.domain ?: "ok",
                        )
                    } else {
                        getString(
                            R.string.cfproxy_test_failed,
                            cfResult.detail ?: "unknown",
                        )
                    }
                },
                onFailure = { error ->
                    getString(
                        R.string.cfproxy_test_failed,
                        error.message ?: error.javaClass.simpleName,
                    )
                },
            )
            Snackbar.make(binding.root, message, Snackbar.LENGTH_LONG).show()
        }
    }

    private fun refreshUpdateStatus(checkNow: Boolean) {
        lifecycleScope.launch {
            val status = runCatching {
                withContext(Dispatchers.IO) {
                    PythonProxyBridge.getUpdateStatus(this@MainActivity, checkNow)
                }
            }.getOrElse { exc ->
                ProxyUpdateStatus(
                    currentVersion = currentAppVersionName(),
                    error = exc.message ?: exc.javaClass.simpleName,
                )
            }
            currentUpdateStatus = status
            renderUpdateStatus(status, binding.checkUpdatesSwitch.isChecked)
        }
    }

    private fun renderUpdateStatus(status: ProxyUpdateStatus?, checkUpdatesEnabled: Boolean) {
        val currentVersion = status?.currentVersion?.takeIf { it.isNotBlank() } ?: currentAppVersionName()
        binding.currentVersionValue.text = getString(
            R.string.updates_current_version_format,
            currentVersion,
        )
        binding.updateStatusValue.text = when {
            !checkUpdatesEnabled -> {
                getString(R.string.updates_status_disabled)
            }
            status == null -> {
                getString(R.string.updates_status_initial)
            }
            !status.error.isNullOrBlank() -> {
                getString(R.string.updates_status_error, status.error)
            }
            !status.checked -> {
                getString(R.string.updates_status_idle)
            }
            status.hasUpdate && !status.latestVersion.isNullOrBlank() -> {
                getString(
                    R.string.updates_status_available,
                    status.latestVersion,
                    status.currentVersion,
                )
            }
            status.aheadOfRelease -> {
                getString(R.string.updates_status_newer, status.currentVersion)
            }
            else -> {
                getString(R.string.updates_status_latest, status.currentVersion)
            }
        }
    }

    private fun currentAppVersionName(): String {
        return runCatching {
            @Suppress("DEPRECATION")
            packageManager.getPackageInfo(packageName, 0).versionName
        }.getOrNull().orEmpty().ifBlank { "unknown" }
    }

    private fun observeServiceState() {
        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                combine(
                    ProxyServiceState.isStarting,
                    ProxyServiceState.isRunning,
                ) { isStarting, isRunning ->
                    isStarting to isRunning
                }.collect { (isStarting, isRunning) ->
                    binding.statusValue.text = getString(
                        when {
                            isStarting -> R.string.status_starting
                            isRunning -> R.string.status_running
                            else -> R.string.status_stopped
                        },
                    )
                    binding.startButton.isEnabled = !isStarting && !isRunning
                    binding.stopButton.isEnabled = isStarting || isRunning
                    binding.restartButton.isEnabled = !isStarting
                }
            }
        }

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                combine(
                    ProxyServiceState.activeConfig,
                    ProxyServiceState.isStarting,
                ) { config, isStarting ->
                    config to isStarting
                }.collect { (config, isStarting) ->
                    binding.serviceHint.text = if (config == null) {
                        getString(R.string.service_hint_idle)
                    } else if (isStarting) {
                        getString(
                            R.string.service_hint_starting,
                            config.host,
                            config.port,
                        )
                    } else {
                        getString(
                            R.string.service_hint_running,
                            config.host,
                            config.port,
                        )
                    }
                    if (config != null) {
                        binding.upstreamStatusValue.text = UpstreamMode.summary(
                            this@MainActivity,
                            config.upstreamMode,
                            config.relayUrl,
                        )
                    }
                }
            }
        }

        lifecycleScope.launch {
            repeatOnLifecycle(Lifecycle.State.STARTED) {
                ProxyServiceState.lastError.collect { error ->
                    if (error.isNullOrBlank()) {
                        binding.lastErrorCard.isVisible = false
                    } else {
                        binding.lastErrorValue.text = error
                        binding.lastErrorCard.isVisible = true
                    }
                }
            }
        }
    }

    private fun renderSystemStatus() {
        val status = AndroidSystemStatus.read(this)

        binding.systemStatusValue.text = getString(
            if (status.canKeepRunningReliably) {
                R.string.system_status_ready
            } else {
                R.string.system_status_attention
            },
        )

        val lines = mutableListOf<String>()
        lines += if (status.ignoringBatteryOptimizations) {
            getString(R.string.system_check_battery_ignored)
        } else {
            getString(R.string.system_check_battery_active)
        }
        lines += if (status.backgroundRestricted) {
            getString(R.string.system_check_background_restricted)
        } else {
            getString(R.string.system_check_background_ok)
        }
        lines += getString(R.string.system_check_oem_note)
        binding.systemStatusHint.text = lines.joinToString("\n")

        binding.disableBatteryOptimizationButton.isVisible = !status.ignoringBatteryOptimizations
        binding.openAppSettingsButton.isVisible = status.backgroundRestricted || !status.ignoringBatteryOptimizations
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            return
        }
        if (ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.POST_NOTIFICATIONS,
            ) == PackageManager.PERMISSION_GRANTED
        ) {
            return
        }
        notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    private fun setupUpstreamModeDropdown() {
        val adapter = ArrayAdapter(
            this,
            android.R.layout.simple_list_item_1,
            upstreamModeOptions.map { it.second },
        )
        binding.upstreamModeInput.setAdapter(adapter)
        binding.upstreamModeInput.setOnClickListener {
            binding.upstreamModeInput.showDropDown()
        }
        binding.upstreamModeInput.setOnFocusChangeListener { _, hasFocus ->
            if (hasFocus) {
                binding.upstreamModeInput.showDropDown()
            }
        }
        binding.upstreamModeInput.setOnItemClickListener { _, _, _, _ ->
            renderUpstreamConfigState(
                selectedUpstreamModeValue(),
                binding.relayUrlInput.text?.toString().orEmpty(),
            )
        }
    }

    private fun setupAppearanceDropdown() {
        val adapter = ArrayAdapter(
            this,
            android.R.layout.simple_list_item_1,
            appearanceOptions.map { it.second },
        )
        binding.appearanceInput.setAdapter(adapter)
        binding.appearanceInput.setOnClickListener {
            binding.appearanceInput.showDropDown()
        }
        binding.appearanceInput.setOnFocusChangeListener { _, hasFocus ->
            if (hasFocus) {
                binding.appearanceInput.showDropDown()
            }
        }
    }

    private fun applyAppearance(mode: String) {
        val nightMode = when (ProxyConfig.normalizeAppearance(mode)) {
            "light" -> AppCompatDelegate.MODE_NIGHT_NO
            "dark" -> AppCompatDelegate.MODE_NIGHT_YES
            else -> AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM
        }
        if (AppCompatDelegate.getDefaultNightMode() != nightMode) {
            AppCompatDelegate.setDefaultNightMode(nightMode)
        }
    }

    private fun appearanceLabelForValue(value: String): String {
        return when (ProxyConfig.normalizeAppearance(value)) {
            "light" -> getString(R.string.appearance_light)
            "dark" -> getString(R.string.appearance_dark)
            else -> getString(R.string.appearance_auto)
        }
    }

    private fun selectedAppearanceValue(): String {
        val selectedLabel = binding.appearanceInput.text?.toString().orEmpty()
        return appearanceOptions.firstOrNull { it.second == selectedLabel }
            ?.first
            ?: ProxyConfig.DEFAULT_APPEARANCE
    }

    private fun upstreamLabelForValue(value: String): String {
        return upstreamModeOptions.firstOrNull { it.first == UpstreamMode.normalize(value) }
            ?.second
            ?: upstreamModeOptions.first().second
    }

    private fun selectedUpstreamModeValue(): String {
        val selectedLabel = binding.upstreamModeInput.text?.toString().orEmpty()
        return upstreamModeOptions.firstOrNull { it.second == selectedLabel }
            ?.first
            ?: UpstreamMode.DIRECT
    }

    private fun renderUpstreamConfigState(upstreamMode: String, relayUrl: String) {
        binding.relayUrlLayout.isVisible = shouldShowRelayFields(upstreamMode)
        binding.relayTokenLayout.isVisible = shouldShowRelayFields(upstreamMode)
        binding.directWsTimeoutLayout.isVisible = shouldShowDirectTimeout(upstreamMode)
        val summary = UpstreamMode.summary(this, upstreamMode, relayUrl)
        binding.upstreamModeHint.text = summary
        binding.upstreamStatusValue.text = summary
    }

    private fun renderCfProxyState(enabled: Boolean) {
        val showDetails = shouldShowCfProxyDetails(enabled)
        binding.cfProxyPrioritySwitch.isVisible = showDetails
        binding.cfProxyCustomDomainSwitch.isVisible = showDetails
        binding.cfProxyUserDomainLayout.isVisible = showDetails
        binding.cfProxyTestButton.isVisible = showDetails
        if (showDetails) {
            renderCustomCfProxyDomainState(binding.cfProxyCustomDomainSwitch.isChecked)
        } else {
            binding.cfProxyUserDomainLayout.isEnabled = false
            binding.cfProxyUserDomainInput.isEnabled = false
        }
    }

    private fun renderCustomCfProxyDomainState(enabled: Boolean) {
        val allowEdit = shouldEnableCustomCfProxyDomain(enabled)
        binding.cfProxyUserDomainLayout.isEnabled = allowEdit
        binding.cfProxyUserDomainInput.isEnabled = allowEdit
        if (!allowEdit) {
            binding.cfProxyUserDomainInput.setText("")
        }
    }

    companion object {
        private const val FUNDING_URL =
            "https://github.com/Dark-Avery/tg-ws-proxy/blob/main/docs/Funding.md"

        @JvmStatic
        fun appearanceModes(): List<String> = listOf("auto", "light", "dark")

        @JvmStatic
        fun shouldShowRelayFields(upstreamMode: String): Boolean {
            return UpstreamMode.requiresRelayConfig(upstreamMode)
        }

        @JvmStatic
        fun shouldShowDirectTimeout(upstreamMode: String): Boolean {
            return UpstreamMode.normalize(upstreamMode) == UpstreamMode.AUTO
        }

        @JvmStatic
        fun shouldShowCfProxyDetails(enabled: Boolean): Boolean {
            return enabled
        }

        @JvmStatic
        fun shouldEnableCustomCfProxyDomain(enabled: Boolean): Boolean {
            return enabled
        }
    }
}
