package ir.patternfinder.app

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.viewmodel.compose.viewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(colorScheme = lightColorScheme(primary = Color(0xFF0F766E), secondary = Color(0xFF0891B2))) {
                // برنامه فارسی است؛ چیدمان راست‌به‌چپ مستقل از زبان گوشی
                CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
                    App()
                }
            }
        }
    }
}

private fun hasAllFilesAccess(): Boolean =
    if (Build.VERSION.SDK_INT >= 30) Environment.isExternalStorageManager() else true

@Composable
fun App(vm: AppViewModel = viewModel()) {
    val ctx = LocalContext.current
    var hasAccess by remember { mutableStateOf(hasAllFilesAccess()) }
    val owner = LocalLifecycleOwner.current
    DisposableEffect(owner) {
        val obs = LifecycleEventObserver { _, e -> if (e == Lifecycle.Event.ON_RESUME) hasAccess = hasAllFilesAccess() }
        owner.lifecycle.addObserver(obs)
        onDispose { owner.lifecycle.removeObserver(obs) }
    }
    val notifLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }
    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) notifLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    when {
        vm.startError != null -> Column(Modifier.fillMaxSize().padding(20.dp).verticalScroll(rememberScrollState())) {
            Text("راه‌اندازی موتور ناموفق بود", style = MaterialTheme.typography.titleMedium)
            Text(vm.startError ?: "")
        }
        !vm.ready -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                CircularProgressIndicator()
                Text("در حال راه‌اندازی موتور پردازش تصویر…", Modifier.padding(top = 12.dp))
            }
        }
        !hasAccess -> Column(
            Modifier.fillMaxSize().padding(24.dp), verticalArrangement = androidx.compose.foundation.layout.Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text("برای خواندن تصاویر کتابخانه، برنامه به دسترسی «مدیریت همهٔ فایل‌ها» نیاز دارد.", style = MaterialTheme.typography.bodyLarge)
            Button(modifier = Modifier.padding(top = 16.dp), onClick = {
                try {
                    ctx.startActivity(Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:${ctx.packageName}")))
                } catch (e: Exception) {
                    ctx.startActivity(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
                }
            }) { Text("باز کردن تنظیمات دسترسی") }
            Text("پس از فعال‌کردن، به برنامه برگردید.", Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodySmall)
        }
        else -> MainShell(vm)
    }
}

@Composable
fun MainShell(vm: AppViewModel) {
    val overlay = vm.editorOpen || (vm.tab == 1 && vm.resultsOpen)
    Scaffold(
        bottomBar = {
            if (!overlay) NavigationBar {
                listOf("📚" to "کتابخانه", "🔍" to "جستجو", "⚙️" to "تنظیمات").forEachIndexed { i, (ic, t) ->
                    NavigationBarItem(selected = vm.tab == i, onClick = { vm.tab = i }, icon = { Text(ic) }, label = { Text(t) })
                }
            }
        },
    ) { pad ->
        Box(Modifier.padding(pad).fillMaxSize()) {
            Column(Modifier.fillMaxSize()) {
                BusyBar(vm)
                Box(Modifier.weight(1f)) {
                    when {
                        vm.editorOpen -> EditorScreen(vm)
                        vm.tab == 1 && vm.resultsOpen -> ResultsScreen(vm)
                        vm.tab == 0 -> LibraryScreen(vm)
                        vm.tab == 1 -> SearchScreen(vm)
                        else -> SettingsScreen(vm)
                    }
                }
            }
            if (vm.quick) Box(Modifier.fillMaxSize().background(Color(0x55000000)), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        }
        MessageDialog(vm)
    }
}
