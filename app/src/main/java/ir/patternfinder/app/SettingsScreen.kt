package ir.patternfinder.app

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

@Composable
fun SettingsScreen(vm: AppViewModel) {
    val cur = vm.settings ?: return
    val labels = vm.labels ?: return
    var weights by remember { mutableStateOf(cur.weights) }
    var topK by remember { mutableStateOf(cur.topK.toFloat()) }
    var rerank by remember { mutableStateOf(cur.rerank.toFloat()) }
    var deep by remember { mutableStateOf(cur.deepScan) }
    var workers by remember { mutableStateOf(cur.workers.toFloat()) }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("وزن‌های امتیاز", style = MaterialTheme.typography.titleMedium)
        labels.weightKeys.forEach { k ->
            val v = (weights[k] ?: 0f) * 100f
            Text("${labels.weightLabels[k] ?: k}: ${Math.round(v)}٪", style = MaterialTheme.typography.bodyMedium)
            Slider(value = v, onValueChange = { weights = weights + (k to it / 100f) }, valueRange = 0f..100f)
        }
        Text("وزن‌ها خودکار نرمال می‌شوند. برای تنظیم دقیق، روی نمونه‌های واقعی خودتان آزمایش کنید.", style = MaterialTheme.typography.bodySmall)
        OutlinedButton(onClick = { weights = labels.defaultWeights }) { Text("بازگشت به وزن‌های پیش‌فرض (۴۰/۳۰/۲۰/۱۰)") }

        Text("تعداد نتایج: ${topK.toInt()}")
        Slider(value = topK, onValueChange = { topK = it }, valueRange = 5f..100f)
        Text("تعداد کاندیدای بازرتبه‌بندی: ${rerank.toInt()}")
        Slider(value = rerank, onValueChange = { rerank = it }, valueRange = 20f..500f)
        Text("تعداد Thread پردازش: ${if (workers.toInt() == 0) "خودکار (۴)" else workers.toInt().toString()}")
        Slider(value = workers, onValueChange = { workers = it }, valueRange = 0f..8f, steps = 7)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(checked = deep, onCheckedChange = { deep = it })
            Text("  جستجوی عمیق (پیدا کردن قطعه داخل کل تصاویر؛ کندتر ولی کامل‌تر)", Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
        }
        Button(modifier = Modifier.fillMaxWidth(), onClick = {
            vm.saveSettings(cur.copy(weights = weights, topK = topK.toInt(), rerank = rerank.toInt(), deepScan = deep, workers = workers.toInt()))
            vm.message = "تنظیمات ذخیره شد."
        }) { Text("ذخیرهٔ تنظیمات") }

        Text("عیب‌یابی", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 12.dp))
        OutlinedButton(modifier = Modifier.fillMaxWidth(), onClick = { vm.runSelftest() }) { Text("آزمون موتور (بررسی سلامت روی این گوشی)") }
        OutlinedButton(modifier = Modifier.fillMaxWidth(), onClick = { vm.showLog() }) { Text("نمایش گزارش خطا (log)") }
        if (vm.lastCrash.isNotEmpty()) {
            OutlinedButton(modifier = Modifier.fillMaxWidth(), onClick = { vm.message = vm.lastCrash; vm.clearCrash() }) { Text("نمایش آخرین کرش برنامه") }
        }
        Text("نسخه: ${vm.engineInfo}", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp))
    }
}
