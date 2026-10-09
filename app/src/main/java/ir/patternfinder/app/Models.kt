package ir.patternfinder.app

import org.json.JSONArray
import org.json.JSONObject

data class Pt(val x: Float, val y: Float)

/** یک قطعه (مختصات در «تصویر کاری»). */
data class Reg(
    val x: Int, val y: Int, val w: Int, val h: Int,
    val poly: List<Pt>?, val source: String, val area: Int = 0,
) {
    fun outline(): List<Pt> = poly ?: listOf(
        Pt(x.toFloat(), y.toFloat()), Pt((x + w).toFloat(), y.toFloat()),
        Pt((x + w).toFloat(), (y + h).toFloat()), Pt(x.toFloat(), (y + h).toFloat()),
    )

    fun contains(p: Pt): Boolean {
        val o = outline()
        var inside = false
        var j = o.lastIndex
        for (i in o.indices) {
            val a = o[i]; val b = o[j]
            if ((a.y > p.y) != (b.y > p.y) &&
                p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y + 1e-9f) + a.x
            ) inside = !inside
            j = i
        }
        return inside
    }

    fun areaGuess(): Float = (if (area > 0) area else w * h).toFloat()

    fun toJson(): JSONObject = JSONObject().apply {
        put("x", x); put("y", y); put("w", w); put("h", h); put("source", source); put("area", area)
        if (poly != null) {
            val arr = JSONArray()
            poly.forEach { arr.put(JSONArray().put(Math.round(it.x)).put(Math.round(it.y))) }
            put("polygon", arr)
        } else put("polygon", JSONObject.NULL)
    }

    companion object {
        fun fromJson(o: JSONObject): Reg {
            var poly: List<Pt>? = null
            if (!o.isNull("polygon")) {
                val a = o.getJSONArray("polygon")
                poly = (0 until a.length()).map { i ->
                    val p = a.getJSONArray(i); Pt(p.getDouble(0).toFloat(), p.getDouble(1).toFloat())
                }
            }
            return Reg(o.getInt("x"), o.getInt("y"), o.getInt("w"), o.getInt("h"), poly,
                o.optString("source", "auto"), o.optInt("area", 0))
        }

        fun fromRect(x0: Float, y0: Float, x1: Float, y1: Float): Reg {
            val x = minOf(x0, x1).toInt(); val y = minOf(y0, y1).toInt()
            return Reg(x, y, maxOf(1, Math.abs(x1 - x0).toInt()), maxOf(1, Math.abs(y1 - y0).toInt()), null, "manual")
        }

        fun fromPolygon(pts: List<Pt>): Reg {
            val minX = pts.minOf { it.x }; val maxX = pts.maxOf { it.x }
            val minY = pts.minOf { it.y }; val maxY = pts.maxOf { it.y }
            return Reg(minX.toInt(), minY.toInt(), maxOf(1, (maxX - minX).toInt()), maxOf(1, (maxY - minY).toInt()),
                pts.map { Pt(Math.round(it.x).toFloat(), Math.round(it.y).toFloat()) }, "manual")
        }

        fun listFromJson(a: JSONArray): List<Reg> = (0 until a.length()).map { fromJson(a.getJSONObject(it)) }
        fun listToJson(l: List<Reg>): String = JSONArray().also { arr -> l.forEach { arr.put(it.toJson()) } }.toString()
    }
}

data class ImageItem(val id: Int, val path: String, val name: String, val status: String, val label: String, val error: String)

data class EditData(
    val id: Int, val path: String, val name: String, val status: String, val label: String, val error: String,
    val mode: String, val polarity: String, val modeUsed: String, val ok: Boolean,
    val preview: String, val binary: String, val width: Int, val height: Int, val regions: List<Reg>,
)

data class QueryData(
    val ok: Boolean, val error: String, val preview: String, val binary: String, val width: Int, val height: Int,
    val mode: String, val polarity: String, val modeUsed: String, val defaultIndex: Int, val regions: List<Reg>,
)

data class ResultItem(
    val imageId: Int, val path: String, val name: String, val score: Float,
    val parts: Map<String, Float>, val componentScore: Float, val imageScore: Float,
    val matchType: String, val label: String, val polygon: String, val thumb: String,
)

data class SearchOutcome(val error: String, val approved: Int, val results: List<ResultItem>)

data class AppSettings(
    val weights: Map<String, Float>, val topK: Int, val rerank: Int, val deepScan: Boolean,
    val defaultMode: String, val workers: Int, val lastLibrary: String,
)

data class Labels(
    val modes: List<Pair<String, String>>, val polarities: List<Pair<String, String>>,
    val weightLabels: Map<String, String>, val defaultWeights: Map<String, Float>, val weightKeys: List<String>,
)

fun interface Progress {
    fun onProgress(i: Int, n: Int, msg: String)
}
