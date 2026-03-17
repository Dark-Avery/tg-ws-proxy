package org.flowseal.tgwsproxy

import android.content.Context
import java.net.URI

object UpstreamMode {
    const val DIRECT = "telegram_ws_direct"
    const val AUTO = "auto"
    const val RELAY = "relay_ws"

    data class Option(val value: String, val labelResId: Int)

    val options = listOf(
        Option(DIRECT, R.string.upstream_mode_direct),
        Option(AUTO, R.string.upstream_mode_auto),
        Option(RELAY, R.string.upstream_mode_relay),
    )

    fun normalize(value: String): String {
        return when (value) {
            DIRECT, AUTO, RELAY -> value
            else -> DIRECT
        }
    }

    fun requiresRelayConfig(value: String): Boolean {
        val normalized = normalize(value)
        return normalized == AUTO || normalized == RELAY
    }

    fun label(context: Context, value: String): String {
        val normalized = normalize(value)
        val option = options.firstOrNull { it.value == normalized } ?: options.first()
        return context.getString(option.labelResId)
    }

    fun summary(context: Context, value: String, relayUrl: String): String {
        val normalized = normalize(value)
        val relayHost = relayHost(relayUrl)
        return when (normalized) {
            AUTO -> {
                if (relayHost.isNullOrBlank()) {
                    context.getString(R.string.upstream_mode_summary_auto_no_relay)
                } else {
                    context.getString(R.string.upstream_mode_summary_auto, relayHost)
                }
            }

            RELAY -> {
                if (relayHost.isNullOrBlank()) {
                    context.getString(R.string.upstream_mode_summary_relay_no_host)
                } else {
                    context.getString(R.string.upstream_mode_summary_relay, relayHost)
                }
            }

            else -> context.getString(R.string.upstream_mode_summary_direct)
        }
    }

    fun relayHost(relayUrl: String): String? {
        val trimmed = relayUrl.trim()
        if (trimmed.isEmpty()) {
            return null
        }
        return runCatching { URI(trimmed).host }
            .getOrNull()
            ?.takeIf { it.isNotBlank() }
    }
}
