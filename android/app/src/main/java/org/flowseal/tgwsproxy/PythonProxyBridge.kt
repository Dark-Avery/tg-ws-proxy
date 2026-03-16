package org.flowseal.tgwsproxy

import android.content.Context
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.io.File

object PythonProxyBridge {
    private const val MODULE_NAME = "android_proxy_bridge"

    fun start(context: Context, config: NormalizedProxyConfig): String {
        val module = getModule(context)
        return module.callAttr(
            "start_proxy",
            File(context.filesDir, "tg-ws-proxy").absolutePath,
            config.host,
            config.port,
            config.dcIpList,
            config.verbose,
        ).toString()
    }

    fun stop(context: Context) {
        if (!Python.isStarted()) {
            return
        }
        getModule(context).callAttr("stop_proxy")
    }

    private fun getModule(context: Context) =
        getPython(context.applicationContext).getModule(MODULE_NAME)

    private fun getPython(context: Context): Python {
        if (!Python.isStarted()) {
            Python.start(AndroidPlatform(context))
        }
        return Python.getInstance()
    }
}
