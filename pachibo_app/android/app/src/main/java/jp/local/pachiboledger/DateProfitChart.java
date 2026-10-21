package jp.local.pachiboledger;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.view.View;
import java.time.LocalDate;
import java.util.*;

/** Rendering only; all monetary totals are computed before conversion to plotting doubles. */
final class DateProfitChart extends View {
    private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG);
    private final SortedMap<String,Double> values=new TreeMap<>();
    private boolean bars;
    private long minimumRangeYen;
    DateProfitChart(Context context) { super(context); setBackgroundColor(FormUi.SURFACE); }
    void setValues(SortedMap<String,Double> values) { this.values.clear(); this.values.putAll(values); invalidate(); }
    void setBars(boolean bars) { this.bars=bars; invalidate(); }
    void setMinimumRangeYen(long yen) { minimumRangeYen=Math.max(0,yen); invalidate(); }
    @Override protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (values.isEmpty()) return;
        float scale=getResources().getDisplayMetrics().density;
        float left=92*scale,right=getWidth()-12*scale,top=18*scale,bottom=getHeight()-38*scale;
        if (right<=left || bottom<=top) return;
        double min=Double.POSITIVE_INFINITY,max=Double.NEGATIVE_INFINITY;
        for (Double value:values.values()) if (value!=null) { min=Math.min(min,value); max=Math.max(max,value); }
        if(!Double.isFinite(min)||!Double.isFinite(max))return;
        if(bars){min=Math.min(0,min);max=Math.max(0,max);}
        if(minimumRangeYen>0 && min>=-minimumRangeYen && max<=minimumRangeYen){
            min=-minimumRangeYen;max=minimumRangeYen;
        }else{
            double padding=Math.max(1,(max-min)*.1);
            if(min==max)padding=Math.max(1000,Math.abs(min)*.1);
            min-=padding;max+=padding;
            if(bars){min=Math.min(0,min);max=Math.max(0,max);}
        }
        long first=LocalDate.parse(values.firstKey()).toEpochDay(),last=LocalDate.parse(values.lastKey()).toEpochDay();
        double span=Math.max(1,last-first);
        float zero=(float)(bottom-(0-min)/(max-min)*(bottom-top));
        paint.setTextSize(11*scale);paint.setStrokeWidth(scale);
        for(int i=0;i<=4;i++){
            float y=top+(bottom-top)*i/4f;
            paint.setColor(FormUi.GRID);canvas.drawLine(left,y,right,y,paint);
            paint.setColor(FormUi.INK);paint.setTextAlign(Paint.Align.RIGHT);
            canvas.drawText(String.format(Locale.JAPAN,"%,.0f円",max-(max-min)*i/4d),left-5*scale,y+4*scale,paint);
        }
        paint.setTextAlign(Paint.Align.LEFT);
        Float oldX=null,oldY=null;
        float barWidth=Math.max(2*scale,Math.min(24*scale,(right-left)/Math.max(1,values.size())*.65f));
        paint.setColor(FormUi.LINE); paint.setStrokeWidth(2*scale);
        for (Map.Entry<String,Double> item:values.entrySet()) {
            if (item.getValue()==null) { oldX=null; oldY=null; continue; }
            float x=(float)(left+(LocalDate.parse(item.getKey()).toEpochDay()-first)/span*(right-left));
            float y=(float)(bottom-(item.getValue()-min)/(max-min)*(bottom-top));
            if (bars) {
                paint.setColor(item.getValue()>=0?FormUi.PLUS:FormUi.MINUS);
                canvas.drawRect(Math.max(left,x-barWidth/2),Math.min(zero,y),Math.min(right,x+barWidth/2),Math.max(zero,y),paint);
                if (item.getValue()==0) canvas.drawCircle(x,zero,2*scale,paint);
            } else {
                if (oldX!=null) canvas.drawLine(oldX,oldY,x,y,paint);
                canvas.drawCircle(x,y,3*scale,paint);
            }
            oldX=x; oldY=y;
        }
        paint.setColor(FormUi.INK); paint.setTextSize(11*scale);
        boolean annual=last-first>180;
        String firstLabel=(annual?values.firstKey().substring(0,7):values.firstKey()).replace('-','/');
        String lastLabel=(annual?values.lastKey().substring(0,7):values.lastKey()).replace('-','/');
        canvas.drawText(firstLabel,left,getHeight()-10*scale,paint);
        if (last!=first) {
            paint.setTextAlign(Paint.Align.RIGHT);
            canvas.drawText(lastLabel,right,getHeight()-10*scale,paint);
            paint.setTextAlign(Paint.Align.LEFT);
            if(right-left>(annual?190:250)*scale && last-first>60){
                String date=LocalDate.ofEpochDay(first+(last-first)/2).toString();
                String middle=(annual?date.substring(0,7):date).replace('-','/');
                if(!middle.equals(firstLabel)&&!middle.equals(lastLabel)){
                    paint.setTextAlign(Paint.Align.CENTER);
                    canvas.drawText(middle,(left+right)/2,getHeight()-10*scale,paint);
                    paint.setTextAlign(Paint.Align.LEFT);
                }
            }
        }
    }
}
