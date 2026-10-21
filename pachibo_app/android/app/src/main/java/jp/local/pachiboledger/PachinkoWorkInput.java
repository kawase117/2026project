package jp.local.pachiboledger;

import android.app.Activity;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.View;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import org.json.JSONObject;
import java.math.BigDecimal;
import java.util.Locale;
import java.util.function.Supplier;

/** Optional calculation fields shared by native and imported record editors. */
final class PachinkoWorkInput {
    private final EditText border,rate,holding,spins;
    private final TextView preview;
    private final LinearLayout panel;
    private final Supplier<String> kind;
    private final Supplier<long[]> exchange;

    PachinkoWorkInput(Activity activity,LinearLayout parent,JSONObject saved,EditText spins,
                      Supplier<String> kind,Supplier<long[]> exchange) {
        this.spins=spins;this.kind=kind;this.exchange=exchange;
        panel=new LinearLayout(activity);panel.setOrientation(1);parent.addView(panel);
        FormUi.label(activity,panel,"4円パチンコの仕事量を計算（任意）");
        border=decimal(activity,panel,"等価ボーダー（回/250玉）",value(saved,"work_equal_border"));
        rate=decimal(activity,panel,"実際の回転率（回/250玉）",value(saved,"work_rotation_rate"));
        holding=decimal(activity,panel,"持ち玉比率（0～100%）",value(saved,"work_holding_percent"));
        preview=FormUi.label(activity,panel,"通常回転数と3項目を入力すると表示します。交換率はこの記録の設定値を使います。");
        TextWatcher watcher=new TextWatcher(){public void beforeTextChanged(CharSequence s,int start,int count,int after){}
            public void onTextChanged(CharSequence s,int start,int before,int count){update();}
            public void afterTextChanged(Editable s){}};
        for(EditText input:new EditText[]{border,rate,holding,spins})input.addTextChangedListener(watcher);
        update();
    }
    void update(){
        panel.setVisibility("パチンコ".equals(kind.get())?View.VISIBLE:View.GONE);
        if(panel.getVisibility()!=View.VISIBLE)return;
        try{
            if(!complete()){
                preview.setText("通常回転数と3項目を入力すると表示します。交換率はこの記録の設定値を使います。");
                return;
            }
            long[] ex=exchange.get();
            BigDecimal unit=PachinkoWork.unit(PachinkoWork.parse(border.getText().toString(),"等価ボーダー"),
                PachinkoWork.parse(rate.getText().toString(),"回転率"),
                PachinkoWork.parse(holding.getText().toString(),"持ち玉比率"),ex[0],ex[1]);
            String message=String.format(Locale.JAPAN,"回転単価 %.2f円/回転",unit);
            String normal=AmountInput.normalize(spins.getText().toString());
            if(!normal.isEmpty())message+=" ／ 仕事量 "+FormUi.money(java.math.BigInteger.valueOf(
                PachinkoWork.workYen(unit,Long.parseLong(normal))));
            preview.setText(message);
        }catch(Exception error){preview.setText(error.getMessage());}
    }
    private boolean complete(){return !border.getText().toString().trim().isEmpty()&&
        !rate.getText().toString().trim().isEmpty()&&!holding.getText().toString().trim().isEmpty();}
    boolean enabled(){return "パチンコ".equals(kind.get())&&
        (!border.getText().toString().trim().isEmpty()||!rate.getText().toString().trim().isEmpty()||
         !holding.getText().toString().trim().isEmpty());}
    void save(JSONObject target,Object spinsValue,Object manualWork)throws Exception{
        if(enabled()){
            if(!complete())throw new IllegalArgumentException("仕事量の計算には等価ボーダー・回転率・持ち玉比率をすべて入力してください");
            if(manualWork!=JSONObject.NULL)throw new IllegalArgumentException("仕事量は手入力か計算の一方を選んでください");
            if(spinsValue==JSONObject.NULL)throw new IllegalArgumentException("仕事量の計算には通常回転数を入力してください");
            long[] ex=exchange.get();
            BigDecimal b=PachinkoWork.parse(border.getText().toString(),"等価ボーダー");
            BigDecimal r=PachinkoWork.parse(rate.getText().toString(),"回転率");
            BigDecimal h=PachinkoWork.parse(holding.getText().toString(),"持ち玉比率");
            long work=PachinkoWork.workYen(PachinkoWork.unit(b,r,h,ex[0],ex[1]),((Number)spinsValue).longValue());
            target.put("work_yen",work).put("work_source","pachinko_formula")
                .put("work_equal_border",b.toPlainString()).put("work_rotation_rate",r.toPlainString())
                .put("work_holding_percent",h.toPlainString())
                .put("work_exchange_yen",ex[0]).put("work_exchange_balls",ex[1]);
        }else{
            target.put("work_yen",manualWork).put("work_source",manualWork==JSONObject.NULL?JSONObject.NULL:"manual")
                .put("work_equal_border",JSONObject.NULL).put("work_rotation_rate",JSONObject.NULL)
                .put("work_holding_percent",JSONObject.NULL).put("work_exchange_yen",JSONObject.NULL)
                .put("work_exchange_balls",JSONObject.NULL);
        }
    }
    private static EditText decimal(Activity a,LinearLayout panel,String label,String value){
        EditText result=FormUi.field(a,panel,label,value);
        result.setInputType(android.text.InputType.TYPE_CLASS_NUMBER|android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL);
        result.setKeyListener(android.text.method.DigitsKeyListener.getInstance("0123456789０１２３４５６７８９.．"));
        return result;
    }
    private static String value(JSONObject saved,String key){return saved==null||saved.isNull(key)?"":saved.optString(key,"");}
}
