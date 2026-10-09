package ir.patternfinder.app

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

class AppViewModel(private val app: Application) : AndroidViewModel(app) {
    // ---- راه‌اندازی ----
    var ready by mutableStateOf(false)
    var startError by mutableStateOf<String?>(null)
    var engineInfo by mutableStateOf("")
    var labels by mutableStateOf<Labels?>(null)
    var settings by mutableStateOf<AppSettings?>(null)
    var lastCrash by mutableStateOf("")

    // ---- ناوبری ----
    var tab by mutableIntStateOf(0)
    var message by mutableStateOf<String?>(null)

    // ---- کار طولانی ----
    var busy by mutableStateOf(false)
    var busyTitle by mutableStateOf("")
    var progI by mutableIntStateOf(0)
    var progN by mutableIntStateOf(0)
    var progMsg by mutableStateOf("")
    var quick by mutableStateOf(false)      // عملیات کوتاه (اسپینر)

    // ---- کتابخانه ----
    var folder by mutableStateOf("")
    var filter by mutableStateOf("")
    var items by mutableStateOf<List<ImageItem>>(emptyList())
    var counts by mutableStateOf<Map<String, Int>>(emptyMap())
    var editing by mutableStateOf<EditData?>(null)
    var editorOpen by mutableStateOf(false)
    var showBinary by mutableStateOf(false)
    val editor = RegionEditor()

    // ---- جستجو ----
    var query by mutableStateOf<QueryData?>(null)
    var queryBinary by mutableStateOf(false)
    val qEditor = RegionEditor()
    var searchMode by mutableStateOf("component")
    var results by mutableStateOf<List<ResultItem>>(emptyList())
    var resultsOpen by mutableStateOf(false)
    var detail by mutableStateOf<ResultItem?>(null)
    var detailPreview by mutableStateOf("")

    init {
        viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) {
                    engineInfo = Engine.start(app)
                    labels = Engine.labels()
                    settings = Engine.settings()
                }
                folder = settings?.lastLibrary ?: ""
                val crash = File(app.filesDir, "crash.txt")
                if (crash.exists()) { lastCrash = crash.readText(); }
                ready = true
                refreshList()
            } catch (e: Throwable) {
                startError = "${e::class.java.simpleName}: ${e.message}"
            }
        }
    }

    fun clearCrash() {
        File(app.filesDir, "crash.txt").delete(); lastCrash = ""
    }

    // ------------------------------------------------------------------ //
    private fun errText(e: Throwable) = "خطا: ${e.message ?: e::class.java.simpleName}"

    private fun job(title: String, block: (Progress) -> Unit) {
        if (busy) return
        busy = true; busyTitle = title; progI = 0; progN = 0; progMsg = ""
        WorkService.start(app, title)
        viewModelScope.launch {
            try {
                withContext(Dispatchers.IO) { block(Progress { i, n, m -> progI = i; progN = n; progMsg = m }) }
            } catch (e: Throwable) {
                message = errText(e)
            } finally {
                busy = false
                WorkService.stop(app)
                refreshList()
            }
        }
    }

    private fun quickOp(block: suspend () -> Unit) {
        viewModelScope.launch {
            quick = true
            try { block() } catch (e: Throwable) { message = errText(e) } finally { quick = false }
        }
    }

    fun cancelJob() = viewModelScope.launch(Dispatchers.IO) { try { Engine.cancel() } catch (_: Throwable) {} }

    // ------------------------------------------------------------------ //
    // کتابخانه
    // ------------------------------------------------------------------ //
    fun refreshList() {
        viewModelScope.launch {
            try {
                val (l, c) = withContext(Dispatchers.IO) { Engine.listImages(filter) to Engine.counts() }
                items = l; counts = c
            } catch (e: Throwable) { message = errText(e) }
        }
    }

    fun setFilterTo(f: String) { filter = f; refreshList() }

    fun scan() {
        val f = folder.trim()
        if (f.isEmpty()) { message = "ابتدا پوشهٔ کتابخانه را انتخاب کنید."; return }
        if (!File(f).isDirectory) { message = "این پوشه پیدا نشد یا دسترسی «همهٔ فایل‌ها» داده نشده:\n$f"; return }
        job("اسکن کتابخانه") { p ->
            val s = Engine.scan(f, p)
            message = s
        }
        settings = settings?.copy(lastLibrary = f)
    }

    fun approveAll() {
        val n = counts["pending"] ?: 0
        if (n == 0) { message = "تصویری در انتظار تأیید نیست."; return }
        job("استخراج ویژگی‌ها") { p ->
            val ok = Engine.approveAll(p)
            message = "$ok تصویر تأیید شد."
        }
    }

    fun openEditor(id: Int) {
        quickOp {
            val d = withContext(Dispatchers.IO) { Engine.loadImage(id) }
            applyEdit(d)
            editorOpen = true
        }
    }

    private fun applyEdit(d: EditData) {
        editing = d
        showBinary = false
        editor.set(d.regions)
    }

    fun redetect(mode: String, pol: String) {
        val id = editing?.id ?: return
        quickOp { applyEdit(withContext(Dispatchers.IO) { Engine.redetect(id, mode, pol) }); refreshList() }
    }

    fun approveCurrent(goNext: Boolean) {
        val id = editing?.id ?: return
        if (editor.regions.isEmpty()) { message = "حداقل یک قطعه لازم است (با مستطیل/چندضلعی بکشید)."; return }
        quickOp {
            val n = withContext(Dispatchers.IO) { Engine.approve(id, editor.regions) }
            refreshList()
            if (n == 0) { message = "در نواحی انتخابی هیچ طرحی پیدا نشد."; return@quickOp }
            if (goNext) {
                val nxt = withContext(Dispatchers.IO) { Engine.nextPending(id, filter) }
                if (nxt < 0) { message = "همهٔ تصاویر بررسی شدند 🎉"; editorOpen = false }
                else applyEdit(withContext(Dispatchers.IO) { Engine.loadImage(nxt) })
            } else {
                message = "ذخیره شد ($n قطعه)"
            }
        }
    }

    // ------------------------------------------------------------------ //
    // جستجو
    // ------------------------------------------------------------------ //
    fun loadQuery(path: String, mode: String = "auto", pol: String = "auto") {
        quickOp {
            val q = withContext(Dispatchers.IO) { Engine.queryLoad(path, mode, pol) }
            if (!q.ok) { message = q.error; return@quickOp }
            query = q; queryBinary = false
            qEditor.set(q.regions, q.defaultIndex)
            results = emptyList()
        }
    }

    fun pickQuery(uri: android.net.Uri) {
        val p = PathUtil.copyToCache(app, uri)
        if (p == null) message = "خواندن تصویر ممکن نیست." else loadQuery(p)
    }

    fun redetectQuery(mode: String, pol: String) {
        val q = query ?: return
        // مسیر ورودی همان فایل کش است
        loadQuery(File(app.cacheDir, "query_input.img").absolutePath, mode, pol)
    }

    fun search() {
        if (query == null) { message = "ابتدا تصویر پرسش را انتخاب کنید."; return }
        val region = qEditor.selected() ?: qEditor.regions.maxByOrNull { it.areaGuess() }
        if (region == null) { message = "ابتدا یک قطعه انتخاب کنید یا بکشید."; return }
        val regs = qEditor.regions
        val mode = searchMode
        var outcome: SearchOutcome? = null
        saveSettings(settings)
        if (busy) return
        busy = true; busyTitle = "جستجو"; progI = 0; progN = 0; progMsg = ""
        WorkService.start(app, "جستجو")
        viewModelScope.launch {
            try {
                outcome = withContext(Dispatchers.IO) {
                    Engine.querySearch(region, regs, mode) { i, n, m -> progI = i; progN = n; progMsg = m }
                }
            } catch (e: Throwable) {
                message = errText(e)
            } finally {
                busy = false
                WorkService.stop(app)
            }
            val o = outcome ?: return@launch
            when (o.error) {
                "no_pattern" -> message = "در ناحیهٔ انتخاب‌شده طرح کافی پیدا نشد."
                "no_region" -> message = "ابتدا یک قطعه انتخاب کنید یا بکشید."
                else -> {
                    results = o.results
                    resultsOpen = true
                    if (o.results.isEmpty() && o.approved == 0)
                        message = "هنوز هیچ تصویری در کتابخانه تأیید نشده است.\nابتدا در تب «کتابخانه» پوشه را اسکن و تصاویر را تأیید کنید."
                }
            }
        }
    }

    fun openDetail(r: ResultItem) {
        quickOp {
            detailPreview = withContext(Dispatchers.IO) { Engine.resultDetail(r.path, r.polygon) }
            detail = r
        }
    }

    // ------------------------------------------------------------------ //
    // تنظیمات / عیب‌یابی
    // ------------------------------------------------------------------ //
    fun saveSettings(s: AppSettings?) {
        s ?: return
        settings = s
        viewModelScope.launch(Dispatchers.IO) { try { Engine.saveSettings(s) } catch (_: Throwable) {} }
    }

    fun runSelftest() {
        quickOp { message = "آزمون موتور:\n" + withContext(Dispatchers.IO) { Engine.selftest() } }
    }

    fun showLog() {
        quickOp { message = withContext(Dispatchers.IO) { Engine.logTail() }.ifBlank { "گزارشی ثبت نشده." } }
    }
}
