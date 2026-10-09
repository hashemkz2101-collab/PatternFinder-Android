package ir.patternfinder.app

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp

private fun statusColor(s: String) = when (s) {
    "approved" -> Color(0xFF15803D)
    "pending" -> Color(0xFFB45309)
    "corrupt" -> Color(0xFFB91C1C)
    "duplicate" -> Color(0xFF6B7280)
    else -> Color.Black
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LibraryScreen(vm: AppViewModel) {
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocumentTree()) { uri ->
        if (uri != null) {
            val p = PathUtil.treeUriToPath(uri)
            if (p == null) vm.message = "این پوشه پشتیبانی نمی‌شود. مسیر را دستی وارد کنید." else vm.folder = p
        }
    }
    val c = vm.counts
    Column(Modifier.fillMaxSize()) {
        Card(Modifier.fillMaxWidth().padding(8.dp)) {
            Column(Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                OutlinedTextField(
                    value = vm.folder, onValueChange = { vm.folder = it }, label = { Text("پوشهٔ کتابخانه") },
                    singleLine = true, modifier = Modifier.fillMaxWidth(),
                )
                Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    OutlinedButton(onClick = { picker.launch(null) }, enabled = !vm.busy) { Text("📁 انتخاب پوشه") }
                    Button(onClick = { vm.scan() }, enabled = !vm.busy) { Text("اسکن") }
                    Button(onClick = { vm.approveAll() }, enabled = !vm.busy) { Text("تأیید همهٔ در انتظار") }
                }
                Text(
                    "کل ${c.values.sum()} | تأییدشده ${c["approved"] ?: 0} | در انتظار ${c["pending"] ?: 0} | خراب ${c["corrupt"] ?: 0} | تکراری ${c["duplicate"] ?: 0}",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            listOf("" to "همه", "pending" to "در انتظار", "approved" to "تأییدشده", "corrupt" to "خراب", "duplicate" to "تکراری").forEach { (k, v) ->
                FilterChip(selected = vm.filter == k, onClick = { vm.setFilterTo(k) }, label = { Text(v) })
            }
        }
        if (vm.items.isEmpty()) {
            Box(Modifier.fillMaxSize().padding(24.dp), contentAlignment = Alignment.Center) {
                Text("هنوز تصویری نیست. پوشه را انتخاب و «اسکن» بزنید.", style = MaterialTheme.typography.bodyMedium)
            }
        } else {
            LazyColumn(Modifier.fillMaxSize()) {
                items(vm.items, key = { it.id }) { it ->
                    Column(Modifier.fillMaxWidth().clickable(enabled = !vm.busy) { vm.openEditor(it.id) }.padding(horizontal = 14.dp, vertical = 8.dp)) {
                        Text(it.name, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(it.label + (if (it.error.isNotEmpty() && it.status != "pending") " — ${it.error}" else ""),
                            color = statusColor(it.status), style = MaterialTheme.typography.bodySmall,
                            maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    HorizontalDivider()
                }
            }
        }
    }
}

@Composable
fun EditorScreen(vm: AppViewModel) {
    val d = vm.editing
    val ed = vm.editor
    val labels = vm.labels
    BackHandler { vm.editorOpen = false }
    val bmp = rememberBitmap(if (d == null) null else if (vm.showBinary) d.binary else d.preview)

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedButton(onClick = { vm.editorOpen = false }) { Text("← بازگشت") }
            Column(Modifier.weight(1f).padding(horizontal = 8.dp)) {
                Text(d?.name ?: "", maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.titleSmall)
                Text(d?.label ?: "", style = MaterialTheme.typography.bodySmall, color = statusColor(d?.status ?: ""))
            }
        }
        if (d != null && !d.ok) {
            Box(Modifier.weight(1f).fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) {
                Text(d.error.ifEmpty { d.label })
            }
        } else {
            ImageCanvas(
                bitmap = bmp, regions = ed.regions, selected = ed.sel, mode = ed.mode, draft = ed.draft,
                modifier = Modifier.weight(1f),
                onTapRegion = { ed.sel = it },
                onRect = { a, b, c, e -> ed.addRect(a, b, c, e) },
                onPolyPoint = { ed.addPolyPoint(it) },
            )
            Text("روش پیش‌پردازش: ${d?.modeUsed ?: ""}   |   قطعات: ${ed.regions.size}", Modifier.padding(horizontal = 10.dp, vertical = 2.dp), style = MaterialTheme.typography.bodySmall)
            RegionToolbar(ed) { vm.message = it }
            if (labels != null && d != null) {
                ModeRow(labels, d.mode, d.polarity) { m, p -> vm.redetect(m, p) }
            }
            Row(
                Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(8.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically,
            ) {
                Button(onClick = { vm.approveCurrent(false) }) { Text("✔ تأیید") }
                Button(onClick = { vm.approveCurrent(true) }) { Text("✔ تأیید و بعدی") }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Switch(checked = vm.showBinary, onCheckedChange = { vm.showBinary = it })
                    Text(" نمایش باینری", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}
