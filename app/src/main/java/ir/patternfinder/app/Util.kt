package ir.patternfinder.app

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Environment
import android.provider.DocumentsContract
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.setValue
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

object PathUtil {
    /** آدرس درخت SAF حافظهٔ داخلی/کارت را به مسیر فایل تبدیل می‌کند (با دسترسی «همهٔ فایل‌ها» قابل استفاده است). */
    fun treeUriToPath(uri: Uri): String? = try {
        val docId = DocumentsContract.getTreeDocumentId(uri)
        val parts = docId.split(":", limit = 2)
        val vol = parts[0]
        val rel = parts.getOrElse(1) { "" }
        val base = if (vol == "primary") Environment.getExternalStorageDirectory().absolutePath else "/storage/$vol"
        if (rel.isEmpty()) base else "$base/$rel"
    } catch (e: Exception) {
        null
    }

    /** تصویر انتخاب‌شده از گالری را به فایلی در کش کپی می‌کند. */
    fun copyToCache(ctx: Context, uri: Uri): String? = try {
        val f = File(ctx.cacheDir, "query_input.img")
        ctx.contentResolver.openInputStream(uri)?.use { input -> f.outputStream().use { input.copyTo(it) } }
        f.absolutePath
    } catch (e: Exception) {
        null
    }
}

@Composable
fun rememberBitmap(path: String?): Bitmap? {
    val state = produceState<Bitmap?>(null, path) {
        value = if (path.isNullOrEmpty()) null else withContext(Dispatchers.IO) { BitmapFactory.decodeFile(path) }
    }
    return state.value
}

enum class DrawMode { PAN, RECT, POLY }

/** وضعیت ویرایش قطعات (هم برای تب کتابخانه، هم برای تصویر پرسش). */
class RegionEditor {
    var regions by mutableStateOf<List<Reg>>(emptyList())
    var sel by mutableIntStateOf(-1)
    var mode by mutableStateOf(DrawMode.PAN)
    var replace by mutableStateOf(false)
    var draft by mutableStateOf<List<Pt>>(emptyList())

    fun set(r: List<Reg>, select: Int = -1) {
        regions = r; sel = select; draft = emptyList(); mode = DrawMode.PAN
    }

    private fun put(r: Reg) {
        if (replace && sel in regions.indices) {
            regions = regions.toMutableList().also { it[sel] = r }
        } else {
            regions = regions + r
            sel = regions.lastIndex
        }
    }

    fun addRect(x0: Float, y0: Float, x1: Float, y1: Float) = put(Reg.fromRect(x0, y0, x1, y1))
    fun addPolyPoint(p: Pt) { draft = draft + p }
    fun undoPoint() { if (draft.isNotEmpty()) draft = draft.dropLast(1) }
    fun cancelPoly() { draft = emptyList() }
    fun finishPoly(): Boolean {
        if (draft.size < 3) return false
        put(Reg.fromPolygon(draft)); draft = emptyList(); return true
    }
    fun deleteSel() {
        if (sel in regions.indices) {
            regions = regions.toMutableList().also { it.removeAt(sel) }
            sel = -1
        }
    }
    fun selected(): Reg? = regions.getOrNull(sel)
}
