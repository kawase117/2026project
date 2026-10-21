package jp.local.pachiboledger;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.view.View;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

final class ProfitChart extends View {
    private final Paint paint = new Paint(3);
    private List<JSONObject> rows = new ArrayList<>();

    ProfitChart(Context context) { super(context); }
    void setRows(List<JSONObject> value) { rows = new ArrayList<>(value); invalidate(); }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float left = 80, right = getWidth() - 20, top = 30, bottom = getHeight() - 50;
        paint.setColor(FormUi.GRID); paint.setStrokeWidth(2);
        canvas.drawLine(left, bottom, right, bottom, paint);
        if (rows.isEmpty()) return;
        Collections.reverse(rows); // DB returns descending dates.
        long total = 0, min = 0, max = 0;
        List<Long> values = new ArrayList<>();
        values.add(0L);
        for (JSONObject row : rows) { total += row.optLong("profit_yen"); values.add(total); min = Math.min(min, total); max = Math.max(max, total); }
        if (max == min) { max++; min--; }
        float oldX = left, oldY = bottom - (0 - min) * (bottom - top) / (max - min);
        paint.setColor(FormUi.LINE); paint.setStrokeWidth(4);
        for (int i = 1; i < values.size(); i++) {
            float x = left + i * (right - left) / (values.size() - 1);
            float y = bottom - (values.get(i) - min) * (bottom - top) / (max - min);
            canvas.drawLine(oldX, oldY, x, y, paint); oldX = x; oldY = y;
        }
        paint.setColor(FormUi.INK); paint.setTextSize(27);
        canvas.drawText(String.format("%,d", max), 5, top + 12, paint);
        canvas.drawText(String.format("%,d", min), 5, bottom, paint);
        canvas.drawText("累積収支（円）", left, getHeight() - 10, paint);
        Collections.reverse(rows);
    }
}
