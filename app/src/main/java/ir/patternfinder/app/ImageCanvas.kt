package ir.patternfinder.app

import android.graphics.Bitmap
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize

private val REGION_COLORS = listOf(
    Color(0xFF2563EB), Color(0xFF16A34A), Color(0xFF9333EA), Color(0xFFDB2777),
    Color(0xFF0891B2), Color(0xFFCA8A04),
)

/**
 * نمایش تصویر با زوم/جابه‌جایی و قطعات.
 * حالت PAN: دو انگشتی زوم، یک انگشتی جابه‌جایی، لمس = انتخاب قطعه.
 * حالت RECT: کشیدن یک انگشتی = مستطیل. حالت POLY: هر لمس یک رأس.
 */
@Composable
fun ImageCanvas(
    bitmap: Bitmap?,
    regions: List<Reg>,
    selected: Int,
    mode: DrawMode,
    draft: List<Pt>,
    modifier: Modifier = Modifier,
    onTapRegion: (Int) -> Unit = {},
    onRect: (Float, Float, Float, Float) -> Unit = { _, _, _, _ -> },
    onPolyPoint: (Pt) -> Unit = {},
) {
    var sc by remember(bitmap) { mutableFloatStateOf(1f) }
    var offset by remember(bitmap) { mutableStateOf(Offset.Zero) }
    var size by remember { mutableStateOf(IntSize.Zero) }
    var fitScale by remember(bitmap) { mutableFloatStateOf(1f) }
    var dragStart by remember { mutableStateOf<Offset?>(null) }
    var dragNow by remember { mutableStateOf<Offset?>(null) }

    LaunchedEffect(bitmap, size) {
        val b = bitmap
        if (b != null && size.width > 0 && size.height > 0) {
            val s = minOf(size.width / b.width.toFloat(), size.height / b.height.toFloat())
            fitScale = s; sc = s
            offset = Offset((size.width - b.width * s) / 2f, (size.height - b.height * s) / 2f)
        }
    }

    val imageBitmap = remember(bitmap) { bitmap?.asImageBitmap() }

    fun toImage(p: Offset) = Pt((p.x - offset.x) / sc, (p.y - offset.y) / sc)

    Canvas(
        modifier = modifier
            .fillMaxSize()
            .background(Color(0xFFE5E7EB))
            .clipToBounds()
            .onSizeChanged { size = it }
            .pointerInput(mode, bitmap) {
                when (mode) {
                    DrawMode.PAN -> detectTransformGestures { centroid, pan, zoom, _ ->
                        val ns = (sc * zoom).coerceIn(fitScale * 0.5f, fitScale * 20f)
                        offset = (offset - centroid) * (ns / sc) + centroid + pan
                        sc = ns
                    }
                    DrawMode.RECT -> detectDragGestures(
                        onDragStart = { dragStart = it; dragNow = it },
                        onDragEnd = {
                            val a = dragStart; val b = dragNow
                            val bm = bitmap
                            if (a != null && b != null && bm != null) {
                                val p0 = toImage(a); val p1 = toImage(b)
                                val x0 = p0.x.coerceIn(0f, bm.width.toFloat()); val x1 = p1.x.coerceIn(0f, bm.width.toFloat())
                                val y0 = p0.y.coerceIn(0f, bm.height.toFloat()); val y1 = p1.y.coerceIn(0f, bm.height.toFloat())
                                if (Math.abs(x1 - x0) > 6f && Math.abs(y1 - y0) > 6f) onRect(x0, y0, x1, y1)
                            }
                            dragStart = null; dragNow = null
                        },
                        onDragCancel = { dragStart = null; dragNow = null },
                        onDrag = { change, _ -> dragNow = change.position },
                    )
                    DrawMode.POLY -> {}
                }
            }
            .pointerInput(mode, bitmap, regions) {
                detectTapGestures { pos ->
                    val p = toImage(pos)
                    when (mode) {
                        DrawMode.POLY -> bitmap?.let {
                            if (p.x in 0f..it.width.toFloat() && p.y in 0f..it.height.toFloat()) onPolyPoint(p)
                        }
                        DrawMode.PAN -> {
                            val hit = regions.withIndex().filter { it.value.contains(p) }.minByOrNull { it.value.areaGuess() }
                            onTapRegion(hit?.index ?: -1)
                        }
                        DrawMode.RECT -> {}
                    }
                }
            },
    ) {
        val bm = bitmap ?: return@Canvas
        withTransform({
            translate(offset.x, offset.y)
            scale(sc, sc, Offset.Zero)
        }) {
            drawImage(imageBitmap ?: bm.asImageBitmap(), srcOffset = IntOffset.Zero, srcSize = IntSize(bm.width, bm.height),
                dstOffset = IntOffset.Zero, dstSize = IntSize(bm.width, bm.height), filterQuality = FilterQuality.Medium)
            regions.forEachIndexed { i, r ->
                val isSel = i == selected
                val col = if (isSel) Color(0xFFF97316) else REGION_COLORS[i % REGION_COLORS.size]
                val path = Path()
                r.outline().forEachIndexed { k, p -> if (k == 0) path.moveTo(p.x, p.y) else path.lineTo(p.x, p.y) }
                path.close()
                drawPath(path, col.copy(alpha = if (isSel) 0.28f else 0.10f))
                drawPath(path, col, style = Stroke(width = (if (isSel) 4.5f else 2.5f) / sc))
            }
            if (draft.isNotEmpty()) {
                val c = Color(0xFFDC2626)
                for (k in 1 until draft.size) {
                    drawLine(c, Offset(draft[k - 1].x, draft[k - 1].y), Offset(draft[k].x, draft[k].y), strokeWidth = 3f / sc)
                }
                draft.forEach { drawCircle(c, radius = 6f / sc, center = Offset(it.x, it.y)) }
            }
        }
        val a = dragStart; val b = dragNow
        if (a != null && b != null) {
            drawRect(Color(0xFFDC2626), topLeft = Offset(minOf(a.x, b.x), minOf(a.y, b.y)),
                size = Size(Math.abs(b.x - a.x), Math.abs(b.y - a.y)), style = Stroke(width = 3f))
        }
    }
}
