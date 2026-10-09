package ir.patternfinder.app

import android.app.Application
import java.io.File

class PatternApp : Application() {
    override fun onCreate() {
        super.onCreate()
        val prev = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { t, e ->
            try {
                File(filesDir, "crash.txt").writeText(
                    "thread=${t.name}\n" + android.util.Log.getStackTraceString(e)
                )
            } catch (_: Exception) {
            }
            prev?.uncaughtException(t, e)
        }
    }
}
