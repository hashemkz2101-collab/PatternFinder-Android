package ir.patternfinder.app

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

private fun pct(v: Float) = "${Math.round(v * 100)}٪"

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SearchScreen(vm: AppViewModel) {
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.GetContent()) { uri -> if (uri != null) vm.pickQuery(uri) }
    val q = vm.query
    val ed = vm.qEditor
    val labels = vm.labels
    val s = vm.settings
    val bmp = rememberBitmap(if (q == null) null else if (vm.queryBinary) q.binary else q.preview)

    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(8.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically,
        ) {
            Button(onClick = { pick.launch("image/*") }, enabled = !vm.busy) { Text("🖼 انتخاب تصویر پرسش") }
            Button(onClick = { vm.search() }, enabled = q != null && !vm.busy) { Text("🔍 جستجو") }
            if (vm.results.isNotEmpty()) OutlinedButton(onClick = { vm.resultsOpen = true }) { Text("آخرین نتایج (${vm.results.size})") }
        }
        if (q == null) {
            Box(Modifier.fillMaxSize().padding(24.dp), contentAlignment = Alignment.Center) {
                Text("تصویر پرسش را انتخاب کنید؛ سپس قطعهٔ مورد نظر را لمس کنید یا با مستطیل/چندضلعی بکشید و «جستجو» بزنید.")
            }
            return@Column
        }
        ImageCanvas(
            bitmap = bmp, regions = ed.regions, selected = ed.sel, mode = ed.mode, draft = ed.draft,
            modifier = Modifier.weight(1f),
            onTapRegion = { ed.sel = it },
            onRect = { a, b, c, e -> ed.addRect(a, b, c, e) },
            onPolyPoint = { ed.addPolyPoint(it) },
        )
        Text(
            if (ed.sel in ed.regions.indices) "قطعهٔ انتخابی: ${ed.sel + 1} از ${ed.regions.size}" else "قطعه‌ای انتخاب نشده (بزرگ‌ترین قطعه استفاده می‌شود)",
            Modifier.padding(horizontal = 10.dp, vertical = 2.dp), style = MaterialTheme.typography.bodySmall,
        )
        RegionToolbar(ed) { vm.message = it }
        if (labels != null) ModeRow(labels, q.mode, q.polarity) { m, p -> vm.redetectQuery(m, p) }
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 8.dp, vertical = 4.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically,
        ) {
            FilterChip(selected = vm.searchMode == "component", onClick = { vm.searchMode = "component" }, label = { Text("جستجوی قطعه") })
            FilterChip(selected = vm.searchMode == "combined", onClick = { vm.searchMode = "combined" }, label = { Text("ترکیبی (قطعه + تصویر مادر)") })
            if (s != null) {
                Checkbox(checked = s.deepScan, onCheckedChange = { vm.saveSettings(s.copy(deepScan = it)) })
                Text("جستجوی عمیق", style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

@Composable
fun ResultsScreen(vm: AppViewModel) {
    BackHandler { if (vm.detail != null) vm.detail = null else vm.resultsOpen = false }
    val det = vm.detail
    if (det != null) {
        DetailScreen(vm, det)
        return
    }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedButton(onClick = { vm.resultsOpen = false }) { Text("← تصویر پرسش") }
            Text("  ${vm.results.size} نتیجه", style = MaterialTheme.typography.titleSmall)
        }
        if (vm.results.isEmpty()) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text("نتیجه‌ای پیدا نشد.") }
        } else {
            LazyColumn(Modifier.fillMaxSize(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(vm.results, key = { it.imageId }) { r ->
                    val thumb = rememberBitmap(r.thumb)
                    Card(Modifier.fillMaxWidth().padding(horizontal = 8.dp).clickable { vm.openDetail(r) }) {
                        Row(Modifier.padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                            if (thumb != null) {
                                Image(thumb.asImageBitmap(), null, Modifier.size(120.dp), contentScale = ContentScale.Fit)
                            } else Box(Modifier.size(120.dp))
                            Column(Modifier.padding(start = 10.dp)) {
                                Text(pct(r.score), style = MaterialTheme.typography.titleMedium)
                                Text(r.name, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium)
                                Text(r.label, style = MaterialTheme.typography.bodySmall)
                                Text(partsLine(vm, r), style = MaterialTheme.typography.labelSmall)
                            }
                        }
                    }
                }
            }
        }
    }
}

private fun partsLine(vm: AppViewModel, r: ResultItem): String {
    val wl = vm.labels?.weightLabels ?: emptyMap()
    val short = mapOf("shape" to "شکل", "local" to "خطوط", "geom" to "هندسه", "layout" to "چیدمان")
    return listOf("shape", "local", "geom", "layout").joinToString(" | ") { k -> "${short[k] ?: wl[k] ?: k} ${pct(r.parts[k] ?: 0f)}" }
}

@Composable
fun DetailScreen(vm: AppViewModel, r: ResultItem) {
    val bmp = rememberBitmap(vm.detailPreview)
    val clip = LocalClipboardManager.current
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedButton(onClick = { vm.detail = null }) { Text("← نتایج") }
            Text("  ${pct(r.score)}  —  ${r.label}", style = MaterialTheme.typography.titleSmall)
        }
        ImageCanvas(bitmap = bmp, regions = emptyList(), selected = -1, mode = DrawMode.PAN, draft = emptyList(), modifier = Modifier.weight(1f))
        Column(Modifier.padding(10.dp)) {
            Text(r.path, style = MaterialTheme.typography.bodySmall)
            Text(partsLine(vm, r) + (if (r.imageScore > 0f) " | تصویر مادر ${pct(r.imageScore)}" else ""), style = MaterialTheme.typography.labelSmall)
            OutlinedButton(onClick = { clip.setText(AnnotatedString(r.path)) }) { Text("کپی مسیر فایل") }
        }
    }
}
