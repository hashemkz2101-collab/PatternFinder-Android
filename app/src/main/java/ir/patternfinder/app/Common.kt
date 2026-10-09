package ir.patternfinder.app

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.foundation.layout.Box
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.material3.ExperimentalMaterial3Api

@Composable
fun Picker(label: String, value: String, options: List<Pair<String, String>>, onPick: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        OutlinedButton(onClick = { open = true }) {
            Text("$label: ${options.firstOrNull { it.first == value }?.second ?: value}", maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            options.forEach { (k, v) ->
                DropdownMenuItem(text = { Text(v) }, onClick = { onPick(k); open = false })
            }
        }
    }
}

@Composable
fun BusyBar(vm: AppViewModel) {
    if (!vm.busy) return
    Surface(tonalElevation = 3.dp, modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp)) {
            Text(vm.busyTitle + (if (vm.progMsg.isNotEmpty()) " — ${vm.progMsg}" else ""), style = MaterialTheme.typography.bodyMedium)
            if (vm.progN > 0) {
                LinearProgressIndicator(progress = { (vm.progI.toFloat() / vm.progN).coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp))
                Text("${vm.progI} / ${vm.progN}", style = MaterialTheme.typography.labelMedium)
            } else {
                LinearProgressIndicator(modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp))
            }
            TextButton(onClick = { vm.cancelJob() }) { Text("لغو") }
        }
    }
}

@Composable
fun MessageDialog(vm: AppViewModel) {
    val m = vm.message ?: return
    AlertDialog(
        onDismissRequest = { vm.message = null },
        confirmButton = { TextButton(onClick = { vm.message = null }) { Text("باشه") } },
        text = { Text(m, modifier = Modifier.horizontalScroll(rememberScrollState())) },
    )
}

/** نوار ابزار ویرایش قطعات: حرکت / مستطیل / چندضلعی / حذف / جایگزینی */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RegionToolbar(ed: RegionEditor, onMessage: (String) -> Unit) {
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically,
    ) {
        FilterChip(selected = ed.mode == DrawMode.PAN, onClick = { ed.mode = DrawMode.PAN; ed.cancelPoly() }, label = { Text("✋ حرکت/انتخاب") })
        FilterChip(selected = ed.mode == DrawMode.RECT, onClick = { ed.mode = DrawMode.RECT; ed.cancelPoly() }, label = { Text("▭ مستطیل") })
        FilterChip(selected = ed.mode == DrawMode.POLY, onClick = { ed.mode = DrawMode.POLY }, label = { Text("⬠ چندضلعی") })
        if (ed.mode == DrawMode.POLY) {
            OutlinedButton(onClick = { if (!ed.finishPoly()) onMessage("حداقل ۳ نقطه لازم است.") }) { Text("پایان") }
            OutlinedButton(onClick = { ed.undoPoint() }) { Text("برگردان") }
            OutlinedButton(onClick = { ed.cancelPoly() }) { Text("لغو") }
        }
        OutlinedButton(onClick = { ed.deleteSel() }, enabled = ed.sel in ed.regions.indices) { Text("🗑 حذف") }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(checked = ed.replace, onCheckedChange = { ed.replace = it })
            Text("جایگزینی قطعهٔ انتخابی", style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
fun ModeRow(labels: Labels, mode: String, pol: String, onApply: (String, String) -> Unit) {
    var m by remember(mode) { mutableStateOf(mode) }
    var p by remember(pol) { mutableStateOf(pol) }
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically,
    ) {
        Picker("پیش‌پردازش", m, labels.modes) { m = it }
        Picker("زمینه", p, labels.polarities) { p = it }
        Button(onClick = { onApply(m, p) }) { Text("تشخیص دوباره") }
    }
}
