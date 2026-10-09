package ir.patternfinder.app

import android.content.Context
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** فراخوانی‌های موتور پایتون (bridge.py). همه blocking هستند؛ از Dispatchers.IO صدا بزنید. */
object Engine {
    private lateinit var mod: PyObject

    fun start(ctx: Context): String {
        if (!Python.isStarted()) Python.start(AndroidPlatform(ctx))
        mod = Python.getInstance().getModule("bridge")
        return call("init", File(ctx.filesDir, "data").absolutePath)
    }

    private fun call(fn: String, vararg a: Any?): String = mod.callAttr(fn, *a).toString()

    fun cancel() { mod.callAttr("cancel") }

    fun labels(): Labels {
        val o = JSONObject(call("labels"))
        fun pairs(a: JSONArray) = (0 until a.length()).map { a.getJSONArray(it).let { p -> p.getString(0) to p.getString(1) } }
        fun fmap(j: JSONObject) = j.keys().asSequence().associateWith { j.getDouble(it).toFloat() }
        val wl = o.getJSONObject("weight_labels")
        val keys = o.getJSONArray("weight_keys").let { a -> (0 until a.length()).map { a.getString(it) } }
        return Labels(pairs(o.getJSONArray("modes")), pairs(o.getJSONArray("polarities")),
            wl.keys().asSequence().associateWith { wl.getString(it) }, fmap(o.getJSONObject("default_weights")), keys)
    }

    fun settings(): AppSettings {
        val o = JSONObject(call("get_settings"))
        val w = o.getJSONObject("weights")
        return AppSettings(w.keys().asSequence().associateWith { w.getDouble(it).toFloat() },
            o.getInt("top_k"), o.getInt("rerank"), o.getBoolean("deep_scan"),
            o.getString("default_mode"), o.getInt("workers"), o.optString("last_library", ""))
    }

    fun saveSettings(s: AppSettings) {
        val o = JSONObject()
        o.put("weights", JSONObject(s.weights.mapValues { it.value.toDouble() }))
        o.put("top_k", s.topK); o.put("rerank", s.rerank); o.put("deep_scan", s.deepScan)
        o.put("default_mode", s.defaultMode); o.put("workers", s.workers); o.put("last_library", s.lastLibrary)
        call("save_settings", o.toString())
    }

    fun counts(): Map<String, Int> {
        val o = JSONObject(call("counts"))
        return o.keys().asSequence().associateWith { o.getInt(it) }
    }

    fun listImages(status: String): List<ImageItem> {
        val a = JSONArray(call("list_images", status))
        return (0 until a.length()).map {
            val o = a.getJSONObject(it)
            ImageItem(o.getInt("id"), o.getString("path"), o.getString("name"), o.getString("status"),
                o.getString("label"), o.optString("error", ""))
        }
    }

    fun scan(folder: String, p: Progress): String = JSONObject(call("scan", folder, p)).getString("summary")
    fun approveAll(p: Progress): Int = mod.callAttr("approve_all", p).toInt()

    private fun editData(js: String): EditData {
        val o = JSONObject(js)
        val ok = o.optBoolean("ok", false)
        return EditData(
            o.optInt("id", -1), o.optString("path"), o.optString("name"), o.optString("status"),
            o.optString("label"), o.optString("error"), o.optString("mode", "auto"),
            o.optString("polarity", "auto"), o.optString("mode_used"), ok,
            o.optString("preview"), o.optString("binary"), o.optInt("width"), o.optInt("height"),
            if (ok) Reg.listFromJson(o.getJSONArray("regions")) else emptyList(),
        )
    }

    fun loadImage(id: Int): EditData = editData(call("load_image", id))
    fun redetect(id: Int, mode: String, pol: String): EditData = editData(call("redetect", id, mode, pol))
    fun approve(id: Int, regs: List<Reg>): Int = mod.callAttr("approve", id, Reg.listToJson(regs)).toInt()
    fun nextPending(afterId: Int, status: String): Int = mod.callAttr("next_pending", afterId, status).toInt()

    fun queryLoad(path: String, mode: String, pol: String): QueryData {
        val o = JSONObject(call("query_load", path, mode, pol))
        if (!o.getBoolean("ok")) return QueryData(false, o.optString("error"), "", "", 0, 0, mode, pol, "", -1, emptyList())
        return QueryData(true, "", o.getString("preview"), o.getString("binary"), o.getInt("width"), o.getInt("height"),
            o.getString("mode"), o.getString("polarity"), o.getString("mode_used"), o.getInt("default_index"),
            Reg.listFromJson(o.getJSONArray("regions")))
    }

    fun querySearch(region: Reg?, regions: List<Reg>, mode: String, p: Progress): SearchOutcome {
        val o = JSONObject(call("query_search", region?.toJson()?.toString() ?: "", Reg.listToJson(regions), mode, p))
        val a = o.getJSONArray("results")
        val list = (0 until a.length()).map {
            val r = a.getJSONObject(it)
            val parts = r.getJSONObject("parts")
            ResultItem(r.getInt("image_id"), r.getString("path"), r.getString("name"), r.getDouble("score").toFloat(),
                parts.keys().asSequence().associateWith { k -> parts.getDouble(k).toFloat() },
                r.getDouble("component_score").toFloat(), r.getDouble("image_score").toFloat(),
                r.getString("match_type"), r.getString("label"), r.getJSONArray("polygon").toString(), r.getString("thumb"))
        }
        return SearchOutcome(o.optString("error"), o.optInt("approved"), list)
    }

    fun resultDetail(path: String, polygonJson: String): String = call("result_detail", path, polygonJson)
    fun selftest(): String = call("selftest")
    fun logTail(): String = call("log_tail", 60)
}
