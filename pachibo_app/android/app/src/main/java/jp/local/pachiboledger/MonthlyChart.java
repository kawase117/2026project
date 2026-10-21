package jp.local.pachiboledger;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.view.View;
import java.util.ArrayList;
import java.util.Map;

final class MonthlyChart extends View {
    private final Paint paint = new Paint(3);
    private final ArrayList<Map.Entry<String, Long>> months = new ArrayList<>();

    MonthlyChart(Context context) { super(context); }
    void setMonths(Map<String, Long> values) {
        months.clear(); months.addAll(values.entrySet());
        invalidate();
    }

    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (months.isEmpty()) return;
        float top = 25, bottom = getHeight() - 65, left = 65, right = getWidth() - 15;
        long min = 0, max = 0;
        for (Map.Entry<String, Long> month : months) {
            min = Math.min(min, month.getValue()); max = Math.max(max, month.getValue());
        }
        if (max == min) { max++; min--; }
        float zero = bottom - (0 - min) * (bottom - top) / (max - min);
        paint.setColor(FormUi.GRID); paint.setStrokeWidth(2);
        canvas.drawLine(left, zero, right, zero, paint);
        float width = (right - left) / months.size();
        for (int i = 0; i < months.size(); i++) {
            long gain = months.get(i).getValue();
            float x = left + i * width + width * 0.15f;
            float y = bottom - (gain - min) * (bottom - top) / (max - min);
            paint.setColor(gain >= 0 ? FormUi.PLUS : FormUi.MINUS);
            canvas.drawRect(x, Math.min(y, zero), x + width * 0.7f, Math.max(y, zero), paint);
            paint.setColor(FormUi.INK); paint.setTextSize(21);
            String label = months.get(i).getKey();
            canvas.drawText(label.substring(2, 4) + "/" + label.substring(5), x, getHeight() - 25, paint);
        }
        paint.setColor(FormUi.INK); paint.setTextSize(23);
        canvas.drawText(String.format("%,d", max), 3, top + 10, paint);
        canvas.drawText(String.format("%,d", min), 3, bottom, paint);
    }
}
