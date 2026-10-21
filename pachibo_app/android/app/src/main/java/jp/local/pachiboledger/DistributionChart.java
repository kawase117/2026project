package jp.local.pachiboledger;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.view.View;

/** Five fixed yen bands; bars show counts, not forecasts. */
final class DistributionChart extends View {
    private static final String[] LABELS={"−2万円未満","−2万～−1円","±0円","＋1～2万円","＋2万円超"};
    private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
    private final int[] counts=new int[5];
    DistributionChart(Context context){super(context);setBackgroundColor(FormUi.SURFACE);}
    void setCounts(int[] values){System.arraycopy(values,0,counts,0,5);invalidate();}
    @Override protected void onDraw(Canvas canvas){
        super.onDraw(canvas);float density=getResources().getDisplayMetrics().density;
        float labelWidth=105*density,top=15*density,row=36*density;
        float barEnd=getWidth()-52*density,maxWidth=Math.max(0,barEnd-labelWidth);
        int max=1;for(int count:counts)max=Math.max(max,count);
        paint.setTextSize(13*density);
        for(int i=0;i<5;i++){
            float y=top+i*row;
            paint.setColor(FormUi.INK);canvas.drawText(LABELS[i],8*density,y+17*density,paint);
            paint.setColor(i<2?FormUi.MINUS:i>2?FormUi.PLUS:FormUi.MUTED);
            float width=maxWidth*counts[i]/max;
            canvas.drawRoundRect(labelWidth,y+4*density,labelWidth+width,y+22*density,4*density,4*density,paint);
            paint.setColor(FormUi.INK);
            canvas.drawText(Integer.toString(counts[i]),barEnd+5*density,y+18*density,paint);
        }
    }
}
