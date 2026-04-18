package org.flowseal.tgwsproxy

import java.io.File
import java.nio.file.Files
import java.nio.file.Paths
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PythonProxyBridgeCfProxyTest {
    private fun findPath(vararg candidates: String): java.nio.file.Path {
        return candidates
            .map { Paths.get(it) }
            .firstOrNull { Files.exists(it) }
            ?: error("resource not found from cwd=${System.getProperty("user.dir")}")
    }

    @Test
    fun parse_cfproxy_test_result_preserves_string_status() {
        val result = PythonProxyBridge.cfProxyTestResultFromMap(
            mapOf(
                "ok" to false,
                "mode" to "auto",
                "status" to "partial",
                "detail" to "1/6 endpoints reachable",
            ),
        )

        assertEquals("partial", result.status)
        assertEquals("auto", result.mode)
        assertEquals("1/6 endpoints reachable", result.detail)
    }

    @Test
    fun bridge_sources_do_not_pass_relay_arguments() {
        val kotlinPath = findPath(
            "app/src/main/java/org/flowseal/tgwsproxy/PythonProxyBridge.kt",
            "src/main/java/org/flowseal/tgwsproxy/PythonProxyBridge.kt",
            "../app/src/main/java/org/flowseal/tgwsproxy/PythonProxyBridge.kt",
        )
        val pythonPath = findPath(
            "app/src/main/python/android_proxy_bridge.py",
            "src/main/python/android_proxy_bridge.py",
            "../app/src/main/python/android_proxy_bridge.py",
        )
        val kotlinSource = File(kotlinPath.toString()).readText()
        val pythonSource = File(pythonPath.toString()).readText()

        assertFalse(kotlinSource.contains("config.relayUrl"))
        assertFalse(kotlinSource.contains("config.relayToken"))
        assertFalse(pythonSource.contains("\"relay_url\""))
        assertFalse(pythonSource.contains("\"relay_token\""))
        assertFalse(pythonSource.contains("relay_url: str"))
        assertFalse(pythonSource.contains("relay_token: str"))
        assertTrue(pythonSource.contains("RELEASES_PAGE_URL = \"https://github.com/Flowseal/tg-ws-proxy/releases/latest\""))
    }
}
